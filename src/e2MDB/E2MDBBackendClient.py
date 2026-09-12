########################################################################################################
# e2MDB backend client                                                                                 #
# -----------------------------------------------------------------------------------------------------#
# Small Unix socket client used by Enigma2 code and command line helpers.                              #
########################################################################################################

from json import dumps, loads
from socket import AF_UNIX, SOCK_STREAM, socket

from .E2MDBBackendConfig import COMMAND_SOCKET


class E2MDBBackendClient:
	def __init__(self, socket_path=COMMAND_SOCKET, timeout=2.0):
		self.socket_path = socket_path
		self.timeout = timeout

	def request(self, command, **payload):
		message = dict(payload)
		message["command"] = command
		data = (dumps(message, sort_keys=True) + "\n").encode("utf-8")
		client = socket(AF_UNIX, SOCK_STREAM)
		try:
			client.settimeout(self.timeout)
			client.connect(self.socket_path)
			client.sendall(data)
			buffer = b""
			while b"\n" not in buffer:
				chunk = client.recv(65536)
				if not chunk:
					break
				buffer += chunk
			line = buffer.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
			return loads(line) if line else {"success": False, "error": "empty response"}
		finally:
			try:
				client.close()
			except Exception:
				pass


def backend_request(command, timeout=None, **payload):
	client = E2MDBBackendClient(timeout=timeout if timeout is not None else 2.0)
	return client.request(command, **payload)


def _serialize_paths(paths):
	items = []
	if not paths:
		return items
	for item in paths:
		try:
			if isinstance(item, dict):
				path = item.get("path")
				mode = item.get("mode", 3)
				recursive = item.get("recursive", True)
			else:
				path = getattr(item, "path", "")
				mode = getattr(item, "mode", 3)
				recursive = getattr(item, "recursive", True)
			path = str(path or "").strip()
			if not path:
				continue
			items.append({"path": path, "mode": int(mode or 0), "recursive": bool(recursive)})
		except Exception:
			continue
	return items


def run_backend_live_cleanup(reason="enigma", dry_run=False, remove_primary_cache=None):
	payload = {"reason": reason, "dry_run": dry_run}
	if remove_primary_cache is not None:
		payload["remove_primary_cache"] = remove_primary_cache
	return backend_request("cleanup_run", **payload)


def start_backend_scan_and_enrich(source="enigma", limit=100, paths=None, only_missing=True, rescan_existing=False):
	options = {"limit": limit, "only_missing": only_missing, "rescan_existing": rescan_existing}
	path_items = _serialize_paths(paths)
	if path_items:
		options["paths"] = path_items
	return backend_request("start_job", job="scan_and_enrich", source=source, options=options)
