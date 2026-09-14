#!/usr/bin/env python3
########################################################################################################
# e2MDB backend daemon                                                                                 #
# -----------------------------------------------------------------------------------------------------#
# Clean-start backend scaffold: Twisted web/API, Unix command socket, backend jobs and status.  #
########################################################################################################

from mimetypes import guess_type
from json import dump, dumps, load, loads
from os import fsync, getpid, makedirs, remove, rename
from os.path import abspath, basename, dirname, exists, getmtime, getsize, isfile, join, realpath
from socket import AF_UNIX, SOCK_DGRAM, SOCK_STREAM, socket, timeout as SocketTimeout
from sys import exit, stdout
from threading import Event, Lock, Thread, current_thread
from time import gmtime, sleep, strftime, time
from traceback import format_exc
from uuid import uuid4

try:
	from E2MDBBackendDatabase import BackendDatabase
except Exception as err:
	BackendDatabase = None
	BACKEND_DATABASE_IMPORT_ERROR = err
else:
	BACKEND_DATABASE_IMPORT_ERROR = None
from E2MDBBackendProvider import BackendProviderEnricher
from E2MDBBackendMetadataScanner import E2MDBBackendMetadataScanner

CONFIG_DIR = "/etc/enigma2/e2mdb"
RUNTIME_DIR = "/var/run/e2mdb"
SETTINGS_FILE = join(CONFIG_DIR, "settings.json")
PATHS_FILE = join(CONFIG_DIR, "paths.json")
SCAN_STATE_FILE = join(CONFIG_DIR, "scan_state.json")
PROVIDER_STATE_FILE = join(CONFIG_DIR, "provider_state.json")
LAST_REFRESH_REPORT_FILE = join(RUNTIME_DIR, "last_media_refresh.json")
LAST_PROVIDER_ENRICH_FILE = join(RUNTIME_DIR, "last_provider_enrich.json")
STATUS_FILE = join(RUNTIME_DIR, "status.json")
GUI_COMMAND_FILE = join(RUNTIME_DIR, "gui_command.json")
COMMAND_SOCKET = join(RUNTIME_DIR, "e2mdbd.sock")
GUI_NOTIFY_SOCKET = join(RUNTIME_DIR, "gui_notify.sock")
PLUGIN_DIR = dirname(__file__)
WEB_DIR = join(PLUGIN_DIR, "web")
DEFAULT_WEB_PORT = 6066


def configured_web_port(webserver):
	webserver = webserver if isinstance(webserver, dict) else {}
	try:
		port = int(webserver.get("port") or DEFAULT_WEB_PORT)
	except Exception:
		port = DEFAULT_WEB_PORT
	if port < 1 or port > 65535:
		port = DEFAULT_WEB_PORT
	return port


def ensure_dirs():
	for path in (CONFIG_DIR, RUNTIME_DIR):
		if not exists(path):
			makedirs(path)


def atomic_write_json(path, payload):
	folder = dirname(path)
	if folder and not exists(folder):
		makedirs(folder)
	tmp_path = f"{path}.tmp"
	with open(tmp_path, "w", encoding="utf-8") as handle:
		dump(payload, handle, indent=2, sort_keys=True)
		handle.write("\n")
		handle.flush()
		try:
			fsync(handle.fileno())
		except Exception:
			pass
	rename(tmp_path, path)


def read_json(path, default=None):
	try:
		if isfile(path):
			with open(path, "r", encoding="utf-8") as handle:
				return load(handle)
	except Exception:
		pass
	return default


def log(message):
	line = f"[e2mdbd] {message}"
	try:
		print(line)
		stdout.flush()
	except Exception:
		pass


def iso_from_timestamp(value):
	try:
		value = int(value)
	except Exception:
		return ""
	if value <= 0:
		return ""
	try:
		return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime(value))
	except Exception:
		return ""


def send_gui_notification(event, source_key="", reason="backend", **payload):
	"""Send a best-effort push notification to Enigma2 without requiring polling."""
	source_key = str(source_key or "").strip()
	if not source_key:
		return False
	message = {"version": 1, "event": str(event or "metadata_updated"), "source_key": source_key, "reason": str(reason or "backend"), "updated": int(time())}
	message.update(payload or {})
	client = None
	try:
		client = socket(AF_UNIX, SOCK_DGRAM)
		client.settimeout(0.05)
		client.connect(GUI_NOTIFY_SOCKET)
		client.sendall((dumps(message, sort_keys=True) + "\n").encode("utf-8"))
		return True
	except Exception:
		return False
	finally:
		try:
			if client:
				client.close()
		except Exception:
			pass


def safe_int(value, default=0):
	try:
		return int(value)
	except Exception:
		return default


def truthy(value):
	return str(value or "").strip().lower() in ("1", "true", "yes", "on", "all", "pending")


class StatusStore:
	def __init__(self):
		self.lock = Lock()
		self.started = int(time())
		self.payload = {
			"version": 1,
			"daemon": {
				"running": True,
				"pid": getpid(),
				"started": self.started,
				"uptime_seconds": 0,
			},
			"job": None,
			"updated": int(time()),
		}
		self.write()

	def update(self, **changes):
		with self.lock:
			self.payload["daemon"]["pid"] = getpid()
			self.payload["daemon"]["uptime_seconds"] = int(time()) - self.started
			for key, value in changes.items():
				self.payload[key] = value
			self.payload["updated"] = int(time())
			self.write_locked()

	def set_job(self, job):
		self.update(job=job)

	def snapshot(self):
		with self.lock:
			self.payload["daemon"]["uptime_seconds"] = int(time()) - self.started
			self.payload["updated"] = int(time())
			return loads(dumps(self.payload))

	def write(self):
		with self.lock:
			self.write_locked()

	def write_locked(self):
		try:
			atomic_write_json(STATUS_FILE, self.payload)
		except Exception as err:
			log(f"status write failed: {err}")


class JobManager:
	def __init__(self, status_store, database=None, settings=None):
		self.status_store = status_store
		self.database = database
		self.settings = settings if isinstance(settings, dict) else {}
		self.provider_enricher = BackendProviderEnricher(self.settings)
		self.metadata_scanner = E2MDBBackendMetadataScanner()
		if self.metadata_scanner and hasattr(self.metadata_scanner, "configure"):
			self.metadata_scanner.configure(self.settings)
		self.lock = Lock()
		self.thread = None
		self.active_job = False
		self.stop_event = Event()
		self.current_job = None
		self.history_limit = 50
		self.live_worker_wake_event = None
		self.live_preempt_event = Event()
		self.last_live_checkpoint_poll = 0
		self.media_waiting_until = 0
		self.media_waiting_job = ""
		self.settings_reload_pending = False
		self.deferred_live = {
			"pending": False,
			"generation": 0,
			"request_count": 0,
			"limit": 0,
			"requested_at": 0,
			"updated_at": 0,
			"source": "",
		}

	def signal_live_worker_wake(self):
		try:
			if self.live_worker_wake_event:
				self.live_worker_wake_event.set()
		except Exception:
			pass

	def is_running(self):
		return bool(self.active_job)

	def _defer_live_request_locked(self, limit=25, source="api"):
		now = int(time())
		try:
			limit = max(1, min(100, safe_int(limit, 25)))
		except Exception:
			limit = 25
		state = self.deferred_live
		state["pending"] = True
		state["generation"] = safe_int(state.get("generation"), 0) + 1
		state["request_count"] = safe_int(state.get("request_count"), 0) + 1
		state["limit"] = max(safe_int(state.get("limit"), 0), limit)
		state["requested_at"] = safe_int(state.get("requested_at"), 0) or now
		state["updated_at"] = now
		state["source"] = str(source or state.get("source") or "api")
		self.live_preempt_event.set()
		self.signal_live_worker_wake()
		return loads(dumps(state))

	def _take_deferred_live_locked(self):
		if not self.deferred_live.get("pending"):
			return None
		request = loads(dumps(self.deferred_live))
		generation = safe_int(self.deferred_live.get("generation"), 0)
		self.deferred_live = {
			"pending": False,
			"generation": generation,
			"request_count": 0,
			"limit": 0,
			"requested_at": 0,
			"updated_at": int(time()),
			"source": "",
		}
		self.live_preempt_event.clear()
		return request

	def _deferred_live_snapshot(self):
		with self.lock:
			return loads(dumps(self.deferred_live))

	def _media_waiting(self):
		with self.lock:
			return bool(self.media_waiting_until > int(time()))

	def _new_job_locked(self, job_type, source, job_options):
		job_id = f"{job_type}-{uuid4().hex[:12]}"
		scheduler_job_id = str(job_options.get("scheduler_job_id") or "").strip()
		scheduler_job_name = str(job_options.get("scheduler_job_name") or scheduler_job_id).strip()
		job = {
			"id": job_id,
			"type": job_type,
			"source": source,
			"state": "queued",
			"phase": "queued",
			"current": 0,
			"total": 0,
			"percent": 0,
			"message": "Queued",
			"started": int(time()),
			"options": job_options,
		}
		if scheduler_job_id:
			job["scheduler_job_id"] = scheduler_job_id
			job["scheduler_job_name"] = scheduler_job_name
		return job

	def start(self, job_type="recording_scan", source="api", scheduler_connection=None, options=None):
		with self.lock:
			if self.is_running():
				if job_type == "live_epg_worker":
					job_options = dict(options) if isinstance(options, dict) else {}
					deferred = self._defer_live_request_locked(job_options.get("limit", 25), source=source)
					return {
						"success": True,
						"deferred": True,
						"busy": True,
						"message": "Backend is busy; Live/EPG worker wake queued",
						"job": self.current_job,
						"deferred_live": deferred,
					}
				if isinstance(self.current_job, dict) and self.current_job.get("type") == "live_epg_worker":
					self.media_waiting_until = int(time()) + 5
					self.media_waiting_job = str(job_type or "")
				return {"success": False, "busy": True, "retry_after_seconds": 1, "error": "job already running", "job": self.current_job}
			self.stop_event.clear()
			job_options = dict(options) if isinstance(options, dict) else {}
			if job_type != "live_epg_worker":
				self.media_waiting_until = 0
				self.media_waiting_job = ""
			if job_type == "live_epg_worker" and self.deferred_live.get("pending"):
				deferred = self._take_deferred_live_locked()
				job_options["limit"] = max(safe_int(job_options.get("limit"), 25), safe_int(deferred.get("limit"), 0))
				job_options["deferred_request_count"] = safe_int(deferred.get("request_count"), 0)
				job_options["deferred_generation"] = safe_int(deferred.get("generation"), 0)
			self.current_job = self._new_job_locked(job_type, source, job_options)
			self.status_store.set_job(self.current_job)
			self.active_job = True
			self.thread = Thread(target=self._run_job, args=(job_type, scheduler_connection, job_options), name="e2mdb-job")
			self.thread.daemon = True
			self.thread.start()
			return {"success": True, "job": self.current_job}

	def stop(self, source="api"):
		self.stop_event.set()
		return {"success": True, "message": "stop requested", "source": source}

	def get_queue_status(self):
		with self.lock:
			current = loads(dumps(self.current_job)) if self.current_job else None
			running = self.is_running()
			pending = []
			if current and str(current.get("state") or "") == "queued":
				pending.append(current)
			if self.deferred_live.get("pending"):
				pending.append({
					"type": "live_epg_worker",
					"state": "deferred",
					"limit": safe_int(self.deferred_live.get("limit"), 0),
					"request_count": safe_int(self.deferred_live.get("request_count"), 0),
					"requested_at": safe_int(self.deferred_live.get("requested_at"), 0),
				})
			return {
				"success": True,
				"queue": {
				"mode": "single_worker",
				"running": running,
				"current_job": current,
				"pending_jobs": pending,
					"pending_count": len(pending),
					"accepts_parallel_jobs": False,
					"deferred_live": loads(dumps(self.deferred_live)),
					"note": "The backend uses one worker. Live/EPG wakeups are coalesced into one durable in-memory handoff while a media job is active."
				}
			}

	def get_live_epg_queue_status(self):
		if self.database:
			return self.database.live_epg_queue_status()
		return {"success": False, "error": "database unavailable"}

	def get_live_epg_queue_items(self, limit=50, state="all", query=""):
		if self.database:
			return self.database.live_epg_queue_list(limit=limit, state=state, query=query)
		return {"success": False, "error": "database unavailable"}

	def get_live_epg_result(self, source_key):
		if self.database:
			return self.database.live_epg_result(source_key)
		return {"success": False, "error": "database unavailable"}

	def get_live_epg_artwork(self, source_key):
		if self.database:
			return self.database.live_epg_artwork(source_key)
		return {"success": False, "error": "database unavailable"}

	def get_live_epg_results(self, limit=50, query=""):
		if self.database:
			return self.database.live_epg_results(limit=limit, query=query)
		return {"success": False, "error": "database unavailable"}

	def get_live_epg_duplicates(self, limit=100, query="", fix=False):
		if self.database:
			return self.database.live_epg_duplicates(limit=limit, query=query, fix=fix)
		return {"success": False, "error": "database unavailable"}

	def reset_live_epg_queue_running(self):
		if self.database:
			return self.database.live_epg_queue_reset_running()
		return {"success": False, "error": "database unavailable"}

	def retry_live_epg_queue_no_match(self, active_only=True, priority=90):
		if self.database:
			return self.database.live_epg_queue_retry_no_match(active_only=active_only, priority=priority)
		return {"success": False, "error": "database unavailable", "matched": 0, "requeued": 0}

	def clear_live_epg_queue(self, mode="failed"):
		if self.database:
			return self.database.live_epg_queue_clear(mode=mode)
		return {"success": False, "error": "database unavailable", "removed": 0}

	def get_media_status(self, include_cache=True):
		if self.database:
			return self.database.media_status(
				scan_state=read_json(SCAN_STATE_FILE, {}),
				provider_state=read_json(PROVIDER_STATE_FILE, {}),
				job_history=read_json(self._job_history_path(), {"version": 1, "items": []}),
				current_job=self.status_store.snapshot().get("job"),
				include_cache=include_cache,
			)
		return {"success": False, "error": "database unavailable"}

	def get_cache_cleanup_status(self):
		if self.database:
			return self.database.cache_cleanup_status()
		return {"success": False, "error": "database unavailable"}

	def run_cache_cleanup(self, action="all_cache", dry_run=False):
		dry_run = str(dry_run).strip().lower() in ("1", "true", "yes", "on") if not isinstance(dry_run, bool) else dry_run
		if self.is_running():
			return {"success": False, "error": "cannot clean cache while a backend job is running"}
		if self.database:
			return self.database.run_cache_cleanup(action=action, dry_run=dry_run)
		return {"success": False, "error": "database unavailable"}

	def get_cleanup_status(self):
		if self.database:
			return self.database.live_epg_cleanup_status()
		return {"success": False, "error": "database unavailable"}

	def run_live_epg_cleanup(self, reason="manual", force=True, dry_run=False, remove_primary_cache=None):
		dry_run = str(dry_run).strip().lower() in ("1", "true", "yes", "on") if not isinstance(dry_run, bool) else dry_run
		if remove_primary_cache is not None and not isinstance(remove_primary_cache, bool):
			remove_primary_cache = str(remove_primary_cache).strip().lower() in ("1", "true", "yes", "on")
		if self.database:
			return self.database.run_live_epg_cleanup(reason=reason, force=force, dry_run=dry_run, remove_primary_cache=remove_primary_cache)
		return {"success": False, "error": "database unavailable"}

	def run_database_maintenance(self, vacuum=False, analyze=True, reindex=False):
		if self.database:
			return self.database.maintenance(vacuum=vacuum, analyze=analyze, reindex=reindex)
		return {"success": False, "error": f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}"}

	def read_recording_catalog(self):
		payload = read_json(self._recordings_catalog_path(), {"version": 1, "updated": 0, "items": []})
		if not isinstance(payload, dict):
			payload = {"version": 1, "updated": 0, "items": []}
		if not isinstance(payload.get("items"), list):
			payload["items"] = []
		return payload

	def get_recordings(self, offset=0, limit=50, query=""):
		if self.database:
			return self.database.list_recordings(offset=offset, limit=limit, query=query)
		catalog = self.read_recording_catalog()
		items = catalog.get("items", [])
		query = str(query or "").strip().lower()
		if query:
			filtered = []
			for item in items:
				text = " ".join([
					str(item.get("title") or ""),
					str(item.get("description") or ""),
					str(item.get("path") or ""),
				])
				if query in text.lower():
					filtered.append(item)
			items = filtered
		total = len(items)
		offset = max(0, safe_int(offset, 0))
		limit = max(1, min(500, safe_int(limit, 50)))
		return {
			"success": True,
			"version": catalog.get("version", 1),
			"updated": catalog.get("updated", 0),
			"total": total,
			"offset": offset,
			"limit": limit,
			"items": items[offset:offset + limit],
		}

	def get_recording(self, recording_id):
		if self.database:
			return self.database.get_recording(recording_id)
		for item in self.read_recording_catalog().get("items", []):
			if item.get("id") == recording_id or item.get("path") == recording_id:
				return {"success": True, "item": item}
		return {"success": False, "error": "recording not found"}

	def get_browser_status(self):
		if self.database:
			return self.database.browser_status()
		catalog = self.read_recording_catalog()
		return {
			"success": True,
			"index_ready": True,
			"index_building": False,
			"people_index_ready": False,
			"total": len(catalog.get("items", [])),
			"source": "json",
		}

	def get_browser_items(self, page=1, offset=None, limit=50, query="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		if self.database:
			return self.database.list_browser(page=page, offset=offset, limit=limit, q=query, media_type=media_type, year=year, genre=genre, cast=cast, letter=letter, include_pending=include_pending)
		recordings = self.get_recordings(offset=offset or 0, limit=limit, query=query)
		items = []
		for item in recordings.get("items", []):
			title = item.get("title") or item.get("name") or item.get("path", "").split("/")[-1]
			items.append({
				"id": item.get("id"),
				"browser_key": item.get("id"),
				"media_hash": item.get("id"),
				"title": title,
				"name": title,
				"file_name": item.get("name") or item.get("path", "").split("/")[-1],
				"file_path": item.get("path"),
				"overview": item.get("description") or item.get("extended_description") or "",
				"media_type": "movie",
				"scan_status": item.get("scan_status") or "pending",
			})
		recordings["items"] = items
		recordings["has_more"] = recordings.get("offset", 0) + recordings.get("limit", 0) < recordings.get("total", 0)
		recordings["facets"] = {"years": [], "genres": [], "casts": [], "index_ready": True, "index_building": False, "people_index_ready": False}
		recordings["index_ready"] = True
		recordings["index_building"] = False
		recordings["people_index_ready"] = False
		recordings["visibility"] = "json-fallback"
		return recordings

	def debug_browser_artwork(self, limit=30, query=""):
		if self.database:
			return self.database.debug_artwork(limit=limit, q=query)
		return {"success": False, "error": "database unavailable"}

	def debug_browser_performance(self, limit=24):
		if self.database:
			return self.database.debug_performance(limit=limit)
		return {"success": False, "error": "database unavailable"}

	def get_browser_item(self, item_id):
		if self.database:
			return self.database.get_browser_item(item_id)
		item = self.get_recording(item_id)
		if not item.get("success"):
			return item
		raw = item.get("item", {})
		title = raw.get("title") or raw.get("name") or raw.get("path", "").split("/")[-1]
		return {"success": True, "media_hash": raw.get("id"), "media_type": "movie", "media": {"id": raw.get("id"), "hash": raw.get("id"), "file_path": raw.get("path"), "file_name": raw.get("name")}, "data": {"title": title, "overview": raw.get("description") or raw.get("extended_description") or "", "media_type": "movie"}, "result": {}, "raw": raw}

	def get_editor_items(self, page=1, limit=30, query="", status="all", media_type="all", letter=""):
		if self.database:
			return self.database.list_editor(page=page, limit=limit, q=query, status=status, media_type=media_type, letter=letter)
		data = self.get_browser_items(page=page, limit=limit, query=query, media_type=media_type, letter=letter)
		return {"success": True, "results": data.get("items", []), "has_more": data.get("has_more", False), "page": page, "limit": limit, "total": data.get("total", 0)}

	def get_editor_item(self, item_id):
		if self.database:
			return self.database.get_editor_item(item_id)
		item = self.get_browser_item(item_id)
		return {"success": item.get("success", False), "media": item.get("media", {}), "data": item.get("data", {}), "results": {"success": True, "results": []}, "scan_info": item.get("raw", {})}

	def get_series_details(self, item_id):
		if self.database:
			return self.database.get_series_details(item_id)
		return {"success": True, "details": {"seasons": [], "cast": []}, "episode_index": {}, "local_inventory": {"seasons": [], "files": [], "season_count": 0, "episode_count": 0}}

	def get_season_details(self, item_id, season_no):
		if self.database:
			return self.database.get_season_details(item_id, season_no)
		return {"success": True, "details": {"season_no": str(season_no or ""), "episodes": []}, "season_no": str(season_no or "")}

	def queue_gui_command(self, action, args=None):
		args = args if isinstance(args, dict) else {}
		command = {
			"version": 1,
			"id": str(uuid4()),
			"action": str(action or ""),
			"created": int(time()),
			"source": "backend-web",
		}
		if action == "play":
			item_id = str(args.get("id") or args.get("media_hash") or "")
			target = self.database.get_playback_target(item_id) if self.database else {"success": False, "error": "database unavailable"}
			if not target.get("success"):
				return {"success": False, "error": target.get("error") or "playback target not found"}
			command.update({
				"target_id": item_id,
				"file_path": target.get("file_path") or "",
				"file_name": target.get("file_name") or "",
				"title": target.get("title") or "",
			})
		try:
			atomic_write_json(GUI_COMMAND_FILE, command)
			return {"success": True, "queued": True, "command": command, "message": "queued for Enigma2 GUI bridge"}
		except Exception as err:
			return {"success": False, "error": f"unable to queue GUI command: {err}"}

	def handle_web_results_action(self, args):
		action = str(args.get("action") or "")
		if action == "i18n":
			return {}
		if action == "browser_status":
			return self.get_browser_status()
		if action == "browser_list":
			return self.get_browser_items(
				page=args.get("page", 1),
				limit=args.get("limit", 24),
				query=args.get("q", args.get("query", "")),
				media_type=args.get("media_type", "all"),
				year=args.get("year", ""),
				genre=args.get("genre", ""),
				cast=args.get("cast", ""),
				letter=args.get("letter", ""),
				include_pending=args.get("include_pending", args.get("show_pending", "0")),
			)
		if action == "browser_item":
			return self.get_browser_item(args.get("id") or args.get("media_hash") or "")
		if action in ("debug_artwork", "browser_debug_artwork"):
			return self.debug_browser_artwork(limit=args.get("limit", 30), query=args.get("q", args.get("query", "")))
		if action in ("debug_performance", "browser_debug_performance"):
			return self.debug_browser_performance(limit=args.get("limit", 24))
		if action == "series_details":
			return self.get_series_details(args.get("id") or "")
		if action == "season_details":
			return self.get_season_details(args.get("id") or "", args.get("season_no") or "")
		if action == "list":
			return self.get_editor_items(page=args.get("page", 1), limit=args.get("limit", 30), query=args.get("q", ""), status=args.get("status", "all"), media_type=args.get("media_type", "all"), letter=args.get("letter", ""))
		if action == "get":
			return self.get_editor_item(args.get("id") or "")
		if action in ("apply_result", "set_images", "rename", "rescan"):
			return {"success": False, "error": "This editor action is not implemented in the backend daemon yet."}
		if action == "play":
			return self.queue_gui_command("play", args)
		if action == "stop":
			return self.queue_gui_command("stop", args)
		if action == "preview":
			return {"success": False, "error": "Preview generation is not implemented in the backend daemon yet."}
		return {"success": False, "error": f"unknown action: {action}"}

	def _compact_media_status(self, include_cache=True):
		if not self.database:
			return {"available": False, "error": "database unavailable"}
		try:
			payload = self.database.media_status(
				scan_state=read_json(SCAN_STATE_FILE, {}),
				provider_state=read_json(PROVIDER_STATE_FILE, {}),
				job_history={"version": 1, "items": []},
				current_job=None,
				include_cache=include_cache,
			)
		except Exception as err:
			return {"available": False, "error": str(err)}
		media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
		browser = payload.get("browser") if isinstance(payload.get("browser"), dict) else {}
		provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
		artwork = payload.get("artwork") if isinstance(payload.get("artwork"), dict) else {}
		cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
		live_epg = payload.get("live_epg") if isinstance(payload.get("live_epg"), dict) else {}
		return {
			"available": True,
			"updated": payload.get("updated", 0),
			"recordings_total": media.get("recordings_total", 0),
			"media_total": media.get("total", 0),
			"movies": media.get("movies", 0),
			"series": media.get("series", 0),
			"local_episodes": media.get("local_episodes", 0),
			"browser_ready": browser.get("ready", 0),
			"browser_pending": browser.get("pending", 0),
			"provider_done": provider.get("done", 0),
			"provider_pending": provider.get("pending", 0),
			"provider_missing": provider.get("missing", 0),
			"provider_errors": provider.get("errors", 0),
			"provider_matches_total": provider.get("matches_total", 0),
			"missing_metadata": provider.get("missing_metadata", 0),
			"media_with_artwork": artwork.get("media_with_artwork", 0),
			"missing_artwork": artwork.get("missing_artwork", 0),
			"artwork_cache_files": artwork.get("cache_files", 0),
			"cache_files": cache.get("files", 0),
			"cache_inventory_skipped": bool(cache.get("inventory_skipped") or artwork.get("inventory_skipped")),
			"live_epg_events_total": live_epg.get("events_total", 0),
			"live_epg_queue_total": live_epg.get("queue_total", 0),
			"warnings": payload.get("warnings", [])[:10] if isinstance(payload.get("warnings"), list) else [],
		}

	def _refresh_report_from_job(self, job, media_summary=None):
		job = job if isinstance(job, dict) else {}
		report = {
			"version": 1,
			"updated": int(time()),
			"job": {
				"id": job.get("id") or "",
				"type": job.get("type") or "",
				"source": job.get("source") or "",
				"state": job.get("state") or "",
				"message": job.get("message") or "",
				"started": job.get("started", 0),
				"finished": job.get("finished", 0),
				"scheduler_job_id": job.get("scheduler_job_id") or "",
				"scheduler_job_name": job.get("scheduler_job_name") or "",
			},
			"scan_state": read_json(SCAN_STATE_FILE, {}),
			"provider_state": read_json(PROVIDER_STATE_FILE, {}),
			"media_summary": media_summary if isinstance(media_summary, dict) else self._compact_media_status(include_cache=False),
		}
		return report

	def get_refresh_status(self):
		current_job = self.status_store.snapshot().get("job")
		report = read_json(LAST_REFRESH_REPORT_FILE, {})
		return {
			"success": True,
			"current_job": current_job,
			"scheduler": self.get_scheduler_status(),
			"scan_state": read_json(SCAN_STATE_FILE, {}),
			"provider_state": read_json(PROVIDER_STATE_FILE, {}),
			"last_refresh_report": report,
			# Cache inventory has its own explicit endpoint and may recursively walk
			# large HDD trees. Refresh/status polling must stay lightweight.
			"media_status": self.get_media_status(include_cache=False),
		}

	def run_refresh_job(self, overrides=None):
		options = {"limit": 0, "only_missing": True, "rescan_existing": False}
		if isinstance(overrides, dict):
			options.update(overrides)
		return self.start(job_type="scan_and_enrich", source="refresh-run", options=options)

	def _append_job_history(self, job):
		try:
			job_history_path = self._job_history_path()
			payload = read_json(job_history_path, {"version": 1, "items": []})
			if not isinstance(payload, dict):
				payload = {"version": 1, "items": []}
			items = payload.get("items", [])
			if not isinstance(items, list):
				items = []
			items.insert(0, job)
			payload["version"] = 1
			payload["updated"] = int(time())
			payload["items"] = items[:self.history_limit]
			atomic_write_json(job_history_path, payload)
		except Exception as err:
			log(f"job history write failed: {err}")

	def _send_scheduler(self, connection, status="RUNNING", progress=0, message="", **extra):
		if not connection:
			return
		payload = {
			"status": status,
			"progress": int(progress or 0),
			"message": message or "",
		}
		payload.update(extra)
		try:
			connection.sendall((dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
		except Exception as err:
			log(f"scheduler send failed: {err}")

	def _update_job(self, scheduler_connection=None, send_scheduler=True, **changes):
		with self.lock:
			if not self.current_job:
				return
			self.current_job.update(changes)
			self.current_job["updated"] = int(time())
			job = loads(dumps(self.current_job))
		self.status_store.set_job(job)
		if send_scheduler:
			self._send_scheduler(
				scheduler_connection,
				status="RUNNING" if job.get("state") == "running" else str(job.get("state", "RUNNING")).upper(),
				progress=job.get("percent", 0),
				message=job.get("message", ""),
				phase=job.get("phase", ""),
			)

	def _finish_job(self, success=True, scheduler_connection=None, message=""):
		state = "success" if success else "error"
		status = "SUCCESS" if success else "ERROR"
		finished = int(time())
		self._update_job(scheduler_connection, send_scheduler=False, state=state, phase="done", percent=100 if success else 0, message=message or state, finished=finished)
		with self.lock:
			job = loads(dumps(self.current_job)) if self.current_job else {}
		try:
			# Job completion must never walk the complete cache/artwork trees. On large
			# disks that used to keep the single worker busy for minutes after the UI
			# already showed 100%, delaying every deferred EPG request.
			job["diagnostics"] = self._compact_media_status(include_cache=False)
		except Exception as err:
			job["diagnostics"] = {"available": False, "error": str(err)}
		if job.get("type") in ("scan_and_enrich", "recording_scan", "metadata_enrich") or job.get("scheduler_job_id") == "daily-media-refresh":
			try:
				atomic_write_json(LAST_REFRESH_REPORT_FILE, self._refresh_report_from_job(job, media_summary=job.get("diagnostics")))
			except Exception as err:
				log(f"refresh report write failed: {err}")
		self._append_job_history(job)
		self._send_scheduler(scheduler_connection, status=status, progress=100 if success else 0, message=message or state)
		try:
			if scheduler_connection:
				scheduler_connection.close()
		except Exception:
			pass

	def _run_job(self, job_type, scheduler_connection, options=None):
		"""Run one serial worker chain and hand deferred Live/EPG work over directly."""
		worker_thread = current_thread()
		current_type = job_type
		current_connection = scheduler_connection
		current_options = dict(options or {})
		try:
			while True:
				try:
					if current_type == "recording_scan":
						self._run_recording_scan(current_connection, options=current_options)
					elif current_type == "metadata_enrich":
						self._run_metadata_enrich(current_connection, current_options)
					elif current_type == "scan_and_enrich":
						job_options = dict(current_options)
						job_options["multi_phase"] = True
						self._run_recording_scan(current_connection, finish=False, options=job_options)
						if not self.stop_event.is_set():
							self._run_metadata_enrich(current_connection, job_options, finish=True)
					elif current_type == "live_epg_worker":
						self._run_live_epg_worker(current_connection, current_options)
					elif current_type == "live_epg_cleanup":
						self._run_live_epg_cleanup_job(current_connection, current_options)
					elif current_type == "sqlite_maintenance":
						self._run_sqlite_maintenance_job(current_connection, current_options)
					else:
						raise RuntimeError(f"unsupported job type: {current_type}")
				except Exception as err:
					log(f"job failed: {err}\n{format_exc()}")
					self._finish_job(success=False, scheduler_connection=current_connection, message=str(err))

				# A Live/EPG request accepted while media was busy is a real handoff,
				# independent of the optional auto-poll worker. Coalesce all wakeups
				# into one batch and keep provider/SQLite work strictly serial.
				pending_settings_reload = False
				with self.lock:
					yield_to_media = current_type == "live_epg_worker" and self.media_waiting_until > int(time())
					deferred = None if yield_to_media else self._take_deferred_live_locked()
					if deferred:
						current_options = {
							"limit": max(1, safe_int(deferred.get("limit"), 25)),
							"deferred_request_count": safe_int(deferred.get("request_count"), 0),
							"deferred_generation": safe_int(deferred.get("generation"), 0),
						}
						self.stop_event.clear()
						self.current_job = self._new_job_locked("live_epg_worker", "deferred-handoff", current_options)
						self.status_store.set_job(self.current_job)
						current_type = "live_epg_worker"
						current_connection = None
					else:
						# Slot release and the final deferred check are atomic. A wake
						# arriving afterwards sees an idle manager and starts directly.
						pending_settings_reload = bool(self.settings_reload_pending)
						self.settings_reload_pending = False
						if not pending_settings_reload:
							self.active_job = False
				if not deferred:
					if pending_settings_reload:
						reload_result = self._reload_settings_now()
						log(f"deferred settings reload completed success={bool(reload_result.get("success"))} error={reload_result.get("error") or ""}")
						with self.lock:
							self.active_job = False
					break
				log(f"deferred Live/EPG handoff started generation={deferred.get("generation", 0)} requests={deferred.get("request_count", 0)} limit={current_options.get("limit", 0)}")
		finally:
			# Release the logical worker slot before waking the poller. The old code
			# relied on Thread.is_alive(), so the wake raced with the finishing thread.
			with self.lock:
				if self.thread is worker_thread:
					self.active_job = False
			self.signal_live_worker_wake()

	def _require_metadata_scanner(self):
		if not self.metadata_scanner:
			raise RuntimeError("E2MDBBackendMetadataScanner unavailable")
		return self.metadata_scanner

	def _normalize_scan_paths(self, paths_payload):
		paths = []
		if isinstance(paths_payload, dict):
			paths_payload = paths_payload.get("paths", [])
		if isinstance(paths_payload, list):
			for item in paths_payload:
				if not isinstance(item, dict):
					continue
				path = str(item.get("path") or "").strip()
				try:
					mode = int(item.get("mode") or 0)
				except Exception:
					mode = 0
				recursive = bool(item.get("recursive", True))
				if path and mode and not any(existing["path"] == path for existing in paths):
					paths.append({"path": path, "mode": mode, "recursive": recursive})
		return paths

	def _load_scan_paths(self):
		paths = self._normalize_scan_paths(read_json(PATHS_FILE, []))
		return paths

	def _cache_results_dir(self):
		# Data dumps that grow with the library (recording catalog, job history)
		# belong next to the database under cache_root/results, not under the
		# small-config directory /etc/enigma2/e2mdb.
		if self.database and getattr(self.database, "db_path", ""):
			root = dirname(self.database.db_path)
		else:
			cache = self.settings.get("cache", {}) if isinstance(self.settings.get("cache", {}), dict) else {}
			database = self.settings.get("database", {}) if isinstance(self.settings.get("database", {}), dict) else {}
			root = str(cache.get("root") or database.get("root") or "/media/hdd/e2MDB")
		return join(root, "results")

	def _recordings_catalog_path(self):
		return join(self._cache_results_dir(), "recordings.json")

	def _job_history_path(self):
		return join(self._cache_results_dir(), "job_history.json")

	def _effective_scan_paths(self, options=None):
		options = options if isinstance(options, dict) else {}
		paths = self._normalize_scan_paths(options.get("paths"))
		return paths or self._load_scan_paths()

	def _scanner_rescan_existing(self, options=None):
		options = options if isinstance(options, dict) else {}
		if "rescan_existing" in options:
			return truthy(options.get("rescan_existing"))
		scanner_settings = self.settings.get("scanner", {}) if isinstance(self.settings.get("scanner", {}), dict) else {}
		return truthy(scanner_settings.get("rescan_existing", False))

	def _file_signature(self, path):
		try:
			return getsize(path), safe_int(getmtime(path), 0)
		except Exception:
			return 0, 0

	def _scan_path_diagnostics(self, scan_paths, count_files=False, checkpoint=None):
		payload = self._require_metadata_scanner().scan_path_diagnostics(scan_paths, count_files=count_files, checkpoint=checkpoint)
		payload["version"] = 1
		payload["updated"] = int(time())
		return payload

	def get_scan_paths_status(self, count_files=False):
		paths = self._load_scan_paths()
		payload = self._scan_path_diagnostics(paths, count_files=count_files)
		payload["source"] = "paths-json"
		payload["paths_file"] = PATHS_FILE
		return payload

	def _iter_video_files(self, scan_paths):
		return self._require_metadata_scanner().iter_media_files(scan_paths)

	def _run_recording_scan(self, scheduler_connection=None, finish=True, options=None):
		options = options if isinstance(options, dict) else {}
		multi_phase = bool(options.get("multi_phase")) or not finish
		scan_paths = self._effective_scan_paths(options)
		self._update_job(
			scheduler_connection,
			state="running",
			phase="validate_paths",
			part_current=1 if multi_phase else 1,
			part_total=3 if multi_phase else 1,
			phase_percent=0,
			message="Validating media scan paths",
		)
		path_status = self._scan_path_diagnostics(
			scan_paths,
			count_files=False,
			checkpoint=lambda: self._media_live_epg_checkpoint(reason="scan-path-validate"),
		)
		if path_status.get("valid_count", 0) <= 0:
			summary = {
				"version": 1,
				"updated": int(time()),
				"updated_iso": iso_from_timestamp(int(time())),
				"total": 0,
				"ts_recordings": 0,
				"media_files": 0,
				"errors": path_status.get("invalid_count", 0),
				"paths": scan_paths,
				"path_status": path_status,
				"message": "No valid recording/media scan paths found",
			}
			atomic_write_json(SCAN_STATE_FILE, summary)
			atomic_write_json(join(RUNTIME_DIR, "last_recording_scan.json"), dict(summary, items=[]))
			self.stop_event.set()
			self._finish_job(success=False, scheduler_connection=scheduler_connection, message="No valid recording/media scan paths found")
			return
		self._update_job(
			scheduler_connection,
			state="running",
			phase="collect",
			part_current=1 if multi_phase else 1,
			part_total=3 if multi_phase else 1,
			phase_percent=5,
			message="Collecting media files",
		)
		scanner = self._require_metadata_scanner()
		files = scanner.collect_media_files(
			scan_paths,
			checkpoint=lambda: self._media_live_epg_checkpoint(reason="scan-file-collect"),
		)
		self._media_live_epg_checkpoint(reason="scan-file-collect-done", force=True)
		total = len(files)
		rescan_existing = self._scanner_rescan_existing(options)
		existing_index = {}
		if self.database and not rescan_existing:
			try:
				existing_index = self.database.recording_index(paths=scan_paths)
			except Exception as err:
				log(f"recording index lookup failed, falling back to normal scan: {err}")
				existing_index = {}
		path_status = self._scan_path_diagnostics(
			scan_paths,
			count_files=True,
			checkpoint=lambda: self._media_live_epg_checkpoint(reason="scan-path-diagnostics"),
		)
		if scanner.native_parser_required_missing(files):
			raise RuntimeError(scanner.native_parser_missing_message())
		if total <= 0:
			summary = {
				"version": 1,
				"updated": int(time()),
				"updated_iso": iso_from_timestamp(int(time())),
				"total": 0,
				"ts_recordings": 0,
				"media_files": 0,
				"errors": len(path_status.get("errors", [])),
				"paths": scan_paths,
				"path_status": path_status,
				"message": "No media files found in configured scan paths",
			}
			atomic_write_json(SCAN_STATE_FILE, summary)
			atomic_write_json(join(RUNTIME_DIR, "last_recording_scan.json"), dict(summary, items=[]))
			if finish:
				self._finish_job(success=True, scheduler_connection=scheduler_connection, message="No media files found in configured scan paths")
			else:
				self._update_job(scheduler_connection, state="running", phase="recording_scan_done", current=0, total=0, percent=50 if multi_phase else 100, phase_percent=100, part_current=2 if multi_phase else 1, part_total=3 if multi_phase else 1, message="No media files found in configured scan paths")
			return
		recordings = []
		seen_ids = []
		error_count = 0
		skipped_existing = 0
		ts_count = 0
		media_count = 0
		# TEMP DEBUG SWITCH: /tmp/e2MDB.flag logs the provider search candidates without querying providers. Remove later.
		scanner_only_debug = isfile("/tmp/e2MDB.flag")
		for index, (media_path, path_item) in enumerate(files, start=1):
			if self.stop_event.is_set():
				self._send_scheduler(scheduler_connection, status="ABORTED", progress=int((index - 1) * 100 / total), message="Aborted")
				self._finish_job(success=False, scheduler_connection=scheduler_connection, message="Aborted")
				return
			self._media_live_epg_checkpoint(reason="recording-scan-before-item")
			recording_id = scanner.make_recording_id(media_path)
			if recording_id and recording_id not in seen_ids:
				seen_ids.append(recording_id)
			file_size, file_mtime = self._file_signature(media_path)
			existing = existing_index.get(recording_id) or existing_index.get(media_path)
			if existing and not rescan_existing:
				existing_size = safe_int(existing.get("size_bytes"), -1)
				existing_mtime = safe_int(existing.get("mtime"), -1)
				if existing_size == file_size and existing_mtime == file_mtime:
					skipped_existing += 1
					source_type = "recording" if scanner.has_sidecar_infos(media_path) else "media_file"
					if source_type == "recording":
						ts_count += 1
					else:
						media_count += 1
					title = existing.get("title") or basename(media_path)
					phase_percent = int(index * 100 / total)
					percent = int(index * 40 / total) if multi_phase else phase_percent
					self._update_job(
						scheduler_connection,
						state="running",
						phase="recording_scan",
						current=index,
						total=total,
						percent=percent,
						phase_percent=phase_percent,
						part_current=1 if multi_phase else 1,
						part_total=3 if multi_phase else 1,
						path=media_path,
						title=title,
						source_type=source_type,
						path_mode=existing.get("path_mode"),
						provider_media_type=existing.get("provider_media_type"),
						message="Skipping unchanged media files",
					)
					self._media_live_epg_checkpoint(reason="recording-scan-after-unchanged")
					continue
			recording = scanner.scan_media_file(media_path, path_item)
			if scanner_only_debug:
				mode = path_item.get("mode") if isinstance(path_item, dict) else None
				log(f"[e2MDB.flag] path='{media_path}' mode={mode} ({scanner.path_mode_label(mode)}) recursive={path_item.get("recursive") if isinstance(path_item, dict) else None}")
				log(f"[e2MDB.flag] parser: title='{recording.get("title")}' source_type={recording.get("source_type")} estimated_media_type={recording.get("estimated_media_type")} media_family={recording.get("media_family")} series_title='{recording.get("series_title")}' movie_title='{recording.get("movie_title")}' season={recording.get("season_no")} episode={recording.get("episode_no")} year={recording.get("year")} parse_error='{recording.get("parse_error")}'")
				if self.provider_enricher:
					candidates = self.provider_enricher.candidate_titles(recording)
					log(f"[e2MDB.flag] search candidates: {candidates}")
			if recording.get("source_type") == "recording":
				ts_count += 1
			else:
				media_count += 1
			if recording.get("scan_status") == "error":
				error_count += 1
			recordings.append(recording)
			title = recording.get("title") or basename(media_path)
			phase_percent = int(index * 100 / total)
			percent = int(index * 40 / total) if multi_phase else phase_percent
			if recording.get("source_type") == "recording":
				scan_message = "Scanning TS recordings"
			else:
				scan_message = "Scanning media files"
			self._update_job(
				scheduler_connection,
				state="running",
				phase="recording_scan",
				current=index,
				total=total,
				percent=percent,
				phase_percent=phase_percent,
				part_current=1 if multi_phase else 1,
				part_total=3 if multi_phase else 1,
				path=media_path,
				title=title,
				source_type=recording.get("source_type"),
				path_mode=recording.get("path_mode"),
				provider_media_type=recording.get("provider_media_type"),
				message=scan_message,
			)
			self._media_live_epg_checkpoint(reason="recording-scan-after-item")
			if index % 25 == 0:
				sleep(0.01)
		summary = {
			"version": 1,
			"updated": int(time()),
			"updated_iso": iso_from_timestamp(int(time())),
			"total": total,
			"scanned": len(recordings),
			"skipped_existing": skipped_existing,
			"rescan_existing": rescan_existing,
			"ts_recordings": ts_count,
			"media_files": media_count,
			"ignored_files": path_status.get("ignored_files", 0),
			"ignored_by_extension": path_status.get("ignored_by_extension", {}),
			"errors": error_count + len(path_status.get("errors", [])),
			"parse_errors": error_count,
			"paths": scan_paths,
			"path_status": path_status,
		}
		payload = dict(summary)
		payload["items"] = recordings
		try:
			atomic_write_json(self._recordings_catalog_path(), payload)
			atomic_write_json(SCAN_STATE_FILE, summary)
			atomic_write_json(join(RUNTIME_DIR, "last_recording_scan.json"), payload)
		except Exception as err:
			log(f"recording catalog write failed: {err}")
		db_result = {}
		if self.database:
			self._media_live_epg_checkpoint(reason="recording-scan-before-db-import", force=True)
			self._update_job(
				scheduler_connection,
				state="running",
				phase="db_import",
				current=total,
				total=total,
				percent=45 if multi_phase else 99,
				phase_percent=0,
				part_current=2 if multi_phase else 1,
				part_total=3 if multi_phase else 1,
				message="Importing scan data",
			)
			try:
				db_result = self.database.upsert_recordings(recordings, prune_missing=True, prune_paths=scan_paths, seen_ids=seen_ids)
				db_result["skipped_existing"] = skipped_existing
				db_result["rescan_existing"] = rescan_existing
				summary["database"] = db_result
				atomic_write_json(SCAN_STATE_FILE, summary)
			except Exception as err:
				log(f"recording database import failed: {err}")
				raise
			self._media_live_epg_checkpoint(reason="recording-scan-after-db-import", force=True)
		message = f"Media path scan completed: {total} supported media files ({ts_count} TS recordings, {media_count} media files), {len(recordings)} scanned, {skipped_existing} unchanged skipped, {error_count} errors"
		if db_result:
			message += f", SQLite imported: {db_result.get("inserted_or_updated", 0)}"
		if finish:
			self._finish_job(success=True, scheduler_connection=scheduler_connection, message=message)
		else:
			self._update_job(
				scheduler_connection,
				state="running",
				phase="recording_scan_done",
				current=total,
				total=total,
				percent=50 if multi_phase else 100,
				phase_percent=100,
				part_current=2 if multi_phase else 1,
				part_total=3 if multi_phase else 1,
				message=message,
			)

	def _run_metadata_enrich(self, scheduler_connection=None, options=None, finish=True):
		if not self.database:
			raise RuntimeError(f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}")
		if not self.provider_enricher:
			raise RuntimeError("provider enricher unavailable")
		options = options if isinstance(options, dict) else {}
		multi_phase = bool(options.get("multi_phase")) or not finish
		limit = safe_int(options.get("limit"), safe_int(self.settings.get("provider", {}).get("job_limit"), 100))
		if limit <= 0:
			limit = 100000
		query = str(options.get("query") or "")
		rescan_existing = self._scanner_rescan_existing(options)
		only_missing = truthy(options.get("only_missing")) if "only_missing" in options else not rescan_existing
		retry_no_match = truthy(options.get("retry_no_match"))
		retry_missing_artwork = truthy(options.get("retry_missing_artwork"))
		path_filters = self._normalize_scan_paths(options.get("paths")) if "paths" in options else None
		self._update_job(
			scheduler_connection,
			state="running",
			phase="provider_prepare",
			current=0,
			total=0,
			percent=50 if multi_phase else 0,
			phase_percent=0,
			part_current=3 if multi_phase else 1,
			part_total=3 if multi_phase else 1,
			message="Preparing provider search",
		)
		items = self.database.list_recordings_for_enrichment(
			limit=limit,
			query=query,
			only_missing=only_missing,
			paths=path_filters,
			retry_no_match=retry_no_match,
			retry_missing_artwork=retry_missing_artwork,
		)
		total = len(items)
		if total <= 0:
			message = "No recordings need provider enrichment"
			state_payload = {"version": 1, "updated": int(time()), "total": 0, "success": 0, "errors": 0, "message": message}
			atomic_write_json(PROVIDER_STATE_FILE, state_payload)
			if finish:
				self._finish_job(success=True, scheduler_connection=scheduler_connection, message=message)
			else:
				self._update_job(scheduler_connection, state="running", phase="provider_done", current=0, total=0, percent=100, phase_percent=100, part_current=3 if multi_phase else 1, part_total=3 if multi_phase else 1, message=message)
			return
		self._media_live_epg_checkpoint(reason="metadata-enrich-start", force=True)
		# TEMP DEBUG SWITCH: /tmp/e2MDB.flag logs the raw provider result. Remove later.
		provider_debug = isfile("/tmp/e2MDB.flag")
		ok_count = 0
		no_match_count = 0
		error_count = 0
		details = []
		for index, item in enumerate(items, start=1):
			if self.stop_event.is_set():
				self._send_scheduler(scheduler_connection, status="ABORTED", progress=int((index - 1) * 100 / total), message="Aborted")
				self._finish_job(success=False, scheduler_connection=scheduler_connection, message="Aborted")
				return
			self._media_live_epg_checkpoint(reason="metadata-enrich-before-item")
			title = item.get("title") or basename(item.get("path") or "")
			phase_percent = int(index * 100 / total)
			if multi_phase:
				percent = 50 + int(index * 50 / total)
			else:
				percent = phase_percent
			self._update_job(
				scheduler_connection,
				state="running",
				phase="provider_lookup",
				current=index,
				total=total,
				percent=percent,
				phase_percent=phase_percent,
				part_current=3 if multi_phase else 1,
				part_total=3 if multi_phase else 1,
				title=title,
				path=item.get("path"),
				message="Searching internet metadata",
			)
			try:
				result = self.provider_enricher.search_item(item)
				if provider_debug:
					log(f"[e2MDB.flag] provider result for '{item.get("path")}': {result}")
				self.database.upsert_provider_result(item, result)
				best = result.get("best") if isinstance(result.get("best"), dict) else {}
				detail = {
					"index": index,
					"id": item.get("id") or "",
					"path": item.get("path") or "",
					"title": title,
					"provider_title": item.get("provider_title") or "",
					"provider_media_type": item.get("provider_media_type") or "",
					"success": bool(result.get("success")),
					"error": str(result.get("error") or ""),
					"matches": len(result.get("matches") if isinstance(result.get("matches"), list) else []),
					"best_provider": best.get("provider") or "",
					"best_provider_id": best.get("provider_id") or best.get("id") or "",
					"best_title": best.get("title") or best.get("original_title") or best.get("episode_name") or "",
				}
				details.append(detail)
				if result.get("success"):
					ok_count += 1
				elif str(result.get("error") or "") == "no provider match":
					no_match_count += 1
				else:
					error_count += 1
			except Exception as err:
				error_count += 1
				error_result = {"success": False, "error": str(err), "matches": [], "best": {}, "updated": int(time())}
				self.database.upsert_provider_result(item, error_result)
				details.append({
					"index": index,
					"id": item.get("id") or "",
					"path": item.get("path") or "",
					"title": title,
					"provider_title": item.get("provider_title") or "",
					"provider_media_type": item.get("provider_media_type") or "",
					"success": False,
					"error": str(err),
					"matches": 0,
				})
				log(f"provider enrichment failed for '{item.get("path")}': {err}")
			self._media_live_epg_checkpoint(reason="metadata-enrich-after-item")
			if index % 5 == 0:
				sleep(0.01)
		state_payload = {
			"version": 1,
			"updated": int(time()),
			"total": total,
			"success": ok_count,
			"no_match": no_match_count,
			"errors": error_count,
			"limit": limit,
			"query": query,
			"only_missing": only_missing,
			"error_items": [item for item in details if not item.get("success")][:50],
		}
		atomic_write_json(PROVIDER_STATE_FILE, state_payload)
		atomic_write_json(LAST_PROVIDER_ENRICH_FILE, {
			"version": 1,
			"updated": state_payload["updated"],
			"total": total,
			"success": ok_count,
			"no_match": no_match_count,
			"errors": error_count,
			"items": details[:200],
		})
		message = f"Provider enrichment completed: {ok_count} ok, {no_match_count} no match, {error_count} errors"
		if finish:
			self._finish_job(success=True, scheduler_connection=scheduler_connection, message=message)
		else:
			self._update_job(scheduler_connection, state="running", phase="provider_done", current=total, total=total, percent=100, phase_percent=100, part_current=3 if multi_phase else 1, part_total=3 if multi_phase else 1, message=message)

	def _live_queue_item_to_provider_item(self, queue_item):
		queue_item = queue_item if isinstance(queue_item, dict) else {}
		source_key = str(queue_item.get("source_key") or "").strip()
		title = str(queue_item.get("search_title") or queue_item.get("title") or "").strip()
		if not title:
			title = str(queue_item.get("title") or source_key or "").strip()
		short_desc = str(queue_item.get("short_desc") or "")
		extended_desc = str(queue_item.get("extended_desc") or "")
		return {
			"id": source_key,
			"source_key": source_key,
			"path": f"live://{source_key}",
			"title": title,
			"description": short_desc,
			"short_desc": short_desc,
			"extended_description": extended_desc,
			"extended_desc": extended_desc,
			"provider_title": title,
			"search_candidates": [value for value in (title, queue_item.get("title"), queue_item.get("search_title"), short_desc) if value],
			"provider_media_type": "multi",
			"estimated_media_type": "multi",
			"media_family": "multi",
			"source_type": "live_epg",
			"service_ref": str(queue_item.get("service_ref") or ""),
			"begin_time": safe_int(queue_item.get("begin_time"), 0),
			"event_end": safe_int(queue_item.get("event_end"), 0),
		}

	def _live_provider_result_is_transient(self, result):
		result = result if isinstance(result, dict) else {}
		if result.get("success"):
			return False
		error = str(result.get("error") or "").strip()
		return bool(result.get("transient_error") or (error and error != "no provider match"))

	def _live_epg_preempt_settings(self):
		live_epg = self.settings.get("live_epg", {}) if isinstance(self.settings.get("live_epg", {}), dict) else {}
		# Keep the threshold at InfoBar/ad-hoc level by default. ServiceList visible-now
		# uses 86, EventView/EPG-open/ad-hoc are above that, while prefill/next rows stay
		# below and continue to wait for the normal Live/EPG worker.
		min_priority = safe_int(live_epg.get("preempt_min_priority", live_epg.get("daemon_preempt_min_priority", 80)), 80)
		max_items = safe_int(live_epg.get("preempt_max_items", live_epg.get("daemon_preempt_max_items", 2)), 2)
		return max(1, min(99, min_priority)), max(0, min(10, max_items))

	def _media_live_epg_checkpoint(self, reason="media-job", force=False):
		"""Yield one complete media safe-point to urgent Live/EPG work.

		The in-memory event makes the per-file check cheap. A calm periodic poll is
		kept as a fallback for queue producers whose socket wake failed.
		"""
		if self.stop_event.is_set():
			return {"success": True, "processed": 0, "stopped": True}
		now = int(time())
		live_epg = self.settings.get("live_epg", {}) if isinstance(self.settings.get("live_epg", {}), dict) else {}
		poll_interval = max(2, min(60, safe_int(live_epg.get("preempt_poll_interval_seconds", 5), 5)))
		event_pending = self.live_preempt_event.is_set()
		if not force and not event_pending and now - safe_int(self.last_live_checkpoint_poll, 0) < poll_interval:
			return {"success": True, "processed": 0, "skipped": True}
		self.last_live_checkpoint_poll = now
		with self.lock:
			generation = safe_int(self.deferred_live.get("generation"), 0)
		result = self._process_high_priority_live_epg_queue(reason=reason, max_items=1)
		# Clear only the fast preemption hint, never the durable deferred handoff.
		# A wake arriving during provider work increments generation and stays set.
		if safe_int(result.get("processed"), 0) <= 0:
			with self.lock:
				if generation == safe_int(self.deferred_live.get("generation"), 0):
					self.live_preempt_event.clear()
		return result

	def _process_high_priority_live_epg_queue(self, reason="media-job", max_items=None, min_priority=None):
		"""Process high-priority Live/EPG queue rows while a media job is running.

		The backend has a single SQLite writer, so this runs inside the active media
		job thread instead of starting a second job. That preserves the v16 behavior
		where current-screen/ad-hoc requests jump ahead of long background scans,
		without bringing back an Enigma2-side worker.
		"""
		if not self.database or not self.provider_enricher:
			return {"success": False, "processed": 0, "error": "database or provider unavailable"}
		default_min_priority, default_max_items = self._live_epg_preempt_settings()
		if min_priority is None:
			min_priority = default_min_priority
		else:
			min_priority = safe_int(min_priority, default_min_priority)
		if max_items is None:
			max_items = default_max_items
		else:
			max_items = safe_int(max_items, default_max_items)
		if max_items <= 0:
			return {"success": True, "processed": 0, "min_priority": min_priority, "disabled": True}
		processed = 0
		ok_count = 0
		no_match_count = 0
		error_count = 0
		items = []
		while processed < max_items and not self.stop_event.is_set():
			queue_item = self.database.live_epg_queue_next_item(int(time()), min_priority=min_priority)
			if not queue_item:
				break
			processed += 1
			source_key = str(queue_item.get("source_key") or "")
			title = str(queue_item.get("search_title") or queue_item.get("title") or source_key)
			event_end = safe_int(queue_item.get("event_end"), 0)
			attempts = safe_int(queue_item.get("attempts"), 0)
			priority = safe_int(queue_item.get("priority"), 0)
			entry = {"source_key": source_key, "title": title, "priority": priority, "reason": queue_item.get("reason") or ""}
			finalized = False
			try:
				if event_end and event_end < int(time()) - 300:
					self.database.live_epg_queue_update_state(source_key, "ended_skipped", attempts=attempts, not_before=0, last_error="event-ended-before-backend-preempt")
					finalized = True
					send_gui_notification("live_epg_skipped", source_key, reason=f"backend-preempt-{reason}", state="ended_skipped")
					no_match_count += 1
					entry.update({"state": "ended_skipped", "success": False, "error": "event-ended-before-backend-preempt"})
					items.append(entry)
					continue
				provider_item = self._live_queue_item_to_provider_item(queue_item)
				result = self.provider_enricher.search_item(provider_item)
				if result.get("success"):
					self.database.live_epg_queue_upsert_backend_result(queue_item, result)
					self.database.live_epg_queue_update_state(source_key, "done", attempts=attempts, not_before=0, last_error="")
					finalized = True
					send_gui_notification("live_epg_updated", source_key, reason=f"backend-preempt-{reason}", state="done")
					ok_count += 1
					entry.update({"state": "done", "success": True})
				elif self._live_provider_result_is_transient(result):
					error_text = str(result.get("error") or "provider temporarily unavailable")
					not_before = int(time()) + min(3600, 300 * max(1, attempts))
					released = self.database.live_epg_queue_release_running(source_key, attempts=attempts, not_before=not_before, last_error=error_text)
					finalized = bool(released.get("updated"))
					error_count += 1
					entry.update({"state": "pending", "success": False, "error": error_text, "not_before": not_before})
				else:
					error_text = str(result.get("error") or "no provider match")
					self.database.live_epg_queue_upsert_backend_result(queue_item, result)
					self.database.live_epg_queue_update_state(source_key, "no_match", attempts=attempts, not_before=0, last_error=error_text)
					finalized = True
					send_gui_notification("live_epg_no_match", source_key, reason=f"backend-preempt-{reason}", state="no_match", error=error_text)
					no_match_count += 1
					entry.update({"state": "no_match", "success": False, "error": error_text})
			except Exception as err:
				error_count += 1
				not_before = int(time()) + min(3600, 300 * max(1, attempts))
				try:
					released = self.database.live_epg_queue_release_running(source_key, attempts=attempts, not_before=not_before, last_error=str(err))
					finalized = bool(released.get("updated"))
				except Exception as release_err:
					log(f"live epg preempt claim recovery failed source_key={source_key}: {release_err}")
				entry.update({"state": "pending", "success": False, "error": str(err)})
				log(f"live epg preempt worker failed source_key={source_key}: {err}")
			if not finalized:
				# TODO: row stuck on state='running', no reaper resets it yet (see stale_running counter)
				log(f"live epg preempt item not finalized, queue row stuck running source_key={source_key}")
			items.append(entry)
		payload = {
			"success": True,
			"processed": processed,
			"done": ok_count,
			"no_match": no_match_count,
			"errors": error_count,
			"min_priority": min_priority,
			"max_items": max_items,
			"reason": reason,
			"updated": int(time()),
			"items": items,
		}
		if processed:
			try:
				self.status_store.update(live_epg_preempt=payload)
			except Exception:
				pass
			log(f"live epg preempt processed={processed} done={ok_count} no_match={no_match_count} errors={error_count} reason={reason} min_priority={min_priority}")
		return payload

	def _run_live_epg_worker(self, scheduler_connection=None, options=None):
		"""Process Live/EPG queue rows in the backend daemon."""
		if not self.database:
			raise RuntimeError(f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}")
		if not self.provider_enricher:
			raise RuntimeError("provider enricher unavailable")
		options = options if isinstance(options, dict) else {}
		limit = safe_int(options.get("limit"), 25)
		if limit <= 0:
			limit = 100000
		processed = 0
		ok_count = 0
		no_match_count = 0
		error_count = 0
		self._update_job(
			scheduler_connection,
			state="running",
			phase="live_queue_prepare",
			current=0,
			total=limit if limit < 100000 else 0,
			percent=0,
			message="Preparing Live/EPG queue worker",
		)
		while processed < limit and not self.stop_event.is_set():
			queue_item = self.database.live_epg_queue_next_item(int(time()))
			if not queue_item:
				break
			processed += 1
			source_key = str(queue_item.get("source_key") or "")
			title = str(queue_item.get("search_title") or queue_item.get("title") or source_key)
			event_end = safe_int(queue_item.get("event_end"), 0)
			attempts = safe_int(queue_item.get("attempts"), 0)
			if event_end and event_end < int(time()) - 300:
				try:
					self.database.live_epg_queue_update_state(source_key, "ended_skipped", attempts=attempts, not_before=0, last_error="event-ended-before-backend-worker")
					send_gui_notification("live_epg_skipped", source_key, reason="event-ended-before-backend-worker", state="ended_skipped")
					no_match_count += 1
				except Exception as err:
					error_count += 1
					not_before = int(time()) + min(3600, 300 * max(1, attempts))
					try:
						self.database.live_epg_queue_release_running(source_key, attempts=attempts, not_before=not_before, last_error=str(err))
					except Exception as release_err:
						log(f"live epg expired claim recovery failed source_key='{source_key}': {release_err}")
				if self._media_waiting():
					log(f"live epg worker yielding after expired item for waiting job={self.media_waiting_job}")
					break
				continue
			percent = int(processed * 100 / limit) if limit and limit < 100000 else 0
			self._update_job(
				scheduler_connection,
				state="running",
				phase="live_provider_lookup",
				current=processed,
				total=limit if limit < 100000 else 0,
				percent=percent,
				title=title,
				message="Searching Live/EPG metadata",
			)
			finalized = False
			try:
				provider_item = self._live_queue_item_to_provider_item(queue_item)
				result = self.provider_enricher.search_item(provider_item)
				if result.get("success"):
					self.database.live_epg_queue_upsert_backend_result(queue_item, result)
					self.database.live_epg_queue_update_state(source_key, "done", attempts=attempts, not_before=0, last_error="")
					finalized = True
					send_gui_notification("live_epg_updated", source_key, reason="backend-live-worker", state="done")
					ok_count += 1
				elif self._live_provider_result_is_transient(result):
					error_text = str(result.get("error") or "provider temporarily unavailable")
					not_before = int(time()) + min(3600, 300 * max(1, attempts))
					released = self.database.live_epg_queue_release_running(source_key, attempts=attempts, not_before=not_before, last_error=error_text)
					finalized = bool(released.get("updated"))
					error_count += 1
				else:
					error_text = str(result.get("error") or "no provider match")
					self.database.live_epg_queue_upsert_backend_result(queue_item, result)
					self.database.live_epg_queue_update_state(source_key, "no_match", attempts=attempts, not_before=0, last_error=error_text)
					finalized = True
					send_gui_notification("live_epg_no_match", source_key, reason="backend-live-worker", state="no_match", error=error_text)
					no_match_count += 1
			except Exception as err:
				error_count += 1
				# Keep retry policy simple and bounded.
				not_before = int(time()) + min(3600, 300 * max(1, attempts))
				try:
					released = self.database.live_epg_queue_release_running(source_key, attempts=attempts, not_before=not_before, last_error=str(err))
					finalized = bool(released.get("updated"))
				except Exception as release_err:
					log(f"live epg backend claim recovery failed source_key='{source_key}': {release_err}")
				log(f"live epg backend worker failed source_key='{source_key}': {err}")
			if not finalized:
				# TODO: row stuck on state='running', no reaper resets it yet (see stale_running counter)
				log(f"live epg worker item not finalized, queue row stuck running source_key='{source_key}'")
			if self._media_waiting():
				log(f"live epg worker yielding after item for waiting job={self.media_waiting_job}")
				break
			if processed % 5 == 0:
				sleep(0.01)
		if self.stop_event.is_set():
			self._finish_job(success=False, scheduler_connection=scheduler_connection, message="Live/EPG worker aborted")
			return
		message = f"Live/EPG queue worker completed: {ok_count} done, {no_match_count} no match/skipped, {error_count} errors"
		self._finish_job(success=True, scheduler_connection=scheduler_connection, message=message)

	def _run_live_epg_cleanup_job(self, scheduler_connection=None, options=None):
		if not self.database:
			raise RuntimeError(f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}")
		options = options if isinstance(options, dict) else {}
		dry_run = str(options.get("dry_run") or "").lower() in ("1", "true", "yes", "on")
		reason = str(options.get("reason") or "backend-job")
		self._update_job(scheduler_connection, state="running", phase="cleanup_prepare", current=0, total=0, percent=0, message="Preparing Live/EPG cleanup")
		result = self.database.run_live_epg_cleanup(reason=reason, force=True, dry_run=dry_run)
		message = f"Live/EPG cleanup completed: events={result.get("events", 0)} queue={result.get("queue", 0)} cache={result.get("cache_deleted", 0)}"
		self._finish_job(success=bool(result.get("success", True)), scheduler_connection=scheduler_connection, message=message)

	def _run_sqlite_maintenance_job(self, scheduler_connection=None, options=None):
		if not self.database:
			raise RuntimeError(f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}")
		options = options if isinstance(options, dict) else {}
		cleanup_settings = self.settings.get("cleanup", {}) if isinstance(self.settings.get("cleanup", {}), dict) else {}
		vacuum = str(options.get("vacuum") if "vacuum" in options else cleanup_settings.get("sqlite_vacuum", True)).lower() in ("1", "true", "yes", "on")
		reindex = str(options.get("reindex") if "reindex" in options else cleanup_settings.get("sqlite_reindex", False)).lower() in ("1", "true", "yes", "on")
		analyze = str(options.get("analyze") if "analyze" in options else True).lower() not in ("0", "false", "no", "off")
		self._update_job(scheduler_connection, state="running", phase="sqlite_maintenance", current=0, total=0, percent=0, message="Running SQLite maintenance")
		result = self.database.maintenance(vacuum=vacuum, analyze=analyze, reindex=reindex)
		message = f"SQLite maintenance completed: saved={result.get("size_saved", 0)} bytes"
		self._finish_job(success=bool(result.get("success", True)), scheduler_connection=scheduler_connection, message=message)

	def get_live_worker_status(self):
		queue_status = self.get_live_epg_queue_status()
		status = self.status_store.snapshot()
		return {
			"success": True,
			"job_running": self.is_running(),
			"backend_busy": self.is_running(),
			"live_job_running": bool(self.is_running() and isinstance(self.current_job, dict) and self.current_job.get("type") == "live_epg_worker"),
			"live_deferred": self._deferred_live_snapshot(),
			"media_waiting": self._media_waiting(),
			"media_waiting_job": self.media_waiting_job,
			"current_job": status.get("job"),
			"auto_worker": status.get("live_epg_worker", {}),
			"preempt": status.get("live_epg_preempt", {}),
			"queue": queue_status.get("queue", {}) if isinstance(queue_status, dict) else {},
		}

	def get_scheduler_status(self):
		return {
			"success": True,
			"enabled": False,
			"removed": True,
			"message": "Daemon scheduler was removed. Use OpenATV FunctionTimer entries registered by the plugin.",
		}

	def get_scheduler_list(self):
		return {
			"success": True,
			"enabled": False,
			"removed": True,
			"jobs": [],
			"message": "Daemon scheduler was removed. Planned jobs belong to the OpenATV Scheduler.",
		}

	def reload_scheduler(self):
		return self.get_scheduler_status()

	def run_scheduler_job(self, job_id, overrides=None):
		job_id = str(job_id or "").strip()
		if job_id in ("daily-media-refresh", "scan_and_enrich", "refresh"):
			return self.run_refresh_job(overrides=overrides or {})
		return {
			"success": False,
			"removed": True,
			"error": "daemon scheduler removed; start concrete backend jobs via start_job",
			"id": job_id,
		}

	def _reload_settings_now(self):
		settings = read_json(SETTINGS_FILE, {}) or {}
		if not isinstance(settings, dict):
			settings = {}
		self.settings = settings
		try:
			if BackendDatabase:
				self.database = BackendDatabase(settings)
		except Exception as err:
			return {"success": False, "error": f"database reload failed: {err}"}
		try:
			self.provider_enricher = BackendProviderEnricher(settings)
		except Exception as err:
			return {"success": False, "error": f"provider reload failed: {err}"}
		try:
			self.metadata_scanner = E2MDBBackendMetadataScanner()
			if self.metadata_scanner and hasattr(self.metadata_scanner, "configure"):
				self.metadata_scanner.configure(settings)
		except Exception as err:
			return {"success": False, "error": f"scanner reload failed: {err}"}
		return {"success": True, "settings": settings, "database_path": getattr(self.database, "db_path", "")}

	def reload_settings(self):
		with self.lock:
			if self.is_running():
				self.settings_reload_pending = True
				return {
					"success": True,
					"deferred": True,
					"busy": True,
					"message": "Settings reload queued after the active backend job",
				}
		return self._reload_settings_now()

	def get_provider_state(self):
		state = read_json(PROVIDER_STATE_FILE, {})
		if self.database:
			try:
				db_state = self.database.provider_state()
				if db_state.get("success"):
					return {"success": True, "provider_state": state, "database": db_state}
			except Exception as err:
				return {"success": False, "error": str(err), "provider_state": state}
		return {"success": True, "provider_state": state}


class CommandSocketServer(Thread):
	def __init__(self, job_manager, status_store, stop_event):
		Thread.__init__(self)
		self.daemon = True
		self.job_manager = job_manager
		self.status_store = status_store
		self.stop_event = stop_event
		self.server = None

	def run(self):
		try:
			if exists(COMMAND_SOCKET):
				remove(COMMAND_SOCKET)
		except Exception:
			pass
		self.server = socket(AF_UNIX, SOCK_STREAM)
		self.server.bind(COMMAND_SOCKET)
		self.server.listen(8)
		self.server.settimeout(1.0)
		log(f"command socket listening on {COMMAND_SOCKET}")
		while not self.stop_event.is_set():
			try:
				connection, _address = self.server.accept()
			except SocketTimeout:
				continue
			except Exception as err:
				if not self.stop_event.is_set():
					log(f"command accept failed: {err}")
				continue
			Thread(target=self.handle_client, args=(connection,), daemon=True).start()
		try:
			self.server.close()
		except Exception:
			pass

	def handle_client(self, connection):
		try:
			buffer = b""
			while b"\n" not in buffer:
				chunk = connection.recv(4096)
				if not chunk:
					break
				buffer += chunk
			line = buffer.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
			request = loads(line) if line else {}
			response = self.dispatch(request)
			connection.sendall((dumps(response, sort_keys=True) + "\n").encode("utf-8"))
		except Exception as err:
			try:
				connection.sendall((dumps({"success": False, "error": str(err)}) + "\n").encode("utf-8"))
			except Exception:
				pass
		finally:
			try:
				connection.close()
			except Exception:
				pass

	def dispatch(self, request):
		command = request.get("command")
		if command == "status":
			return {"success": True, "status": self.status_store.snapshot()}
		if command == "recordings":
			return self.job_manager.get_recordings(offset=request.get("offset", 0), limit=request.get("limit", 50), query=request.get("query", ""))
		if command == "recording":
			return self.job_manager.get_recording(request.get("id") or request.get("path") or "")
		if command == "browser_status":
			return self.job_manager.get_browser_status()
		if command == "browser":
			return self.job_manager.get_browser_items(
				page=request.get("page", 1),
				offset=request.get("offset") if "offset" in request else None,
				limit=request.get("limit", 50),
				query=request.get("query", request.get("q", "")),
				media_type=request.get("media_type", "all"),
				year=request.get("year", ""),
				genre=request.get("genre", ""),
				cast=request.get("cast", ""),
				letter=request.get("letter", ""),
				include_pending=request.get("include_pending", request.get("show_pending", False)),
			)
		if command == "browser_item":
			return self.job_manager.get_browser_item(request.get("id") or request.get("media_hash") or "")
		if command == "browser_debug_artwork":
			return self.job_manager.debug_browser_artwork(limit=request.get("limit", 30), query=request.get("query", request.get("q", "")))
		if command == "browser_debug_performance":
			return self.job_manager.debug_browser_performance(limit=request.get("limit", 24))
		if command == "editor":
			return self.job_manager.get_editor_items(page=request.get("page", 1), limit=request.get("limit", 30), query=request.get("query", request.get("q", "")), status=request.get("status", "all"), media_type=request.get("media_type", "all"), letter=request.get("letter", ""))
		if command == "editor_item":
			return self.job_manager.get_editor_item(request.get("id") or "")
		if command == "scan_state":
			return {"success": True, "scan_state": read_json(SCAN_STATE_FILE, {})}
		if command == "scan_paths":
			return self.job_manager.get_scan_paths_status(count_files=truthy(request.get("count_files", request.get("count", False))))
		if command == "provider_state":
			return self.job_manager.get_provider_state()
		if command == "settings_reload":
			return self.job_manager.reload_settings()
		if command == "media_status":
			return self.job_manager.get_media_status()
		if command == "refresh_status":
			return self.job_manager.get_refresh_status()
		if command == "refresh_run":
			overrides = request.get("options") if isinstance(request.get("options"), dict) else request
			return self.job_manager.run_refresh_job(overrides=overrides)
		if command == "database_status":
			if self.job_manager.database:
				return self.job_manager.database.status()
			return {"success": False, "error": f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}"}
		if command == "database_schema":
			if self.job_manager.database:
				return self.job_manager.database.schema()
			return {"success": False, "error": f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}"}
		if command == "database_maintenance":
			return self.job_manager.run_database_maintenance(
				vacuum=bool(request.get("vacuum", False)),
				analyze=bool(request.get("analyze", True)),
				reindex=bool(request.get("reindex", False)),
			)
		if command == "paths":
			return {"success": True, "paths": self.job_manager._load_scan_paths()}
		if command == "history":
			return {"success": True, "history": read_json(self.job_manager._job_history_path(), {"version": 1, "items": []})}
		if command == "current_job":
			return {"success": True, "job": self.job_manager.status_store.snapshot().get("job")}
		if command == "queue":
			return self.job_manager.get_queue_status()
		if command == "live_queue_status":
			return self.job_manager.get_live_epg_queue_status()
		if command == "live_queue":
			return self.job_manager.get_live_epg_queue_items(limit=request.get("limit", 50), state=request.get("state", "all"), query=request.get("query", request.get("q", "")))
		if command == "live_result":
			return self.job_manager.get_live_epg_result(request.get("source_key") or request.get("id") or "")
		if command == "live_artwork":
			return self.job_manager.get_live_epg_artwork(request.get("source_key") or request.get("id") or "")
		if command == "live_results":
			return self.job_manager.get_live_epg_results(limit=request.get("limit", 50), query=request.get("query", request.get("q", "")))
		if command == "live_duplicates":
			return self.job_manager.get_live_epg_duplicates(limit=request.get("limit", 100), query=request.get("query", request.get("q", "")), fix=request.get("fix", False))
		if command == "live_dedupe":
			return self.job_manager.get_live_epg_duplicates(limit=request.get("limit", 100), query=request.get("query", request.get("q", "")), fix=True)
		if command == "live_queue_reset_running":
			return self.job_manager.reset_live_epg_queue_running()
		if command == "live_queue_retry_no_match":
			return self.job_manager.retry_live_epg_queue_no_match(
				active_only=request.get("active_only", True),
				priority=request.get("priority", 90),
			)
		if command == "live_queue_clear":
			return self.job_manager.clear_live_epg_queue(mode=request.get("mode") or request.get("state") or "failed")
		if command == "cleanup_status":
			return self.job_manager.get_cleanup_status()
		if command == "cleanup_run":
			return self.job_manager.run_live_epg_cleanup(reason=request.get("reason") or "socket", force=True, dry_run=request.get("dry_run", False), remove_primary_cache=request.get("remove_primary_cache") if "remove_primary_cache" in request else None)
		if command == "cache_cleanup_status":
			return self.job_manager.get_cache_cleanup_status()
		if command == "cache_cleanup_run":
			return self.job_manager.run_cache_cleanup(action=request.get("action") or "all_cache", dry_run=request.get("dry_run", False))
		if command == "live_worker_status":
			return self.job_manager.get_live_worker_status()
		if command == "live_worker_start":
			return self.job_manager.start(job_type="live_epg_worker", source=request.get("source") or "socket", options={"limit": request.get("limit", 25)})
		if command == "scheduler_status":
			return self.job_manager.get_scheduler_status()
		if command == "scheduler_list":
			return self.job_manager.get_scheduler_list()
		if command == "scheduler_e2gui":
			return self.job_manager.get_scheduler_status()
		if command == "scheduler_reload":
			return self.job_manager.reload_scheduler()
		if command == "scheduler_run":
			overrides = request.get("options") if isinstance(request.get("options"), dict) else request
			return self.job_manager.run_scheduler_job(request.get("id") or request.get("job_id") or "", overrides=overrides)
		if command == "start_job":
			options = request.get("options") if isinstance(request.get("options"), dict) else {}
			for key in ("limit", "query", "only_missing", "rescan_existing", "retry_no_match", "retry_missing_artwork"):
				if key in request and key not in options:
					options[key] = request.get(key)
			return self.job_manager.start(job_type=request.get("job") or "recording_scan", source=request.get("source") or "socket", options=options)
		if command == "stop_job":
			return self.job_manager.stop(source=request.get("source") or "socket")
		if command == "shutdown":
			self.stop_event.set()
			return {"success": True, "message": "shutdown requested"}
		return {"success": False, "error": "unknown command"}


class LiveEPGAutoWorker(Thread):
	"""Daemon-side Live/EPG queue driver.

	Enigma2 only produces queue rows and sends wake requests. This thread sleeps
	without GUI load while idle, but switches to a short active wait while a backend
	job is running or queue rows are pending. Therefore the next Live/EPG batch is
	started at most about one second after the current backend job has finished.
	"""

	def __init__(self, job_manager, status_store, stop_event):
		Thread.__init__(self)
		self.daemon = True
		self.job_manager = job_manager
		self.status_store = status_store
		self.stop_event = stop_event
		self.last_run = 0
		self.last_error = ""
		self.wake_event = Event()
		self.job_manager.live_worker_wake_event = self.wake_event
		self.last_status = {
			"enabled": False,
			"running": False,
			"pending": 0,
			"last_run": 0,
			"last_error": "",
			"idle_interval_seconds": 0,
			"active_wait_seconds": 1,
		}

	def _settings(self):
		settings = read_json(SETTINGS_FILE, {}) or {}
		live_epg = settings.get("live_epg", {}) if isinstance(settings, dict) else {}
		if not isinstance(live_epg, dict):
			live_epg = {}
		return live_epg

	def _enabled(self, live_epg):
		return bool(live_epg.get("daemon_auto_worker_enabled", live_epg.get("backend_worker_enabled", True)))

	def _interval(self, live_epg):
		# Normal idle interval: used only when no queue rows are pending and no
		# backend job is running. This can stay relatively calm because GUI wake
		# requests interrupt the wait through wake_event.
		value = safe_int(live_epg.get("daemon_worker_interval_seconds", live_epg.get("backend_interval_seconds", 30)), 30)
		return max(2, min(3600, value))

	def _active_wait(self, live_epg):
		# Active interval while work is pending/running. Keep this low so the next
		# batch starts quickly after the current backend job finishes.
		value = safe_int(live_epg.get("daemon_worker_active_wait_seconds", live_epg.get("backend_active_wait_seconds", 1)), 1)
		return max(1, min(10, value))

	def _wait(self, seconds):
		try:
			self.wake_event.wait(max(1, int(seconds or 1)))
			self.wake_event.clear()
		except Exception:
			self.stop_event.wait(max(1, int(seconds or 1)))

	def _batch_limit(self, live_epg):
		value = safe_int(live_epg.get("daemon_worker_batch_limit", live_epg.get("backend_batch_limit", 25)), 25)
		if value <= 0:
			value = 25
		return max(1, min(100, value))

	def _publish(self, enabled=False, pending=0, message="", idle_interval=0, active_wait=1):
		deferred = self.job_manager._deferred_live_snapshot()
		self.last_status = {
			"enabled": bool(enabled),
			"running": bool(self.job_manager.is_running()),
			"pending": safe_int(pending, 0),
			"deferred": deferred,
			"last_run": self.last_run,
			"last_error": self.last_error,
			"message": message or "",
			"idle_interval_seconds": safe_int(idle_interval, 0),
			"active_wait_seconds": safe_int(active_wait, 1),
		}
		try:
			self.status_store.update(live_epg_worker=self.last_status)
		except Exception:
			pass

	def run(self):
		log("live epg auto worker active")
		# Interrupted backend runs can leave queue rows in 'running'. Reset once at daemon start.
		try:
			live_epg = self._settings()
			if bool(live_epg.get("daemon_reset_running_on_start", True)):
				self.job_manager.reset_live_epg_queue_running()
		except Exception as err:
			self.last_error = str(err)
		while not self.stop_event.is_set():
			try:
				live_epg = self._settings()
				enabled = self._enabled(live_epg)
				interval = self._interval(live_epg)
				active_wait = self._active_wait(live_epg)
				if not enabled:
					self._publish(enabled=False, pending=0, message="Live/EPG auto worker disabled", idle_interval=interval, active_wait=active_wait)
					self._wait(interval)
					continue

				if self.job_manager.is_running():
					self._publish(enabled=True, pending=0, message="backend busy", idle_interval=interval, active_wait=active_wait)
					self._wait(active_wait)
					continue
				if self.job_manager._media_waiting():
					self._publish(enabled=True, pending=0, message="yielding to waiting media job", idle_interval=interval, active_wait=active_wait)
					self._wait(active_wait)
					continue

				status = self.job_manager.get_live_epg_queue_status()
				if not isinstance(status, dict) or not status.get("success"):
					self.last_error = str((status or {}).get("error") or "Live/EPG queue status unavailable")
					self._publish(enabled=True, pending=0, message="queue status error", idle_interval=interval, active_wait=active_wait)
					self._wait(active_wait)
					continue
				queue = status.get("queue", {}) if isinstance(status, dict) else {}
				pending = safe_int(queue.get("pending"), 0) if isinstance(queue, dict) else 0
				due_pending = safe_int(queue.get("due_pending", queue.get("eligible_pending", pending)), pending) if isinstance(queue, dict) else 0
				next_due = safe_int(queue.get("next_due"), 0) if isinstance(queue, dict) else 0
				deferred = self.job_manager._deferred_live_snapshot()
				if due_pending:
					queue_message = "pending"
				elif pending:
					queue_message = "waiting for retry"
				elif deferred.get("pending"):
					queue_message = "deferred wake pending"
				else:
					queue_message = "idle"
				self._publish(enabled=True, pending=pending, message=queue_message, idle_interval=interval, active_wait=active_wait)
				if due_pending:
					limit = self._batch_limit(live_epg)
					response = self.job_manager.start(job_type="live_epg_worker", source="daemon-auto", options={"limit": limit})
					if response.get("success") and not response.get("deferred"):
						self.last_run = int(time())
						self.last_error = ""
						self._publish(enabled=True, pending=pending, message=f"started batch limit {limit}", idle_interval=interval, active_wait=active_wait)
					else:
						self.last_error = str(response.get("error") or response.get("message") or "start skipped")
						self._publish(enabled=True, pending=pending, message="start skipped", idle_interval=interval, active_wait=active_wait)
					self._wait(active_wait)
				else:
					wait_seconds = interval
					if next_due > int(time()):
						wait_seconds = max(1, min(interval, next_due - int(time())))
					elif deferred.get("pending"):
						wait_seconds = active_wait
					self._wait(wait_seconds)
			except Exception as err:
				self.last_error = str(err)
				log(f"live epg auto worker failed: {err}")
				self._publish(enabled=True, pending=0, message="error", idle_interval=10, active_wait=1)
				self._wait(10)


class TwistedWebServer(Thread):
	def __init__(self, job_manager, status_store, stop_event):
		Thread.__init__(self)
		self.daemon = True
		self.job_manager = job_manager
		self.status_store = status_store
		self.stop_event = stop_event

	def run(self):
		try:
			from twisted.internet import reactor
			from twisted.web import resource, server, static
		except Exception as err:
			log(f"twisted web disabled: {err}")
			return

		status_store = self.status_store
		job_manager = self.job_manager

		class JsonResource(resource.Resource):
			isLeaf = True

			def __init__(self, endpoint):
				resource.Resource.__init__(self)
				self.endpoint = endpoint

			def render_GET(self, request):
				return self.render_POST(request)

			def _args(self, request):
				result = {}
				for key, values in (request.args or {}).items():
					try:
						name = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
					except Exception:
						name = str(key)
					try:
						value = values[0] if values else b""
						result[name] = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
					except Exception:
						result[name] = ""
				return result

			def render_POST(self, request):
				try:
					if self.endpoint == "results":
						payload = job_manager.handle_web_results_action(self._args(request))
					elif self.endpoint == "details":
						args = self._args(request)
						payload = job_manager.handle_web_results_action(args)
					elif self.endpoint == "browser/status":
						payload = job_manager.get_browser_status()
					elif self.endpoint == "browser/item":
						args = self._args(request)
						payload = job_manager.get_browser_item(args.get("id") or args.get("media_hash") or "")
					elif self.endpoint == "browser/debug-artwork":
						args = self._args(request)
						payload = job_manager.debug_browser_artwork(limit=args.get("limit", 30), query=args.get("q", args.get("query", "")))
					elif self.endpoint == "browser/debug-performance":
						args = self._args(request)
						payload = job_manager.debug_browser_performance(limit=args.get("limit", 24))
					elif self.endpoint == "browser/series":
						args = self._args(request)
						payload = job_manager.get_series_details(args.get("id") or "")
					elif self.endpoint == "browser/season":
						args = self._args(request)
						payload = job_manager.get_season_details(args.get("id") or "", args.get("season_no") or "")
					elif self.endpoint == "status":
						payload = {"success": True, "status": status_store.snapshot()}
					elif self.endpoint == "settings":
						payload = {"success": True, "settings": read_json(SETTINGS_FILE, {})}
					elif self.endpoint == "settings/reload":
						payload = job_manager.reload_settings()
					elif self.endpoint == "jobs/scan/start":
						payload = job_manager.start(job_type="recording_scan", source="http")
					elif self.endpoint == "jobs/scan/stop":
						payload = job_manager.stop(source="http")
					elif self.endpoint == "jobs/metadata/start":
						args = request.args or {}
						limit = args.get(b"limit", [b"100"])[0].decode("utf-8", "replace")
						query = args.get(b"query", [b""])[0].decode("utf-8", "replace")
						payload = job_manager.start(job_type="metadata_enrich", source="http", options={"limit": limit, "query": query})
					elif self.endpoint == "jobs/scan-enrich/start":
						args = request.args or {}
						limit = args.get(b"limit", [b"100"])[0].decode("utf-8", "replace")
						payload = job_manager.start(job_type="scan_and_enrich", source="http", options={"limit": limit})
					elif self.endpoint == "jobs/current":
						payload = {"success": True, "job": status_store.snapshot().get("job")}
					elif self.endpoint == "jobs/queue":
						payload = job_manager.get_queue_status()
					elif self.endpoint == "live/queue/status":
						payload = job_manager.get_live_epg_queue_status()
					elif self.endpoint == "live/queue/list":
						args = self._args(request)
						payload = job_manager.get_live_epg_queue_items(limit=args.get("limit", 50), state=args.get("state", "all"), query=args.get("q", args.get("query", "")))
					elif self.endpoint == "live/result":
						args = self._args(request)
						payload = job_manager.get_live_epg_result(args.get("source_key") or args.get("id") or "")
					elif self.endpoint == "live/artwork":
						args = self._args(request)
						payload = job_manager.get_live_epg_artwork(args.get("source_key") or args.get("id") or "")
					elif self.endpoint == "live/results":
						args = self._args(request)
						payload = job_manager.get_live_epg_results(limit=args.get("limit", 50), query=args.get("q", args.get("query", "")))
					elif self.endpoint == "live/duplicates":
						args = self._args(request)
						payload = job_manager.get_live_epg_duplicates(limit=args.get("limit", 100), query=args.get("q", args.get("query", "")), fix=False)
					elif self.endpoint == "live/dedupe":
						args = self._args(request)
						payload = job_manager.get_live_epg_duplicates(limit=args.get("limit", 100), query=args.get("q", args.get("query", "")), fix=True)
					elif self.endpoint == "live/queue/reset-running":
						payload = job_manager.reset_live_epg_queue_running()
					elif self.endpoint == "live/queue/retry-no-match":
						args = self._args(request)
						payload = job_manager.retry_live_epg_queue_no_match(
							active_only=args.get("active_only", "1"),
							priority=args.get("priority", 90),
						)
					elif self.endpoint == "live/queue/clear":
						args = self._args(request)
						payload = job_manager.clear_live_epg_queue(mode=args.get("mode") or args.get("state") or "failed")
					elif self.endpoint == "cleanup/status":
						payload = job_manager.get_cleanup_status()
					elif self.endpoint == "cleanup/run":
						args = self._args(request)
						payload = job_manager.run_live_epg_cleanup(reason=args.get("reason") or "http", force=True, dry_run=args.get("dry_run", args.get("dryrun", "0")), remove_primary_cache=args.get("remove_primary_cache") if "remove_primary_cache" in args else None)
					elif self.endpoint == "cache/status":
						payload = job_manager.get_cache_cleanup_status()
					elif self.endpoint == "cache/cleanup":
						args = self._args(request)
						payload = job_manager.run_cache_cleanup(action=args.get("action", "all_cache"), dry_run=args.get("dry_run", args.get("dryrun", "0")))
					elif self.endpoint == "live/worker/status":
						payload = job_manager.get_live_worker_status()
					elif self.endpoint == "live/worker/start":
						args = self._args(request)
						payload = job_manager.start(job_type="live_epg_worker", source="http", options={"limit": args.get("limit", 25)})
					elif self.endpoint == "scheduler/status":
						payload = job_manager.get_scheduler_status()
					elif self.endpoint == "scheduler/list":
						payload = job_manager.get_scheduler_list()
					elif self.endpoint == "scheduler/e2gui":
						payload = job_manager.get_scheduler_status()
					elif self.endpoint == "scheduler/reload":
						payload = job_manager.reload_scheduler()
					elif self.endpoint == "scheduler/run":
						args = self._args(request)
						payload = job_manager.run_scheduler_job(args.get("id") or args.get("job_id") or "", overrides=args)
					elif self.endpoint == "jobs/history":
						payload = {"success": True, "history": read_json(job_manager._job_history_path(), {"version": 1, "items": []})}
					elif self.endpoint == "scanner/state":
						payload = {"success": True, "scan_state": read_json(SCAN_STATE_FILE, {})}
					elif self.endpoint == "scanner/paths":
						args = self._args(request)
						payload = job_manager.get_scan_paths_status(count_files=truthy(args.get("count_files", args.get("count", "0"))))
					elif self.endpoint == "provider/state":
						payload = job_manager.get_provider_state()
					elif self.endpoint == "media/status":
						payload = job_manager.get_media_status()
					elif self.endpoint == "refresh/status":
						payload = job_manager.get_refresh_status()
					elif self.endpoint == "refresh/run":
						args = self._args(request)
						payload = job_manager.run_refresh_job(overrides=args)
					elif self.endpoint == "database/status":
						payload = job_manager.database.status() if job_manager.database else {"success": False, "error": f"database unavailable: {BACKEND_DATABASE_IMPORT_ERROR}"}
					elif self.endpoint == "database/maintenance":
						args = request.args or {}
						vacuum = args.get(b"vacuum", [b"0"])[0].decode("utf-8", "replace") in ("1", "true", "yes")
						reindex = args.get(b"reindex", [b"0"])[0].decode("utf-8", "replace") in ("1", "true", "yes")
						payload = job_manager.run_database_maintenance(vacuum=vacuum, analyze=True, reindex=reindex)
					elif self.endpoint == "browser/list":
						args = self._args(request)
						payload = job_manager.get_browser_items(
							page=args.get("page", 1),
							offset=args.get("offset") if "offset" in args else None,
							limit=args.get("limit", 50),
							query=args.get("q", args.get("query", "")),
							media_type=args.get("media_type", "all"),
							year=args.get("year", ""),
							genre=args.get("genre", ""),
							cast=args.get("cast", ""),
							letter=args.get("letter", ""),
							include_pending=args.get("include_pending", args.get("show_pending", "0")),
						)
					elif self.endpoint == "browser/debug-artwork":
						args = self._args(request)
						payload = job_manager.debug_browser_artwork(limit=args.get("limit", 30), query=args.get("q", args.get("query", "")))
					elif self.endpoint == "browser/debug-performance":
						args = self._args(request)
						payload = job_manager.debug_browser_performance(limit=args.get("limit", 24))
					elif self.endpoint == "recordings/list":
						args = request.args or {}
						offset = args.get(b"offset", [b"0"])[0].decode("utf-8", "replace")
						limit = args.get(b"limit", [b"50"])[0].decode("utf-8", "replace")
						query = args.get(b"query", [b""])[0].decode("utf-8", "replace")
						payload = job_manager.get_recordings(offset=offset, limit=limit, query=query)
					elif self.endpoint == "recordings/item":
						args = request.args or {}
						recording_id = args.get(b"id", [b""])[0].decode("utf-8", "replace")
						payload = job_manager.get_recording(recording_id)
					else:
						payload = {"success": False, "error": "unknown api path", "path": self.endpoint}
				except Exception as err:
					payload = {"success": False, "error": str(err)}
				request.setHeader(b"Content-Type", b"application/json; charset=UTF-8")
				return dumps(payload, sort_keys=True).encode("utf-8")

		class ArtworkFileResource(resource.Resource):
			isLeaf = True

			def _first_arg(self, request, name):
				try:
					values = (request.args or {}).get(name.encode("utf-8"), [])
					value = values[0] if values else b""
					return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
				except Exception:
					return ""

			def _allowed_roots(self):
				settings = job_manager.settings if isinstance(job_manager.settings, dict) else {}
				cache = settings.get("cache", {}) if isinstance(settings.get("cache", {}), dict) else {}
				database = settings.get("database", {}) if isinstance(settings.get("database", {}), dict) else {}
				roots = [
					cache.get("root") or "",
					database.get("root") or "",
					"/media/hdd/e2MDB",
					"/media/usb/e2MDB",
				]
				result = []
				for root_path in roots:
					root_path = str(root_path or "").strip()
					if not root_path:
						continue
					try:
						root_real = realpath(abspath(root_path))
						if root_real not in result:
							result.append(root_real)
					except Exception:
						pass
				return result

			def _is_allowed(self, path):
				try:
					file_real = realpath(abspath(path))
				except Exception:
					return False
				for root_real in self._allowed_roots():
					if file_real == root_real or file_real.startswith(root_real.rstrip("/") + "/"):
						return True
				return False

			def render_GET(self, request):
				path = self._first_arg(request, "path")
				if not path:
					request.setResponseCode(400)
					return b"missing path"
				if not self._is_allowed(path):
					request.setResponseCode(403)
					return b"forbidden"
				if not isfile(path):
					request.setResponseCode(404)
					return b"not found"
				mime = guess_type(path)[0] or "application/octet-stream"
				request.setHeader(b"Content-Type", mime.encode("utf-8"))
				request.setHeader(b"Cache-Control", b"public, max-age=86400")
				try:
					with open(path, "rb") as handle:
						return handle.read()
				except Exception as err:
					request.setResponseCode(500)
					return str(err).encode("utf-8", "replace")

		api_root = resource.Resource()
		api_root.putChild(b"status", JsonResource("status"))
		api_root.putChild(b"settings", JsonResource("settings"))
		api_root.putChild(b"settings-reload", JsonResource("settings/reload"))
		api_root.putChild(b"results", JsonResource("results"))
		api_root.putChild(b"details", JsonResource("details"))
		artwork_root = resource.Resource()
		api_root.putChild(b"artwork", artwork_root)
		artwork_root.putChild(b"file", ArtworkFileResource())
		jobs_root = resource.Resource()
		api_root.putChild(b"jobs", jobs_root)
		scan_root = resource.Resource()
		jobs_root.putChild(b"scan", scan_root)
		scan_root.putChild(b"start", JsonResource("jobs/scan/start"))
		scan_root.putChild(b"stop", JsonResource("jobs/scan/stop"))
		metadata_root = resource.Resource()
		jobs_root.putChild(b"metadata", metadata_root)
		metadata_root.putChild(b"start", JsonResource("jobs/metadata/start"))
		scan_enrich_root = resource.Resource()
		jobs_root.putChild(b"scan-enrich", scan_enrich_root)
		scan_enrich_root.putChild(b"start", JsonResource("jobs/scan-enrich/start"))
		jobs_root.putChild(b"current", JsonResource("jobs/current"))
		jobs_root.putChild(b"queue", JsonResource("jobs/queue"))
		jobs_root.putChild(b"history", JsonResource("jobs/history"))
		scanner_root = resource.Resource()
		api_root.putChild(b"scanner", scanner_root)
		scanner_root.putChild(b"state", JsonResource("scanner/state"))
		scanner_root.putChild(b"paths", JsonResource("scanner/paths"))
		provider_root = resource.Resource()
		api_root.putChild(b"provider", provider_root)
		provider_root.putChild(b"state", JsonResource("provider/state"))
		media_root = resource.Resource()
		api_root.putChild(b"media", media_root)
		media_root.putChild(b"status", JsonResource("media/status"))
		refresh_root = resource.Resource()
		api_root.putChild(b"refresh", refresh_root)
		refresh_root.putChild(b"status", JsonResource("refresh/status"))
		refresh_root.putChild(b"run", JsonResource("refresh/run"))

		database_root = resource.Resource()
		api_root.putChild(b"database", database_root)
		database_root.putChild(b"status", JsonResource("database/status"))
		database_root.putChild(b"maintenance", JsonResource("database/maintenance"))
		cleanup_root = resource.Resource()
		api_root.putChild(b"cleanup", cleanup_root)
		cleanup_root.putChild(b"status", JsonResource("cleanup/status"))
		cleanup_root.putChild(b"run", JsonResource("cleanup/run"))
		cache_root = resource.Resource()
		api_root.putChild(b"cache", cache_root)
		cache_root.putChild(b"status", JsonResource("cache/status"))
		cache_root.putChild(b"cleanup", JsonResource("cache/cleanup"))
		browser_root = resource.Resource()
		api_root.putChild(b"browser", browser_root)
		browser_root.putChild(b"status", JsonResource("browser/status"))
		browser_root.putChild(b"list", JsonResource("browser/list"))
		browser_root.putChild(b"item", JsonResource("browser/item"))
		browser_root.putChild(b"debug-artwork", JsonResource("browser/debug-artwork"))
		browser_root.putChild(b"debug-performance", JsonResource("browser/debug-performance"))
		browser_root.putChild(b"series", JsonResource("browser/series"))
		browser_root.putChild(b"season", JsonResource("browser/season"))
		live_root = resource.Resource()
		api_root.putChild(b"live", live_root)
		live_queue_root = resource.Resource()
		live_root.putChild(b"queue", live_queue_root)
		live_queue_root.putChild(b"status", JsonResource("live/queue/status"))
		live_queue_root.putChild(b"list", JsonResource("live/queue/list"))
		live_queue_root.putChild(b"reset-running", JsonResource("live/queue/reset-running"))
		live_queue_root.putChild(b"retry-no-match", JsonResource("live/queue/retry-no-match"))
		live_queue_root.putChild(b"clear", JsonResource("live/queue/clear"))
		live_root.putChild(b"result", JsonResource("live/result"))
		live_root.putChild(b"artwork", JsonResource("live/artwork"))
		live_root.putChild(b"results", JsonResource("live/results"))
		live_root.putChild(b"duplicates", JsonResource("live/duplicates"))
		live_root.putChild(b"dedupe", JsonResource("live/dedupe"))
		live_worker_root = resource.Resource()
		live_root.putChild(b"worker", live_worker_root)
		live_worker_root.putChild(b"status", JsonResource("live/worker/status"))
		live_worker_root.putChild(b"start", JsonResource("live/worker/start"))
		scheduler_root = resource.Resource()
		api_root.putChild(b"scheduler", scheduler_root)
		scheduler_root.putChild(b"status", JsonResource("scheduler/status"))
		scheduler_root.putChild(b"list", JsonResource("scheduler/list"))
		scheduler_root.putChild(b"e2gui", JsonResource("scheduler/e2gui"))
		scheduler_root.putChild(b"reload", JsonResource("scheduler/reload"))
		scheduler_root.putChild(b"run", JsonResource("scheduler/run"))

		recordings_root = resource.Resource()
		api_root.putChild(b"recordings", recordings_root)
		recordings_root.putChild(b"list", JsonResource("recordings/list"))
		recordings_root.putChild(b"item", JsonResource("recordings/item"))

		root = static.File(WEB_DIR if exists(WEB_DIR) else PLUGIN_DIR)
		root.indexNames = [b"index.html"]
		root.putChild(b"api", api_root)

		settings = read_json(SETTINGS_FILE, {}) or {}
		webserver = settings.get("webserver", {}) if isinstance(settings, dict) else {}
		host = str(webserver.get("host") or "0.0.0.0")
		port = configured_web_port(webserver)
		reactor.listenTCP(port, server.Site(root), interface=host)
		log(f"twisted web listening on {host}:{port}")
		reactor.run(installSignalHandlers=False)


def ensure_default_files():
	ensure_dirs()
	if not isfile(SETTINGS_FILE):
		atomic_write_json(SETTINGS_FILE, {
			"version": 1,
			"updated": int(time()),
			"language": "de-DE",
			"cache": {"root": "/media/hdd/e2MDB"},
			"database": {"root": "/media/hdd/e2MDB", "journal_mode": "wal", "busy_timeout_ms": 5000, "single_writer": True},
			"webserver": {"enabled": True, "host": "0.0.0.0", "port": DEFAULT_WEB_PORT},
			"scanner": {"recording_paths": ["/media/hdd/movie"], "parse_meta": True, "parse_eit": True, "parse_cuts": True},
			"provider": {
				"tmdb_enabled": True, "tmdb_api_key": "",
				"tvdb_enabled": True, "tvdb_api_key": "",
				"omdb_enabled": False, "omdb_api_key": "",
				# "imdb_enabled": False,  # IMDB provider disabled, keep provider/IMDB.py in place
				"tvmaze_enabled": False, "cinemeta_enabled": False,
				"anime_enabled": False, "kitsu_enabled": False,
				"english_text_fallback": True,
				"translate_metadata_fallback": False,
				"translate_title_search": False,
				"translate_title_search_language": "",
				"job_limit": 100
			},
			"artwork": {"download_enabled": True, "fanart_enabled": False, "fanart_api_key": ""},
		})
	if not isfile(PATHS_FILE):
		atomic_write_json(PATHS_FILE, [{"path": "/media/hdd/movie", "mode": 3, "recursive": True}])
	# The recording catalog is a scan-result data dump, not small config - it
	# belongs next to the database under cache_root/results, not /etc/enigma2/e2mdb.
	startup_settings = read_json(SETTINGS_FILE, {}) or {}
	startup_cache = startup_settings.get("cache", {}) if isinstance(startup_settings.get("cache", {}), dict) else {}
	startup_database = startup_settings.get("database", {}) if isinstance(startup_settings.get("database", {}), dict) else {}
	startup_results_dir = join(str(startup_cache.get("root") or startup_database.get("root") or "/media/hdd/e2MDB"), "results")
	recordings_file = join(startup_results_dir, "recordings.json")
	if not isfile(recordings_file):
		try:
			atomic_write_json(recordings_file, {"version": 1, "updated": 0, "total": 0, "items": []})
		except Exception as err:
			log(f"recording catalog default write failed: {err}")
	if not isfile(SCAN_STATE_FILE):
		atomic_write_json(SCAN_STATE_FILE, {"version": 1, "updated": 0, "total": 0, "errors": 0, "paths": []})
	if not isfile(PROVIDER_STATE_FILE):
		atomic_write_json(PROVIDER_STATE_FILE, {"version": 1, "updated": 0, "total": 0, "success": 0, "errors": 0})
	job_history_file = join(startup_results_dir, "job_history.json")
	if not isfile(job_history_file):
		try:
			atomic_write_json(job_history_file, {"version": 1, "updated": 0, "items": []})
		except Exception as err:
			log(f"job history default write failed: {err}")


def main():
	ensure_default_files()
	stop_event = Event()
	status_store = StatusStore()
	settings = read_json(SETTINGS_FILE, {}) or {}
	database = None
	if BackendDatabase:
		try:
			database = BackendDatabase(settings)
			log(f"database ready path={database.db_path}")
		except Exception as err:
			log(f"database disabled: {err}")
	else:
		log(f"database disabled: {BACKEND_DATABASE_IMPORT_ERROR}")
	job_manager = JobManager(status_store, database=database, settings=settings)
	command_server = CommandSocketServer(job_manager, status_store, stop_event)
	web_server = TwistedWebServer(job_manager, status_store, stop_event)
	live_auto_worker = LiveEPGAutoWorker(job_manager, status_store, stop_event)
	command_server.start()
	live_auto_worker.start()
	web_server.start()
	log(f"started pid={getpid()}")
	try:
		while not stop_event.is_set():
			sleep(1.0)
	except KeyboardInterrupt:
		stop_event.set()
	try:
		if exists(COMMAND_SOCKET):
			remove(COMMAND_SOCKET)
	except Exception:
		pass
	status_store.update(daemon={"running": False, "pid": getpid(), "started": status_store.started, "uptime_seconds": int(time()) - status_store.started})
	log("stopped")
	return 0


if __name__ == "__main__":
	exit(main())
