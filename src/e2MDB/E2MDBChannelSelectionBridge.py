########################################################################################################
# e2MDB Live/EPG ChannelSelection bridge                                                               #
# -----------------------------------------------------------------------------------------------------#
# Adds e2MDB Live/EPG skin sources to OpenATV ChannelSelection screens. The channel list focuses        #
# services, not files, so this bridge resolves the current/now EPG event for the selected service and  #
# feeds the existing Live/EPG cache pipeline. Provider work is queued only; no ad-hoc lookup runs while #
# the user scrolls through the channel list.                                                           #
########################################################################################################

# PYTHON IMPORTS
from threading import Lock, Thread
from time import localtime, strftime, time

# ENIGMA IMPORTS
from Components.config import config
from enigma import eEPGCache, eServiceReference, eTimer

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBEPGCandidate, E2MDBLiveEPG
from .E2MDBEPGBridge import _actionable_missing_images, _apply_standard_epg_meta, _clear_standard_epg_meta, _ensure_resultsdb_ready, _unregister_standard_epg_sources
from .E2MDBPriority import PRIORITY_ADHOC_NOW, PRIORITY_CHANNEL_SELECTION, PRIORITY_SERVICELIST_NEXT, PRIORITY_SERVICELIST_NOW, clamp_priority


_old_channel_selection_init = None
_old_selection_event_info_update = None
_channel_hooks_installed = False
CHANNEL_SELECTION_UPDATE_DELAY_MS = 350
CHANNEL_QUEUE_LIMIT = 15
CHANNEL_PREFETCH_TTL = 180
CHANNEL_SELECTION_ROW_CACHE_TTL = 60
CHANNEL_SELECTION_MISS_CACHE_TTL = 2
CHANNEL_BACKGROUND_TRIGGER_INTERVAL = 180
CHANNEL_VISIBLE_PREFETCH_INTERVAL = 15
CHANNEL_VISIBLE_PREFETCH_DELAY_MS = 1200
CHANNEL_PREVIEW_REFRESH_DELAY_MS = 250


class E2MDBChannelSelectionBridge:
	"""Controller attached to one OpenATV ChannelSelection instance."""

	MODULE_NAME = "[e2MDB][CHANNEL]"

	def __init__(self, screen):
		self.screen = screen
		self.adapter = E2MDBLiveEPG()
		self.db_ready_logged = False
		self.last_source_key = ""
		self.last_processed_time = 0
		self.seen_keys = set()
		self.insert_count = 0
		self.hit_count = 0
		self.queue_new_count = 0
		self.queue_update_count = 0
		self.queue_skip_count = 0
		self.queue_limit_skip_count = 0
		self.provider_skip_count = 0
		self.skip_count = 0
		self.prefetch_requested = {}
		self.prefetch_skip_updates = 2
		self.selection_row_cache = {}
		self.visible_preview_source_keys = set()
		self.last_background_trigger_time = 0
		self.last_visible_prefetch_trigger_time = 0
		self.visible_prefetch_pending = False
		self.visible_prefetch_reason = ""
		self.visible_prefetch_block_key = ""
		self.last_visible_prefetch_block_key = ""
		self.prefetch_write_lock = Lock()
		self.prefetch_write_pending = []
		self.prefetch_write_thread = None
		self.persisted_selected_source_key = ""
		self.visible_prefetch_timer = eTimer()
		try:
			self.visible_prefetch_timer.callback.append(self._run_visible_window_prefetch)
		except Exception:
			pass
		self.selection_update_timer = eTimer()
		try:
			self.selection_update_timer.callback.append(self._run_deferred_selection_update)
		except Exception:
			pass
		self.deferred_selection_reason = "selection"
		self.selection_update_pending = False
		self.closed = False
		self.preview_refresh_source_key = ""
		self.preview_refresh_reason = ""
		self.preview_refresh_pending = False
		self.preview_refresh_timer = eTimer()
		try:
			self.preview_refresh_timer.callback.append(self._run_service_list_refresh)
		except Exception:
			pass
		self.service_list_refresh_callback = self._service_list_metadata_updated
		try:
			from .E2MDBServiceListPreview import registerE2MDBServiceListRefreshCallback
			registerE2MDBServiceListRefreshCallback(self.service_list_refresh_callback)
		except Exception as err:
			self.log(f"SERVICELIST refresh callback registration failed error={err}", force=True)

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			return strftime("%Y-%m-%d %H:%M:%S", localtime(int(timestamp or 0)))
		except Exception:
			return str(timestamp or 0)

	def _enabled(self):
		try:
			return bool(config.plugins.e2mdb.epgChannelSelectionEnabled.value)
		except Exception:
			return True

	def _mark_standard_sources_deferred(self, reason="selection"):
		"""Keep Event/Service converters cache-only until the selection is stable.

		SelectionEventInfo.updateEventInfo() changes the normal OpenATV Event source
		immediately. Skins that use E2MDBEventInfo on this source can therefore call
		Event.getMeta() before our delayed ChannelSelection update runs. The marker is
		read by E2MDBComponentMeta and returns cheap event/picon metadata without any
		SQLite lookup while the user scrolls quickly.
		"""
		try:
			ref = self._current_service_ref()
		except Exception:
			ref = None
		for source_name in ("Event", "Service"):
			try:
				source = self.screen[source_name]
			except Exception:
				continue
			try:
				setattr(source, "_e2mdb_channel_selection_deferred", True)
				setattr(source, "_e2mdb_channel_selection_deferred_reason", reason or "selection")
			except Exception:
				pass
			try:
				setattr(source, "service", ref)
			except Exception:
				pass

	def _clear_standard_sources_deferred(self):
		for source_name in ("Event", "Service"):
			try:
				source = self.screen[source_name]
			except Exception:
				continue
			try:
				setattr(source, "_e2mdb_channel_selection_deferred", False)
			except Exception:
				pass

	def schedule_update(self, reason="selection"):
		if self.closed:
			return
		self.deferred_selection_reason = reason or "selection"
		self.selection_update_pending = True
		# Do not invalidate the full ServiceList while key-repeat scrolling is
		# active. Keep a pending backend refresh and release it only after this
		# same selection debounce has reached a stable row.
		if self.preview_refresh_pending:
			try:
				self.preview_refresh_timer.stop()
			except Exception:
				pass
		delay = CHANNEL_SELECTION_UPDATE_DELAY_MS
		try:
			self.selection_update_timer.stop()
		except Exception:
			pass
		if delay <= 0:
			self._run_deferred_selection_update()
		else:
			try:
				self.selection_update_timer.start(delay, True)
			except Exception:
				self._run_deferred_selection_update()

	def _run_deferred_selection_update(self):
		try:
			self.selection_update_timer.stop()
		except Exception:
			pass
		self.selection_update_pending = False
		reason = self.deferred_selection_reason or "selection"
		try:
			self.update(reason=reason)
		except Exception as err:
			self.log(f"DEFERRED selection update failed reason={reason} error={err}", force=True)
		if self.preview_refresh_pending and not self.closed:
			try:
				self.preview_refresh_timer.start(CHANNEL_PREVIEW_REFRESH_DELAY_MS, True)
			except Exception:
				self._run_service_list_refresh()

	def _service_list_metadata_updated(self, source_key="", reason="backend-notify"):
		if self.closed:
			return
		source_key = str(source_key or "")
		if source_key and source_key != self.last_source_key and source_key not in self.visible_preview_source_keys:
			return
		self.preview_refresh_source_key = source_key
		self.preview_refresh_reason = str(reason or "backend-notify")
		self.preview_refresh_pending = True
		if self.selection_update_pending:
			return
		try:
			self.preview_refresh_timer.start(CHANNEL_PREVIEW_REFRESH_DELAY_MS, True)
		except Exception:
			self._run_service_list_refresh()

	def _run_service_list_refresh(self):
		try:
			self.preview_refresh_timer.stop()
		except Exception:
			pass
		if self.closed or not self.preview_refresh_pending:
			return
		if self.selection_update_pending:
			return
		self.preview_refresh_pending = False
		source_key = self.preview_refresh_source_key
		reason = self.preview_refresh_reason
		self.selection_row_cache.clear()
		try:
			list_widget = self.screen["list"]
		except Exception:
			return
		refreshed = False
		for target, method_name in (
			(getattr(list_widget, "l", None), "invalidate"),
			(getattr(list_widget, "instance", None), "invalidate"),
			(list_widget, "refresh"),
			(list_widget, "doReload"),
		):
			method = getattr(target, method_name, None) if target is not None else None
			if method and callable(method):
				try:
					method()
					refreshed = True
					break
				except Exception:
					pass
		self.log(f"SERVICELIST_REFRESH source_key={source_key} reason={reason} refreshed={refreshed} debounce_ms={CHANNEL_PREVIEW_REFRESH_DELAY_MS}")

	def _service_ref_to_string(self, ref):
		try:
			return ref.toString() if ref else ""
		except Exception:
			return str(ref or "")

	def _is_usable_service(self, ref):
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

	def _current_service_ref(self):
		try:
			return self.screen.getCurrentSelection()
		except Exception:
			return None

	def _service_name(self, ref):
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

	def _current_event_from_source(self):
		try:
			service_source = self.screen["Service"]
			event = getattr(service_source, "event", None)
			if event is not None:
				return event
		except Exception:
			pass
		try:
			event_source = self.screen["Event"]
			event = getattr(event_source, "event", None)
			if event is not None:
				return event
		except Exception:
			pass
		return None

	def _lookup_event(self, ref):
		# Prefer the Event/Service sources already filled by SelectionEventInfo.updateEventInfo().
		event = self._current_event_from_source()
		if event is not None:
			return event, "source"
		try:
			epg = eEPGCache.getInstance()
			event = ref and ref.valid() and epg.lookupEventTime(ref, -1)
			if event:
				return event, "epgcache"
		except Exception as err:
			self.log(f"EPGCACHE lookup failed service='{self._service_ref_to_string(ref)}' error={err}", force=True)
		return None, "missing"

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

	def _mark_provider_skipped(self, candidate, status, reason, detail="", existing=False):
		status = status or "skipped"
		expires_at = self.adapter.default_expiry(candidate.event_end, status=status)
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
		self.provider_skip_count += 1
		self.log(f"PROVIDER SKIP source_key={candidate.source_key} status={status} reason={reason} detail='{detail or ""}' expires='{self._format_time(expires_at)}' title='{candidate.title}' search_title='{candidate.search_title}'")

	def _queue_event(self, candidate, priority=PRIORITY_CHANNEL_SELECTION, reason="channel-selection", ignore_limit=False):
		priority = int(priority or PRIORITY_CHANNEL_SELECTION)
		reason = reason or "channel-selection"

		existing_event = resultsdb.get_epg_event(candidate.source_key)
		if existing_event:
			queue_needed, queue_reason = self._queue_needed(existing_event, int(time()), candidate.search_title)
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
		elif not ignore_limit and self.queue_new_count >= CHANNEL_QUEUE_LIMIT:
			self.queue_limit_skip_count += 1
			self.log(f"QUEUE LIMIT source_key={candidate.source_key} limit={CHANNEL_QUEUE_LIMIT} reason={reason} title='{candidate.title}'")
			return False

		ok = resultsdb.upsert_fetch_queue({
			"source_key": candidate.source_key,
			"source_type": candidate.source_type,
			"service_ref": candidate.service_ref,
			"title": candidate.title,
			"search_title": candidate.search_title,
			"begin_time": candidate.begin_time,
			"event_end": candidate.event_end,
			"priority": priority,
			"reason": reason,
			"state": "pending",
		})
		if ok:
			if existing_queue:
				self.queue_update_count += 1
			else:
				self.queue_new_count += 1
		self.log(f"QUEUE {"UPDATE" if existing_queue and ok else ("UPSERT" if ok else "FAILED")} source_key={candidate.source_key} priority={priority} reason={reason} title='{candidate.title}' search_title='{candidate.search_title}'")
		return ok

	def _preview_prefetch_enabled(self):
		try:
			return bool(config.plugins.e2mdb.epgMetaEnabled.value)
		except Exception:
			return True

	def _should_prefetch_source_key(self, source_key):
		if not source_key:
			return False
		now = int(time())
		last = int(self.prefetch_requested.get(source_key) or 0)
		if last and now - last < CHANNEL_PREFETCH_TTL:
			return False
		self.prefetch_requested[source_key] = now
		if len(self.prefetch_requested) > 500:
			cutoff = now - CHANNEL_PREFETCH_TTL
			self.prefetch_requested = {key: value for key, value in self.prefetch_requested.items() if int(value or 0) >= cutoff}
		return True

	def _visible_prefetch_count(self, list_widget):
		# The ServiceList item height can be temporarily wrong while the screen is
		# opening or when a skin/template switches layout.  If we trust that value
		# blindly the visible prefetch window may shrink to only a few rows.  Use
		# the measured value when it looks useful, but never go below the stable
		# default window derived from the queue limit.
		try:
			fallback_count = min(12, max(4, int(CHANNEL_QUEUE_LIMIT or 15)))
		except Exception:
			fallback_count = 8

		item_height = 0
		for getter in (
			lambda: getattr(getattr(list_widget, "l", None), "getItemSize")().height(),
			lambda: getattr(list_widget, "ItemHeight", 0),
		):
			try:
				item_height = int(getter() or 0)
				if item_height > 0:
					break
			except Exception:
				item_height = 0

		try:
			list_height = int(list_widget.instance.size().height())
		except Exception:
			list_height = 0

		if item_height > 0 and list_height > 0:
			try:
				measured_count = min(30, max(1, int(list_height // item_height) or 1))
				return min(30, max(fallback_count, measured_count))
			except Exception:
				pass
		return fallback_count

	def _visible_prefetch_block_key(self):
		try:
			list_widget = self.screen["list"]
		except Exception:
			return ""
		try:
			current_index = max(0, int(list_widget.getCurrentIndex() or 0))
		except Exception:
			current_index = 0
		# Keep one debounced GUI slice bounded on slower dual-core receivers.
		# SQLite writes already run off-thread; EPG-cache candidate discovery still
		# belongs on the Enigma2 main loop and therefore must stay small as well.
		visible_count = min(CHANNEL_QUEUE_LIMIT, self._visible_prefetch_count(list_widget))
		try:
			block = current_index // max(1, visible_count)
		except Exception:
			block = 0
		return f"{block}:{visible_count}"

	def _schedule_visible_window_prefetch(self, reason="selection"):
		if self.closed or not self._enabled() or not self._preview_prefetch_enabled():
			return False
		now = int(time())
		block_key = self._visible_prefetch_block_key()
		last = int(self.last_visible_prefetch_trigger_time or 0)
		same_block = block_key and block_key == self.last_visible_prefetch_block_key
		if same_block and last and now - last < CHANNEL_VISIBLE_PREFETCH_INTERVAL and not self.visible_prefetch_pending:
			return False

		self.visible_prefetch_reason = reason or "selection"
		self.visible_prefetch_block_key = block_key
		if block_key:
			self.last_visible_prefetch_block_key = block_key
		self.last_visible_prefetch_trigger_time = now
		try:
			# If a timer is already pending, restart it. This is the debounce behavior:
			# scrolling only schedules work; the background prefetch starts after pause.
			self.visible_prefetch_pending = True
			self.visible_prefetch_timer.start(CHANNEL_VISIBLE_PREFETCH_DELAY_MS, True)
			self.log(f"VISIBLE_PREFETCH_SCHEDULE reason={self.visible_prefetch_reason} block={block_key or "-"} delay_ms={CHANNEL_VISIBLE_PREFETCH_DELAY_MS} interval={CHANNEL_VISIBLE_PREFETCH_INTERVAL}")
			return True
		except Exception as err:
			self.visible_prefetch_pending = False
			self.log(f"VISIBLE_PREFETCH_SCHEDULE failed reason={reason} error={err}", force=True)
		return False

	def _run_visible_window_prefetch(self):
		if self.closed:
			self.visible_prefetch_pending = False
			return
		reason = self.visible_prefetch_reason or "timer"
		block_key = self.visible_prefetch_block_key or ""
		self.visible_prefetch_pending = False
		try:
			self._prefetch_window_events(reason=f"background-{reason}")
		except Exception as err:
			self.log(f"VISIBLE_PREFETCH failed reason={reason} block={block_key or "-"} error={err}", force=True)

	def _schedule_prefetch_queue_plan(self, queue_plan, reason="selection", selected=False):
		"""Serialize SQLite queue writes outside the Enigma2 render/main thread."""
		if self.closed or not queue_plan:
			return False
		entry = {"plan": list(queue_plan), "reason": str(reason or "selection"), "selected": bool(selected)}
		with self.prefetch_write_lock:
			if selected:
				# Keep only the newest selected-only request waiting and place it
				# ahead of bulk visible-window plans.
				self.prefetch_write_pending = [item for item in self.prefetch_write_pending if not item.get("selected")]
				self.prefetch_write_pending.insert(0, entry)
			else:
				# One pending bulk plan is enough; a newer visible block supersedes it.
				self.prefetch_write_pending = [item for item in self.prefetch_write_pending if item.get("selected")]
				self.prefetch_write_pending.append(entry)
			if self.prefetch_write_thread is None or not self.prefetch_write_thread.is_alive():
				self.prefetch_write_thread = Thread(target=self._run_prefetch_queue_writer, name="e2MDBChannelPrefetch")
				self.prefetch_write_thread.daemon = True
				self.prefetch_write_thread.start()
		return True

	def _run_prefetch_queue_writer(self):
		wake_pending = 0
		wake_reason = "selection"
		while True:
			with self.prefetch_write_lock:
				if not self.prefetch_write_pending:
					self.prefetch_write_thread = None
					entry = None
				else:
					entry = self.prefetch_write_pending.pop(0)
			if entry is None:
				if wake_pending:
					try:
						from .E2MDBBackendLiveBridge import poke_backend_live_epg_worker
						poke_backend_live_epg_worker(reason=f"servicelist-{wake_reason}", limit=max(1, min(25, wake_pending)))
					except Exception as err:
						self.log(f"PREFETCH_WRITER worker poke failed reason={wake_reason} error={err}", force=True)
				return
			if self.closed:
				continue
			queue_plan = entry.get("plan") or []
			reason = entry.get("reason") or "selection"
			queued = 0
			yielded_to_selected = False
			for plan_index, (candidate, priority, reason_text) in enumerate(queue_plan):
				if self.closed:
					break
				if entry.get("selected"):
					with self.prefetch_write_lock:
						if any(item.get("selected") for item in self.prefetch_write_pending):
							yielded_to_selected = True
					if yielded_to_selected:
						break
				try:
					if self._queue_service_list_candidate(candidate, priority, reason_text, immediate=False, ignore_recent=True, ignore_limit=True):
						queued += 1
						if entry.get("selected"):
							self.persisted_selected_source_key = candidate.source_key
				except Exception as err:
					self.log(f"PREFETCH_WRITER failed source_key={getattr(candidate, "source_key", "")} reason={reason_text} error={err}", force=True)
				if not entry.get("selected"):
					with self.prefetch_write_lock:
						selected_waiting = any(item.get("selected") for item in self.prefetch_write_pending)
						if selected_waiting:
							remaining = queue_plan[plan_index + 1:]
							has_newer_bulk = any(not item.get("selected") for item in self.prefetch_write_pending)
							if remaining and not has_newer_bulk:
								self.prefetch_write_pending.append({
									"plan": remaining,
									"reason": reason,
									"selected": False,
								})
							yielded_to_selected = True
					if yielded_to_selected:
						break
			if entry.get("selected") and not yielded_to_selected:
				with self.prefetch_write_lock:
					yielded_to_selected = any(item.get("selected") for item in self.prefetch_write_pending)
			if queued:
				wake_pending += queued
				wake_reason = reason
			# When a selected-only plan arrived while a visible bulk plan was
			# being written, persist the selected priority-90 row before waking
			# the backend. Otherwise the backend could claim the first bulk row
			# in the tiny gap between both writes.
			if wake_pending and not yielded_to_selected:
				try:
					from .E2MDBBackendLiveBridge import poke_backend_live_epg_worker
					poke_backend_live_epg_worker(reason=f"servicelist-{wake_reason}", limit=max(1, min(25, wake_pending)))
				except Exception as err:
					self.log(f"PREFETCH_WRITER worker poke failed reason={wake_reason} error={err}", force=True)
				wake_pending = 0
			self.log(f"PREFETCH_WRITER_DONE reason={reason} selected={entry.get("selected")} planned={len(queue_plan)} queued_or_satisfied={queued} yielded_to_selected={yielded_to_selected}")

	def _get_cached_event_row(self, source_key):
		if not source_key:
			return False, {}
		now = int(time())
		item = self.selection_row_cache.get(source_key)
		if item:
			row = item.get("row") or {}
			status = str(row.get("status") or "unknown").lower()
			expires_at = int(row.get("expires_at") or 0)
			is_expired = bool(expires_at and expires_at <= now)
			is_stable_negative = status in ("no_match", "ignored", "short_skipped", "ended_skipped", "skipped")
			# matched/done rows may still receive late artwork and a backend push.
			# Keep those short-lived so an old selection cache cannot overwrite it.
			ttl = -1 if is_expired else (CHANNEL_SELECTION_ROW_CACHE_TTL if row and is_stable_negative else CHANNEL_SELECTION_MISS_CACHE_TTL)
			if now - int(item.get("timestamp") or 0) <= ttl:
				return True, row
		try:
			if item:
				del self.selection_row_cache[source_key]
		except Exception:
			pass
		return False, {}

	def _set_cached_event_row(self, source_key, row):
		if not source_key:
			return
		now = int(time())
		if len(self.selection_row_cache) > 300:
			cutoff = now - CHANNEL_SELECTION_ROW_CACHE_TTL
			self.selection_row_cache = {key: value for key, value in self.selection_row_cache.items() if int(value.get("timestamp") or 0) >= cutoff}
			if len(self.selection_row_cache) > 300:
				self.selection_row_cache.clear()
		self.selection_row_cache[source_key] = {"timestamp": now, "row": row or {}}

	def _get_event_row_readonly(self, source_key):
		cached, row = self._get_cached_event_row(source_key)
		if cached:
			return row, "cache"
		try:
			row = resultsdb.get_epg_event_readonly(source_key) or {}
		except Exception as err:
			self.log(f"DB READONLY error source_key={source_key} error={err}", force=True)
			row = {}
		self._set_cached_event_row(source_key, row)
		return row, "db"

	def _trigger_background_worker(self, reason="selection"):
		now = int(time())
		last = int(self.last_background_trigger_time or 0)
		if last and now - last < CHANNEL_BACKGROUND_TRIGGER_INTERVAL:
			return False
		self.last_background_trigger_time = now
		try:
			from .E2MDBBackendLiveBridge import poke_backend_live_epg_worker
			poke_backend_live_epg_worker(reason=f"channel-selection-{reason}")
			self.log(f"BACKGROUND_TRIGGER reason={reason} interval={CHANNEL_BACKGROUND_TRIGGER_INTERVAL}")
			return True
		except Exception as err:
			self.log(f"BACKGROUND_TRIGGER failed reason={reason} error={err}", force=True)
		return False

	def _row_has_landscape_preview(self, row):
		if not row:
			return False
		try:
			from .E2MDBServiceListPreview import _full_cache_path
		except Exception:
			_full_cache_path = lambda value: value or ""
		for key in ("metadata_backdrop_path", "metadata_image_path"):
			path = _full_cache_path(row.get(key) or "")
			if path:
				try:
					from os.path import isfile
					if isfile(path):
						return True
				except Exception:
					pass
		return False

	def _event_needs_service_list_prefetch(self, candidate):
		try:
			row = resultsdb.get_epg_event(candidate.source_key)
		except Exception:
			row = {}
		if not row:
			return True, "missing-event-row"
		if self._row_has_landscape_preview(row):
			return False, "has-landscape-preview"
		status = str(row.get("status") or "unknown").lower()
		expires_at = int(row.get("expires_at") or 0)
		now = int(time())
		if status in ("no_match", "ignored", "short_skipped", "ended_skipped", "skipped") and (not expires_at or expires_at > now):
			return False, f"fresh-terminal-{status}"
		if status in ("matched", "done") and (row.get("json_path") or "") and (not expires_at or expires_at > now):
			# Existing provider data without a landscape preview is not complete enough for
			# the ServiceList/InfoBar image use case.  Do not suppress the visible-window
			# queue here; _queue_needed() will decide the exact missing image types and
			# the worker can backfill them from the stored JSON without a full provider
			# lookup if possible.
			return True, "fresh-missing-landscape-preview"
		return True, f"needs-provider-data-{status}"

	def _epg_tuple_to_candidate(self, ref, row, service_name=""):
		try:
			begin_time = int(row[0] or 0)
		except Exception:
			begin_time = 0
		try:
			duration = int(row[1] or 0)
		except Exception:
			duration = 0
		try:
			title = str(row[2] or "")
		except Exception:
			title = ""
		try:
			short_desc = str(row[3] or "")
		except Exception:
			short_desc = ""
		if not title or not begin_time:
			return None
		service_ref = self.adapter.normalize_service_ref(ref)
		event_end = begin_time + duration if begin_time and duration else 0
		source_key = self.adapter.source_key(service_ref, 0, begin_time, title, source_type=self.adapter.SOURCE_EPG, event_end=event_end, duration=duration)
		search_title = self.adapter.epg_search_title(title)
		return E2MDBEPGCandidate(
			source_key=source_key,
			source_type=self.adapter.SOURCE_EPG,
			service_ref=service_ref,
			service_name=service_name,
			event_id=0,
			title=title,
			search_title=search_title,
			short_desc=short_desc,
			extended_desc="",
			begin_time=begin_time,
			duration=duration,
			event_end=event_end,
			virtual_path=self.adapter.virtual_path(source_key, title, source_type=self.adapter.SOURCE_EPG),
			expires_at=self.adapter.default_expiry(event_end, status="unknown"),
		)

	def _prefetch_service_candidates(self, epg, ref, service_name=""):
		candidates = []
		try:
			rows = epg.lookupEvent(["BDTS2", (self.adapter.normalize_service_ref(ref), 0, -1, 3 * 3600)]) or []
		except Exception:
			rows = []
		for row in rows[:2]:
			candidate = self._epg_tuple_to_candidate(ref, row, service_name=service_name)
			if candidate:
				candidates.append(candidate)
		if candidates:
			return candidates
		try:
			event = epg.lookupEventTime(ref, -1)
		except Exception:
			event = None
		if event:
			candidate = self.adapter.event_to_candidate(ref, event, service_name=service_name, source_type=self.adapter.SOURCE_EPG)
			if candidate and candidate.title and candidate.begin_time:
				return [candidate]
		return []

	def _queue_item_was_service_list_next(self, queue_item):
		reason = str((queue_item or {}).get("reason") or "").lower().replace("_", "-")
		return "servicelist" in reason and ("-next" in reason or reason.endswith("next"))

	def _queue_service_list_candidate(self, candidate, priority, reason_text, immediate=False, ignore_recent=False, ignore_limit=False):
		if not candidate or not candidate.title or not candidate.begin_time:
			return False
		needs, need_reason = self._event_needs_service_list_prefetch(candidate)
		if not needs:
			return False

		# A following event may have been queued as ServiceList next with low priority.
		# When that same event later becomes the visible ServiceList now event, bypass
		# the short prefetch TTL so it can be promoted and started as ad-hoc.
		existing_queue = None
		promote_from_next = False
		if immediate:
			try:
				existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
			except Exception:
				existing_queue = None
			if existing_queue:
				try:
					existing_priority = int(existing_queue.get("priority") or 0)
				except Exception:
					existing_priority = 0
				existing_state = str(existing_queue.get("state") or "pending").lower()
				promote_from_next = existing_state in ("pending", "running") and (
					existing_priority < int(priority or 0) or self._queue_item_was_service_list_next(existing_queue)
				)

		if not ignore_recent and not promote_from_next and not self._should_prefetch_source_key(candidate.source_key):
			return False
		try:
			if not resultsdb.get_epg_event(candidate.source_key):
				resultsdb.upsert_epg_event(candidate.as_dict())
		except Exception as err:
			self.log(f"PREFETCH upsert event failed source_key={candidate.source_key} error={err}", force=True)
			return False
		queued = self._queue_event(candidate, priority=priority, reason=f"servicelist-{reason_text}-{need_reason}", ignore_limit=ignore_limit)
		if immediate:
			try:
				from .E2MDBBackendLiveBridge import request_backend_live_epg_processing
				request_backend_live_epg_processing(candidate.source_key, callback=None, priority=priority, reason="servicelist-prefetch")
				if promote_from_next:
					self.log(f"PREFETCH PROMOTE next-now source_key={candidate.source_key} priority={priority} title='{candidate.title}'", force=True)
			except Exception as err:
				self.log(f"PREFETCH ad-hoc failed source_key={candidate.source_key} error={err}", force=True)
		return queued

	def _prefetch_window_events(self, reason="selection"):
		if self.closed or not self._enabled() or not self._preview_prefetch_enabled():
			return
		try:
			list_widget = self.screen["list"]
		except Exception:
			return
		try:
			services = list_widget.getRootServices() or []
		except Exception:
			services = []
		if not services:
			return
		try:
			current_index = max(0, int(list_widget.getCurrentIndex() or 0))
		except Exception:
			current_index = 0
		try:
			limit = max(1, int(CHANNEL_QUEUE_LIMIT or 15))
		except Exception:
			limit = 15

		visible_count = min(limit, self._visible_prefetch_count(list_widget))
		# The selection is not always the first visible row. Include a tiny amount
		# above the cursor to avoid missing the first painted rows after screen open.
		try:
			above = min(current_index, max(0, min(2, visible_count // 4)))
		except Exception:
			above = min(current_index, 2)
		visible_start = max(0, current_index - above)
		if visible_start + visible_count > len(services):
			visible_start = max(0, len(services) - visible_count)
		visible_end = min(len(services), visible_start + visible_count)
		if visible_start >= visible_end:
			return

		visible_size = visible_end - visible_start
		reserve_budget = max(0, limit - visible_size)
		right_reserve_size = (reserve_budget + 1) // 2
		left_reserve_size = reserve_budget // 2
		right_reserve_start = visible_end
		right_reserve_end = min(len(services), right_reserve_start + right_reserve_size)
		left_reserve_end = visible_start
		left_reserve_start = max(0, left_reserve_end - left_reserve_size)

		epgg = eEPGCache.getInstance()
		queued_visible_now = 0
		queued_right_reserve_now = 0
		queued_left_reserve_now = 0
		queued_visible_next = 0
		queued_right_reserve_next = 0
		queued_left_reserve_next = 0

		def candidate_debug_text(candidate):
			try:
				return f"{candidate.title}@{self._format_time(candidate.begin_time)}"
			except Exception:
				try:
					return str(candidate.title or "")
				except Exception:
					return ""

		def collect_candidates(block_name, start, end, seen_refs):
			items = []
			for slot_index, service_value in enumerate(services[start:end], start):
				try:
					ref = service_value if hasattr(service_value, "toString") else eServiceReference(str(service_value))
				except Exception as err:
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=skip reason=bad-ref error={err}")
					continue
				try:
					ref_string = ref.toString()
				except Exception:
					ref_string = str(ref or "")
				service_name = self._service_name(ref)
				if ref_string in seen_refs:
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=skip reason=duplicate service='{ref_string}' service_name='{service_name}'")
					continue
				seen_refs.add(ref_string)
				usable, skip_reason = self._is_usable_service(ref)
				if not usable:
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=skip reason={skip_reason} service='{ref_string}' service_name='{service_name}'")
					continue
				try:
					candidates = self._prefetch_service_candidates(epgg, ref, service_name=service_name)
				except Exception as err:
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=skip reason=candidate-error service='{ref_string}' service_name='{service_name}' error={err}", force=True)
					candidates = []
				if candidates:
					now_text = candidate_debug_text(candidates[0]) if len(candidates) > 0 else ""
					next_text = candidate_debug_text(candidates[1]) if len(candidates) > 1 else ""
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=candidate events={len(candidates)} service='{ref_string}' service_name='{service_name}' now='{now_text}' next='{next_text}'")
					items.append(candidates[:2])
				else:
					self.log(f"VISIBLE_PREFETCH_AUDIT block={block_name} index={slot_index} action=skip reason=no-now-next service='{ref_string}' service_name='{service_name}'")
			return items

		seen_refs = set()
		visible_candidates = collect_candidates("visible", visible_start, visible_end, seen_refs)
		right_reserve_candidates = collect_candidates("right", right_reserve_start, right_reserve_end, seen_refs) if right_reserve_start < right_reserve_end else []
		left_reserve_candidates = collect_candidates("left", left_reserve_start, left_reserve_end, seen_refs) if left_reserve_start < left_reserve_end else []

		priority_visible_now = PRIORITY_SERVICELIST_NOW
		priority_right_now = PRIORITY_SERVICELIST_NOW - 1
		priority_left_now = PRIORITY_SERVICELIST_NOW - 2
		priority_visible_next = PRIORITY_SERVICELIST_NEXT
		priority_right_next = PRIORITY_SERVICELIST_NEXT - 1
		priority_left_next = PRIORITY_SERVICELIST_NEXT - 2

		def plan_entries(block_candidates, event_offset, priority, reason_suffix):
			return [
				(candidates[event_offset], priority, f"{reason}-{reason_suffix}")
				for candidates in block_candidates
				if len(candidates) > event_offset
			]

		# The selected NOW event was already persisted by the 350-ms selected-only
		# plan. Do not spend another SQLite read/write and wake on it here.
		selected_persisted = bool(self.last_source_key and self.persisted_selected_source_key == self.last_source_key)
		selected_retry_plan = []
		visible_now_plan = []
		for entry in plan_entries(visible_candidates, 0, priority_visible_now, "visible-now"):
			if entry[0].source_key != self.last_source_key:
				visible_now_plan.append(entry)
			elif not selected_persisted:
				selected_retry_plan.append((entry[0], PRIORITY_ADHOC_NOW, f"{entry[2]}-selected-retry"))
		reserve_now_plan = (
			plan_entries(right_reserve_candidates, 0, priority_right_now, "right-reserve-now")
			+ plan_entries(left_reserve_candidates, 0, priority_left_now, "left-reserve-now")
		)

		# Keep the selected service's NEXT event at the head of the low-priority
		# tier. With the normal 12-row window this reserves up to three NEXT rows
		# without dropping a visible NOW row.
		selected_groups = [items for items in visible_candidates if items and items[0].source_key == self.last_source_key]
		other_groups = [items for items in visible_candidates if not items or items[0].source_key != self.last_source_key]
		visible_next_plan = plan_entries(selected_groups + other_groups, 1, priority_visible_next, "visible-next")
		reserve_next_plan = (
			plan_entries(right_reserve_candidates, 1, priority_right_next, "right-reserve-next")
			+ plan_entries(left_reserve_candidates, 1, priority_left_next, "left-reserve-next")
		)

		# Cover all visible NOW rows first. The current row is already in the
		# selected-only plan, so remaining capacity can serve a small NEXT tier,
		# then adjacent NOW rows for the next scroll step.
		queue_plan = (selected_retry_plan + visible_now_plan)[:limit]
		next_quota = min(3, max(0, limit - len(queue_plan)), len(visible_next_plan))
		queue_plan.extend(visible_next_plan[:next_quota])
		for entry in reserve_now_plan + visible_next_plan[next_quota:] + reserve_next_plan:
			if len(queue_plan) >= limit:
				break
			queue_plan.append(entry)
		self.visible_preview_source_keys = {self.last_source_key} if self.last_source_key else set()
		self.visible_preview_source_keys.update(
			candidate.source_key for candidate, _priority, _reason_text in queue_plan if candidate and candidate.source_key
		)

		# Candidate discovery stays on the Enigma2 main loop, but all SQLite writes
		# and socket wakeups are serialized by the background queue writer.
		scheduled = self._schedule_prefetch_queue_plan(queue_plan, reason=f"visible-{reason}", selected=False)
		self.log(f"VISIBLE_PREFETCH_SCHEDULED reason={reason} current={current_index} left_reserve={left_reserve_start}:{left_reserve_end} visible={visible_start}:{visible_end} right_reserve={right_reserve_start}:{right_reserve_end} services={len(services)} visible_count={visible_size} candidates_visible={len(visible_candidates)} candidates_right={len(right_reserve_candidates)} candidates_left={len(left_reserve_candidates)} plan={len(queue_plan)} selected_persisted={selected_persisted} selected_retry={bool(selected_retry_plan)} next_reserved={next_quota} scheduled={scheduled}")

	def _apply_selection_meta(self, candidate, event_row=None, event=None, service=None, reason="selection"):
		try:
			self._clear_standard_sources_deferred()
		except Exception:
			pass
		try:
			_apply_standard_epg_meta(self.screen, event=event, service=service, candidate=candidate, event_row=event_row or {}, reason=reason)
			return True
		except Exception as err:
			self.log(f"META apply failed source_key={getattr(candidate, "source_key", "")} reason={reason} error={err}", force=True)
			return False

	def update(self, reason="selection"):
		if self.closed:
			return
		if not self._enabled() or not config.plugins.e2mdb.epgMetaEnabled.value:
			self._clear_standard_sources_deferred()
			try:
				_clear_standard_epg_meta(self.screen, reason=reason)
			except Exception:
				pass
			return
		if not _ensure_resultsdb_ready(f"channel-{reason}", log_ready=not self.db_ready_logged):
			return
		self.db_ready_logged = True

		ref = self._current_service_ref()
		usable, skip_reason = self._is_usable_service(ref)
		if not usable:
			self.skip_count += 1
			self.log(f"SKIP reason={skip_reason} service='{self._service_ref_to_string(ref)}'")
			return

		event, event_source = self._lookup_event(ref)
		if event is None:
			self.skip_count += 1
			self.log(f"SKIP reason=no-event service='{self._service_ref_to_string(ref)}' service_name='{self._service_name(ref)}'")
			return

		candidate = self.adapter.event_to_candidate(ref, event, service_name=self._service_name(ref), source_type=self.adapter.SOURCE_EPG)
		if not candidate.title:
			self.skip_count += 1
			self.log(f"SKIP reason=empty-title service='{self._service_ref_to_string(ref)}'")
			return

		now = int(time())
		existing, row_source = self._get_event_row_readonly(candidate.source_key)
		self._apply_selection_meta(candidate, existing, event=event, service=ref, reason=reason)

		if candidate.source_key == self.last_source_key and now - int(self.last_processed_time or 0) <= 1:
			return
		self.last_source_key = candidate.source_key
		self.visible_preview_source_keys.add(candidate.source_key)
		self.last_processed_time = now
		self.seen_keys.add(candidate.source_key)
		# Do not prefetch provider data while the user scrolls through the service list.
		# Rendering and cursor movement must stay read-only; otherwise ChannelSelection can
		# stutter because visible-window prefetch queues/ad-hoc worker requests are triggered
		# on selection changes. Background/prefill jobs should be started outside the list
		# render/scroll path.

		self.log(f"SELECTION source_key={candidate.source_key} reason={reason} eventSource={event_source} rowSource={row_source} service='{candidate.service_ref}' service_name='{candidate.service_name}' begin='{self._format_time(candidate.begin_time)}' duration={candidate.duration} title='{candidate.title}' search_title='{candidate.search_title}'")

		# The 350-ms selection debounce has expired. Queue the stable selected event
		# first at ad-hoc priority, but keep every SQLite write off the GUI thread.
		self._schedule_prefetch_queue_plan(
			[(candidate, PRIORITY_ADHOC_NOW, f"servicelist-{reason or "selection"}-selected-now")],
			reason=f"selected-{reason or "selection"}",
			selected=True,
		)
		# The wider visible now/next window follows later and at lower priorities.
		self._schedule_visible_window_prefetch(reason=reason)

	def close(self):
		self.closed = True
		try:
			self.visible_prefetch_timer.stop()
		except Exception:
			pass
		try:
			self.selection_update_timer.stop()
		except Exception:
			pass
		try:
			self.preview_refresh_timer.stop()
		except Exception:
			pass
		try:
			from .E2MDBServiceListPreview import unregisterE2MDBServiceListRefreshCallback
			unregisterE2MDBServiceListRefreshCallback(self.service_list_refresh_callback)
		except Exception:
			pass
		try:
			self._clear_standard_sources_deferred()
		except Exception:
			pass
		_unregister_standard_epg_sources(self.screen)
		self.log(f"CLOSE summary seen={len(self.seen_keys)} inserts={self.insert_count} hits={self.hit_count} queue_new={self.queue_new_count} queue_updates={self.queue_update_count} queue_skips={self.queue_skip_count} queue_limit_skips={self.queue_limit_skip_count} provider_skips={self.provider_skip_count} skips={self.skip_count}")


def _attach_channel_selection_bridge(screen):
	try:
		bridge = E2MDBChannelSelectionBridge(screen)
		screen._e2mdb_channel_selection_bridge = bridge
		if hasattr(screen, "onClose"):
			screen.onClose.append(bridge.close)
		return bridge
	except Exception as err:
		write_log(f"[e2MDB][CHANNEL] bridge attach failed: {err}")
		return None


def _patched_channel_selection_init(self, *args, **kwargs):
	_old_channel_selection_init(self, *args, **kwargs)
	try:
		bridge = _attach_channel_selection_bridge(self)
		if bridge:
			# Initial update is delayed as well so the first ChannelSelection paint stays light.
			bridge.schedule_update(reason="init")
	except Exception as err:
		write_log(f"[e2MDB][CHANNEL] init bridge update failed: {err}")


def _patched_selection_event_info_update(self):
	bridge = getattr(self, "_e2mdb_channel_selection_bridge", None)
	try:
		if bridge:
			bridge._mark_standard_sources_deferred(reason="selection")
	except Exception:
		pass
	_old_selection_event_info_update(self)
	try:
		bridge = getattr(self, "_e2mdb_channel_selection_bridge", None)
		if bridge:
			bridge.schedule_update(reason="selection")
	except Exception as err:
		write_log(f"[e2MDB][CHANNEL] selection update failed: {err}")


def install_channel_selection_hooks():
	"""Install OpenATV ChannelSelection hooks once per Enigma2 session."""
	global _old_channel_selection_init, _old_selection_event_info_update, _channel_hooks_installed
	if _channel_hooks_installed:
		return True
	try:
		from Screens.ChannelSelection import ChannelSelection, SelectionEventInfo
		_old_channel_selection_init = ChannelSelection.__init__
		_old_selection_event_info_update = SelectionEventInfo.updateEventInfo
		ChannelSelection.__init__ = _patched_channel_selection_init
		SelectionEventInfo.updateEventInfo = _patched_selection_event_info_update
		_channel_hooks_installed = True
		write_log(f"[e2MDB][CHANNEL] HOOK installed; metaEnabled={config.plugins.e2mdb.epgMetaEnabled.value} enabled={getattr(config.plugins.e2mdb, "epgChannelSelectionEnabled", None).value if hasattr(config.plugins.e2mdb, "epgChannelSelectionEnabled") else True} queueEnabled=True priority={PRIORITY_CHANNEL_SELECTION}")
		return True
	except Exception as err:
		write_log(f"[e2MDB][CHANNEL] ERROR installing ChannelSelection hook: {err}")
		return False
