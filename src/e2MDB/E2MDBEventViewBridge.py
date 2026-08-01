########################################################################################################
# e2MDB Live/EPG EventView bridge                                                                      #
# -----------------------------------------------------------------------------------------------------#
# Adds e2MDB Live/EPG skin sources to OpenATV EventView screens and keeps them in sync when the user    #
# navigates to previous/next events. Provider lookups are queued only; no provider work runs here.      #
########################################################################################################

# PYTHON IMPORTS
from time import localtime, strftime, time

# ENIGMA IMPORTS
from Components.config import config

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBLiveEPG
from .E2MDBEPGBridge import _actionable_missing_images, _ensure_resultsdb_ready
from .E2MDBPriority import PRIORITY_EVENTVIEW
from .E2MDBSkin import apply_epg_skin_data, build_epg_skin_data, clear_epg_skin_sources, ensure_epg_skin_sources


_old_event_view_base_init = None
_old_event_view_base_set_event = None
_old_event_view_base_set_service = None
_event_view_hooks_installed = False


class E2MDBEventViewBridge:
	"""Controller attached to one OpenATV EventView instance."""

	MODULE_NAME = "[e2MDB][EVENTVIEW]"

	def __init__(self, screen):
		self.screen = screen
		self.adapter = E2MDBLiveEPG()
		self.db_ready_logged = False
		self.last_source_key = ""
		self.last_processed_time = 0
		self.update_count = 0
		self.queue_count = 0
		self.skip_count = 0
		self.ad_hoc_count = 0
		self.ad_hoc_running = set()
		self.closed = False
		ensure_epg_skin_sources(self.screen)

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			return strftime("%Y-%m-%d %H:%M:%S", localtime(int(timestamp or 0)))
		except Exception:
			return str(timestamp or 0)

	def _service_ref(self):
		return getattr(self.screen, "serviceRef", None)

	def _event(self):
		return getattr(self.screen, "event", None)

	def _service_name(self, service_ref):
		try:
			return service_ref.getServiceName() or ""
		except Exception:
			return ""


	def _apply_row_to_skin(self, candidate, row, reason="eventview"):
		try:
			skin_data = build_epg_skin_data(candidate=candidate, event_row=row or {})
			apply_epg_skin_data(self.screen, skin_data)
			self.update_count += 1
			self.log("SKIN UPDATE source_key=%s reason=%s title='%s' cover='%s' backdrop='%s' image='%s'" % (
				skin_data.get("source_key") or getattr(candidate, "source_key", ""),
				reason,
				skin_data.get("title") or "",
				skin_data.get("cover_path") or "",
				skin_data.get("backdrop_path") or "",
				skin_data.get("image_path") or "",
			))
			return True
		except Exception as err:
			self.log(f"SKIN UPDATE failed reason={reason} error={err}", force=True)
			return False

	def _clear_skin(self, reason="eventview"):
		try:
			clear_epg_skin_sources(self.screen)
			self.log(f"SKIN CLEAR reason={reason}")
		except Exception as err:
			self.log(f"SKIN CLEAR failed reason={reason} error={err}", force=True)

	def _queue_needed(self, existing, now, candidate_search_title=""):
		if not existing:
			return True, "new"
		status = (existing.get("status") or "unknown").lower()
		expires_at = int(existing.get("expires_at") or 0)
		json_path = existing.get("json_path") or ""
		if status in ("matched", "done") and json_path and (expires_at <= 0 or expires_at > now):
			missing_images = _actionable_missing_images(existing)
			if missing_images:
				return True, "fresh-missing-images:%s" % ",".join(missing_images)
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
		self.skip_count += 1
		self.log("PROVIDER SKIP source_key=%s status=%s reason=%s detail='%s' expires='%s' title='%s' search_title='%s'" % (
			candidate.source_key,
			status,
			reason,
			detail or "",
			self._format_time(expires_at),
			candidate.title,
			candidate.search_title,
		))

	def _request_ad_hoc(self, candidate, reason="eventview"):
		if candidate.source_key in self.ad_hoc_running:
			self.log(f"ADHOC SKIP source_key={candidate.source_key} reason=already-running")
			return False
		try:
			from .E2MDBBackendLiveBridge import request_backend_live_epg_processing
			self.ad_hoc_running.add(candidate.source_key)
			ok = request_backend_live_epg_processing(candidate.source_key, callback=None, reason=reason)
			self.ad_hoc_running.discard(candidate.source_key)
			if ok:
				self.ad_hoc_count += 1
				self.log("ADHOC BACKEND WAKE source_key=%s reason=%s title='%s' search_title='%s'" % (
					candidate.source_key,
					reason,
					candidate.title,
					candidate.search_title,
				), force=True)
			else:
				self.log(f"ADHOC QUEUED source_key={candidate.source_key} reason={reason} title='{candidate.title}'")
			return ok
		except Exception as err:
			self.ad_hoc_running.discard(candidate.source_key)
			self.log(f"ADHOC REQUEST failed source_key={candidate.source_key} error={err}", force=True)
			return False

	def _ad_hoc_finished(self, source_key, result, error=""):
		self.ad_hoc_running.discard(source_key)
		if self.closed:
			return
		if source_key != self.last_source_key:
			self.log(f"ADHOC FINISH stale source_key={source_key} current={self.last_source_key} result={result}")
			return
		row = resultsdb.get_epg_event(source_key)
		if not row:
			self.log(f"ADHOC FINISH source_key={source_key} result={result} error={error or ''} row=missing", force=True)
			return
		self.log("ADHOC FINISH source_key=%s result=%s status=%s json='%s' error=%s" % (
			source_key,
			result,
			row.get("status") or "unknown",
			row.get("json_path") or "",
			error or "",
		), force=True)
		try:
			event = self._event()
			service_ref = self._service_ref()
			candidate = self.adapter.event_to_candidate(service_ref, event, service_name=self._service_name(service_ref), source_type=self.adapter.SOURCE_EPG) if event is not None and service_ref is not None else None
			self._apply_row_to_skin(candidate, row, reason="adhoc-finish")
		except Exception as err:
			self.log(f"ADHOC FINISH skin update failed source_key={source_key} error={err}", force=True)

	def _queue_event(self, candidate, priority=PRIORITY_EVENTVIEW, reason="eventview"):
		existing_event = resultsdb.get_epg_event(candidate.source_key)
		if existing_event:
			queue_needed, queue_reason = self._queue_needed(existing_event, int(time()), candidate.search_title)
			if not queue_needed:
				self.log("QUEUE SKIP source_key=%s reason=%s event_status=%s" % (
					candidate.source_key,
					queue_reason,
					existing_event.get("status") or "unknown",
				))
				return True

		existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
		if existing_queue:
			existing_priority = int(existing_queue.get("priority") or 0)
			existing_state = existing_queue.get("state") or "pending"
			if existing_state == "pending" and existing_priority >= int(priority or 0):
				self.log("QUEUE SKIP source_key=%s existing_state=%s existing_priority=%s requested_priority=%s reason=%s" % (
					candidate.source_key,
					existing_state,
					existing_priority,
					priority,
					reason,
				))
				return True

		ok = resultsdb.upsert_fetch_queue({
			"source_key": candidate.source_key,
			"source_type": candidate.source_type,
			"service_ref": candidate.service_ref,
			"title": candidate.title,
			"search_title": candidate.search_title,
			"begin_time": candidate.begin_time,
			"event_end": candidate.event_end,
			"priority": int(priority or 0),
			"reason": reason or "eventview",
			"state": "pending",
		})
		if ok:
			self.queue_count += 1
		self.log("QUEUE %s source_key=%s priority=%s reason=%s title='%s' search_title='%s'" % (
			"UPSERT" if ok else "FAILED",
			candidate.source_key,
			priority,
			reason,
			candidate.title,
			candidate.search_title,
		))
		return ok

	def update(self, reason="eventview"):
		if not config.plugins.e2mdb.epgMetaEnabled.value:
			return
		if not _ensure_resultsdb_ready(f"eventview-{reason}", log_ready=not self.db_ready_logged):
			return
		self.db_ready_logged = True

		event = self._event()
		service_ref = self._service_ref()
		if event is None or service_ref is None:
			self._clear_skin(reason="no-event-service")
			self.log(f"SKIP no usable event/service reason={reason}")
			return

		candidate = self.adapter.event_to_candidate(service_ref, event, service_name=self._service_name(service_ref), source_type=self.adapter.SOURCE_EPG)
		if not candidate.title:
			self._clear_skin(reason="no-title")
			self.log(f"SKIP event without title reason={reason}")
			return

		now = int(time())
		if candidate.source_key == self.last_source_key and now - int(self.last_processed_time or 0) <= 1:
			return
		self.last_source_key = candidate.source_key
		self.last_processed_time = now

		self.log("EVENT source_key=%s reason=%s service='%s' begin='%s' duration=%s title='%s' search_title='%s'" % (
			candidate.source_key,
			reason,
			candidate.service_ref,
			self._format_time(candidate.begin_time),
			candidate.duration,
			candidate.title,
			candidate.search_title,
		))

		existing = resultsdb.get_epg_event(candidate.source_key)
		skip_status, skip_reason, skip_detail = self.adapter.epg_provider_skip_reason(candidate)

		if existing:
			queue_needed, queue_reason = self._queue_needed(existing, now, candidate.search_title)
			if skip_status and queue_needed:
				self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=True)
				return
			row = dict(existing)
			if candidate.search_title and existing.get("search_title") != candidate.search_title:
				resultsdb.update_epg_event_search_title(candidate.source_key, candidate.search_title)
				row["search_title"] = candidate.search_title
			if queue_reason == "improved-search-title":
				resultsdb.update_epg_event_status(candidate.source_key, "unknown", confidence=0.0, json_path="", expires_at=candidate.expires_at)
				row.update({
					"status": "unknown",
					"confidence": 0.0,
					"json_path": "",
					"expires_at": candidate.expires_at,
				})
				self.log("DB RESET source_key=%s reason=improved-search-title old_search_title='%s' new_search_title='%s'" % (
					candidate.source_key,
					existing.get("search_title") or "",
					candidate.search_title,
				))
			self.log("DB HIT id=%s status=%s json='%s' expires='%s' search_title='%s' queue_needed=%s queue_reason=%s" % (
				row.get("id"),
				row.get("status") or "unknown",
				row.get("json_path") or "",
				self._format_time(row.get("expires_at") or 0),
				row.get("search_title") or candidate.search_title,
				queue_needed,
				queue_reason,
			))
			self._apply_row_to_skin(candidate, row, reason=reason)
			if queue_needed:
				queued = self._queue_event(candidate, priority=PRIORITY_EVENTVIEW, reason=queue_reason)
				if queued:
					self._request_ad_hoc(candidate, reason=queue_reason)
			return

		if skip_status:
			self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=False)
			return

		event_id = resultsdb.upsert_epg_event(candidate.as_dict())
		row = resultsdb.get_epg_event(candidate.source_key)
		self._apply_row_to_skin(candidate, row, reason=reason)
		self.log("DB INSERT id=%s source_key=%s expires='%s' service_name='%s'" % (
			event_id,
			candidate.source_key,
			self._format_time(candidate.expires_at),
			candidate.service_name,
		))
		queued = self._queue_event(candidate, priority=PRIORITY_EVENTVIEW, reason=reason)
		if queued:
			self._request_ad_hoc(candidate, reason=reason)

	def close(self):
		self.closed = True
		self.log(f"CLOSE updates={self.update_count} queues={self.queue_count} skips={self.skip_count} adhoc={self.ad_hoc_count}")


def _attach_eventview_bridge(screen):
	try:
		bridge = E2MDBEventViewBridge(screen)
		screen._e2mdb_eventview_bridge = bridge
		if hasattr(screen, "onClose"):
			screen.onClose.append(bridge.close)
		return bridge
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] bridge attach failed: {err}")
		return None


def _patched_event_view_base_init(self, event, serviceRef, callback=None, similarEPGCB=None):
	_old_event_view_base_init(self, event, serviceRef, callback=callback, similarEPGCB=similarEPGCB)
	_attach_eventview_bridge(self)


def _patched_event_view_base_set_event(self, event):
	_old_event_view_base_set_event(self, event)
	try:
		bridge = getattr(self, "_e2mdb_eventview_bridge", None)
		if bridge:
			bridge.update(reason="setEvent")
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] setEvent update failed: {err}")


def _patched_event_view_base_set_service(self, service):
	_old_event_view_base_set_service(self, service)
	try:
		bridge = getattr(self, "_e2mdb_eventview_bridge", None)
		if bridge:
			bridge.update(reason="setService")
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] setService update failed: {err}")


def install_event_view_hooks():
	"""Install OpenATV EventView hooks once per Enigma2 session."""
	global _old_event_view_base_init, _old_event_view_base_set_event, _old_event_view_base_set_service, _event_view_hooks_installed
	if _event_view_hooks_installed:
		return True
	try:
		from Screens.EventView import EventViewBase
		_old_event_view_base_init = EventViewBase.__init__
		_old_event_view_base_set_event = EventViewBase.setEvent
		_old_event_view_base_set_service = EventViewBase.setService
		EventViewBase.__init__ = _patched_event_view_base_init
		EventViewBase.setEvent = _patched_event_view_base_set_event
		EventViewBase.setService = _patched_event_view_base_set_service
		_event_view_hooks_installed = True
		write_log("[e2MDB][EVENTVIEW] HOOK installed; metaEnabled=%s" % (
			config.plugins.e2mdb.epgMetaEnabled.value,
		))
		return True
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] ERROR installing EventView hook: {err}")
		return False
