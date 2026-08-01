########################################################################################################
# e2MDB backend Live/EPG bridge                                                                         #
# ---------------------------------------------------------------------------------------------------- #
# Enigma2 is allowed to create Live/EPG queue candidates, but provider work is backend-only.            #
########################################################################################################

from threading import Lock, Thread
from time import sleep

from . import write_log
from .E2MDBBackendClient import backend_request


MODULE_NAME = "[e2MDB][BACKEND-LIVE-BRIDGE]"
_wake_lock = Lock()
_wake_pending = None
_wake_thread = None


def _run_backend_wakes():
	"""Process coalesced daemon wakeups outside the Enigma2 main thread."""
	global _wake_pending, _wake_thread
	while True:
		with _wake_lock:
			request = _wake_pending
			_wake_pending = None
			if request is None:
				_wake_thread = None
				return
		try:
			response = None
			last_error = ""
			for attempt in range(1, 4):
				try:
					response = backend_request(
						"live_worker_start",
						timeout=0.75,
						source="enigma-%s" % (request.get("reason") or "live"),
						limit=max(1, int(request.get("limit") or 1)),
					)
					if response and response.get("success"):
						break
					last_error = str((response or {}).get("error") or "backend request rejected")
				except Exception as err:
					last_error = str(err)
					response = None
				if attempt < 3:
					sleep(0.25 * attempt)
			if response and response.get("success"):
				job = response.get("job") if isinstance(response.get("job"), dict) else {}
				state = "deferred" if response.get("deferred") else "started"
				write_log(MODULE_NAME, "WAKE %s reason=%s limit=%s requests=%s job_id=%s current_job_type=%s" % (
					state,
					request.get("reason") or "",
					request.get("limit") or 1,
					request.get("request_count") or 1,
					job.get("id") or response.get("job_id") or "",
					job.get("type") or "",
				))
			else:
				write_log(MODULE_NAME, "WAKE rejected reason=%s limit=%s error=%s" % (
					request.get("reason") or "",
					request.get("limit") or 1,
					last_error or "backend request rejected",
				))
		except Exception as err:
			write_log(MODULE_NAME, "WAKE failed reason=%s limit=%s error=%s" % (
				request.get("reason") or "",
				request.get("limit") or 1,
				err,
			))


def _schedule_backend_wake(reason="live", limit=1):
	"""Queue one coalesced worker wakeup and return without waiting for its ACK."""
	global _wake_pending, _wake_thread
	try:
		reason = str(reason or "live")
		limit = max(1, int(limit or 1))
		with _wake_lock:
			if _wake_pending is None:
				_wake_pending = {
					"reason": reason,
					"limit": limit,
					"request_count": 1,
				}
			else:
				_wake_pending["limit"] = max(int(_wake_pending.get("limit") or 1), limit)
				_wake_pending["request_count"] = int(_wake_pending.get("request_count") or 1) + 1
			if _wake_thread is None or not _wake_thread.is_alive():
				_wake_thread = Thread(target=_run_backend_wakes, name="e2MDBBackendWake")
				_wake_thread.daemon = True
				try:
					_wake_thread.start()
				except Exception:
					_wake_thread = None
					raise
		return True
	except Exception as err:
		write_log(MODULE_NAME, "WAKE schedule failed reason=%s limit=%s error=%s" % (reason or "live", limit or 1, err))
		return False


def request_backend_live_epg_processing(source_key, callback=None, priority=None, limit=1, reason="adhoc"):
	"""Ask the daemon to process the Live/EPG queue.

	This replaces the old in-process Enigma2 EPG worker. The daemon request is
	fire-and-forget from the GUI perspective: no provider work and no forced
	metadata refresh run in Enigma2.
	"""
	source_key = str(source_key or "")
	scheduled = _schedule_backend_wake(reason=reason or "live", limit=limit)
	if scheduled:
		write_log(MODULE_NAME, "REQUEST scheduled source_key=%s priority=%s limit=%s reason=%s" % (
			source_key,
			priority,
			limit,
			reason or "",
		))
	return scheduled


def poke_backend_live_epg_worker(reason="poke", limit=25):
	"""Wake the daemon-side Live/EPG worker without running provider code in Enigma2."""
	return _schedule_backend_wake(reason=reason or "poke", limit=limit or 25)
