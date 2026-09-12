########################################################################################################
# e2MDB Live/EPG bridge                                                                                #
# -----------------------------------------------------------------------------------------------------#
# This module hooks OpenATV EPGSelection and stores lightweight EPG event candidates in the shared       #
# e2MDB database. It deliberately does not perform provider lookups in the GUI thread.                  #
########################################################################################################

# PYTHON IMPORTS
from os import makedirs
from json import load
from os.path import isfile, join
from threading import Lock
from time import localtime, strftime, time

# ENIGMA IMPORTS
from enigma import eTimer
from Components.config import config

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBLiveEPG
from .E2MDBPriority import PRIORITY_EPG_OPEN, PRIORITY_EPG_SELECTION
from .E2MDBSkin import apply_epg_skin_data, build_epg_skin_data, clear_epg_skin_sources, ensure_epg_skin_sources


_old_epg_selection_init = None
_old_epg_selection_on_selection_changed = None
_epg_hooks_installed = False
_active_epg_screen_count = 0
_resultsdb_schema_ready_path = ""
_resultsdb_schema_lock = Lock()
EPG_SELECTION_UPDATE_DELAY_MS = 350
EPG_QUEUE_LIMIT = 25


def set_epg_screen_active(active=True):
	"""Track whether an OpenATV EPG screen is currently open."""
	global _active_epg_screen_count
	if active:
		_active_epg_screen_count += 1
	else:
		_active_epg_screen_count = max(0, _active_epg_screen_count - 1)
	return _active_epg_screen_count


def is_epg_screen_active():
	return _active_epg_screen_count > 0


def active_epg_screen_count():
	return _active_epg_screen_count


def is_epg_worker_paused_for_open_epg():
	"""Return True when EPG screens must stay cache-only and must not feed/start workers."""
	return is_epg_screen_active()


def _json_has_image_source(json_path, pic_type):
	"""Return True when a stored metadata JSON can actually provide or retry a missing image type."""
	data = _load_metadata_json(json_path)
	return _json_data_has_image_source(data, pic_type)


def _load_metadata_json(json_path):
	try:
		if not json_path or not isfile(json_path):
			return {}
		with open(json_path, "r") as handle:
			data = load(handle)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _json_data_has_image_source(data, pic_type):
	"""Check one already-loaded provider JSON dictionary for an image type."""
	if not isinstance(data, dict) or not data:
		return False
	keys = {
		"cover": ("cover_url", "cover_path", "series_cover_url", "series_poster_url", "poster_url", "poster_path"),
		"backdrop": ("backdrop_url", "backdrop_path", "series_backdrop_url", "series_backdrop_path", "fanart_url", "fanart_path"),
		"titlelogo": ("titlelogo_url", "logo_url", "clearlogo_url", "titlelogo_path", "logo_path"),
		"image": ("image_url", "preview_url", "still_url", "image_path", "preview_path", "still_path", "episode_image_url", "episode_still_url", "episode_path"),
	}.get(pic_type, (f"{pic_type}_url", f"{pic_type}_path"))
	checks = [data]
	for nested_key in ("best", "artwork"):
		nested = data.get(nested_key)
		if isinstance(nested, dict):
			checks.append(nested)
	if any(mapping.get(key) for mapping in checks for key in keys):
		return True
	if pic_type == "backdrop":
		lookup_text = str(data.get("artwork_lookup_version") or "").strip()
		lookup_version = int(lookup_text) if lookup_text.isdigit() else 0
		best = data.get("best") if isinstance(data.get("best"), dict) else data
		provider = str(best.get("provider") or data.get("provider") or "").strip().lower()
		media_type = str(best.get("media_type") or data.get("media_type") or "").strip().lower()
		# Older provider-result JSON was written before TVDB /series/{id}/artworks
		# and alternate-provider backdrop fill were available. One retry is useful;
		# new JSON writes artwork_lookup_version >= 2 and will not loop forever.
		if lookup_version < 2 and provider in ("tvdb", "tmdb", "tvmaze") and media_type == "series":
			return True
	return False


def _actionable_missing_images(existing, image_types=("cover", "backdrop", "image")):
	"""Return only missing artwork types that can be downloaded or restored from JSON.

	A fresh matched event may legitimately have no cover/backdrop URL, e.g. when
	TVSpielfilm only supplied an editorial still and IMDb has no artwork. Such
	missing fields are not actionable and must not keep re-queuing ad-hoc work.
	"""
	if not existing:
		return []
	column_map = {
		"cover": "metadata_cover_path",
		"backdrop": "metadata_backdrop_path",
		"titlelogo": "metadata_logo_path",
		"image": "metadata_image_path",
	}
	json_path = existing.get("json_path") or ""
	json_data = _load_metadata_json(json_path)
	missing = []
	for pic_type in image_types:
		column = column_map.get(pic_type)
		if not column:
			continue
		if existing.get(column):
			continue
		if _json_data_has_image_source(json_data, pic_type):
			missing.append(pic_type)
	return missing


class E2MDBEPGLogMixin:
	MODULE_NAME = "[e2MDB][EPG]"

	@staticmethod
	def log(message, force=False):
		write_log(E2MDBEPGLogMixin.MODULE_NAME, message)


def _configured_cache_path():
	"""Return the configured e2MDB cache root used for results.db."""
	try:
		cache_dir = config.plugins.e2mdb.cachePath.value or "/media/hdd/"
	except Exception:
		cache_dir = "/media/hdd/"
	cache_dir = cache_dir.rstrip("/")
	return "/e2MDB" if cache_dir == "" else join(cache_dir, "e2MDB")


def _set_source_meta(source, meta, reason="selection"):
	try:
		if hasattr(source, "setMeta"):
			source_key = str((meta or {}).get("source_key") or "")
			if not source_key:
				try:
					from .E2MDBBackendNotify import unregister_meta_source
					old_source_key = str(getattr(source, "_e2mdb_registered_source_key", "") or "")
					if old_source_key:
						unregister_meta_source(old_source_key, source)
				except Exception:
					pass
			source.setMeta(meta or {})
			# OpenATV Event and ServiceEvent sources already invalidate their
			# renderers from setMeta() when a source_key is present. Calling
			# changed() again doubles the renderer work for every EPG selection.
			if source_key:
				try:
					from .E2MDBBackendNotify import register_meta_source
					register_meta_source(source_key, source)
				except Exception:
					pass
				return True
			try:
				source.changed((source.CHANGED_CLEAR,))
			except Exception:
				pass
			return True
	except Exception as err:
		E2MDBEPGLogMixin.log(f"META source update failed reason={reason} error={err}")
	return False


def _clear_standard_epg_meta(screen, reason="clear"):
	meta = {
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
	for source_name in ("Event", "Service"):
		try:
			source = screen[source_name]
		except Exception:
			continue
		_set_source_meta(source, meta, reason=reason)


def _set_standard_epg_sources_deferred(screen, deferred=True):
	"""Mark only this EPG screen's standard sources as transient selection sources."""
	for source_name in ("Event", "Service"):
		try:
			source = screen[source_name]
		except Exception:
			continue
		try:
			setattr(source, "_e2mdb_epg_selection_deferred", bool(deferred))
		except Exception:
			pass


def _unregister_standard_epg_sources(screen):
	"""Drop backend-notify registrations owned by a closing EPG screen."""
	try:
		from .E2MDBBackendNotify import unregister_meta_source
	except Exception:
		return
	for source_name in ("Event", "Service"):
		try:
			source = screen[source_name]
			source_key = str(getattr(source, "_e2mdb_registered_source_key", "") or "")
			if source_key:
				unregister_meta_source(source_key, source)
		except Exception:
			pass


def _apply_standard_epg_meta(screen, event=None, service=None, candidate=None, event_row=None, skin_data=None, reason="selection"):
	"""Attach selected EPG metadata to the normal OpenATV Event/Service sources.

	This lets standard EPG skins add optional panels such as:
	  <widget source="Event" render="Pixmap" condition="config.plugins.e2mdb.epgMetaEnabled.value">
	      <convert type="E2MDBEventInfo">Cover</convert>
	  </widget>
	without requiring any E2MDB-specific EPG screen aliases.
	"""
	try:
		data = dict(skin_data or build_epg_skin_data(candidate=candidate, event_row=event_row or {}))
	except Exception:
		data = {}
	if not data:
		_clear_standard_epg_meta(screen, reason=reason)
		return False
	meta = {
		"source_key": data.get("source_key") or getattr(candidate, "source_key", "") or "",
		"service_ref": getattr(candidate, "service_ref", "") or (event_row or {}).get("service_ref") or "",
		"event_id": getattr(candidate, "event_id", 0) or (event_row or {}).get("event_id") or 0,
		"begin_time": getattr(candidate, "begin_time", 0) or (event_row or {}).get("begin_time") or 0,
		"title": data.get("title") or "",
		"subtitle": data.get("subtitle") or "",
		"overview": data.get("overview") or "",
		"description": data.get("overview") or "",
		"infoline": data.get("infoline") or "",
		"status_text": data.get("status_text") or "",
		"provider": data.get("provider") or "",
		"media_type": data.get("media_type") or "",
		"genres": data.get("genres") or "",
		"runtime": data.get("runtime") or "",
		"rating": data.get("rating") or "",
		"year": data.get("year") or "",
		"cast_short": data.get("cast_short") or "",
		"crew_short": data.get("crew_short") or "",
		"cover_path": data.get("cover_path") or "",
		"backdrop_path": data.get("backdrop_path") or "",
		"titlelogo_path": data.get("titlelogo_path") or "",
		"image_path": data.get("image_path") or "",
		"image_or_picon_path": data.get("image_or_picon_path") or "",
	}
	updated = False
	for source_name in ("Event", "Service"):
		try:
			source = screen[source_name]
		except Exception:
			continue
		try:
			setattr(source, "event", event)
		except Exception:
			pass
		try:
			setattr(source, "service", getattr(service, "ref", service))
		except Exception:
			pass
		updated = _set_source_meta(source, meta, reason=reason) or updated
	return updated


def _ensure_resultsdb_ready(context="", log_ready=True):
	"""Ensure resultsdb has a valid path before Live/EPG code touches SQLite."""
	global _resultsdb_schema_ready_path
	try:
		db_path = getattr(resultsdb, "db_path", None)
		if db_path and db_path == _resultsdb_schema_ready_path:
			if log_ready:
				E2MDBEPGLogMixin.log(f"DB READY context={context or 'unknown'} db_path='{db_path}' schema=cached")
			return True

		# Schema creation/migration is startup work. Several GUI bridges call this
		# helper before reading metadata, so cache the completed path and keep DDL
		# completely out of selection/scroll callbacks.
		with _resultsdb_schema_lock:
			db_path = getattr(resultsdb, "db_path", None)
			if not db_path:
				cache_path = _configured_cache_path()
				makedirs(cache_path, exist_ok=True)
				resultsdb.set_path(cache_path)
				db_path = getattr(resultsdb, "db_path", None)
			elif db_path != _resultsdb_schema_ready_path:
				resultsdb.ensure_live_epg_schema()
			if not db_path:
				raise RuntimeError("results database path was not initialized")
			_resultsdb_schema_ready_path = db_path
		if log_ready:
			E2MDBEPGLogMixin.log(f"DB READY context={context or 'unknown'} db_path='{db_path}' schema=checked")
		return True
	except Exception as e:
		E2MDBEPGLogMixin.log(f"DB NOT READY context={context or 'unknown'} error={e}", force=True)
		return False


class E2MDBEPGSelectionBridge:
	"""Small controller attached to one OpenATV EPGSelection screen instance."""

	MODULE_NAME = "[e2MDB][EPG]"

	def __init__(self, screen):
		self.screen = screen
		self.adapter = E2MDBLiveEPG()
		self.last_source_key = ""
		self.last_processed_source_key = ""
		self.last_processed_time = 0
		self.db_ready_logged = False
		self.events_seen = set()
		self.db_insert_count = 0
		self.db_hit_count = 0
		self.queue_upsert_count = 0
		self.queue_update_count = 0
		self.queue_skip_count = 0
		self.queue_limit_skip_count = 0
		self.provider_skip_count = 0
		self._active_registered = False
		self._selection_update_timer = eTimer()
		self._selection_update_timer.callback.append(self._run_deferred_selection)
		self._deferred_selection_reason = "selection"

	def schedule_selection_update(self, reason="selection"):
		"""Debounce metadata DB reads while the user scrolls through EPG lists.

		The actual selection is read when the timer fires, so fast cursor moves only
		process the final highlighted event. This keeps EPG screens cache-only and
		prevents repeated SQLite reads during rapid navigation.
		"""
		self._deferred_selection_reason = reason or "selection"
		delay = EPG_SELECTION_UPDATE_DELAY_MS
		try:
			self._selection_update_timer.stop()
		except Exception:
			pass
		if delay <= 0:
			self._run_deferred_selection()
		else:
			try:
				self._selection_update_timer.start(delay, True)
			except Exception:
				self._run_deferred_selection()

	def _run_deferred_selection(self):
		try:
			self._selection_update_timer.stop()
		except Exception:
			pass
		reason = self._deferred_selection_reason or "selection"
		try:
			self.handle_selection(reason=reason)
		except Exception as err:
			self.log(f"DEFERRED selection failed reason={reason} error={err}")

	def log(self, message):
		write_log(self.MODULE_NAME, message)

	def _short_ref(self, service_ref):
		service_ref = service_ref or ""
		return service_ref[:72] + "..." if len(service_ref) > 75 else service_ref

	def _format_time(self, timestamp):
		try:
			return strftime("%Y-%m-%d %H:%M:%S", localtime(int(timestamp or 0)))
		except Exception:
			return str(timestamp or 0)

	def _get_current_epg_entry(self):
		try:
			active_list = getattr(self.screen, "activeList", "")
			if getattr(self.screen, "type", None) != self._epg_type_vertical():
				active_list = ""
			list_name = f"list{active_list}"
			try:
				epg_list = self.screen[list_name]
			except Exception:
				self.log(f"SKIP no EPG list component='{list_name}'")
				return None, None, "", ""
			cur = epg_list.getCurrent()
			if not cur:
				self.log(f"SKIP empty current EPG selection list='{list_name}'")
				return None, None, "", list_name
			event = cur[0] if len(cur) > 0 else None
			service = cur[1] if len(cur) > 1 else None
			if service is None:
				service = getattr(self.screen, "currentService", None)
			if service is None:
				try:
					service = self.screen.session.nav.getCurrentlyPlayingServiceOrGroup()
				except Exception:
					service = None
			return event, service, self._service_name(service), list_name
		except Exception as e:
			self.log(f"ERROR reading current EPG selection: {e}")
			return None, None, "", ""

	def _epg_type_vertical(self):
		try:
			from Components.EpgList import EPG_TYPE_VERTICAL
			return EPG_TYPE_VERTICAL
		except Exception:
			return -1

	def _service_name(self, service):
		try:
			name = service.getServiceName() if service else ""
			return name or ""
		except Exception:
			pass
		try:
			return service.toString() if service else ""
		except Exception:
			return ""

	def _queue_needed(self, existing, now, candidate_search_title=""):
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

	def _queue_event(self, candidate, priority, reason):
		priority = int(priority or 0)
		reason = reason or "selection"
		if is_epg_worker_paused_for_open_epg():
			self.queue_skip_count += 1
			self.log(f"QUEUE SKIP source_key={candidate.source_key} reason=epg-screen-open requested_reason={reason} priority={priority}")
			return False
		# Never revive a queue item when the EPG event already has fresh provider/no-match data.
		# This can happen during GraphicalEPG open/selection duplicate callbacks.
		existing_event = resultsdb.get_epg_event(candidate.source_key)
		if existing_event:
			queue_needed, queue_reason = self._queue_needed(existing_event, int(time()))
			if not queue_needed:
				self.queue_skip_count += 1
				self.log(f"QUEUE SKIP source_key={candidate.source_key} reason={queue_reason} event_status={existing_event.get("status") or "unknown"} requested_priority={priority}")
				return True
		existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
		if existing_queue:
			existing_priority = int(existing_queue.get("priority") or 0)
			existing_state = existing_queue.get("state") or "pending"
			if existing_state == "pending" and existing_priority >= priority:
				self.queue_skip_count += 1
				self.log(f"QUEUE SKIP source_key={candidate.source_key} existing_state={existing_state} existing_priority={existing_priority} requested_priority={priority} reason={reason}")
				return True
		elif self.queue_upsert_count >= EPG_QUEUE_LIMIT:
			self.queue_limit_skip_count += 1
			self.log(f"QUEUE LIMIT source_key={candidate.source_key} limit={EPG_QUEUE_LIMIT} reason={reason} title='{candidate.title}'")
			return False

		ok = resultsdb.upsert_fetch_queue({
			"source_key": candidate.source_key,
			"source_type": candidate.source_type,
			"service_ref": candidate.service_ref,
			"title": candidate.title,
			"search_title": getattr(candidate, "search_title", candidate.title),
			"begin_time": candidate.begin_time,
			"event_end": candidate.event_end,
			"priority": priority,
			"reason": reason,
			"state": "pending",
		})
		action = "UPSERT"
		if existing_queue:
			action = "UPDATE"
		if ok:
			if existing_queue:
				self.queue_update_count += 1
			else:
				self.queue_upsert_count += 1
		self.log(f"QUEUE {action if ok else "FAILED"} source_key={candidate.source_key} priority={priority} reason={reason} title='{candidate.title}'")
		return ok

	def _mark_provider_skipped(self, candidate, status, reason, detail="", existing=False):
		status = status or "skipped"
		reason = reason or "provider-skip"
		expires_at = self.adapter.default_expiry(candidate.event_end, status=status)
		data = candidate.as_dict()
		data.update({
			"status": status,
			"confidence": 0.0,
			"json_path": "",
			"expires_at": expires_at,
		})
		if existing:
			resultsdb.update_epg_event_search_title(candidate.source_key, getattr(candidate, "search_title", candidate.title))
			resultsdb.update_epg_event_status(candidate.source_key, status, confidence=0.0, json_path="", expires_at=expires_at)
		else:
			resultsdb.upsert_epg_event(data)
		queue_item = resultsdb.get_fetch_queue_item(candidate.source_key)
		if queue_item:
			resultsdb.update_fetch_queue_state(candidate.source_key, status, last_error=f"{reason}:{detail or ''}")
		self.provider_skip_count += 1
		self.log(f"PROVIDER SKIP source_key={candidate.source_key} status={status} reason={reason} detail='{detail or ""}' expires='{self._format_time(expires_at)}' title='{candidate.title}' search_title='{getattr(candidate, "search_title", candidate.title)}'")
		return True

	def register_open(self):
		if not self._active_registered:
			self._active_registered = True
			count = set_epg_screen_active(True)
			self.log(f"SCREEN ACTIVE count={count}")

	def handle_open(self):
		"""Bound callback for Screen.onLayoutFinish.

		OpenATV executes non-bound callbacks in onLayoutFinish as source code via exec().
		Therefore this must be appended as a real bound method, not as lambda/partial.
		"""
		self.schedule_selection_update(reason="open")

	def handle_close(self):
		"""Log a compact per-screen summary for debugging queue pressure."""
		try:
			self._selection_update_timer.stop()
		except Exception:
			pass
		_set_standard_epg_sources_deferred(self.screen, False)
		_unregister_standard_epg_sources(self.screen)
		if self._active_registered:
			self._active_registered = False
			count = set_epg_screen_active(False)
		else:
			count = active_epg_screen_count()
		self.log(f"CLOSE summary seen={len(self.events_seen)} inserts={self.db_insert_count} hits={self.db_hit_count} provider_skips={self.provider_skip_count} queue_new={self.queue_upsert_count} queue_updates={self.queue_update_count} queue_skips={self.queue_skip_count} queue_limit_skips={self.queue_limit_skip_count} activeScreens={count}")

	def _apply_epg_preview(self, candidate=None, event_row=None, reason="selection", event=None, service=None):
		"""Update optional e2MDB skin sources on any OpenATV EPGSelection screen."""
		try:
			ensure_epg_skin_sources(self.screen)
		except Exception as err:
			self.log(f"PREVIEW source attach failed reason={reason} error={err}")
			return False
		if candidate is None:
			try:
				clear_epg_skin_sources(self.screen)
			except Exception:
				pass
			_clear_standard_epg_meta(self.screen, reason=reason)
			return False
		try:
			row = event_row or {}
			if not row:
				row = candidate.as_dict()
			skin_data = build_epg_skin_data(candidate=candidate, event_row=row)
			apply_epg_skin_data(self.screen, skin_data)
			_apply_standard_epg_meta(self.screen, event=event, service=service, candidate=candidate, event_row=row, skin_data=skin_data, reason=reason)
			return True
		except Exception as err:
			self.log(f"PREVIEW update failed reason={reason} error={err}")
			try:
				clear_epg_skin_sources(self.screen)
			except Exception:
				pass
			return False

	def _handle_cache_only_selection(self, candidate, event, service, reason="selection"):
		"""When EPG worker pause is active, only read cached metadata and never mutate queues.

		This keeps cursor movement in EPG screens smooth: no queue upserts, no touch writes,
		no provider-skip writes and no ad-hoc worker promotion while an EPG screen is open.
		"""
		existing = None
		try:
			existing = resultsdb.get_epg_event_readonly(candidate.source_key)
		except Exception as err:
			self.log(f"CACHE-ONLY DB lookup failed source_key={candidate.source_key} reason={reason} error={err}")
		self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
		if candidate.source_key != self.last_source_key:
			self.last_source_key = candidate.source_key
			self.log(f"CACHE-ONLY source_key={candidate.source_key} reason=epg-screen-open selection_reason={reason} status={(existing or {}).get("status") or "missing"} title='{candidate.title}'")
		return True

	def handle_selection(self, reason="selection"):
		if not config.plugins.e2mdb.epgMetaEnabled.value:
			if reason == "open":
				self.log("OPEN SKIP Live/EPG metadata cache disabled")
			self._apply_epg_preview(None, None, reason=reason)
			return
		if not _ensure_resultsdb_ready(f"selection-{reason}", log_ready=not self.db_ready_logged):
			self.log(f"SKIP database not ready reason={reason}")
			self._apply_epg_preview(None, None, reason=reason)
			return
		self.db_ready_logged = True
		event, service, service_name, list_name = self._get_current_epg_entry()
		if event is None or service is None:
			self.log(f"SKIP no usable event/service reason={reason} list={list_name}")
			self._apply_epg_preview(None, None, reason=reason)
			return

		candidate = self.adapter.event_to_candidate(service, event, service_name=service_name, source_type=self.adapter.SOURCE_EPG)
		if not candidate.title:
			self.log(f"SKIP event without title service='{self._short_ref(candidate.service_ref)}' reason={reason}")
			self._apply_epg_preview(None, None, reason=reason)
			return

		if is_epg_worker_paused_for_open_epg():
			self._handle_cache_only_selection(candidate, event, service, reason=reason)
			return

		self.events_seen.add(candidate.source_key)
		now = int(time())
		existing = resultsdb.get_epg_event(candidate.source_key)
		if reason == "selection" and candidate.source_key == self.last_source_key:
			self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
			return
		if candidate.source_key == self.last_processed_source_key and now - int(self.last_processed_time or 0) <= 2:
			# OpenATV GraphicalEPG may fire selection/open callbacks for the same event during screen creation.
			# Keep the higher open priority, but still refresh the optional preview sources.
			if reason == "open":
				self._queue_event(candidate, priority=PRIORITY_EPG_OPEN, reason="open-duplicate-priority")
			self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
			return
		self.last_source_key = candidate.source_key
		self.last_processed_source_key = candidate.source_key
		self.last_processed_time = now

		self.log(f"EVENT source_key={candidate.source_key} list={list_name} reason={reason} service='{self._short_ref(candidate.service_ref)}' begin='{self._format_time(candidate.begin_time)}' duration={candidate.duration} title='{candidate.title}' search_title='{getattr(candidate, "search_title", candidate.title)}'")

		skip_status, skip_reason, skip_detail = self.adapter.epg_provider_skip_reason(candidate)

		if existing:
			self.db_hit_count += 1
			resultsdb.touch_epg_event(candidate.source_key, now)
			candidate_search_title = getattr(candidate, "search_title", candidate.title)
			queue_needed, queue_reason = self._queue_needed(existing, now, candidate_search_title)
			if skip_status and queue_needed:
				self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=True)
				existing = resultsdb.get_epg_event(candidate.source_key) or existing
				self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
				return
			if candidate_search_title and existing.get("search_title") != candidate_search_title:
				resultsdb.update_epg_event_search_title(candidate.source_key, candidate_search_title)
				existing = resultsdb.get_epg_event(candidate.source_key) or existing
			if queue_reason == "improved-search-title":
				resultsdb.update_epg_event_status(candidate.source_key, "unknown", confidence=0.0, json_path="", expires_at=candidate.expires_at)
				existing = resultsdb.get_epg_event(candidate.source_key) or existing
				self.log(f"DB RESET source_key={candidate.source_key} reason=improved-search-title old_search_title='{existing.get("search_title") or ""}' new_search_title='{candidate_search_title}'")
			self.log(f"DB HIT id={existing.get("id")} status={existing.get("status") or "unknown"} json='{existing.get("json_path") or ""}' expires='{self._format_time(existing.get("expires_at") or 0)}' search_title='{candidate_search_title}' queue_needed={queue_needed} queue_reason={queue_reason}")
			if queue_needed:
				self._queue_event(candidate, priority=PRIORITY_EPG_OPEN if reason == "open" else PRIORITY_EPG_SELECTION, reason=queue_reason)
			else:
				self.log(f"QUEUE SKIP source_key={candidate.source_key} reason={queue_reason}")
			self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
			return

		if skip_status:
			self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=False)
			self.db_insert_count += 1
			existing = resultsdb.get_epg_event(candidate.source_key)
			self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
			return

		event_id = resultsdb.upsert_epg_event(candidate.as_dict())
		self.db_insert_count += 1
		self.log(f"DB INSERT id={event_id} source_key={candidate.source_key} expires='{self._format_time(candidate.expires_at)}' service_name='{candidate.service_name}'")
		existing = resultsdb.get_epg_event(candidate.source_key)
		self._apply_epg_preview(candidate, existing, reason=reason, event=event, service=service)
		self._queue_event(candidate, priority=PRIORITY_EPG_OPEN if reason == "open" else PRIORITY_EPG_SELECTION, reason=reason)


def _patched_epg_selection_init(self, *args, **kwargs):
	_old_epg_selection_init(self, *args, **kwargs)
	try:
		ensure_epg_skin_sources(self)
	except Exception as err:
		E2MDBEPGLogMixin.log(f"ERROR attaching EPG preview sources: {err}")
	_set_standard_epg_sources_deferred(self, True)
	try:
		self._e2mdb_epg_bridge = E2MDBEPGSelectionBridge(self)
		self._e2mdb_epg_bridge.register_open()
		E2MDBEPGLogMixin.log(f"OPEN type={getattr(self, "type", "?")} skin={getattr(self, "skinName", "")} metaEnabled={config.plugins.e2mdb.epgMetaEnabled.value}")
		if hasattr(self, "onLayoutFinish"):
			# Screen.createGUIScreen() calls exec() for non-bound callbacks.
			# Keep this as a bound method to avoid crashing during skin creation.
			self.onLayoutFinish.append(self._e2mdb_epg_bridge.handle_open)
			E2MDBEPGLogMixin.log(f"OPEN callback attached method={self._e2mdb_epg_bridge.handle_open.__name__}")
		else:
			self._e2mdb_epg_bridge.handle_open()
		if hasattr(self, "onClose"):
			self.onClose.append(self._e2mdb_epg_bridge.handle_close)
	except Exception as e:
		E2MDBEPGLogMixin.log(f"ERROR attaching EPG bridge: {e}")


def _patched_epg_selection_on_selection_changed(self):
	_old_epg_selection_on_selection_changed(self)
	try:
		if not config.plugins.e2mdb.epgMetaEnabled.value:
			return
		bridge = getattr(self, "_e2mdb_epg_bridge", None)
		if bridge is None:
			bridge = E2MDBEPGSelectionBridge(self)
			self._e2mdb_epg_bridge = bridge
		bridge.schedule_selection_update(reason="selection")
	except Exception as e:
		E2MDBEPGLogMixin.log(f"ERROR processing selection: {e}")


def install_epg_selection_hooks():
	"""Install OpenATV EPGSelection hooks once per Enigma2 session."""
	global _old_epg_selection_init, _old_epg_selection_on_selection_changed, _epg_hooks_installed
	if _epg_hooks_installed:
		return True
	try:
		from Screens.EpgSelection import EPGSelection
		_old_epg_selection_init = EPGSelection.__init__
		_old_epg_selection_on_selection_changed = EPGSelection.onSelectionChanged
		EPGSelection.__init__ = _patched_epg_selection_init
		EPGSelection.onSelectionChanged = _patched_epg_selection_on_selection_changed
		_epg_hooks_installed = True
		reset_count = "n/a"
		if _ensure_resultsdb_ready("hook-install"):
			try:
				reset_count = resultsdb.reset_running_queue()
			except Exception as db_error:
				E2MDBEPGLogMixin.log(f"HOOK installed; queue reset failed: {db_error}", force=True)
		E2MDBEPGLogMixin.log(f"HOOK installed; metaEnabled={config.plugins.e2mdb.epgMetaEnabled.value} db_path='{getattr(resultsdb, "db_path", None)}' reset_running_queue={reset_count}", force=True)
		return True
	except Exception as e:
		E2MDBEPGLogMixin.log(f"ERROR installing EPGSelection hook: {e}")
		return False
