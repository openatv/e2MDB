########################################################################################################
# e2MDB Live/EPG InfoBar bridge                                                                        #
# -----------------------------------------------------------------------------------------------------#
# Adds e2MDB Live/EPG skin sources to the live TV InfoBar. The InfoBar is a zapping/live path, so it    #
# must stay light: it reads cached DB/JSON data immediately and only queues missing provider work.       #
# Missing current-event metadata is queued with an asynchronous high-priority backend wake.             #
########################################################################################################

# PYTHON IMPORTS
from time import localtime, strftime, time

# ENIGMA IMPORTS
from Components.config import config
from Components.ServiceEventTracker import ServiceEventTracker
from enigma import eEPGCache, eServiceReference, eTimer, iPlayableService

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBLiveEPG
from .E2MDBEPGBridge import _actionable_missing_images, _ensure_resultsdb_ready
from .E2MDBPriority import PRIORITY_ADHOC_NOW, PRIORITY_INFOBAR_NOW, clamp_priority


_old_infobar_init = None
_old_infobar_service_started = None
_infobar_hooks_installed = False
INFOBAR_QUEUE_PRIORITY = PRIORITY_INFOBAR_NOW
INFOBAR_ADHOC_PRIORITY = PRIORITY_ADHOC_NOW
INFOBAR_UPDATE_DELAY_MS = 2000
INFOBAR_ADHOC_ENABLED = True


class E2MDBInfoBarBridge:
	"""Controller attached to the singleton OpenATV InfoBar instance."""

	MODULE_NAME = "[e2MDB][INFOBAR]"

	def __init__(self, screen):
		self.screen = screen
		self.adapter = E2MDBLiveEPG()
		self.db_ready_logged = False
		self.last_source_key = ""
		self.last_processed_time = 0
		self.last_preview_source_key = ""
		self.update_count = 0
		self.hit_count = 0
		self.insert_count = 0
		self.queue_count = 0
		self.queue_skip_count = 0
		self.provider_skip_count = 0
		self.skip_count = 0
		self.ad_hoc_count = 0
		self.ad_hoc_running = set()
		self.closed = False
		self.update_timer = eTimer()
		self.update_timer.callback.append(self._timer_fired)
		self.event_tracker = self._create_event_tracker()

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			return strftime("%Y-%m-%d %H:%M:%S", localtime(int(timestamp or 0)))
		except Exception:
			return str(timestamp or 0)

	def _enabled(self):
		try:
			return bool(config.plugins.e2mdb.epgInfoBarEnabled.value)
		except Exception:
			return True


	def _service_ref_to_string(self, ref):
		try:
			return ref.toString() if ref else ""
		except Exception:
			return str(ref or "")

	def _create_event_tracker(self):
		# Track the same event-info update path used by the OpenATV InfoBar, but keep the work delayed.
		try:
			eventmap = {}
			for event_name in ("evStart", "evUpdatedEventInfo", "evUpdateTags", "evUpdatedInfo"):
				try:
					eventmap[getattr(iPlayableService, event_name)] = self.on_service_event
				except Exception:
					pass
			return ServiceEventTracker(screen=self.screen, eventmap=eventmap) if eventmap else None
		except Exception as err:
			self.log(f"EVENTTRACKER failed error={err}", force=True)
			return None

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
			nav = self.screen.session.nav
			if hasattr(nav, "getCurrentlyPlayingServiceReference"):
				ref = nav.getCurrentlyPlayingServiceReference()
				if ref:
					return ref
			if hasattr(nav, "getCurrentlyPlayingServiceOrGroup"):
				return nav.getCurrentlyPlayingServiceOrGroup()
		except Exception:
			pass
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

	def _current_event_from_service(self):
		try:
			service = self.screen.session.nav.getCurrentService()
			info = service and service.info()
			event = info and info.getEvent(0)
			if event:
				return event, "current-service"
		except Exception:
			pass
		return None, "missing"

	def _lookup_event(self, ref):
		event, source = self._current_event_from_service()
		if event:
			return event, source
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
		self.provider_skip_count += 1
		self.log("PROVIDER SKIP source_key=%s status=%s reason=%s detail='%s' expires='%s' title='%s' search_title='%s'" % (
			candidate.source_key,
			status,
			reason,
			detail or "",
			self._format_time(expires_at),
			candidate.title,
			candidate.search_title,
		))

	def _queue_event(self, candidate, priority=PRIORITY_INFOBAR_NOW, reason="infobar"):
		priority = int(priority or INFOBAR_QUEUE_PRIORITY)
		reason = reason or "infobar"

		existing_event = resultsdb.get_epg_event(candidate.source_key)
		if existing_event:
			queue_needed, queue_reason = self._queue_needed(existing_event, int(time()), candidate.search_title)
			if not queue_needed:
				self.queue_skip_count += 1
				self.log("QUEUE SKIP source_key=%s reason=%s event_status=%s requested_priority=%s" % (
					candidate.source_key,
					queue_reason,
					existing_event.get("status") or "unknown",
					priority,
				))
				return True

		existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
		if existing_queue:
			existing_priority = int(existing_queue.get("priority") or 0)
			existing_state = existing_queue.get("state") or "pending"
			if existing_state == "pending" and existing_priority >= priority:
				self.queue_skip_count += 1
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
			"priority": priority,
			"reason": reason,
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

	def _request_ad_hoc(self, candidate, reason="infobar"):
		if not INFOBAR_ADHOC_ENABLED:
			return False
		if candidate.source_key in self.ad_hoc_running:
			return False
		try:
			from .E2MDBBackendLiveBridge import request_backend_live_epg_processing
			# The normal InfoBar queue tier is 80. An explicit current-event request
			# must promote that same row to the ad-hoc tier so media safe-points pick
			# it before visible-window and background work.
			self._queue_event(candidate, priority=INFOBAR_ADHOC_PRIORITY, reason="%s-adhoc" % (reason or "infobar"))
			self.ad_hoc_running.add(candidate.source_key)
			ok = request_backend_live_epg_processing(candidate.source_key, callback=None, priority=INFOBAR_ADHOC_PRIORITY, reason=reason)
			try:
				self.ad_hoc_running.discard(candidate.source_key)
			except Exception:
				pass
			if ok:
				self.ad_hoc_count += 1
				self.log("ADHOC REQUEST source_key=%s reason=%s title='%s' search_title='%s'" % (
					candidate.source_key,
					reason,
					candidate.title,
					candidate.search_title,
				), force=True)
			else:
				self.log(f"ADHOC QUEUED source_key={candidate.source_key} reason={reason} title='{candidate.title}'")
			return ok
		except Exception as err:
			try:
				self.ad_hoc_running.discard(candidate.source_key)
			except Exception:
				pass
			self.log(f"ADHOC REQUEST failed source_key={candidate.source_key} error={err}", force=True)
			return False

	def _queue_item_was_event_next(self, queue_item):
		reason = str((queue_item or {}).get("reason") or "").lower().replace("_", "-")
		return "event-next" in reason or reason.endswith("-next") or "next-event" in reason

	def _event_row_needs_provider_data(self, event_row):
		if not event_row:
			return True
		status = str(event_row.get("status") or "unknown").lower()
		json_path = event_row.get("json_path") or ""
		if status not in ("matched", "done"):
			return True
		return not bool(json_path)

	def _promote_event_next_to_ad_hoc(self, candidate, existing=None, reason="infobar"):
		if not candidate or not candidate.source_key:
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
		if not self._queue_item_was_event_next(queue_item) and not self._event_row_needs_provider_data(existing):
			return False
		priority = INFOBAR_ADHOC_PRIORITY
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
			self.log("EVENT_NEXT PROMOTE queue update failed source_key=%s error=%s" % (candidate.source_key, err), force=True)
			return False
		self.log("EVENT_NEXT PROMOTE source_key=%s old_reason=%s state=%s priority=%s title='%s' trigger=%s" % (
			candidate.source_key,
			queue_item.get("reason") or "",
			state,
			priority,
			candidate.title,
			reason or "",
		), force=True)
		return self._request_ad_hoc(candidate, reason="promoted-event-next-now")

	def _ad_hoc_finished(self, source_key, result, error=""):
		try:
			self.ad_hoc_running.discard(source_key)
		except Exception:
			pass
		if self.closed or source_key != self.last_source_key:
			return
		row = resultsdb.get_epg_event(source_key)
		if not row:
			return
		candidate = self._candidate_from_current_event()
		self.log("ADHOC FINISH source_key=%s result=%s status=%s json='%s' error=%s" % (
			source_key,
			result,
			row.get("status") or "unknown",
			row.get("json_path") or "",
			error or "",
		), force=True)

	def _preview_current_event(self, reason="schedule"):
		"""Immediately replace stale InfoBar e2MDB data while the delayed DB lookup is pending."""
		try:
			if not self._enabled() or not config.plugins.e2mdb.epgMetaEnabled.value:
				return False
		except Exception:
			return False
		candidate = self._candidate_from_current_event()
		if not candidate or not candidate.title:
			return False
		# Do not blank/repaint the same event; this avoids flicker when the InfoBar is simply shown again.
		if candidate.source_key == self.last_source_key or candidate.source_key == self.last_preview_source_key:
			return False
		row = {
			"source_key": candidate.source_key,
			"title": candidate.title,
			"search_title": candidate.search_title,
			"short_desc": candidate.short_desc,
			"extended_desc": candidate.extended_desc,
			"status": "pending",
			"json_path": "",
		}
		self.last_preview_source_key = candidate.source_key
		self.log("SKIN PREVIEW source_key=%s reason=%s title='%s' search_title='%s'" % (
			candidate.source_key,
			reason,
			candidate.title,
			candidate.search_title,
		))
		return True

	def _candidate_from_current_event(self):
		ref = self._current_service_ref()
		usable, skip_reason = self._is_usable_service(ref)
		if not usable:
			self.skip_count += 1
			self.log(f"SKIP reason={skip_reason} service='{self._service_ref_to_string(ref)}'")
			return None
		event, event_source = self._lookup_event(ref)
		if event is None:
			self.skip_count += 1
			self.log(f"SKIP reason=no-event service='{self._service_ref_to_string(ref)}' service_name='{self._service_name(ref)}'")
			return None

		# Use the same EPG source_key as GraphicalEPG/EventView so cached results are reused in the InfoBar.
		candidate = self.adapter.event_to_candidate(ref, event, service_name=self._service_name(ref), source_type=self.adapter.SOURCE_EPG)
		candidate._event_source = event_source
		return candidate

	def process_update(self, reason="timer"):
		if self.closed:
			return
		if not self._enabled() or not config.plugins.e2mdb.epgMetaEnabled.value:
			return
		if not _ensure_resultsdb_ready(f"infobar-{reason}", log_ready=not self.db_ready_logged):
			return
		self.db_ready_logged = True

		candidate = self._candidate_from_current_event()
		if not candidate or not candidate.title:
			return

		try:
			from .E2MDBPrefillManager import record_live_service
			record_live_service(candidate.service_ref, candidate.service_name, reason=reason or "infobar")
		except Exception as err:
			self.log(f"STATS failed service='{candidate.service_ref}' error={err}", force=True)

		now = int(time())
		if candidate.source_key == self.last_source_key and now - int(self.last_processed_time or 0) <= 1:
			return
		self.last_source_key = candidate.source_key
		self.last_processed_time = now

		self.log("EVENT source_key=%s reason=%s eventSource=%s service='%s' service_name='%s' begin='%s' duration=%s title='%s' search_title='%s'" % (
			candidate.source_key,
			reason,
			getattr(candidate, "_event_source", ""),
			candidate.service_ref,
			candidate.service_name,
			self._format_time(candidate.begin_time),
			candidate.duration,
			candidate.title,
			candidate.search_title,
		))

		existing = resultsdb.get_epg_event(candidate.source_key)
		skip_status, skip_reason, skip_detail = self.adapter.epg_provider_skip_reason(candidate)

		if existing:
			resultsdb.touch_epg_event(candidate.source_key, now)
			queue_needed, queue_reason = self._queue_needed(existing, now, candidate.search_title)
			if skip_status and queue_needed:
				self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=True)
				return
			if candidate.search_title and existing.get("search_title") != candidate.search_title:
				resultsdb.update_epg_event_search_title(candidate.source_key, candidate.search_title)
			if queue_reason == "improved-search-title":
				resultsdb.update_epg_event_status(candidate.source_key, "unknown", confidence=0.0, json_path="", expires_at=candidate.expires_at)
				self.log("DB RESET source_key=%s reason=improved-search-title old_search_title='%s' new_search_title='%s'" % (
					candidate.source_key,
					existing.get("search_title") or "",
					candidate.search_title,
				))
			row = resultsdb.get_epg_event(candidate.source_key)
			self.hit_count += 1
			self.log("DB HIT id=%s status=%s json='%s' expires='%s' search_title='%s' queue_needed=%s queue_reason=%s" % (
				row.get("id"),
				row.get("status") or "unknown",
				row.get("json_path") or "",
				self._format_time(row.get("expires_at") or 0),
				row.get("search_title") or candidate.search_title,
				queue_needed,
				queue_reason,
			))
			if queue_needed:
				self._queue_event(candidate, priority=INFOBAR_QUEUE_PRIORITY, reason=queue_reason)
				if not self._promote_event_next_to_ad_hoc(candidate, existing=row, reason=reason):
					self._request_ad_hoc(candidate, reason=queue_reason)
			else:
				# If this was queued as Event_Next while standby-only blocked the
				# background worker, promote it once it becomes the visible live event.
				self._promote_event_next_to_ad_hoc(candidate, existing=row, reason=reason)
			return

		if skip_status:
			self._mark_provider_skipped(candidate, skip_status, skip_reason, skip_detail, existing=False)
			return

		event_id = resultsdb.upsert_epg_event(candidate.as_dict())
		row = resultsdb.get_epg_event(candidate.source_key)
		self.insert_count += 1
		self.log("DB INSERT id=%s source_key=%s expires='%s' service_name='%s'" % (
			event_id,
			candidate.source_key,
			self._format_time(candidate.expires_at),
			candidate.service_name,
		))
		self._queue_event(candidate, priority=INFOBAR_QUEUE_PRIORITY, reason=reason)
		self._request_ad_hoc(candidate, reason=reason)

	def _timer_fired(self):
		self.process_update(reason=getattr(self, "_pending_reason", "timer"))

	def schedule_update(self, reason="update", immediate=False):
		if self.closed:
			return
		self._pending_reason = reason or "update"
		try:
			self.update_timer.stop()
		except Exception:
			pass
		if immediate:
			self.process_update(reason=reason)
			return
		# Prevent stale e2MDB cover/text from the previous service while the delayed DB lookup is pending.
		try:
			self._preview_current_event(reason=reason)
		except Exception as err:
			self.log(f"SKIN PREVIEW failed reason={reason} error={err}", force=True)
		delay = INFOBAR_UPDATE_DELAY_MS
		try:
			self.update_timer.start(delay, True)
		except Exception:
			try:
				self.update_timer.startLongTimer(max(1, delay // 1000))
			except Exception:
				self.process_update(reason=reason)

	def on_show(self):
		self.schedule_update(reason="show")

	def on_service_event(self):
		self.schedule_update(reason="service-event")

	def close(self):
		self.closed = True
		try:
			self.update_timer.stop()
		except Exception:
			pass
		try:
			from .E2MDBPrefillManager import close_channel_stats_tracker
			close_channel_stats_tracker()
		except Exception:
			pass
		self.log("CLOSE summary inserts=%s hits=%s queue=%s queue_skips=%s provider_skips=%s updates=%s adhoc=%s skips=%s" % (
			self.insert_count,
			self.hit_count,
			self.queue_count,
			self.queue_skip_count,
			self.provider_skip_count,
			self.update_count,
			self.ad_hoc_count,
			self.skip_count,
		))


def _attach_infobar_bridge(screen):
	try:
		bridge = E2MDBInfoBarBridge(screen)
		screen._e2mdb_infobar_bridge = bridge
		if hasattr(screen, "onShow"):
			screen.onShow.append(bridge.on_show)
		if hasattr(screen, "onClose"):
			screen.onClose.append(bridge.close)
		bridge.schedule_update(reason="init")
		return bridge
	except Exception as err:
		write_log(f"[e2MDB][INFOBAR] bridge attach failed: {err}")
		return None


def _patched_infobar_init(self, *args, **kwargs):
	_old_infobar_init(self, *args, **kwargs)
	try:
		_attach_infobar_bridge(self)
	except Exception as err:
		write_log(f"[e2MDB][INFOBAR] init bridge update failed: {err}")


def _patched_infobar_service_started(self, *args, **kwargs):
	result = _old_infobar_service_started(self, *args, **kwargs)
	try:
		bridge = getattr(self, "_e2mdb_infobar_bridge", None)
		if bridge:
			bridge.schedule_update(reason="serviceStarted")
	except Exception as err:
		write_log(f"[e2MDB][INFOBAR] serviceStarted update failed: {err}")
	return result


def install_infobar_hooks():
	"""Install OpenATV InfoBar hooks once per Enigma2 session."""
	global _old_infobar_init, _old_infobar_service_started, _infobar_hooks_installed
	if _infobar_hooks_installed:
		return True
	try:
		from Screens.InfoBar import InfoBar
		_old_infobar_init = InfoBar.__init__
		_old_infobar_service_started = InfoBar.serviceStarted
		InfoBar.__init__ = _patched_infobar_init
		InfoBar.serviceStarted = _patched_infobar_service_started
		_infobar_hooks_installed = True
		write_log("[e2MDB][INFOBAR] HOOK installed; metaEnabled=%s enabled=%s queueEnabled=True priority=%s delay=2s adhoc=False" % (
			config.plugins.e2mdb.epgMetaEnabled.value,
			getattr(config.plugins.e2mdb, "epgInfoBarEnabled", None).value if hasattr(config.plugins.e2mdb, "epgInfoBarEnabled") else True,
			PRIORITY_INFOBAR_NOW,
		))
		return True
	except Exception as err:
		write_log(f"[e2MDB][INFOBAR] ERROR installing InfoBar hook: {err}")
		return False
