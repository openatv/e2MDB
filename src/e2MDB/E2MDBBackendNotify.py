########################################################################################################
# e2MDB backend notification bridge                                                                    #
# ---------------------------------------------------------------------------------------------------- #
# Push based GUI refresh bridge. The daemon sends small Unix datagram notifications when backend        #
# metadata changed. Enigma2 keeps one blocking listener thread; there is no GUI polling loop.           #
########################################################################################################

from json import dumps, loads
from os import makedirs, remove
from os.path import dirname, exists
from socket import AF_UNIX, SOCK_DGRAM, socket, timeout as SocketTimeout
from threading import Lock, Thread, Timer
from weakref import ref as weakref_ref

from . import write_log
from .E2MDBBackendConfig import GUI_NOTIFY_SOCKET, RUNTIME_DIR
from .E2MDBBackendClient import backend_request
from .E2MDBSkin import build_epg_skin_data


MODULE_NAME = "[e2MDB][BACKEND-NOTIFY]"
_listener = None
_listener_lock = Lock()
_sources_lock = Lock()
_sources_by_key = {}
_retry_lock = Lock()
_retry_timers = {}


def _log(message, level=None):
	try:
		write_log(MODULE_NAME, message, level=level)
	except Exception:
		pass


def _make_source_ref(source):
	try:
		return weakref_ref(source)
	except Exception:
		return lambda: source


def register_meta_source(source_key, source):
	"""Register an on-screen source for push refresh by source_key."""
	source_key = str(source_key or "").strip()
	if not source_key or source is None:
		return False
	try:
		old_source_key = str(getattr(source, "_e2mdb_registered_source_key", "") or "").strip()
	except Exception:
		old_source_key = ""
	if old_source_key and old_source_key != source_key:
		unregister_meta_source(old_source_key, source)
	try:
		setattr(source, "_e2mdb_registered_source_key", source_key)
	except Exception:
		pass
	with _sources_lock:
		items = _sources_by_key.setdefault(source_key, [])
		source_id = id(source)
		for item in items:
			if item.get("id") == source_id:
				return True
		items.append({"id": source_id, "ref": _make_source_ref(source)})
		# Keep the registry bounded. Closed screens are pruned on notification.
		if len(items) > 32:
			del items[:-32]
	return True


def unregister_meta_source(source_key, source=None):
	source_key = str(source_key or "").strip()
	if not source_key:
		return False
	with _sources_lock:
		if source is None:
			_sources_by_key.pop(source_key, None)
			return True
		items = _sources_by_key.get(source_key) or []
		source_id = id(source)
		items = [item for item in items if item.get("id") != source_id]
		if items:
			_sources_by_key[source_key] = items
		else:
			_sources_by_key.pop(source_key, None)
	try:
		if str(getattr(source, "_e2mdb_registered_source_key", "") or "") == source_key:
			setattr(source, "_e2mdb_registered_source_key", "")
	except Exception:
		pass
	return True


def _registered_sources(source_key):
	source_key = str(source_key or "").strip()
	if not source_key:
		return []
	result = []
	with _sources_lock:
		items = _sources_by_key.get(source_key) or []
		kept = []
		for item in items:
			try:
				source = item.get("ref")()
			except Exception:
				source = None
			if source is None:
				continue
			kept.append(item)
			result.append(source)
		if kept:
			_sources_by_key[source_key] = kept
		else:
			_sources_by_key.pop(source_key, None)
	return result


def _source_still_matches(source, source_key):
	try:
		meta = source.getMeta() if hasattr(source, "getMeta") else {}
		return bool(isinstance(meta, dict) and str(meta.get("source_key") or "") == source_key)
	except Exception:
		return False


def _apply_meta_on_mainthread(source_key, skin_data, reason="backend-notify"):
	updated = 0
	for source in _registered_sources(source_key):
		if not _source_still_matches(source, source_key):
			continue
		try:
			current = source.getMeta() if hasattr(source, "getMeta") else {}
		except Exception:
			current = {}
		meta = dict(current) if isinstance(current, dict) else {}
		meta.update(skin_data or {})
		meta["source_key"] = source_key
		meta["e2mdb_backend_notify_reason"] = reason or "backend-notify"
		try:
			source.setMeta(meta)
			updated += 1
		except Exception as err:
			_log(f"APPLY failed source_key={source_key} error={err}", level="error")
	if updated:
		_log(f"APPLY source_key={source_key} updated_sources={updated} reason={reason or ""}")
	return updated


def _apply_notification_on_mainthread(source_key, skin_data=None, reason="backend-notify"):
	updated = 0
	if isinstance(skin_data, dict):
		updated = _apply_meta_on_mainthread(source_key, skin_data, reason)
	try:
		from .E2MDBServiceListPreview import notifyE2MDBServiceListUpdated
		notifyE2MDBServiceListUpdated(source_key=source_key, reason=reason)
	except Exception as err:
		_log(f"SERVICELIST notify failed source_key={source_key} error={err}", level="error")
	return updated


def _retry_fetch(source_key, reason, attempt):
	retry_key = str(source_key or "")
	with _retry_lock:
		_retry_timers.pop(retry_key, None)
	if not _registered_sources(retry_key):
		return
	_fetch_and_apply({
		"source_key": retry_key,
		"reason": f"{reason or "backend-notify"}-retry-{attempt}",
		"retry_attempt": attempt,
	})


def _cancel_fetch_retry(source_key):
	with _retry_lock:
		timer = _retry_timers.pop(str(source_key or ""), None)
	if timer:
		try:
			timer.cancel()
		except Exception:
			pass


def _schedule_fetch_retry(source_key, reason, attempt):
	source_key = str(source_key or "").strip()
	if not source_key or attempt > 2 or not _registered_sources(source_key):
		return False
	with _retry_lock:
		if source_key in _retry_timers:
			return True
		timer = Timer(0.4 * attempt, _retry_fetch, args=(source_key, reason, attempt))
		timer.daemon = True
		_retry_timers[source_key] = timer
	try:
		timer.start()
	except Exception as err:
		with _retry_lock:
			if _retry_timers.get(source_key) is timer:
				_retry_timers.pop(source_key, None)
		_log(f"RETRY start failed source_key={source_key} error={err}", level="error")
		return False
	return True


def _fetch_and_apply(payload):
	source_key = str((payload or {}).get("source_key") or "").strip()
	if not source_key:
		return False
	reason = str((payload or {}).get("reason") or "backend-notify")
	try:
		retry_attempt = int((payload or {}).get("retry_attempt") or 0)
	except Exception:
		retry_attempt = 0
	skin_data = None
	fetch_succeeded = False
	if _registered_sources(source_key):
		response = backend_request("live_result", timeout=1.25, source_key=source_key)
		if not response or not response.get("success"):
			_log(f"FETCH failed source_key={source_key} error={(response or {}).get("error") or "no response"}")
			_schedule_fetch_retry(source_key, reason, retry_attempt + 1)
		else:
			fetch_succeeded = True
			_cancel_fetch_retry(source_key)
			event_row = response.get("event") if isinstance(response.get("event"), dict) else {}
			try:
				skin_data = build_epg_skin_data(candidate=None, event_row=event_row)
			except Exception as err:
				_log(f"BUILD failed source_key={source_key} error={err}", level="error")
	# The original datagram always invalidates the ServiceList cache. A failed
	# retry contains no new data and must not cause another full list repaint.
	if retry_attempt and not fetch_succeeded:
		return True
	try:
		from twisted.internet import reactor
		# ServiceList rows are not registered Event/Service sources. Always
		# invalidate their negative cache on the GUI thread, even when there is no
		# standard source to update for this source_key.
		reactor.callFromThread(_apply_notification_on_mainthread, source_key, skin_data, reason)
		return True
	except Exception as err:
		_log(f"CALLFROMTHREAD failed source_key={source_key} error={err}", level="error")
		return False


class BackendNotifyListener(Thread):
	def __init__(self):
		Thread.__init__(self)
		self.daemon = True
		self.running = True
		self.sock = None

	def stop(self):
		self.running = False
		try:
			if self.sock:
				self.sock.close()
		except Exception:
			pass

	def run(self):
		try:
			folder = dirname(GUI_NOTIFY_SOCKET) or RUNTIME_DIR
			if folder and not exists(folder):
				makedirs(folder)
			try:
				remove(GUI_NOTIFY_SOCKET)
			except Exception:
				pass
			self.sock = socket(AF_UNIX, SOCK_DGRAM)
			self.sock.bind(GUI_NOTIFY_SOCKET)
			self.sock.settimeout(1.0)
			_log(f"LISTENER active socket={GUI_NOTIFY_SOCKET}")
		except Exception as err:
			_log(f"LISTENER start failed socket={GUI_NOTIFY_SOCKET} error={err}", level="error")
			return
		while self.running:
			try:
				data = self.sock.recv(65535)
			except SocketTimeout:
				continue
			except Exception:
				break
			try:
				payload = loads(data.decode("utf-8", "replace")) if data else {}
			except Exception as err:
				_log(f"LISTENER decode failed error={err}")
				continue
			event = str(payload.get("event") or "")
			if event in ("live_epg_updated", "metadata_updated", "live_epg_no_match", "live_epg_skipped"):
				_fetch_and_apply(payload)
		try:
			if self.sock:
				self.sock.close()
		except Exception:
			pass
		try:
			remove(GUI_NOTIFY_SOCKET)
		except Exception:
			pass
		_log("LISTENER stopped")


def start_backend_notify_listener():
	global _listener
	with _listener_lock:
		if _listener and _listener.is_alive():
			return True
		_listener = BackendNotifyListener()
		_listener.start()
	return True
