########################################################################################################
# e2MDB OpenATV scheduler task bridge                                                                  #
# ---------------------------------------------------------------------------------------------------- #
# Keeps OpenATV FunctionTimers running until the backend daemon reports a final job state.              #
########################################################################################################

from threading import Lock, Thread
from time import sleep, strftime, localtime, time

from Components.config import config

from . import write_log
from .E2MDBBackendClient import backend_request


TERMINAL_SUCCESS_STATES = ("success", "done")
TERMINAL_FAILURE_STATES = ("error", "failed", "aborted", "abort", "cancelled", "canceled")
START_RETRY_INTERVAL_SECONDS = 60


class E2MDBBackendJobSchedulerTask:
	MODULE_NAME = "[e2MDB][SCHEDULER][BACKEND]"
	POLL_INTERVAL_SECONDS = 3
	MAX_STATUS_ERRORS = 20

	def __init__(self, name, job_type, options_factory=None):
		self.name = name
		self.job_type = job_type
		self.options_factory = options_factory
		self.lock = Lock()
		self.callback = None
		self.entry = None
		self.job_id = ""
		self.running = False
		self.cancel_requested = False
		self.worker_thread = None
		self.last_log_key = None
		self.last_start_log = 0

	def _options(self):
		if self.options_factory and callable(self.options_factory):
			return self.options_factory() or {}
		return {}

	def _log_timer(self, code, message):
		entry = self.entry
		try:
			if entry and hasattr(entry, "log"):
				entry.log(code, message)
		except Exception:
			pass

	def _retry_deadline(self):
		entry = self.entry
		try:
			return int(getattr(entry, "end", 0) or 0)
		except Exception:
			return 0

	def _retry_window_text(self, deadline):
		if deadline > 0:
			try:
				return strftime("%H:%M:%S", localtime(deadline))
			except Exception:
				return str(deadline)
		return "timer end"

	def _is_backend_busy_response(self, response):
		if not isinstance(response, dict):
			return False
		error = str(response.get("error") or response.get("message") or "").lower()
		return bool(response.get("busy")) or "already running" in error or "backend is busy" in error or "busy" in error

	def _finish(self, success):
		with self.lock:
			callback = self.callback
			self.callback = None
			self.entry = None
			self.job_id = ""
			self.running = False
			self.cancel_requested = False
			self.last_log_key = None
			self.last_start_log = 0
		if callback and callable(callback):
			try:
				callback(bool(success))
			except Exception as err:
				write_log(self.MODULE_NAME, f"CALLBACK failed task={self.name} error={err}", level="error")

	def _start_backend_job(self):
		options = self._options()
		return backend_request(
			"start_job",
			timeout=5.0,
			job=self.job_type,
			source="openatv-functiontimer",
			options=options,
		)

	def start(self, callback, entry=None, **kwargs):
		if not callback or not callable(callback):
			return False
		with self.lock:
			if self.running:
				write_log(self.MODULE_NAME, f"START refused task={self.name} reason=already-running job={self.job_id}", level="error")
				return False
			self.callback = callback
			self.entry = entry
			self.running = True
			self.cancel_requested = False
			self.job_id = ""
			self.last_log_key = None
			self.last_start_log = 0
		self._log_timer(10, f"e2MDB {self.name} timer started.")
		write_log(self.MODULE_NAME, f"TIMER start task={self.name} type={self.job_type}")
		self.worker_thread = Thread(target=self._run_lifecycle, name=f"e2mdb-scheduler-{self.job_type}")
		self.worker_thread.daemon = True
		self.worker_thread.start()
		return True

	def stop(self, **kwargs):
		with self.lock:
			if not self.running:
				return False
			self.cancel_requested = True
			job_id = self.job_id
		write_log(self.MODULE_NAME, f"STOP requested task={self.name} job={job_id}")
		self._log_timer(20, f"e2MDB {self.name} cancel requested.")
		if not job_id:
			self._finish(False)
			return True
		try:
			backend_request("stop_job", timeout=2.0, source="openatv-functiontimer-cancel")
		except Exception as err:
			write_log(self.MODULE_NAME, f"STOP backend request failed task={self.name} error={err}", level="error")
		return True

	def _sleep_retry(self, deadline, retry_after_seconds=None):
		now = int(time())
		if deadline > 0 and now >= deadline:
			return False
		try:
			wait_seconds = int(retry_after_seconds) if retry_after_seconds is not None else START_RETRY_INTERVAL_SECONDS
		except Exception:
			wait_seconds = START_RETRY_INTERVAL_SECONDS
		wait_seconds = max(1, min(START_RETRY_INTERVAL_SECONDS, wait_seconds))
		if deadline > 0:
			wait_seconds = max(1, min(wait_seconds, deadline - now))
		end_time = time() + wait_seconds
		while time() < end_time:
			with self.lock:
				if not self.running or self.cancel_requested:
					return False
			sleep(min(1, max(0.1, end_time - time())))
		return True

	def _run_lifecycle(self):
		if not self._wait_for_backend_slot():
			return
		self._poll_backend()

	def _wait_for_backend_slot(self):
		while True:
			with self.lock:
				if not self.running:
					return False
				if self.cancel_requested:
					self._finish(False)
					return False
			try:
				response = self._start_backend_job()
			except Exception as err:
				deadline = self._retry_deadline()
				if deadline > int(time()):
					self._log_timer(20, f"e2MDB {self.name} backend not reachable; retrying until {self._retry_window_text(deadline)}.")
					write_log(self.MODULE_NAME, f"START retry task={self.name} reason=backend-unreachable error={err}", level="error")
					if self._sleep_retry(deadline):
						continue
				else:
					write_log(self.MODULE_NAME, f"START failed task={self.name} error={err}", level="error")
				self._log_timer(30, f"e2MDB {self.name} could not contact backend: {err}")
				self._finish(False)
				return False
			job = response.get("job") if isinstance(response, dict) else None
			if isinstance(response, dict) and response.get("success") and isinstance(job, dict) and not response.get("deferred"):
				with self.lock:
					self.job_id = str(job.get("id") or "")
				self._log_timer(10, f"e2MDB {self.name} backend job started: {self.job_id}")
				write_log(self.MODULE_NAME, f"START task={self.name} job={self.job_id} type={self.job_type}")
				return True
			error = response.get("error", "backend did not accept job") if isinstance(response, dict) else "invalid backend response"
			deadline = self._retry_deadline()
			if self._is_backend_busy_response(response) and deadline > int(time()):
				now = int(time())
				if now - self.last_start_log >= START_RETRY_INTERVAL_SECONDS - 1:
					self.last_start_log = now
					self._log_timer(20, f"e2MDB {self.name} backend busy; retrying until {self._retry_window_text(deadline)}.")
				write_log(self.MODULE_NAME, f"START retry task={self.name} reason=backend-busy until={self._retry_window_text(deadline)}")
				if self._sleep_retry(deadline, retry_after_seconds=response.get("retry_after_seconds", START_RETRY_INTERVAL_SECONDS)):
					continue
			self._log_timer(30, f"e2MDB {self.name} could not start: {error}")
			write_log(self.MODULE_NAME, f"START refused task={self.name} error={error}", level="error")
			self._finish(False)
			return False

	def _current_job(self):
		payload = backend_request("current_job", timeout=3.0)
		return payload.get("job") if isinstance(payload, dict) else None

	def _job_state_from_history(self):
		try:
			payload = backend_request("history", timeout=3.0)
		except Exception:
			return None
		history = payload.get("history") if isinstance(payload, dict) else {}
		items = history.get("items") if isinstance(history, dict) else []
		for item in items if isinstance(items, list) else []:
			if isinstance(item, dict) and item.get("id") == self.job_id:
				return item
		return None

	def _format_progress(self, job):
		phase = str(job.get("phase") or job.get("state") or "running")
		percent = int(job.get("percent") or 0)
		current = int(job.get("current") or 0)
		total = int(job.get("total") or 0)
		message = str(job.get("message") or phase)
		if total > 0:
			return f"{percent}% - {message} ({current}/{total})"
		return f"{percent}% - {message}"

	def _log_progress(self, job):
		state = str(job.get("state") or "").lower()
		phase = str(job.get("phase") or "")
		percent = int(job.get("percent") or 0)
		current = int(job.get("current") or 0)
		total = int(job.get("total") or 0)
		key = (state, phase, percent // 5, current, total)
		if key == self.last_log_key:
			return
		self.last_log_key = key
		self._log_timer(20, f"e2MDB {self.name}: {self._format_progress(job)}")

	def _poll_backend(self):
		status_errors = 0
		while True:
			with self.lock:
				if not self.running:
					return
				job_id = self.job_id
				cancel_requested = self.cancel_requested
			try:
				job = self._current_job()
				if not isinstance(job, dict) or job.get("id") != job_id:
					job = self._job_state_from_history()
				if not isinstance(job, dict):
					raise RuntimeError("backend job status unavailable")
				status_errors = 0
			except Exception as err:
				status_errors += 1
				write_log(self.MODULE_NAME, f"STATUS failed task={self.name} job={job_id} error={err}", level="error")
				if status_errors >= self.MAX_STATUS_ERRORS:
					self._log_timer(30, f"e2MDB {self.name} failed: backend status timeout.")
					self._finish(False)
					return
				sleep(self.POLL_INTERVAL_SECONDS)
				continue
			self._log_progress(job)
			state = str(job.get("state") or "").lower()
			if state in TERMINAL_SUCCESS_STATES:
				self._log_timer(10, f"e2MDB {self.name} finished successfully.")
				self._finish(not cancel_requested)
				return
			if state in TERMINAL_FAILURE_STATES:
				self._log_timer(30, f"e2MDB {self.name} failed: {job.get("message") or state}")
				self._finish(False)
				return
			if cancel_requested:
				try:
					backend_request("stop_job", timeout=2.0, source="openatv-functiontimer-cancel")
				except Exception:
					pass
			sleep(self.POLL_INTERVAL_SECONDS)


def scan_options():
	rescan_existing = bool(config.plugins.e2mdb.scannerRescanExisting.value)
	return {
		"limit": 0,
		"only_missing": not rescan_existing,
		"rescan_existing": rescan_existing,
	}


def cleanup_options():
	return {
		"reason": "scheduler-task",
		"dry_run": False,
	}


SCAN_TASK = E2MDBBackendJobSchedulerTask("media refresh", "scan_and_enrich", scan_options)
CLEANUP_TASK = E2MDBBackendJobSchedulerTask("Live/EPG cleanup", "live_epg_cleanup", cleanup_options)
SQLITE_MAINTENANCE_TASK = E2MDBBackendJobSchedulerTask("SQLite maintenance", "sqlite_maintenance")


def start_scan_task(callback, entry=None, **kwargs):
	return SCAN_TASK.start(callback, entry, **kwargs)


def stop_scan_task(**kwargs):
	return SCAN_TASK.stop(**kwargs)


def start_cleanup_task(callback, entry=None, **kwargs):
	return CLEANUP_TASK.start(callback, entry, **kwargs)


def stop_cleanup_task(**kwargs):
	return CLEANUP_TASK.stop(**kwargs)


def start_sqlite_maintenance_task(callback, entry=None, **kwargs):
	return SQLITE_MAINTENANCE_TASK.start(callback, entry, **kwargs)


def stop_sqlite_maintenance_task(**kwargs):
	return SQLITE_MAINTENANCE_TASK.stop(**kwargs)
