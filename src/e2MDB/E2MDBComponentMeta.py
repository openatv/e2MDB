########################################################################################################
# e2MDB Live/EPG component metadata bridge                                                             #
# -----------------------------------------------------------------------------------------------------#
# Populates meta dictionaries on OpenATV EventInfo/ServiceEvent sources. Skins can then use normal      #
# sources such as Event_Now with the E2MDBEventInfo converter. This replaces the old InfoBar-specific   #
# screen-source hook when the extended OpenATV components are available.                                #
########################################################################################################

from os.path import basename, splitext
from time import time
from urllib.parse import unquote

from Components.config import config
from Components.ServiceEventTracker import ServiceEventTracker
from enigma import eServiceReference, iPlayableService

from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBEPGBridge import _actionable_missing_images, _ensure_resultsdb_ready, is_epg_worker_paused_for_open_epg
from .E2MDBLiveEPG import E2MDBLiveEPG
from .E2MDBSkin import build_epg_skin_data, _full_cache_path
from .E2MDBPriority import PRIORITY_ADHOC_NOW, PRIORITY_INFOBAR_NOW
from .E2MDBBackendNotify import register_meta_source, unregister_meta_source


MODULE_NAME = "[e2MDB][COMPONENTMETA]"
_hooks_installed = False
_old_eventinfo_update_source = None
_old_serviceevent_new_service = None
_old_servicelist_refresh = None
_old_infobar_init = None
COMPONENT_META_QUEUE_PRIORITY = PRIORITY_INFOBAR_NOW
COMPONENT_META_ADHOC_PRIORITY = PRIORITY_ADHOC_NOW
COMPONENT_META_ADHOC_ENABLED = True


class _MetaState:
	last_keys = {}
	last_log = {}
	session_sources_attached = False
	ad_hoc_running = set()
	ad_hoc_last_request = {}
	ad_hoc_sources = {}


def _log(message, force=False, level=None):
	write_log(MODULE_NAME, message, level=level)


def _debug(message):
	_log(f"DEBUG {message}", force=True)


def _safe_event_id(event):
	try:
		return event.getEventId()
	except Exception:
		return 0


def _safe_event_title(event):
	try:
		return event.getEventName() or ""
	except Exception:
		return ""


def _safe_event_begin(event):
	try:
		return int(event.getBeginTime() or 0)
	except Exception:
		return 0


def _describe_source(source):
	try:
		meta = source.getMeta() if hasattr(source, "getMeta") else {}
	except Exception:
		meta = {}
	service = _get_service_from_source(source)
	event = _get_event_from_source(source)
	return f"id={id(source)} class={source.__class__.__name__} service='{_service_ref_to_string(service)}' event_id={_safe_event_id(event)} begin={_safe_event_begin(event)} title='{_safe_event_title(event)}' meta_source_key='{(meta or {}).get("source_key", "") if isinstance(meta, dict) else ""}' meta_cover='{(meta or {}).get("cover_path", "") if isinstance(meta, dict) else ""}' meta_backdrop='{(meta or {}).get("backdrop_path", "") if isinstance(meta, dict) else ""}' meta_image='{(meta or {}).get("image_path", "") if isinstance(meta, dict) else ""}' empty={(meta or {}).get("e2mdb_empty", "") if isinstance(meta, dict) else ""} clear_reason='{(meta or {}).get("e2mdb_clear_reason", "") if isinstance(meta, dict) else ""}'"


def _enabled():
	try:
		return bool(config.plugins.e2mdb.epgInfoBarEnabled.value)
	except Exception:
		return True


def _is_now_source(source):
	try:
		return int(getattr(source, "nowOrNext", 0) or 0) == 0
	except Exception:
		return True


def _is_ad_hoc_reason(reason):
	reason = str(reason or "")
	return (
		reason.startswith("eventinfo-")
		or reason.startswith("serviceevent-newService")
		or reason.startswith("infobar-service-")
		or reason.startswith("missing-provider-data")
		or reason.startswith("fresh-missing-images")
		or reason.startswith("promoted-event-next-now")
		or reason.startswith("event-next-now")
		or reason.startswith("new")
		or reason.startswith("expired")
	)


def _service_ref_to_string(ref):
	try:
		return ref.toString() if ref else ""
	except Exception:
		return str(ref or "")


def _service_name(ref):
	try:
		from ServiceReference import ServiceReference
		return ServiceReference(ref).getServiceName() or ""
	except Exception:
		pass
	try:
		return ref.getName() or ""
	except Exception:
		pass
	return ""


def _is_usable_service(ref):
	if ref is None:
		return False, "no-service"
	try:
		if hasattr(ref, "valid") and not ref.valid():
			return False, "invalid-service"
	except Exception:
		pass
	try:
		flags = int(getattr(ref, "flags", 0) or 0)
		if flags & eServiceReference.isMarker:
			return False, "marker"
		if flags & eServiceReference.isDirectory:
			return False, "directory"
	except Exception:
		pass
	return True, ""


def _get_event_from_source(source):
	try:
		event = getattr(source, "event", None)
		if event:
			return event
	except Exception:
		pass
	try:
		if hasattr(source, "getCurrentEvent"):
			return source.getCurrentEvent()
	except Exception:
		pass
	return None


def _get_service_from_source(source):
	try:
		service = getattr(source, "service", None)
		if service:
			return service
	except Exception:
		pass
	try:
		if hasattr(source, "getCurrentService"):
			service = source.getCurrentService()
			if service:
				return service
	except Exception:
		pass
	try:
		navcore = getattr(source, "navcore", None)
		if navcore and hasattr(navcore, "getCurrentlyPlayingServiceReference"):
			ref = navcore.getCurrentlyPlayingServiceReference()
			if ref:
				return ref
		if navcore and hasattr(navcore, "getCurrentlyPlayingServiceOrGroup"):
			ref = navcore.getCurrentlyPlayingServiceOrGroup()
			if ref:
				return ref
	except Exception:
		pass
	return None


def _safe_service_path(ref):
	"""Return a playable local media path from an eServiceReference if available."""
	path = ""
	try:
		if ref and hasattr(ref, "getPath"):
			path = ref.getPath() or ""
	except Exception:
		path = ""
	if not path:
		try:
			ref_string = _service_ref_to_string(ref)
			# Last field usually contains the path for file service references.
			candidate = ref_string.rsplit(":", 1)[-1] if ref_string else ""
			if candidate and (candidate.startswith("/") or candidate.startswith("file%3a") or candidate.startswith("file%3A") or candidate.startswith("file:")):
				path = candidate
		except Exception:
			path = ""
	try:
		path = unquote(path or "")
	except Exception:
		path = path or ""
	if path.startswith("file://"):
		path = path[7:]
	return path.strip()


def _service_cache_paths(media_path):
	"""Return the scanner hash for a local MoviePlayer/recording path.

	The JSON path is returned only as a debug artifact path. Display metadata is
	resolved from SQLite below.
	"""
	media_path = str(media_path or "").strip()
	if not media_path:
		return "", ""
	try:
		from .E2MDBHelper import E2MDBHelper
		helper = E2MDBHelper()
		return helper.get_reduced_org_hash(media_path), helper.get_primary_datapath(media_path)
	except Exception as err:
		_debug(f"SERVICE DB helper failed path='{media_path}' error={err}")
		return "", ""


def _media_row_has_display_metadata(row):
	if not isinstance(row, dict):
		return False
	for key in (
		"metadata_title", "metadata_subtitle", "metadata_overview", "metadata_genres",
		"metadata_provider", "metadata_media_type", "metadata_cover_path",
		"metadata_backdrop_path", "metadata_logo_path", "metadata_image_path",
		"metadata_released", "metadata_cast", "metadata_crew"
	):
		if str(row.get(key) or "").strip():
			return True
	return False


def _find_media_metadata_by_path(media_path):
	"""Find final display metadata for a MoviePlayer/local-file path in SQLite.

	Primary JSON files are debug/cache artifacts only and are intentionally not
	parsed for UI or skin rendering.
	"""
	media_path = str(media_path or "").strip()
	if not media_path:
		return "", "", {}, {}
	hash_id, json_path = _service_cache_paths(media_path)
	try:
		if hash_id:
			row = resultsdb.get_media_metadata(hash_id) or {}
			if row:
				return hash_id, json_path, row, resultsdb.get_media_display_data(hash_id) or {}
	except Exception as err:
		_debug(f"SERVICE DB hash lookup failed path='{media_path}' hash='{hash_id}' error={err}")

	try:
		folder = media_path.rsplit("/", 1)[0] if "/" in media_path else ""
		name = basename(media_path)
		with resultsdb._connect() as conn:
			conn.row_factory = None
			row = conn.execute("""
				SELECT *
				FROM e2mdb_media
				WHERE (file_path = ? AND file_name = ?) OR (? = file_path || '/' || file_name)
				ORDER BY updated_at DESC
				LIMIT 1
			""", (folder, name, media_path)).fetchone()
			if row:
				columns = [item[0] for item in conn.execute("SELECT * FROM e2mdb_media LIMIT 0").description]
				db_row = dict(zip(columns, row))
				hash_id = db_row.get("hash") or hash_id
				data = resultsdb.get_media_display_data(hash_id) if hash_id else {}
				return hash_id, json_path, db_row, data or {}
	except Exception as err:
		_debug(f"SERVICE DB path lookup failed path='{media_path}' error={err}")
	return hash_id, json_path, {}, {}


def _service_path_title(media_path, data=None):
	data = data if isinstance(data, dict) else {}
	title = data.get("title") or data.get("name") or data.get("original_title") or ""
	if title:
		return str(title or "")
	base = splitext(basename(media_path or ""))[0]
	return base.replace(".", " ").replace("_", " ").strip()


def _update_source_meta_from_service_path(source, service, reason="refresh", notify=False, log_miss=True):
	"""Populate metadata from SQLite when MoviePlayer has service/path but no EPG event."""
	media_path = _safe_service_path(service)
	if not media_path:
		return False
	hash_id, json_path, db_row, data = _find_media_metadata_by_path(media_path)
	if not db_row or not _media_row_has_display_metadata(db_row):
		if log_miss:
			_debug(f"SERVICE DB miss reason={reason} service='{_service_ref_to_string(service)}' path='{media_path}' hash='{hash_id or ""}'")
		return False

	title = _service_path_title(media_path, data)
	event_row = dict(db_row)
	event_row.update({
		"source_key": f"media:{hash_id or media_path}",
		"title": title,
		"search_title": title,
		"short_desc": data.get("episode_name") or data.get("tagline") or "",
		"extended_desc": data.get("overview") or data.get("description") or "",
		"status": "matched",
		"json_path": json_path,
	})
	meta = build_epg_skin_data(candidate=None, event_row=event_row)
	try:
		meta.update({
			"source_key": f"media:{hash_id or media_path}",
			"service_ref": _service_ref_to_string(service),
			"event_id": 0,
			"begin_time": 0,
			"media_path": media_path,
		})
	except Exception:
		pass
	try:
		source.setMeta(meta)
		register_meta_source(meta.get("source_key") or "", source)
	except Exception as err:
		_debug(f"SERVICE DB setMeta failed reason={reason} path='{media_path}' error={err}")
		return False

	key_id = id(source)
	last_key = _MetaState.last_keys.get(key_id)
	if last_key != meta.get("source_key"):
		_MetaState.last_keys[key_id] = meta.get("source_key")
		_log(f"SERVICE DB HIT reason={reason} source_key={meta.get("source_key") or ""} service='{_service_ref_to_string(service)}' path='{media_path}' debug_json='{json_path}' title='{title}' cover='{meta.get("cover_path") or ""}'", force=True)
	if notify:
		try:
			source.changed((source.CHANGED_ALL,))
		except Exception:
			pass
	return True


def _queue_needed(existing, now, candidate_search_title=""):
	if not existing:
		return True, "new"
	status = (existing.get("status") or "unknown").lower()
	expires_at = int(existing.get("expires_at") or 0)
	json_path = existing.get("json_path") or ""
	if status in ("matched", "done") and json_path and (expires_at <= 0 or expires_at > now):
		missing_images = _actionable_missing_images(existing)
		if missing_images:
			return True, f"fresh-missing-images:{",".join(missing_images)}"
		return False, "fresh-provider-data"
	if status == "no_match" and expires_at > now:
		stored_search_title = existing.get("search_title") or ""
		if candidate_search_title and (not stored_search_title or stored_search_title != candidate_search_title):
			return True, "improved-search-title"
		return False, "fresh-no-match"
	if status in ("skipped", "ended_skipped", "short_skipped", "ignored") and expires_at > now:
		return False, "fresh-provider-skip"
	if expires_at and expires_at <= now:
		return True, "expired"
	return True, "missing-provider-data"


def _mark_provider_skipped(adapter, candidate, status, reason, detail="", existing=False):
	status = status or "skipped"
	expires_at = adapter.default_expiry(candidate.event_end, status=status)
	data = candidate.as_dict()
	data.update({
		"status": status,
		"confidence": 0.0,
		"json_path": "",
		"expires_at": expires_at,
	})
	if existing:
		resultsdb.update_epg_event_search_title(candidate.source_key, candidate.search_title)
		resultsdb.update_epg_event_status(candidate.source_key, status, confidence=0.0, json_path="", expires_at=expires_at)
	else:
		resultsdb.upsert_epg_event(data)
	queue_item = resultsdb.get_fetch_queue_item(candidate.source_key)
	if queue_item:
		resultsdb.update_fetch_queue_state(candidate.source_key, status, last_error=f"{reason}:{detail or ''}")


def _queue_event(candidate, priority=None, reason="component-meta"):
	if is_epg_worker_paused_for_open_epg():
		return False
	priority = int(priority if priority is not None else COMPONENT_META_QUEUE_PRIORITY)
	existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
	if existing_queue:
		existing_priority = int(existing_queue.get("priority") or 0)
		existing_state = existing_queue.get("state") or "pending"
		if existing_state == "pending" and existing_priority >= priority:
			return True
	resultsdb.upsert_fetch_queue({
		"source_key": candidate.source_key,
		"source_type": candidate.source_type,
		"service_ref": candidate.service_ref,
		"title": candidate.title,
		"search_title": candidate.search_title,
		"begin_time": candidate.begin_time,
		"event_end": candidate.event_end,
		"priority": priority,
		"reason": reason or "component-meta",
		"state": "pending",
	})
	return True


def _get_provider_asset_meta(source_key):
	"""Return linked provider asset image metadata for an EPG event source_key."""
	if not source_key:
		return {}
	try:
		with resultsdb._connect() as conn:
			conn.row_factory = None
			row = conn.execute("""
				SELECT
					a.provider,
					a.provider_id,
					a.title,
					a.media_type,
					a.cover_path,
					a.backdrop_path,
					a.logo_path,
					a.json_path,
					m.confidence
				FROM e2mdb_epg_events e
				JOIN e2mdb_epg_event_asset_map m ON m.epg_event_id = e.id
				JOIN e2mdb_provider_assets a ON a.id = m.asset_id
				WHERE e.source_key = ?
				ORDER BY m.confidence DESC, a.updated_at DESC
				LIMIT 1
			""", (source_key,)).fetchone()
			if not row:
				return {}
			return {
				"provider": row[0] or "",
				"provider_id": row[1] or "",
				"asset_title": row[2] or "",
				"asset_media_type": row[3] or "",
				"cover_path": _full_cache_path(row[4] or ""),
				"backdrop_path": _full_cache_path(row[5] or ""),
				"titlelogo_path": _full_cache_path(row[6] or ""),
				"asset_json_path": _full_cache_path(row[7] or ""),
				"asset_confidence": row[8] or 0,
			}
	except Exception as err:
		_debug(f"ASSET fallback failed source_key={source_key} error={err}")
	return {}


def _apply_provider_asset_fallback(meta, source_key, reason=""):
	"""Fill missing skin meta image fields from linked provider_assets."""
	if not isinstance(meta, dict):
		return meta
	if meta.get("cover_path") and meta.get("backdrop_path"):
		return meta
	asset = _get_provider_asset_meta(source_key)
	if not asset:
		return meta
	changed = []
	for key in ("cover_path", "backdrop_path", "titlelogo_path"):
		if not meta.get(key) and asset.get(key):
			meta[key] = asset.get(key) or ""
			changed.append(key)
	if not meta.get("provider") and asset.get("provider"):
		meta["provider"] = asset.get("provider") or ""
	if not meta.get("media_type") and asset.get("asset_media_type"):
		meta["media_type"] = asset.get("asset_media_type") or ""
	if changed:
		_log(f"ASSET FALLBACK reason={reason} source_key={source_key} fields={",".join(changed)} cover='{meta.get("cover_path") or ""}' backdrop='{meta.get("backdrop_path") or ""}' provider={asset.get("provider") or ""} provider_id={asset.get("provider_id") or ""}", force=True)
	return meta


def _remember_ad_hoc_source(source_key, source):
	"""Attach this source to an already requested ad-hoc result refresh."""
	if not source_key or source is None:
		return
	try:
		sources = _MetaState.ad_hoc_sources.setdefault(source_key, [])
		if all(id(item) != id(source) for item in sources):
			sources.append(source)
	except Exception:
		pass


def _queue_item_was_event_next(queue_item):
	reason = str((queue_item or {}).get("reason") or "").lower().replace("_", "-")
	return "event-next" in reason or reason.endswith("-next") or "next-event" in reason


def _event_row_needs_provider_data(event_row):
	if not event_row:
		return True
	status = str(event_row.get("status") or "unknown").lower()
	json_path = event_row.get("json_path") or ""
	if status not in ("matched", "done"):
		return True
	return not bool(json_path)


def _promote_event_next_to_ad_hoc(source, candidate, event_row=None, reason="component-meta"):
	"""Promote a pending Event_Next queue row when the same EPG event becomes Event_Now.

	An event that was queued as Event_Next but is now the visible live event should
	be promoted immediately. Otherwise the user can see no cover/info exactly at
	the program switch while the normal background worker is still waiting.
	"""
	if not candidate or not candidate.source_key or not _is_now_source(source):
		return False
	if is_epg_worker_paused_for_open_epg():
		return False
	try:
		queue_item = resultsdb.get_fetch_queue_item(candidate.source_key)
	except Exception:
		queue_item = {}
	if not queue_item:
		return False
	state = str(queue_item.get("state") or "pending").lower()
	if state not in ("pending", "running"):
		return False
	if not _queue_item_was_event_next(queue_item) and not _event_row_needs_provider_data(event_row):
		return False
	priority = COMPONENT_META_ADHOC_PRIORITY
	try:
		resultsdb.upsert_fetch_queue({
			"source_key": candidate.source_key,
			"source_type": candidate.source_type,
			"service_ref": candidate.service_ref,
			"title": candidate.title,
			"search_title": candidate.search_title,
			"begin_time": candidate.begin_time,
			"event_end": candidate.event_end,
			"priority": priority,
			"reason": "promoted-event-next-now-adhoc",
			"state": "pending" if state != "running" else state,
		})
	except Exception as err:
		_log(f"EVENT_NEXT PROMOTE queue update failed source_key={candidate.source_key} error={err}", force=True)
		return False
	_log(f"EVENT_NEXT PROMOTE source_key={candidate.source_key} old_reason={queue_item.get("reason") or ""} state={state} priority={priority} title='{candidate.title}' trigger={reason or ""}", force=True)
	return _request_ad_hoc(source, candidate, reason="promoted-event-next-now")


def _request_ad_hoc(source, candidate, reason="component-meta"):
	"""Request immediate worker processing and refresh all matching EventInfo sources afterwards."""
	if not candidate or not candidate.source_key:
		return False
	if not COMPONENT_META_ADHOC_ENABLED:
		return False
	if is_epg_worker_paused_for_open_epg():
		return False
	if not _is_now_source(source):
		_log(f"ADHOC SKIP source_key={candidate.source_key} reason=not-now-source trigger={reason}")
		return False
	if not _is_ad_hoc_reason(reason):
		_log(f"ADHOC SKIP source_key={candidate.source_key} reason=unsupported-trigger trigger={reason}")
		return False

	# Important: skins may use session.Event_Now while the first update happened on screen['Event_Now'].
	# Always attach every matching source to the same in-flight ad-hoc result.
	_remember_ad_hoc_source(candidate.source_key, source)

	queue_item = resultsdb.get_fetch_queue_item(candidate.source_key)
	if queue_item and (queue_item.get("state") or "") == "running":
		_log(f"ADHOC ATTACH source_key={candidate.source_key} reason=already-running trigger={reason} source_id={id(source)}")
		return False
	now = int(time())
	last = int(_MetaState.ad_hoc_last_request.get(candidate.source_key) or 0)
	if candidate.source_key in _MetaState.ad_hoc_running and now - last < 30:
		_log(f"ADHOC ATTACH source_key={candidate.source_key} reason=already-requested trigger={reason} source_id={id(source)}")
		return False

	_MetaState.ad_hoc_running.add(candidate.source_key)
	_MetaState.ad_hoc_last_request[candidate.source_key] = now
	_queue_event(candidate, priority=COMPONENT_META_ADHOC_PRIORITY, reason=f"{reason or "component-meta"}-adhoc")
	try:
		from .E2MDBBackendLiveBridge import request_backend_live_epg_processing
		started = request_backend_live_epg_processing(candidate.source_key, callback=None, priority=COMPONENT_META_ADHOC_PRIORITY, reason=reason)
		_MetaState.ad_hoc_running.discard(candidate.source_key)
		_MetaState.ad_hoc_sources.pop(candidate.source_key, None)
		_log(f"ADHOC BACKEND WAKE source_key={candidate.source_key} started={started} priority={COMPONENT_META_ADHOC_PRIORITY} trigger={reason} title='{candidate.title}' source_id={id(source)}", force=True)
		if not started:
			# Keep it upgraded in queue. No callback will happen, so allow another request later.
			_MetaState.ad_hoc_running.discard(candidate.source_key)
		return bool(started)
	except Exception as err:
		_MetaState.ad_hoc_running.discard(candidate.source_key)
		_log(f"ADHOC REQUEST failed source_key={candidate.source_key} error={err}", force=True)
		return False


def _empty_meta(reason="clear"):
	return {
		"source_key": "",
		"service_ref": "",
		"event_id": 0,
		"begin_time": 0,
		"cover_path": "",
		"backdrop_path": "",
		"titlelogo_path": "",
		"image_path": "",
		"e2mdb_empty": True,
		"e2mdb_clear_reason": reason or "clear",
	}


def _source_generation(source):
	try:
		return int(getattr(source, "_e2mdb_meta_generation", 0) or 0)
	except Exception:
		return 0


def _clear_source_meta(source, reason="clear", notify=True):
	try:
		try:
			old_meta = source.getMeta() if hasattr(source, "getMeta") else {}
			if isinstance(old_meta, dict) and old_meta.get("source_key"):
				unregister_meta_source(old_meta.get("source_key"), source)
		except Exception:
			pass
		try:
			setattr(source, "_e2mdb_meta_generation", _source_generation(source) + 1)
		except Exception:
			pass
		_debug(f"CLEAR before reason={reason} {_describe_source(source)}")
		source.setMeta(_empty_meta(reason))
	except Exception as err:
		_debug(f"CLEAR failed reason={reason} error={err}")
		return False
	if notify:
		try:
			source.changed((source.CHANGED_ALL,))
			_debug(f"CLEAR notify reason={reason} {_describe_source(source)}")
		except Exception as err:
			_debug(f"CLEAR notify failed reason={reason} error={err}")
	return True


def _update_source_meta_now(source, reason="refresh", notify=True):
	_debug(f"UPDATE_NOW start reason={reason} {_describe_source(source)}")
	result = update_source_meta(source, reason=reason, notify=notify)
	_debug(f"UPDATE_NOW end reason={reason} result={result} {_describe_source(source)}")
	return result


def _set_open_epg_cache_only_meta(source, service, event, reason="refresh", notify=False):
	"""Keep e2MDB metadata deferred while an EPG/channel list is moving.

	This avoids synchronous SQLite reads triggered by Event.getMeta()/ServiceEvent.getMeta()
	during rapid cursor movement. It also avoids nested source.changed() calls and
	title/picon preparation for transient rows. The debounced screen bridge fills
	the selected row after the cursor is stable.
	"""
	try:
		old_source_key = str(getattr(source, "_e2mdb_registered_source_key", "") or "")
		if old_source_key:
			unregister_meta_source(old_source_key, source)
		meta = _empty_meta(reason or "epg-selection-deferred")
		meta["e2mdb_cache_only"] = True
		meta["e2mdb_cache_only_reason"] = reason or "epg-selection-deferred"
		source.setMeta(meta)
		return True
	except Exception as err:
		_debug(f"CACHE_ONLY meta failed reason={reason} error={err}")
		return False


def _is_channel_selection_deferred_source(source):
	try:
		return bool(getattr(source, "_e2mdb_channel_selection_deferred", False))
	except Exception:
		return False


def _is_epg_selection_deferred_source(source):
	try:
		return bool(getattr(source, "_e2mdb_epg_selection_deferred", False))
	except Exception:
		return False


def update_source_meta(source, reason="refresh", notify=False):
	"""Populate source.setMeta() with cached e2MDB data for its current event/service."""
	if not _enabled():
		return False

	service = _get_service_from_source(source)
	usable, skip_reason = _is_usable_service(service)
	if not usable:
		_debug(f"UPDATE skip reason={skip_reason} {_describe_source(source)}")
		try:
			source.setMeta(_empty_meta(f"skip-{skip_reason}"))
		except Exception:
			pass
		return False

	event = _get_event_from_source(source)
	if event and (_is_epg_selection_deferred_source(source) or _is_channel_selection_deferred_source(source)):
		cache_reason = reason
		try:
			if _is_channel_selection_deferred_source(source):
				cache_reason = getattr(source, "_e2mdb_channel_selection_deferred_reason", "channel-selection") or "channel-selection"
		except Exception:
			pass
		return _set_open_epg_cache_only_meta(source, service, event, reason=cache_reason, notify=notify)

	if not _ensure_resultsdb_ready(f"component-meta-{reason}"):
		return False

	# Prefer the normal scanner cache for MoviePlayer/local files when it exists.
	# Live/EPG services simply fall through to the event-based path below.
	if _update_source_meta_from_service_path(source, service, reason=f"{reason or "refresh"}-service-cache", notify=notify, log_miss=False):
		return True

	if not event:
		# MoviePlayer/local files often have no EPG event. In that case keep the
		# EventInfo/ServiceEvent skin path working by loading the scanner cache
		# through the current service reference path. Live/EPG continues below when
		# an event exists.
		if _update_source_meta_from_service_path(source, service, reason=reason, notify=notify):
			return True
		_debug(f"UPDATE skip reason=no-event {_describe_source(source)}")
		try:
			source.setMeta(_empty_meta("skip-no-event"))
		except Exception:
			pass
		return False

	adapter = E2MDBLiveEPG()
	candidate = adapter.event_to_candidate(service, event, service_name=_service_name(service), source_type=adapter.SOURCE_EPG)
	if not candidate.source_key or not candidate.title:
		_debug(f"UPDATE skip reason=no-candidate service='{_service_ref_to_string(service)}' title='{_safe_event_title(event)}'")
		return False
	_debug(f"UPDATE candidate reason={reason} source_key={candidate.source_key} service='{candidate.service_ref}' event_id={candidate.event_id} begin={candidate.begin_time} title='{candidate.title}' search_title='{candidate.search_title}'")

	now = int(time())
	if is_epg_worker_paused_for_open_epg():
		existing = resultsdb.get_epg_event_readonly(candidate.source_key)
	else:
		existing = resultsdb.get_epg_event(candidate.source_key)
	if is_epg_worker_paused_for_open_epg():
		# EPG screens are in cache-only mode. Do not insert/touch queue rows, do not
		# promote Event_Next and do not start ad-hoc lookups while the user moves
		# through EPG lists. Existing cached metadata is still exposed to the skin.
		try:
			current_meta = {}
			# refreshData() is normally entered from getMeta() after refresh was
			# cleared. Avoid a recursive getMeta() call if another caller invokes
			# this update while the source is still marked for refresh.
			if not bool(getattr(source, "refresh", False)) and hasattr(source, "getMeta"):
				current_meta = source.getMeta()
				if not isinstance(current_meta, dict):
					current_meta = {}
			current_matches = str(current_meta.get("source_key") or "") == candidate.source_key
			if not existing and current_matches:
				# A fail-fast SQLite miss may only mean that the daemon currently
				# owns the database lock. Keep already rendered artwork instead of
				# replacing it with candidate-only metadata.
				register_meta_source(candidate.source_key, source)
				return True
			meta = build_epg_skin_data(candidate=candidate, event_row=existing or {})
			if current_matches:
				for key in ("cover_path", "backdrop_path", "titlelogo_path", "image_path", "image_or_picon_path"):
					if not meta.get(key) and current_meta.get(key):
						meta[key] = current_meta.get(key)
			meta.update({
				"service_ref": candidate.service_ref,
				"event_id": candidate.event_id,
				"begin_time": candidate.begin_time,
			})
			source.setMeta(meta)
			register_meta_source(candidate.source_key, source)
			return bool(existing)
		except Exception:
			return False
	status, provider_reason, detail = adapter.epg_provider_skip_reason(candidate)
	queue_required_for_ad_hoc = False
	queue_reason_for_ad_hoc = ""
	if status:
		_mark_provider_skipped(adapter, candidate, status, provider_reason, detail, existing=bool(existing))
		existing = resultsdb.get_epg_event(candidate.source_key)
	else:
		if not existing:
			data = candidate.as_dict()
			data.update({"status": "unknown", "expires_at": candidate.expires_at})
			resultsdb.upsert_epg_event(data)
			existing = resultsdb.get_epg_event(candidate.source_key)
			_queue_event(candidate, reason=reason)
			queue_required_for_ad_hoc = True
			queue_reason_for_ad_hoc = "new"
		else:
			if (existing.get("search_title") or "") != candidate.search_title:
				resultsdb.update_epg_event_search_title(candidate.source_key, candidate.search_title)
				existing = resultsdb.get_epg_event(candidate.source_key)
			queue_required, queue_reason = _queue_needed(existing, now, candidate.search_title)
			if queue_required:
				_queue_event(candidate, reason=queue_reason or reason)
				queue_required_for_ad_hoc = True
				queue_reason_for_ad_hoc = queue_reason or reason

	if queue_required_for_ad_hoc:
		if not _promote_event_next_to_ad_hoc(source, candidate, event_row=existing, reason=reason):
			_request_ad_hoc(source, candidate, reason=queue_reason_for_ad_hoc or reason)
	else:
		# A next-event may already be in the normal queue. When it becomes the
		# current Event_Now, promote it to ad-hoc so standby-only does not block it.
		_promote_event_next_to_ad_hoc(source, candidate, event_row=existing, reason=reason)

	meta = build_epg_skin_data(candidate=candidate, event_row=existing or {})
	meta = _apply_provider_asset_fallback(meta, candidate.source_key, reason=reason)
	_debug(f"UPDATE meta reason={reason} source_key={candidate.source_key} status={(existing or {}).get("status") or "unknown"} json='{(existing or {}).get("json_path") or ""}' cover='{meta.get("cover_path") or ""}' backdrop='{meta.get("backdrop_path") or ""}' image='{meta.get("image_path") or ""}' titlelogo='{meta.get("titlelogo_path") or ""}' provider='{meta.get("provider") or ""}'")
	try:
		meta.update({
			"service_ref": candidate.service_ref,
			"event_id": candidate.event_id,
			"begin_time": candidate.begin_time,
		})
	except Exception:
		pass
	try:
		source.setMeta(meta)
		register_meta_source(candidate.source_key, source)
	except Exception:
		return False

	key_id = id(source)
	last_key = _MetaState.last_keys.get(key_id)
	if last_key != candidate.source_key:
		_MetaState.last_keys[key_id] = candidate.source_key
		_log(f"UPDATE reason={reason} source_key={candidate.source_key} service='{_service_ref_to_string(service)}' title='{candidate.title}' status={(existing or {}).get("status") or "unknown"} cover='{meta.get("cover_path") or ""}'")

	if notify:
		try:
			source.changed((source.CHANGED_ALL,))
		except Exception:
			pass
	return True


def _event_refresh(self):
	# TODO: this will be called on every selection change in EPGSelection.
	return update_source_meta(self, reason="event-refresh", notify=False)


def _eventinfo_refresh(self):
	return update_source_meta(self, reason="eventinfo-refresh", notify=False)


def _eventinfo_update_source(self, ref):
	_debug(f"EVENTINFO updateSource begin ref='{_service_ref_to_string(ref)}' {_describe_source(self)}")
	_clear_source_meta(self, reason="eventinfo-updateSource-preclear", notify=True)
	_old_eventinfo_update_source(self, ref)
	_debug(f"EVENTINFO updateSource after-old ref='{_service_ref_to_string(ref)}' {_describe_source(self)}")
	_update_source_meta_now(self, reason="eventinfo-updateSource", notify=True)


def _serviceevent_refresh(self):
	return update_source_meta(self, reason="serviceevent-refresh", notify=False)


def _serviceevent_new_service(self, ref, event=None):
	_debug(f"SERVICEEVENT newService begin ref='{_service_ref_to_string(ref)}' event='{_safe_event_title(event)}' {_describe_source(self)}")
	_clear_source_meta(self, reason="serviceevent-newService-preclear", notify=True)
	_old_serviceevent_new_service(self, ref, event)
	_debug(f"SERVICEEVENT newService after-old ref='{_service_ref_to_string(ref)}' {_describe_source(self)}")
	_update_source_meta_now(self, reason="serviceevent-newService", notify=True)


def _get_session_source(screen, name):
	try:
		return getattr(screen.session, name, None)
	except Exception:
		return None


def _set_session_source(screen, name, source):
	try:
		setattr(screen.session, name, source)
		return True
	except Exception:
		return False


def _iter_infobar_event_sources(screen):
	seen = set()
	for name in ("Event_Now", "Event_Next"):
		source = None
		try:
			source = screen[name]
		except Exception:
			pass
		if source and id(source) not in seen:
			seen.add(id(source))
			yield name, source
		source = _get_session_source(screen, name)
		if source and id(source) not in seen:
			seen.add(id(source))
			yield f"session.{name}", source


def _clear_infobar_event_sources(screen, reason="infobar-service-preclear"):
	cleared = []
	for name, source in _iter_infobar_event_sources(screen):
		if _clear_source_meta(source, reason=reason, notify=True):
			cleared.append(name)
	if cleared:
		_log(f"INFOBAR sources cleared reason={reason} aliases={",".join(cleared)}")
	return cleared


def _update_infobar_event_sources(screen, reason="infobar-service"):
	for name, source in _iter_infobar_event_sources(screen):
		_update_source_meta_now(source, reason=f"{reason}-{name}", notify=True)


def _infobar_service_event(screen):
	try:
		_debug("INFOBAR service event begin")
		_clear_infobar_event_sources(screen, reason="infobar-service-preclear")
		_update_infobar_event_sources(screen, reason="infobar-service")
	except Exception as err:
		_log(f"INFOBAR service event clear/update failed error={err}", force=True)


def _install_infobar_service_tracker(screen):
	try:
		if getattr(screen, "_e2mdb_component_meta_service_tracker", None):
			return True
		eventmap = {}
		for event_name in ("evStart", "evUpdatedEventInfo", "evUpdateTags", "evUpdatedInfo", "evEnd"):
			try:
				eventmap[getattr(iPlayableService, event_name)] = lambda: _infobar_service_event(screen)
			except Exception:
				pass
		if eventmap:
			screen._e2mdb_component_meta_service_tracker = ServiceEventTracker(screen=screen, eventmap=eventmap)
			_log("INFOBAR service tracker installed", force=True)
		return True
	except Exception as err:
		_log(f"INFOBAR service tracker failed error={err}", force=True)
		return False


def _screen_has_source(screen, name):
	try:
		screen[name]
		return True
	except Exception:
		return False


def _install_infobar_event_sources(screen):
	try:
		from Components.Sources.EventInfo import EventInfo
		attached = []
		if not _screen_has_source(screen, "Event_Now"):
			screen["Event_Now"] = EventInfo(screen.session.nav, EventInfo.NOW)
			attached.append("Event_Now")
		if not _screen_has_source(screen, "Event_Next"):
			screen["Event_Next"] = EventInfo(screen.session.nav, EventInfo.NEXT)
			attached.append("Event_Next")

		# Skins on some OpenATV setups use source="session.Event_Now".
		# Provide those aliases too, but do not replace an existing session source.
		if not _get_session_source(screen, "Event_Now"):
			_set_session_source(screen, "Event_Now", EventInfo(screen.session.nav, EventInfo.NOW))
			attached.append("session.Event_Now")
		if not _get_session_source(screen, "Event_Next"):
			_set_session_source(screen, "Event_Next", EventInfo(screen.session.nav, EventInfo.NEXT))
			attached.append("session.Event_Next")

		for name, source in _iter_infobar_event_sources(screen):
			try:
				_clear_source_meta(source, reason="infobar-source-init-clear", notify=True)
				_update_source_meta_now(source, reason=f"infobar-source-init-{name}", notify=True)
			except Exception as err:
				_debug(f"INFOBAR source init failed name={name} error={err}")
		if attached:
			_log(f"INFOBAR sources attached aliases={",".join(attached)}", force=True)
		_install_infobar_service_tracker(screen)
		return True
	except Exception as err:
		_log(f"INFOBAR source attach failed error={err}", force=True)
		return False


def _infobar_init(self, *args, **kwargs):
	_old_infobar_init(self, *args, **kwargs)
	_install_infobar_event_sources(self)


def _servicelist_refresh(self):
	return update_source_meta(self, reason="servicelist-refresh", notify=False)


def component_meta_supported():
	try:
		from Components.Sources.EventInfo import EventInfo
		from Components.Sources.ServiceEvent import ServiceEvent
		from Components.Sources.Event import Event
		return all(hasattr(cls, "getMeta") and hasattr(cls, "setMeta") and hasattr(cls, "refreshData") for cls in (Event, EventInfo, ServiceEvent))
	except Exception:
		return False


def install_component_meta_hooks():
	global _hooks_installed, _old_eventinfo_update_source, _old_serviceevent_new_service, _old_servicelist_refresh, _old_infobar_init
	if _hooks_installed:
		return True
	try:
		from Components.Sources.EventInfo import EventInfo
		from Components.Sources.ServiceEvent import ServiceEvent
		from Components.Sources.Event import Event
		try:
			from Components.Sources.ServiceList import ServiceList as SourceServiceList
		except Exception:
			SourceServiceList = None
		from Screens.InfoBar import InfoBar
		if not component_meta_supported():
			_log("HOOK skipped reason=component-meta-not-supported", force=True)
			return False
#		_old_eventinfo_update_source = EventInfo.updateSource  # TODO maybe not needed
#		_old_serviceevent_new_service = ServiceEvent.newService  # TODO maybe not needed
		_old_infobar_init = InfoBar.__init__
		EventInfo.refreshData = _eventinfo_refresh
#		EventInfo.updateSource = _eventinfo_update_source  # TODO maybe not needed
		ServiceEvent.refreshData = _serviceevent_refresh
		Event.refreshData = _event_refresh  # Some skins use Event instead of ServiceEvent for the infobar sources. Hook it too just in case.
#		ServiceEvent.newService = _serviceevent_new_service  # TODO maybe not needed
		service_list_ready = bool(SourceServiceList and all(hasattr(SourceServiceList, name) for name in ("getMeta", "setMeta", "refreshData")))
		if service_list_ready:
			_old_servicelist_refresh = SourceServiceList.refreshData
			SourceServiceList.refreshData = _servicelist_refresh
#		InfoBar.__init__ = _infobar_init  # TODO maybe not needed
		_hooks_installed = True
		_log(f"HOOK installed mode=component-meta-event-transition-adhoc eventinfo-aliases=Event_Now,Event_Next serviceListMeta={service_list_ready} old-infobar-hook-not-required", force=True)
		return True
	except Exception as err:
		_log(f"HOOK failed error={err}", force=True)
		return False
