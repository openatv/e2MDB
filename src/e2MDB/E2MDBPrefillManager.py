########################################################################################################
# e2MDB Live/EPG prefill and channel statistics manager                                                #
# -----------------------------------------------------------------------------------------------------#
# Tracks real live-TV usage through the InfoBar path and uses the collected channel statistics to       #
# enqueue future EPG events for preferred channels. This module never starts provider lookups directly; #
# it only fills e2mdb_epg_events/e2mdb_fetch_queue so the existing worker can process them later.       #
########################################################################################################

# PYTHON IMPORTS
from time import localtime, strftime, time
from traceback import format_exc
from json import dump, load
from os import makedirs, remove, rename
from os.path import dirname, exists, isfile
# ENIGMA IMPORTS
from Components.config import config
from enigma import eServiceReference, eEPGCache, eTimer

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBEPGCandidate, E2MDBLiveEPG
from .E2MDBEPGBridge import _ensure_resultsdb_ready
from .E2MDBPrefillConfig import E2MDBPrefillServices
from .E2MDBIgnoreConfig import E2MDBIgnorePatterns
from .E2MDBPriority import PRIORITY_PREFILL, PRIORITY_PREFILL_IDLE, PRIORITY_PREFILL_STANDBY, clamp_priority


_PREFILL_MANAGER = None
_PREFILL_BACKGROUND = None
_CHANNEL_STATS = None
PREFILL_REQUEST_FILE = "/var/run/e2mdb/prefill_request.json"
PREFILL_MIN_WATCH_SECONDS = 60
PREFILL_RUN_INTERVAL_SECONDS = 24 * 3600
PREFILL_BOOST_SLICE_DELAY_MS = 500


class E2MDBPrefillServiceState:
	"""Persistent lightweight per-service prefill state.

	This file is intentionally outside /etc/enigma2/settings. It records services that repeatedly
	return no EPG during prefill so later runs can skip them for a configurable cooldown period.
	"""

	MODULE_NAME = "[e2MDB][PREFILL][STATE]"
	CONFIG_FILE = "/etc/enigma2/e2mdb/prefill_state.json"
	VERSION = 1

	def __init__(self):
		self.data = None

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def _empty(self):
		return {"version": self.VERSION, "updated": int(time()), "services": {}}

	def load(self):
		if self.data is not None:
			return self.data
		if not isfile(self.CONFIG_FILE):
			self.data = self._empty()
			return self.data
		try:
			with open(self.CONFIG_FILE, "r", encoding="utf-8") as handle:
				data = load(handle) or {}
			if not isinstance(data, dict):
				data = self._empty()
			if not isinstance(data.get("services"), dict):
				data["services"] = {}
			data["version"] = int(data.get("version") or self.VERSION)
			self.data = data
		except Exception as err:
			self.log(f"READ failed file='{self.CONFIG_FILE}' error={err}", force=True)
			self.data = self._empty()
		return self.data

	def save(self):
		data = self.load()
		data["updated"] = int(time())
		try:
			folder = dirname(self.CONFIG_FILE)
			if folder and not exists(folder):
				makedirs(folder)
			tmp_path = self.CONFIG_FILE + ".tmp"
			with open(tmp_path, "w", encoding="utf-8") as handle:
				dump(data, handle, indent=2, sort_keys=True)
				handle.write("\n")
			rename(tmp_path, self.CONFIG_FILE)
		except Exception as err:
			self.log(f"SAVE failed file='{self.CONFIG_FILE}' error={err}", force=True)

	def get(self, service_ref):
		services = self.load().setdefault("services", {})
		state = services.get(service_ref) or {}
		if not isinstance(state, dict):
			state = {}
			services[service_ref] = state
		return state

	def is_no_epg_blocked(self, service_ref, now=None):
		now = int(now or time())
		try:
			blocked_until = int(self.get(service_ref).get("no_epg_until") or 0)
		except Exception:
			blocked_until = 0
		return blocked_until > now, blocked_until

	def record_no_epg(self, service_ref, service_name="", source="", now=None):
		now = int(now or time())
		threshold = 1
		retry_hours = 12
		state = self.get(service_ref)
		count = int(state.get("consecutive_no_epg") or 0) + 1
		blocked_until = now + retry_hours * 3600 if count >= threshold else 0
		state.update({
			"service_name": service_name or state.get("service_name", ""),
			"source": source or state.get("source", ""),
			"consecutive_no_epg": count,
			"last_no_epg": now,
			"last_events": 0,
			"no_epg_until": blocked_until,
		})
		self.save()
		return count, blocked_until

	def record_has_events(self, service_ref, service_name="", source="", event_count=0, now=None):
		now = int(now or time())
		state = self.get(service_ref)
		state.update({
			"service_name": service_name or state.get("service_name", ""),
			"source": source or state.get("source", ""),
			"consecutive_no_epg": 0,
			"last_events": int(event_count or 0),
			"last_has_events": now,
			"no_epg_until": 0,
		})
		self.save()

	def path(self):
		return self.CONFIG_FILE


_PREFILL_SERVICE_STATE = None


def get_prefill_service_state():
	global _PREFILL_SERVICE_STATE
	if _PREFILL_SERVICE_STATE is None:
		_PREFILL_SERVICE_STATE = E2MDBPrefillServiceState()
	return _PREFILL_SERVICE_STATE


class E2MDBChannelStats(E2MDBLiveEPG):
	"""Collect lightweight zap/watch statistics for preferred-channel decisions."""

	MODULE_NAME = "[e2MDB][STATS]"

	def __init__(self):
		E2MDBLiveEPG.__init__(self)
		self.current_service_ref = ""
		self.current_service_name = ""
		self.current_started = 0
		self.last_zap_time = 0
		self.zap_count_session = 0
		self.watch_seconds_session = 0

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def _enabled(self):
		try:
			return bool(config.plugins.e2mdb.epgMetaEnabled.value)
		except Exception:
			return False

	def _commit_current_watch(self, now=None, reason="switch"):
		if not self.current_service_ref or not self._enabled():
			return 0
		now = int(now or time())
		started = int(self.current_started or now)
		watch_seconds = max(0, now - started)
		if watch_seconds < PREFILL_MIN_WATCH_SECONDS:
			self.log(f"WATCH SKIP service='{self.current_service_ref}' seconds={watch_seconds} reason={reason}")
			return 0
		try:
			resultsdb.upsert_channel_stat(
				self.current_service_ref,
				self.current_service_name,
				zap_increment=0,
				watch_seconds_increment=watch_seconds,
				now=now,
			)
			self.watch_seconds_session += watch_seconds
			self.log(f"WATCH service='{self.current_service_ref}' name='{self.current_service_name}' seconds={watch_seconds} reason={reason}")
			return watch_seconds
		except Exception as err:
			self.log(f"WATCH FAILED service='{self.current_service_ref}' error={err}", force=True)
			return 0

	def record_service(self, service_ref, service_name="", reason="live"):
		"""Record a zap when the live service changes and close the previous watch interval."""
		if not self._enabled():
			return False
		if not _ensure_resultsdb_ready(f"stats-{reason or "live"}", log_ready=False):
			return False
		service_ref = self.normalize_service_ref(service_ref).strip()
		if not service_ref or service_ref.startswith("-1:"):
			return False
		now = int(time())
		if service_ref == self.current_service_ref:
			# Same live service; no new zap. Watch time is committed when the service changes or on shutdown.
			return False
		self._commit_current_watch(now=now, reason="service-change")
		self.last_zap_time = now
		self.current_service_ref = service_ref
		self.current_service_name = service_name or ""
		self.current_started = now
		try:
			resultsdb.upsert_channel_stat(service_ref, service_name or "", zap_increment=1, watch_seconds_increment=0, now=now)
			self.zap_count_session += 1
			self.log(f"ZAP service='{service_ref}' name='{service_name or ''}' reason={reason or 'live'}")
			return True
		except Exception as err:
			self.log(f"ZAP FAILED service='{service_ref}' error={err}", force=True)
			return False

	def idle_seconds(self, now=None):
		now = int(now or time())
		if not self.current_service_ref or not self.current_started:
			return 0
		return max(0, now - int(self.current_started or now))

	def seconds_since_last_zap(self, now=None):
		now = int(now or time())
		last = int(self.last_zap_time or self.current_started or 0)
		if not last:
			return 0
		return max(0, now - last)

	def is_live_idle_for_prefill(self, now=None):
		now = int(now or time())
		threshold = 5 * 60
		idle = self.idle_seconds(now)
		since_zap = self.seconds_since_last_zap(now)
		return bool(self.current_service_ref and idle >= threshold and since_zap >= threshold), idle

	def close(self):
		self._commit_current_watch(reason="close")
		self.log(f"CLOSE summary zaps={self.zap_count_session} watch_seconds={self.watch_seconds_session} current='{self.current_service_ref}'", force=True)


def get_channel_stats_tracker():
	global _CHANNEL_STATS
	if _CHANNEL_STATS is None:
		_CHANNEL_STATS = E2MDBChannelStats()
	return _CHANNEL_STATS


def record_live_service(service_ref, service_name="", reason="live"):
	try:
		return get_channel_stats_tracker().record_service(service_ref, service_name=service_name, reason=reason)
	except Exception as err:
		write_log("[e2MDB][STATS]", f"record_live_service failed: {err}")
		return False


def close_channel_stats_tracker():
	try:
		if _CHANNEL_STATS is not None:
			_CHANNEL_STATS.close()
	except Exception:
		pass


def _prefill_config_value(name, default=None):
	try:
		entry = getattr(config.plugins.e2mdb, name, None)
		return getattr(entry, "value", default)
	except Exception:
		return default


def _prefill_in_standby():
	try:
		from Screens import Standby
		return Standby.inStandby is not None
	except Exception:
		return False


def _prefill_night_window_active(now=None):
	try:
		hour = int(localtime(int(now or time())).tm_hour)
	except Exception:
		hour = 0
	try:
		start_hour = int(_prefill_config_value("epgPrefillStartHour", 5) or 5) % 24
	except Exception:
		start_hour = 5
	# Keep the historical single start-hour setting useful by treating the
	# configured hour as the beginning of a conservative 4-hour maintenance window.
	for offset in range(4):
		if hour == ((start_hour + offset) % 24):
			return True
	return False


def get_prefill_runtime_state(now=None):
	"""Return whether prefill/worker boost is currently allowed.

	The worker and the prefill queue filler both use this helper.  Older builds
	called this function but did not define it, so standby prefill silently fell
	back to a non-boosted/active state and scheduler-triggered runs could be
	skipped even while the receiver was in standby.
	"""
	now = int(now or time())
	standby = _prefill_in_standby()
	idle = False
	idle_seconds = 0
	try:
		tracker = get_channel_stats_tracker()
		idle, idle_seconds = tracker.is_live_idle_for_prefill(now)
	except Exception:
		idle = False
		idle_seconds = 0
	mode = str(_prefill_config_value("epgPrefillMode", "standby") or "standby").lower()
	night = _prefill_night_window_active(now)
	if mode == "off":
		boost = False
		reason = "off"
	elif mode == "night":
		boost = bool(standby or night)
		reason = "standby" if standby else ("night" if night else "active")
	elif mode == "idle":
		boost = bool(standby or idle)
		reason = "standby" if standby else ("idle" if idle else "active")
	else:
		boost = bool(standby or idle)
		reason = "standby" if standby else ("idle" if idle else "active")
	return {
		"boost": boost,
		"mode": reason,
		"configured_mode": mode,
		"standby": standby,
		"idle": idle,
		"idle_seconds": int(idle_seconds or 0),
		"night": night,
		"now": now,
	}


class E2MDBPrefillManager(E2MDBLiveEPG):
	"""Scheduled preferred-channel prefill manager."""

	MODULE_NAME = "[e2MDB][PREFILL]"

	def __init__(self, session=None):
		E2MDBLiveEPG.__init__(self)
		self.session = session
		self.request_timer = eTimer()
		self.request_timer.callback.append(self._request_timer_fired)
		self.standby_timer = eTimer()
		self.standby_timer.callback.append(self._standby_timer_fired)
		self.standby_notifier_registered = False
		self.started = False
		self.running = False
		self.last_result = {}

	def log(self, message, force=False):
		write_log(self.MODULE_NAME, message)

	def start(self):
		if self.started:
			return self
		self.started = True
		self.log(f"MANAGER started enabled={getattr(config.plugins.e2mdb.epgPrefillEnabled, "value", False)} horizon={getattr(config.plugins.e2mdb.epgPrefillHorizonDays, "value", 1)}d maxEvents={getattr(config.plugins.e2mdb.epgPrefillMaxEvents, "value", 0)} maxPerService={getattr(config.plugins.e2mdb.epgPrefillMaxEventsPerService, "value", 0)} topN={getattr(config.plugins.e2mdb.epgZapHistoryTopN, "value", 0)} scheduler=task-menu requestPoll=True boostEnabled={True} idleAfter={5}min", force=True)
		self._install_standby_notifier()
		# Poll a lightweight request file for setup-triggered prefill.
		# Periodic scheduling is handled by the OpenATV task/timer menu only.
		self.request_timer.startLongTimer(5)
		return self

	def _install_standby_notifier(self):
		if self.standby_notifier_registered:
			return
		try:
			standby_counter = getattr(getattr(config, "misc", None), "standbyCounter", None)
			if standby_counter is not None:
				standby_counter.addNotifier(self._standby_counter_changed, initial_call=False)
				self.standby_notifier_registered = True
				self.log("STANDBY notifier registered", force=True)
		except Exception as err:
			self.log(f"STANDBY notifier failed error={err}", force=True)

	def _standby_counter_changed(self, *args, **kwargs):
		try:
			self.log("STANDBY notifier fired action=delayed-prefill-poke", force=True)
			self.standby_timer.startLongTimer(3)
		except Exception as err:
			self.log(f"STANDBY notifier timer failed error={err}", force=True)

	def _standby_timer_fired(self):
		try:
			if not self._in_standby():
				self.log("STANDBY skipped reason=not-in-standby-after-delay", force=True)
				return
			self.log("STANDBY accepted action=poke-worker-and-run-prefill-if-due", force=True)
			try:
				from .E2MDBBackendLiveBridge import poke_backend_live_epg_worker
				poke_backend_live_epg_worker(reason="standby-enter")
			except Exception as err:
				self.log(f"STANDBY worker poke failed error={err}", force=True)
			try:
				if self._enabled() and not prefill_background_running():
					run_prefill_background(reason="standby-enter", force=False)
			except Exception as err:
				self.log(f"STANDBY prefill start failed error={err}", force=True)
		except Exception as err:
			self.log(f"STANDBY handler failed error={err}\n{format_exc()}", force=True)


	def _request_timer_fired(self):
		try:
			if exists(PREFILL_REQUEST_FILE):
				reason = "setup-manual"
				force = True
				try:
					with open(PREFILL_REQUEST_FILE, "r") as handle:
						request = load(handle) or {}
					reason = request.get("reason") or reason
					force = bool(request.get("force", True))
				except Exception as err:
					self.log(f"REQUEST read failed error={err}", force=True)
				try:
					remove(PREFILL_REQUEST_FILE)
				except Exception:
					pass
				self.log(f"REQUEST accepted reason={reason} force={force}", force=True)
				if not run_prefill_background(reason=reason, force=force):
					self.log("REQUEST skipped reason=background-busy-or-failed", force=True)
		except Exception as err:
			self.log(f"REQUEST failed error={err}\n{format_exc()}", force=True)
		try:
			self.request_timer.startLongTimer(5)
		except Exception:
			pass


	def _boost_state(self, now=None):
		try:
			return get_prefill_runtime_state(now)
		except Exception:
			return {"boost": False, "mode": "active", "idle_seconds": 0}

	def _priority(self):
		base = PRIORITY_PREFILL
		state = self._boost_state()
		if not state.get("boost"):
			return base
		if state.get("mode") == "standby":
			boost = PRIORITY_PREFILL_STANDBY
		else:
			boost = PRIORITY_PREFILL_IDLE
		# Ad-hoc/current visible events use priority >= 95. Keep boosted prefill below that.
		return min(94, max(base, boost))

	def _worker_allowed_now(self):
		try:
			if not bool(config.plugins.e2mdb.epgMetaEnabled.value):
				return False, "worker-disabled"
		except Exception:
			return False, "worker-disabled"
		return True, "allowed"

	def _poke_worker_after_queue(self, source_key="", reason="prefill"):
		allowed, allowed_reason = self._worker_allowed_now()
		if not allowed:
			self.log(f"WORKER POKE skipped source_key={source_key or ""} reason={reason or "prefill"} state={allowed_reason}")
			return False
		state = self._boost_state()
		trigger = f"prefill-{state.get("mode") or allowed_reason or "queue"}"
		try:
			from .E2MDBBackendLiveBridge import poke_backend_live_epg_worker
			ok = poke_backend_live_epg_worker(reason=trigger)
			self.log(f"WORKER POKE source_key={source_key or ""} reason={reason or "prefill"} trigger={trigger} boost={state.get("boost")} standby={state.get("standby")} idle={state.get("idle")} ok={ok}")
			return bool(ok)
		except Exception as err:
			self.log(f"WORKER POKE failed source_key={source_key or ""} reason={reason or "prefill"} error={err}", force=True)
			return False

	def _enabled(self):
		try:
			return bool(config.plugins.e2mdb.epgMetaEnabled.value and config.plugins.e2mdb.epgPrefillEnabled.value)
		except Exception:
			return False

	def _in_standby(self):
		try:
			from Screens import Standby
			return Standby.inStandby is not None
		except Exception:
			return False

	def _allowed_now(self, now=None):
		if not self._enabled():
			return False, "disabled"
		try:
			mode = str(_prefill_config_value("epgPrefillMode", "standby") or "standby").lower()
			if mode == "off":
				return False, "mode-off"
		except Exception:
			pass
		state = self._boost_state(now)
		if not state.get("boost"):
			return False, "active-not-idle"
		return True, f"allowed-{state.get("mode") or "boost"}"

	def _due_now(self, now=None):
		now = int(now or time())
		try:
			last_run = int(resultsdb.get_cleanup_state("last_epg_prefill", "0") or 0)
		except Exception:
			last_run = 0
		if last_run and now - last_run < PREFILL_RUN_INTERVAL_SECONDS:
			return False, "recent-run"
		return True, "due"

	def _manual_services(self):
		try:
			return E2MDBPrefillServices.parse()
		except Exception as err:
			self.log(f"MANUAL services read failed error={err}", force=True)
			return []

	def _service_name(self, service_ref, fallback=""):
		try:
			from ServiceReference import ServiceReference
			return ServiceReference(service_ref).getServiceName() or fallback or ""
		except Exception:
			return fallback or ""

	def _prefill_state(self):
		return get_prefill_service_state()

	def _no_epg_skip_enabled(self):
		return True

	def _service_ignore_patterns_enabled(self):
		return False

	def _service_ignore_patterns(self):
		try:
			return [pattern.lower() for pattern in E2MDBIgnorePatterns.parse(E2MDBIgnorePatterns.SERVICE_NAME)]
		except Exception:
			return []

	def _service_ignore_match(self, service_name):
		if not self._service_ignore_patterns_enabled():
			return ""
		service_name_l = (service_name or "").lower()
		for pattern in self._service_ignore_patterns():
			if pattern and pattern in service_name_l:
				return pattern
		return ""

	def _service_no_epg_blocked(self, service_ref, now=None):
		if not self._no_epg_skip_enabled():
			return False, 0
		return self._prefill_state().is_no_epg_blocked(service_ref, now=now)

	def _record_service_no_epg(self, service_ref, service_name="", source=""):
		if not self._no_epg_skip_enabled():
			return 0, 0
		count, blocked_until = self._prefill_state().record_no_epg(service_ref, service_name=service_name, source=source)
		self.log(f"NO_EPG service='{service_ref}' name='{service_name or ""}' count={count} blocked_until='{self._format_time(blocked_until) if blocked_until else ""}'")
		return count, blocked_until

	def _record_service_has_events(self, service_ref, service_name="", source="", event_count=0):
		try:
			self._prefill_state().record_has_events(service_ref, service_name=service_name, source=source, event_count=event_count)
		except Exception:
			pass

	def _preferred_services(self):
		services = []
		seen = set()
		for service_ref in self._manual_services():
			if service_ref not in seen:
				seen.add(service_ref)
				services.append({"service_ref": service_ref, "service_name": self._service_name(service_ref), "source": "manual"})
		try:
			use_zap = bool(config.plugins.e2mdb.epgUseZapHistory.value)
		except Exception:
			use_zap = True
		if use_zap:
			try:
				limit = int(config.plugins.e2mdb.epgZapHistoryTopN.value or 10)
			except Exception:
				limit = 10
			for row in resultsdb.get_top_channels(limit=limit, include_pinned=True):
				service_ref = row.get("service_ref") or ""
				if service_ref and service_ref not in seen:
					seen.add(service_ref)
					services.append({"service_ref": service_ref, "service_name": row.get("service_name") or self._service_name(service_ref), "source": "zap", "score": row.get("score")})
		return services

	def _horizon_days(self):
		try:
			return max(1, min(7, int(getattr(config.plugins.e2mdb, "epgPrefillHorizonDays", None).value or 1)))
		except Exception:
			return 1

	def _horizon_seconds(self):
		return self._horizon_days() * 24 * 3600

	def _max_events_per_service(self):
		try:
			return max(1, min(500, int(getattr(config.plugins.e2mdb, "epgPrefillMaxEventsPerService", None).value or 50)))
		except Exception:
			return 50

	def _events_for_service(self, service_ref, max_events):
		"""Return future EPG events as plain tuples.

		Do not use eEPGCache.lookupEvent(["BDTS..."]) here. On some boxes that
		bulk API can trigger a native Enigma2 crash as soon as it returns real EPG
		results for specific services. The ChannelSelection/EventView code paths use
		lookupEventTime(ref, when), so prefill follows that safer path and walks the
		events one by one.
		"""
		horizon = self._horizon_seconds()
		try:
			max_count = max(1, int(max_events or 10))
		except Exception:
			max_count = 10
		now = int(time())
		until = now + horizon
		events = []
		try:
			service = eServiceReference(service_ref)
			epg = eEPGCache.getInstance()
			lookup_time = -1
			last_begin = 0
			self.log(f"EPGCACHE query service='{service_ref}' method=lookupEventTime maxEvents={max_count} start={lookup_time} horizon={horizon} days={self._horizon_days()}")
			while len(events) < max_count:
				event = epg.lookupEventTime(service, lookup_time)
				if not event:
					break
				begin = int(event.getBeginTime() or 0)
				duration = int(event.getDuration() or 0)
				title = str(event.getEventName() or "")
				if not begin or not duration or not title:
					break
				if last_begin and begin <= last_begin:
					break
				last_begin = begin
				if begin > until:
					break
				events.append((
					begin,
					duration,
					title,
					str(event.getShortDescription() or ""),
					str(event.getExtendedDescription() or ""),
				))
				lookup_time = begin + max(1, duration) + 1
			return events
		except Exception as err:
			self.log(f"EPGCACHE failed service='{service_ref}' method=lookupEventTime error={err}", force=True)
			return []

	def _tuple_to_candidate(self, service_ref, service_name, event_tuple):
		try:
			begin = int(event_tuple[0] or 0)
			duration = int(event_tuple[1] or 0)
			title = str(event_tuple[2] or "")
			short_desc = str(event_tuple[3] or "") if len(event_tuple) > 3 else ""
			extended_desc = str(event_tuple[4] or "") if len(event_tuple) > 4 else ""
		except Exception:
			return None
		if not begin or not duration or not title:
			return None
		source_key = self.source_key(service_ref, 0, begin, title, source_type=self.SOURCE_EPG, event_end=begin + duration, duration=duration)
		search_title = self.epg_search_title(title)
		return E2MDBEPGCandidate(
			source_key=source_key,
			source_type=self.SOURCE_EPG,
			service_ref=service_ref,
			service_name=service_name or self._service_name(service_ref),
			event_id=0,
			title=title,
			search_title=search_title,
			short_desc=short_desc,
			extended_desc=extended_desc,
			begin_time=begin,
			duration=duration,
			event_end=begin + duration,
			virtual_path=self.virtual_path(source_key, title, source_type=self.SOURCE_EPG),
			expires_at=self.default_expiry(begin + duration, status="unknown"),
		)

	def _is_fresh_or_terminal(self, row, now=None):
		if not row:
			return False, "new"
		now = int(now or time())
		status = str(row.get("status") or "unknown").lower()
		expires_at = int(row.get("expires_at") or 0)
		json_path = row.get("json_path") or ""
		if status in ("matched", "done") and json_path and (expires_at <= 0 or expires_at > now):
			return True, "fresh-provider-data"
		if status in ("no_match", "ignored", "short_skipped", "ended_skipped", "skipped") and expires_at > now:
			return True, "fresh-terminal"
		return False, "needs-queue"

	def run_prefill(self, force=False, reason="timer"):
		if self.running:
			return {"result": "busy"}
		self.running = True
		try:
			now = int(time())
			if not _ensure_resultsdb_ready("prefill", log_ready=False):
				return {"result": "db-not-ready"}
			allowed, allowed_reason = self._allowed_now(now)
			if not force and not allowed:
				self.log(f"SKIP reason={allowed_reason} mode={getattr(config.plugins.e2mdb.epgPrefillMode, 'value', 'off')}")
				return {"result": allowed_reason}
			due, due_reason = self._due_now(now)
			if not force and not due:
				self.log(f"SKIP reason={due_reason}")
				return {"result": due_reason}
			services = self._preferred_services()
			try:
				max_events = max(1, int(config.plugins.e2mdb.epgPrefillMaxEvents.value or 100))
			except Exception:
				max_events = 100
			if not services:
				self.log("SKIP reason=no-preferred-services")
				resultsdb.set_cleanup_state("last_epg_prefill", str(now))
				return {"result": "no-services"}

			enqueued = 0
			inserted = 0
			skipped = 0
			provider_skipped = 0
			no_epg_services = 0
			no_epg_skipped = 0
			ignored_services = 0
			service_count = 0
			per_service = self._max_events_per_service()
			for service in services:
				if enqueued >= max_events:
					break
				service_ref = service.get("service_ref") or ""
				service_name = service.get("service_name") or self._service_name(service_ref)
				if not service_ref:
					continue
				ignore_pattern = self._service_ignore_match(service_name)
				if ignore_pattern:
					ignored_services += 1
					skipped += 1
					self.log(f"SERVICE SKIP service='{service_ref}' name='{service_name}' reason=ignored-service-pattern detail='{ignore_pattern}'")
					continue
				blocked, blocked_until = self._service_no_epg_blocked(service_ref, now=now)
				if blocked:
					no_epg_skipped += 1
					skipped += 1
					self.log(f"SERVICE SKIP service='{service_ref}' name='{service_name}' reason=no-epg-cooldown until='{self._format_time(blocked_until)}'")
					continue
				service_count += 1
				events = self._events_for_service(service_ref, per_service)
				if events:
					self._record_service_has_events(service_ref, service_name, service.get("source", ""), len(events))
				else:
					no_epg_services += 1
					self._record_service_no_epg(service_ref, service_name, service.get("source", ""))
				self.log(f"SERVICE service='{service_ref}' name='{service_name}' source={service.get('source', '')} events={len(events)}")
				for event_tuple in events:
					if enqueued >= max_events:
						break
					candidate = self._tuple_to_candidate(service_ref, service_name, event_tuple)
					if not candidate:
						skipped += 1
						continue
					existing = resultsdb.get_epg_event(candidate.source_key)
					fresh, fresh_reason = self._is_fresh_or_terminal(existing, now)
					if fresh:
						skipped += 1
						continue
					skip_status, skip_reason, skip_detail = self.epg_provider_skip_reason(candidate)
					if skip_status:
						data = candidate.as_dict()
						data.update({"status": skip_status, "json_path": "", "confidence": 0.0, "expires_at": self.default_expiry(candidate.event_end, status=skip_status)})
						resultsdb.upsert_epg_event(data)
						provider_skipped += 1
						self.log(f"PROVIDER SKIP source_key={candidate.source_key} status={skip_status} reason={skip_reason} detail='{skip_detail or ''}' title='{candidate.title}'")
						continue
					if not existing:
						resultsdb.upsert_epg_event(candidate.as_dict())
						inserted += 1
					existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
					if existing_queue and existing_queue.get("state") == "pending" and int(existing_queue.get("priority") or 0) >= self._priority():
						skipped += 1
						continue
					ok = resultsdb.upsert_fetch_queue({
						"source_key": candidate.source_key,
						"source_type": candidate.source_type,
						"service_ref": candidate.service_ref,
						"title": candidate.title,
						"search_title": candidate.search_title,
						"begin_time": candidate.begin_time,
						"event_end": candidate.event_end,
						"priority": self._priority(),
						"reason": f"prefill-{reason or "timer"}",
						"state": "pending",
					})
					if ok:
						enqueued += 1
						self.log(f"QUEUE UPSERT source_key={candidate.source_key} priority={self._priority()} service='{candidate.service_name}' begin='{self._format_time(candidate.begin_time)}' title='{candidate.title}' search_title='{candidate.search_title}'")
						self._poke_worker_after_queue(candidate.source_key, reason=reason)
			resultsdb.set_cleanup_state("last_epg_prefill", str(now))
			result = {
				"result": "ok",
				"services": service_count,
				"inserted": inserted,
				"queued": enqueued,
				"skipped": skipped,
				"provider_skipped": provider_skipped,
				"no_epg_services": no_epg_services,
				"no_epg_skipped": no_epg_skipped,
				"ignored_services": ignored_services,
			}
			self.last_result = result
			self.log(f"DONE services={service_count} inserted={inserted} queued={enqueued} skipped={skipped} provider_skipped={provider_skipped} no_epg={no_epg_services} no_epg_skipped={no_epg_skipped} ignored_services={ignored_services}", force=True)
			return result
		finally:
			self.running = False

	def _format_time(self, timestamp):
		try:
			return strftime("%Y-%m-%d %H:%M:%S", localtime(int(timestamp or 0)))
		except Exception:
			return str(timestamp or 0)


class E2MDBPrefillBackgroundJob:
	"""Run prefill incrementally on the Enigma2 main loop.

	Important: eEPGCache access is not safe from a Twisted worker thread on
	some images. Earlier background-thread versions could trigger a native
	Enigma2 crash. This job therefore behaves like a background task from the
	user perspective, but it processes one service per eTimer tick on the main
	loop. This keeps the UI responsive and keeps all Enigma2 API calls on the
	thread they expect.
	"""

	MODULE_NAME = "[e2MDB][PREFILL][ASYNC]"

	def __init__(self):
		self.running = False
		self.callback = None
		self.manager = None
		self.reason = "manual"
		self.force = True
		self.timer = eTimer()
		self.timer.callback.append(self._process_step)
		self.services = []
		self.service_index = 0
		self.max_events = 0
		self.per_service = 1
		self.pending_events = []
		self.current_service = None
		self.result = {}
		self.error = None

	def start(self, reason="manual", force=True, callback=None):
		if self.running:
			write_log(self.MODULE_NAME, f"START skipped reason=busy requested={reason or "manual"}")
			return False
		manager = start_prefill_manager()
		if not manager:
			write_log(self.MODULE_NAME, f"START failed reason=manager-unavailable requested={reason or "manual"}")
			return False
		self.running = True
		self.callback = callback
		self.manager = manager
		self.reason = reason or "manual"
		self.force = bool(force)
		self.error = None
		self.result = {"result": "running", "services": 0, "inserted": 0, "queued": 0, "skipped": 0, "provider_skipped": 0, "no_epg_services": 0, "no_epg_skipped": 0, "ignored_services": 0}
		self.services = []
		self.service_index = 0
		self.max_events = 0
		self.per_service = 1
		self.pending_events = []
		self.current_service = None
		write_log(self.MODULE_NAME, f"START reason={self.reason} force={self.force} mode=mainloop-sliced-lookupEventTime")
		try:
			self._prepare()
		except Exception as err:
			self.error = err
			self.result = {"result": "failed", "services": 0, "inserted": 0, "queued": 0, "skipped": 0, "provider_skipped": 0, "no_epg_services": 0, "no_epg_skipped": 0, "ignored_services": 0}
			write_log(self.MODULE_NAME, f"FAILED prepare reason={self.reason} error={err}\n{format_exc()}")
			self._finish()
			return True
		try:
			self.timer.start(1, True)
		except Exception:
			self._process_step()
		return True

	def _prepare(self):
		manager = self.manager
		now = int(time())
		if not _ensure_resultsdb_ready("prefill-async", log_ready=False):
			self.result["result"] = "db-not-ready"
			return
		allowed, allowed_reason = manager._allowed_now(now)
		if not self.force and not allowed:
			manager.log(f"SKIP reason={allowed_reason} scheduler=task-menu")
			self.result["result"] = allowed_reason
			return
		due, due_reason = manager._due_now(now)
		if not self.force and not due:
			manager.log(f"SKIP reason={due_reason}")
			self.result["result"] = due_reason
			return
		self.services = manager._preferred_services()
		try:
			self.max_events = max(1, int(config.plugins.e2mdb.epgPrefillMaxEvents.value or 100))
		except Exception:
			self.max_events = 100
		if not self.services:
			manager.log("SKIP reason=no-preferred-services")
			resultsdb.set_cleanup_state("last_epg_prefill", str(now))
			self.result["result"] = "no-services"
			return
		self.per_service = manager._max_events_per_service()
		self.result["result"] = "running"
		state = manager._boost_state()
		write_log(self.MODULE_NAME, f"PREPARED reason={self.reason} services={len(self.services)} horizonDays={manager._horizon_days()} maxEvents={self.max_events} maxPerService={self.per_service} priority={manager._priority()} boost={state.get("boost")} mode={state.get("mode")} idleSeconds={state.get("idle_seconds", 0)}")

	def _finish(self):
		try:
			self.timer.stop()
		except Exception:
			pass
		callback = self.callback
		result = self.result or {}
		error = self.error
		reason = self.reason
		manager = self.manager
		# Individual queue inserts already poke the daemon, but one coalesced final
		# wake closes the race where the last insert happened while a media scan was
		# finishing or an existing pending row needed no new upsert.
		if manager and result.get("result") == "ok" and (
			int(result.get("queued", 0) or 0) > 0 or int(result.get("skipped", 0) or 0) > 0
		):
			try:
				manager._poke_worker_after_queue("", reason=f"{reason or "prefill"}-complete")
			except Exception as err:
				write_log(self.MODULE_NAME, f"FINAL WORKER POKE failed reason={reason} error={err}")
		self.callback = None
		self.manager = None
		self.running = False
		self.services = []
		self.service_index = 0
		self.pending_events = []
		self.current_service = None
		write_log(self.MODULE_NAME, f"DONE reason={reason} result={result.get("result", "unknown")} services={result.get("services", 0)} inserted={result.get("inserted", 0)} queued={result.get("queued", 0)} skipped={result.get("skipped", 0)} provider_skipped={result.get("provider_skipped", 0)} no_epg={result.get("no_epg_services", 0)} no_epg_skipped={result.get("no_epg_skipped", 0)} ignored_services={result.get("ignored_services", 0)}")
		if callback and callable(callback):
			try:
				callback(result, error)
			except Exception:
				pass

	def _next_delay_ms(self, event_phase=False):
		"""Return the next timer delay in milliseconds.

		The prefill job deliberately uses a slow cadence because several Enigma2
		APIs involved here are native code. Rapid repeated EPG lookups followed by
		DB work have proven unstable on some boxes. The delay keeps this task out
		of the critical UI path and makes crashes easier to isolate in logs.
		"""
		base = 250
		try:
			if self.manager:
				state = self.manager._boost_state()
				if state.get("boost"):
					return max(250, min(base, PREFILL_BOOST_SLICE_DELAY_MS))
		except Exception:
			pass
		return max(250, base)

	def _schedule_next(self, event_phase=False):
		try:
			self.timer.start(self._next_delay_ms(event_phase=event_phase), True)
		except Exception:
			pass

	def _process_step(self):
		if not self.running:
			return
		manager = self.manager
		try:
			if not manager or self.result.get("result") not in ("running", "ok"):
				self._finish()
				return
			if int(self.result.get("queued", 0) or 0) >= self.max_events:
				self._complete_ok()
				return
			if self.pending_events:
				event_data = self.pending_events.pop(0)
				self._process_event_data(manager, event_data)
				self._schedule_next(event_phase=True)
				return
			if self.service_index >= len(self.services):
				self._complete_ok()
				return
			service = self.services[self.service_index]
			self.service_index += 1
			self._lookup_service_events(manager, service)
			self._schedule_next(event_phase=False)
		except Exception as err:
			self.error = err
			self.result["result"] = "failed"
			write_log(self.MODULE_NAME, f"FAILED step reason={self.reason} error={err}\n{format_exc()}")
			self._finish()

	def _complete_ok(self):
		now = int(time())
		try:
			resultsdb.set_cleanup_state("last_epg_prefill", str(now))
		except Exception:
			pass
		self.result["result"] = "ok"
		try:
			self.manager.last_result = dict(self.result)
		except Exception:
			pass
		try:
			self.manager.log(f"DONE services={self.result.get("services", 0)} inserted={self.result.get("inserted", 0)} queued={self.result.get("queued", 0)} skipped={self.result.get("skipped", 0)} provider_skipped={self.result.get("provider_skipped", 0)} no_epg={self.result.get("no_epg_services", 0)} no_epg_skipped={self.result.get("no_epg_skipped", 0)} ignored_services={self.result.get("ignored_services", 0)}", force=True)
		except Exception:
			pass
		self._finish()

	def _plain_event_data(self, event_tuple):
		try:
			begin = int(event_tuple[0] or 0)
			duration = int(event_tuple[1] or 0)
			title = str(event_tuple[2] or "")
			short_desc = str(event_tuple[3] or "") if len(event_tuple) > 3 else ""
			extended_desc = str(event_tuple[4] or "") if len(event_tuple) > 4 else ""
		except Exception:
			return None
		if not begin or not duration or not title:
			return None
		return {
			"begin": begin,
			"duration": duration,
			"title": title,
			"short_desc": short_desc,
			"extended_desc": extended_desc,
		}

	def _lookup_service_events(self, manager, service):
		service_ref = service.get("service_ref") or ""
		service_name = service.get("service_name") or manager._service_name(service_ref)
		if not service_ref:
			return
		ignore_pattern = manager._service_ignore_match(service_name)
		if ignore_pattern:
			self.result["ignored_services"] = int(self.result.get("ignored_services", 0) or 0) + 1
			self.result["skipped"] = int(self.result.get("skipped", 0) or 0) + 1
			manager.log(f"SERVICE SKIP service='{service_ref}' name='{service_name}' reason=ignored-service-pattern detail='{ignore_pattern}'")
			return
		blocked, blocked_until = manager._service_no_epg_blocked(service_ref)
		if blocked:
			self.result["no_epg_skipped"] = int(self.result.get("no_epg_skipped", 0) or 0) + 1
			self.result["skipped"] = int(self.result.get("skipped", 0) or 0) + 1
			manager.log(f"SERVICE SKIP service='{service_ref}' name='{service_name}' reason=no-epg-cooldown until='{manager._format_time(blocked_until)}'")
			return
		self.result["services"] = int(self.result.get("services", 0) or 0) + 1
		events = manager._events_for_service(service_ref, self.per_service)
		if events:
			manager._record_service_has_events(service_ref, service_name, service.get("source", ""), len(events))
		else:
			self.result["no_epg_services"] = int(self.result.get("no_epg_services", 0) or 0) + 1
			manager._record_service_no_epg(service_ref, service_name, service.get("source", ""))
		plain_events = []
		for event_tuple in events:
			data = self._plain_event_data(event_tuple)
			if data:
				data["service_ref"] = service_ref
				data["service_name"] = service_name
				data["source"] = service.get("source", "")
				plain_events.append(data)
		manager.log(f"SERVICE service='{service_ref}' name='{service_name}' source={service.get('source', '')} events={len(events)} queuedForProcessing={len(plain_events)}")
		self.pending_events.extend(plain_events)

	def _candidate_from_event_data(self, manager, event_data):
		service_ref = event_data.get("service_ref") or ""
		service_name = event_data.get("service_name") or manager._service_name(service_ref)
		begin = int(event_data.get("begin") or 0)
		duration = int(event_data.get("duration") or 0)
		title = str(event_data.get("title") or "")
		short_desc = str(event_data.get("short_desc") or "")
		extended_desc = str(event_data.get("extended_desc") or "")
		if not service_ref or not begin or not duration or not title:
			return None
		source_key = manager.source_key(service_ref, 0, begin, title, source_type=manager.SOURCE_EPG, event_end=begin + duration, duration=duration)
		search_title = manager.epg_search_title(title)
		return E2MDBEPGCandidate(
			source_key=source_key,
			source_type=manager.SOURCE_EPG,
			service_ref=service_ref,
			service_name=service_name,
			event_id=0,
			title=title,
			search_title=search_title,
			short_desc=short_desc,
			extended_desc=extended_desc,
			begin_time=begin,
			duration=duration,
			event_end=begin + duration,
			virtual_path=manager.virtual_path(source_key, title, source_type=manager.SOURCE_EPG),
			expires_at=manager.default_expiry(begin + duration, status="unknown"),
		)

	def _process_event_data(self, manager, event_data):
		if int(self.result.get("queued", 0) or 0) >= self.max_events:
			return
		write_log(self.MODULE_NAME, f"EVENT service='{event_data.get("service_ref", "")}' begin='{manager._format_time(event_data.get("begin", 0))}' title='{event_data.get("title", "")}'")
		candidate = self._candidate_from_event_data(manager, event_data)
		if not candidate:
			self.result["skipped"] = int(self.result.get("skipped", 0) or 0) + 1
			return
		existing = resultsdb.get_epg_event(candidate.source_key)
		fresh, fresh_reason = manager._is_fresh_or_terminal(existing, int(time()))
		if fresh:
			self.result["skipped"] = int(self.result.get("skipped", 0) or 0) + 1
			return
		skip_status, skip_reason, skip_detail = manager.epg_provider_skip_reason(candidate)
		if skip_status:
			data = candidate.as_dict()
			data.update({"status": skip_status, "json_path": "", "confidence": 0.0, "expires_at": manager.default_expiry(candidate.event_end, status=skip_status)})
			resultsdb.upsert_epg_event(data)
			self.result["provider_skipped"] = int(self.result.get("provider_skipped", 0) or 0) + 1
			manager.log(f"PROVIDER SKIP source_key={candidate.source_key} status={skip_status} reason={skip_reason} detail='{skip_detail or ''}' title='{candidate.title}'")
			return
		if not existing:
			resultsdb.upsert_epg_event(candidate.as_dict())
			self.result["inserted"] = int(self.result.get("inserted", 0) or 0) + 1
		existing_queue = resultsdb.get_fetch_queue_item(candidate.source_key)
		if existing_queue and existing_queue.get("state") == "pending" and int(existing_queue.get("priority") or 0) >= manager._priority():
			self.result["skipped"] = int(self.result.get("skipped", 0) or 0) + 1
			return
		ok = resultsdb.upsert_fetch_queue({
			"source_key": candidate.source_key,
			"source_type": candidate.source_type,
			"service_ref": candidate.service_ref,
			"title": candidate.title,
			"search_title": candidate.search_title,
			"begin_time": candidate.begin_time,
			"event_end": candidate.event_end,
			"priority": manager._priority(),
			"reason": f"prefill-{self.reason or "timer"}",
			"state": "pending",
		})
		if ok:
			self.result["queued"] = int(self.result.get("queued", 0) or 0) + 1
			manager.log(f"QUEUE UPSERT source_key={candidate.source_key} priority={manager._priority()} service='{candidate.service_name}' begin='{manager._format_time(candidate.begin_time)}' title='{candidate.title}' search_title='{candidate.search_title}'")
			manager._poke_worker_after_queue(candidate.source_key, reason=self.reason)

def get_prefill_background_job():
	global _PREFILL_BACKGROUND
	if _PREFILL_BACKGROUND is None:
		_PREFILL_BACKGROUND = E2MDBPrefillBackgroundJob()
	return _PREFILL_BACKGROUND


def run_prefill_background(reason="manual", force=True, callback=None):
	return get_prefill_background_job().start(reason=reason, force=force, callback=callback)


def request_prefill_background(reason="setup-manual", force=True):
	try:
		with open(PREFILL_REQUEST_FILE, "w") as handle:
			dump({"reason": reason or "setup-manual", "force": bool(force), "created": int(time())}, handle)
		write_log("[e2MDB][PREFILL][REQUEST]", f"WRITE file={PREFILL_REQUEST_FILE} reason={reason or 'setup-manual'} force={bool(force)}")
		return True
	except Exception as err:
		write_log("[e2MDB][PREFILL][REQUEST]", f"WRITE failed file={PREFILL_REQUEST_FILE} error={err}")
		return False


def prefill_background_running():
	return bool(_PREFILL_BACKGROUND and _PREFILL_BACKGROUND.running)


def start_prefill_manager(session=None):
	global _PREFILL_MANAGER
	try:
		if _PREFILL_MANAGER is None:
			_PREFILL_MANAGER = E2MDBPrefillManager(session=session)
		_PREFILL_MANAGER.start()
		return _PREFILL_MANAGER
	except Exception as err:
		write_log("[e2MDB][PREFILL]", f"MANAGER start failed: {err}")
		return None


def run_prefill_now(reason="manual"):
	manager = start_prefill_manager()
	return manager.run_prefill(force=True, reason=reason) if manager else {"result": "manager-failed"}
