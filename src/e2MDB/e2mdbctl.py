#!/usr/bin/env python3
########################################################################################################
# e2MDB backend CLI                                                                                    #
########################################################################################################

from json import dumps, loads
from os.path import join
from socket import AF_UNIX, SOCK_STREAM, socket
from sys import argv, exit
from time import sleep, time

RUNTIME_DIR = "/var/run/e2mdb"
COMMAND_SOCKET = join(RUNTIME_DIR, "e2mdbd.sock")


def request(payload):
	client = socket(AF_UNIX, SOCK_STREAM)
	try:
		client.settimeout(30.0)
		client.connect(COMMAND_SOCKET)
		client.sendall((dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
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


def parse_run_options(values):
	options = {}
	query_parts = []
	for value in values:
		lower = value.lower()
		if lower == "all":
			options["limit"] = 0
		elif lower in ("only-missing", "missing"):
			options["only_missing"] = True
		elif lower in ("all-items", "allitems", "refresh-all"):
			options["only_missing"] = False
		else:
			try:
				options["limit"] = int(value)
			except Exception:
				query_parts.append(value)
	if query_parts:
		options["query"] = " ".join(query_parts)
	return options


def history_items(payload):
	history = payload.get("history") if isinstance(payload, dict) else {}
	items = history.get("items") if isinstance(history, dict) else []
	return items if isinstance(items, list) else []


def find_history_job(job_id):
	payload = request({"command": "history"})
	for item in history_items(payload):
		if isinstance(item, dict) and item.get("id") == job_id:
			return item
	return None


def wait_for_backend_job(job_id, timeout_seconds=21600, interval_seconds=2):
	deadline = time() + max(1, int(timeout_seconds))
	last_seen = None
	while time() < deadline:
		current_payload = request({"command": "current_job"})
		current = current_payload.get("job") if isinstance(current_payload, dict) else None
		if isinstance(current, dict) and current.get("id") == job_id:
			last_seen = current
			state = str(current.get("state") or "").lower()
			if state in ("success", "error", "aborted", "cancelled", "canceled"):
				return current
		else:
			history_job = find_history_job(job_id)
			if history_job:
				return history_job
		sleep(max(1, int(interval_seconds)))
	if last_seen:
		last_seen["wait_timeout"] = True
		return last_seen
	return {"id": job_id, "state": "unknown", "wait_timeout": True, "message": "job did not appear in current job or history before timeout"}


def run_scheduler_and_wait(job_id, options=None, timeout_seconds=21600):
	start_payload = request({"command": "scheduler_run", "id": job_id, "options": options or {}})
	backend_job = start_payload.get("job") if isinstance(start_payload, dict) else None
	if not start_payload.get("success") or not isinstance(backend_job, dict):
		return {"success": False, "start": start_payload}
	finished_job = wait_for_backend_job(backend_job.get("id") or "", timeout_seconds=timeout_seconds)
	media_payload = request({"command": "media_status"})
	refresh_payload = request({"command": "refresh_status"})
	return {
		"success": str(finished_job.get("state") or "").lower() == "success",
		"start": start_payload,
		"finished_job": finished_job,
		"media_status": media_payload,
		"refresh_status": refresh_payload,
	}


def usage():
	print("Usage:")
	print("  e2mdbctl.py status")
	print("  e2mdbctl.py scan start")
	print("  e2mdbctl.py scan stop")
	print("  e2mdbctl.py scan state")
	print("  e2mdbctl.py scan paths [count]")
	print("  e2mdbctl.py metadata start [limit|all] [query]")
	print("  e2mdbctl.py metadata retry-missing [limit|all] [query]")
	print("  e2mdbctl.py metadata state")
	print("  e2mdbctl.py scan-enrich start [limit|all]")
	print("  e2mdbctl.py recordings [limit] [query]")
	print("  e2mdbctl.py recording <id-or-path>")
	print("  e2mdbctl.py browser status")
	print("  e2mdbctl.py browser list [limit] [query]")
	print("  e2mdbctl.py browser list-all [limit] [query]   # include pending/provider-unfinished rows")
	print("  e2mdbctl.py browser item <id-or-path>")
	print("  e2mdbctl.py browser debug-artwork [limit] [query]")
	print("  e2mdbctl.py browser debug-performance [limit]")
	print("  e2mdbctl.py editor list [limit] [query]")
	print("  e2mdbctl.py editor item <id-or-path>")
	print("  e2mdbctl.py media status")
	print("  e2mdbctl.py refresh status")
	print("  e2mdbctl.py refresh run [limit|all] [only-missing|all-items] [query]")
	print("  e2mdbctl.py db status")
	print("  e2mdbctl.py db schema")
	print("  e2mdbctl.py db maintenance [vacuum] [reindex]")
	print("  e2mdbctl.py paths")
	print("  e2mdbctl.py queue")
	print("  e2mdbctl.py live-queue status")
	print("  e2mdbctl.py live-queue list [limit] [state|all] [query]")
	print("  e2mdbctl.py live-queue reset-running")
	print("  e2mdbctl.py live-queue retry-no-match [active|all]")
	print("  e2mdbctl.py live-queue clear [finished|failed|prefill|all]")
	print("  e2mdbctl.py live-result <source_key>")
	print("  e2mdbctl.py live-artwork <source_key>")
	print("  e2mdbctl.py live-results [limit] [query]")
	print("  e2mdbctl.py live-duplicates [limit] [query]")
	print("  e2mdbctl.py live-dedupe [limit] [query]")
	print("  e2mdbctl.py live-worker status")
	print("  e2mdbctl.py live-worker start [limit|all]")
	print("  e2mdbctl.py live-worker stop")
	print("  e2mdbctl.py cleanup status")
	print("  e2mdbctl.py cleanup dry-run")
	print("  e2mdbctl.py cleanup run")
	print("  e2mdbctl.py cache status")
	print("  e2mdbctl.py cache dry-run <all_cache|series_cache|movie_cache|epg_cache|artwork_cache|database_only|all_with_db>")
	print("  e2mdbctl.py cache cleanup <all_cache|series_cache|movie_cache|epg_cache|artwork_cache|database_only|all_with_db>")
	print("  e2mdbctl.py scheduler status")
	print("  e2mdbctl.py scheduler list")
	print("  e2mdbctl.py scheduler e2gui")
	print("  e2mdbctl.py scheduler reload")
	print("  e2mdbctl.py scheduler run <job-id> [limit|all] [only-missing|all-items] [query]")
	print("  e2mdbctl.py scheduler run-wait <job-id> [limit|all] [only-missing|all-items] [query]")
	print("  e2mdbctl.py jobs current")
	print("  e2mdbctl.py jobs queue")
	print("  e2mdbctl.py jobs history")
	print("  e2mdbctl.py history")
	print("  e2mdbctl.py shutdown")


def main():
	if len(argv) <= 1 or argv[1] in ("status", "--status"):
		payload = {"command": "status"}
	elif argv[1] == "scan" and len(argv) > 2 and argv[2] == "start":
		payload = {"command": "start_job", "job": "recording_scan", "source": "cli"}
	elif argv[1] == "scan" and len(argv) > 2 and argv[2] == "stop":
		payload = {"command": "stop_job", "source": "cli"}
	elif argv[1] == "scan" and len(argv) > 2 and argv[2] == "state":
		payload = {"command": "scan_state"}
	elif argv[1] == "scan" and len(argv) > 2 and argv[2] == "paths":
		payload = {"command": "scan_paths", "count_files": len(argv) > 3 and argv[3].lower() in ("1", "true", "yes", "on", "count", "full")}
	elif argv[1] == "metadata" and len(argv) > 2 and argv[2] in ("start", "retry-missing"):
		limit = 100
		query = ""
		if len(argv) > 3:
			if argv[3].lower() == "all":
				limit = 0
			else:
				try:
					limit = int(argv[3])
				except Exception:
					query = argv[3]
		if len(argv) > 4:
			query = " ".join(argv[4:])
		payload = {"command": "start_job", "job": "metadata_enrich", "source": "cli", "limit": limit, "query": query}
		if argv[2] == "retry-missing":
			payload.update({
				"only_missing": True,
				"rescan_existing": False,
				"retry_no_match": True,
				"retry_missing_artwork": True,
			})
	elif argv[1] == "metadata" and len(argv) > 2 and argv[2] == "state":
		payload = {"command": "provider_state"}
	elif argv[1] == "scan-enrich" and len(argv) > 2 and argv[2] == "start":
		limit = 100
		if len(argv) > 3:
			if argv[3].lower() == "all":
				limit = 0
			else:
				try:
					limit = int(argv[3])
				except Exception:
					limit = 100
		payload = {"command": "start_job", "job": "scan_and_enrich", "source": "cli", "limit": limit}
	elif argv[1] == "recordings":
		limit = 50
		query = ""
		if len(argv) > 2:
			try:
				limit = int(argv[2])
			except Exception:
				query = argv[2]
		if len(argv) > 3:
			query = " ".join(argv[3:])
		payload = {"command": "recordings", "offset": 0, "limit": limit, "query": query}
	elif argv[1] == "recording" and len(argv) > 2:
		payload = {"command": "recording", "id": " ".join(argv[2:])}
	elif argv[1] == "browser" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "browser_status"}
	elif argv[1] == "browser" and len(argv) > 2 and argv[2] in ("list", "list-all"):
		limit = 50
		query = ""
		if len(argv) > 3:
			try:
				limit = int(argv[3])
			except Exception:
				query = argv[3]
		if len(argv) > 4:
			query = " ".join(argv[4:])
		payload = {"command": "browser", "page": 1, "limit": limit, "query": query}
		if argv[2] == "list-all":
			payload["include_pending"] = True
	elif argv[1] == "browser" and len(argv) > 2 and argv[2] == "debug-artwork":
		limit = 30
		query = ""
		if len(argv) > 3:
			try:
				limit = int(argv[3])
			except Exception:
				query = argv[3]
		if len(argv) > 4:
			query = " ".join(argv[4:])
		payload = {"command": "browser_debug_artwork", "limit": limit, "query": query}
	elif argv[1] == "browser" and len(argv) > 2 and argv[2] == "debug-performance":
		limit = 24
		if len(argv) > 3:
			try:
				limit = int(argv[3])
			except Exception:
				limit = 24
		payload = {"command": "browser_debug_performance", "limit": limit}
	elif argv[1] == "browser" and len(argv) > 3 and argv[2] == "item":
		payload = {"command": "browser_item", "id": " ".join(argv[3:])}
	elif argv[1] == "editor" and len(argv) > 2 and argv[2] == "list":
		limit = 30
		query = ""
		if len(argv) > 3:
			try:
				limit = int(argv[3])
			except Exception:
				query = argv[3]
		if len(argv) > 4:
			query = " ".join(argv[4:])
		payload = {"command": "editor", "page": 1, "limit": limit, "query": query}
	elif argv[1] == "editor" and len(argv) > 3 and argv[2] == "item":
		payload = {"command": "editor_item", "id": " ".join(argv[3:])}
	elif argv[1] == "media" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "media_status"}
	elif argv[1] == "refresh" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "refresh_status"}
	elif argv[1] == "refresh" and len(argv) > 2 and argv[2] in ("run", "run-wait"):
		result = run_scheduler_and_wait("daily-media-refresh", options=parse_run_options(argv[3:]))
		print(dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
		return 0 if result.get("success") else 1
	elif argv[1] == "db" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "database_status"}
	elif argv[1] == "db" and len(argv) > 2 and argv[2] == "schema":
		payload = {"command": "database_schema"}
	elif argv[1] == "db" and len(argv) > 2 and argv[2] == "maintenance":
		payload = {
			"command": "database_maintenance",
			"vacuum": "vacuum" in argv[3:],
			"reindex": "reindex" in argv[3:],
			"analyze": True,
		}
	elif argv[1] == "paths":
		payload = {"command": "paths"}
	elif argv[1] == "queue":
		payload = {"command": "queue"}
	elif argv[1] == "live-queue" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "live_queue_status"}
	elif argv[1] == "live-queue" and len(argv) > 2 and argv[2] == "list":
		limit = 50
		state = "all"
		query = ""
		if len(argv) > 3:
			try:
				limit = int(argv[3])
			except Exception:
				state = argv[3]
		if len(argv) > 4:
			state = argv[4]
		if len(argv) > 5:
			query = " ".join(argv[5:])
		payload = {"command": "live_queue", "limit": limit, "state": state, "query": query}
	elif argv[1] == "live-queue" and len(argv) > 2 and argv[2] == "reset-running":
		payload = {"command": "live_queue_reset_running"}
	elif argv[1] == "live-queue" and len(argv) > 2 and argv[2] == "retry-no-match":
		active_only = not (len(argv) > 3 and argv[3].lower() == "all")
		payload = {"command": "live_queue_retry_no_match", "active_only": active_only, "priority": 90}
	elif argv[1] == "live-queue" and len(argv) > 2 and argv[2] == "clear":
		mode = argv[3] if len(argv) > 3 else "failed"
		payload = {"command": "live_queue_clear", "mode": mode}
	elif argv[1] == "live-result" and len(argv) > 2:
		payload = {"command": "live_result", "source_key": argv[2]}
	elif argv[1] == "live-artwork" and len(argv) > 2:
		payload = {"command": "live_artwork", "source_key": argv[2]}
	elif argv[1] == "live-results":
		limit = 50
		query = ""
		if len(argv) > 2:
			try:
				limit = int(argv[2])
			except Exception:
				query = argv[2]
		if len(argv) > 3:
			query = " ".join(argv[3:])
		payload = {"command": "live_results", "limit": limit, "query": query}
	elif argv[1] in ("live-duplicates", "live-dedupe"):
		limit = 100
		query = ""
		if len(argv) > 2:
			try:
				limit = int(argv[2])
			except Exception:
				query = argv[2]
		if len(argv) > 3:
			query = " ".join(argv[3:])
		payload = {"command": "live_dedupe" if argv[1] == "live-dedupe" else "live_duplicates", "limit": limit, "query": query}
	elif argv[1] == "live-worker" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "live_worker_status"}
	elif argv[1] == "live-worker" and len(argv) > 2 and argv[2] == "start":
		limit = 25
		if len(argv) > 3:
			if argv[3].lower() == "all":
				limit = 0
			else:
				try:
					limit = int(argv[3])
				except Exception:
					limit = 25
		payload = {"command": "live_worker_start", "source": "cli", "limit": limit}
	elif argv[1] == "live-worker" and len(argv) > 2 and argv[2] == "stop":
		payload = {"command": "stop_job", "source": "cli"}
	elif argv[1] == "cleanup" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "cleanup_status"}
	elif argv[1] == "cleanup" and len(argv) > 2 and argv[2] in ("dry-run", "dryrun"):
		payload = {"command": "cleanup_run", "source": "cli", "reason": "cli-dry-run", "dry_run": True}
	elif argv[1] == "cleanup" and len(argv) > 2 and argv[2] == "run":
		payload = {"command": "cleanup_run", "source": "cli", "reason": "cli", "dry_run": False}
	elif argv[1] == "cache" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "cache_cleanup_status"}
	elif argv[1] == "cache" and len(argv) > 2 and argv[2] in ("dry-run", "dryrun"):
		payload = {"command": "cache_cleanup_run", "source": "cli", "action": argv[3] if len(argv) > 3 else "all_cache", "dry_run": True}
	elif argv[1] == "cache" and len(argv) > 2 and argv[2] in ("cleanup", "run"):
		payload = {"command": "cache_cleanup_run", "source": "cli", "action": argv[3] if len(argv) > 3 else "all_cache", "dry_run": False}
	elif argv[1] == "scheduler" and len(argv) > 2 and argv[2] == "status":
		payload = {"command": "scheduler_status"}
	elif argv[1] == "scheduler" and len(argv) > 2 and argv[2] == "list":
		payload = {"command": "scheduler_list"}
	elif argv[1] == "scheduler" and len(argv) > 2 and argv[2] in ("e2gui", "openatv", "xml"):
		payload = {"command": "scheduler_e2gui"}
	elif argv[1] == "scheduler" and len(argv) > 2 and argv[2] == "reload":
		payload = {"command": "scheduler_reload"}
	elif argv[1] == "scheduler" and len(argv) > 3 and argv[2] == "run":
		payload = {"command": "scheduler_run", "id": argv[3], "options": parse_run_options(argv[4:])}
	elif argv[1] == "scheduler" and len(argv) > 3 and argv[2] in ("run-wait", "runwait"):
		result = run_scheduler_and_wait(argv[3], options=parse_run_options(argv[4:]))
		print(dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
		return 0 if result.get("success") else 1
	elif argv[1] == "jobs" and len(argv) > 2 and argv[2] == "current":
		payload = {"command": "current_job"}
	elif argv[1] == "jobs" and len(argv) > 2 and argv[2] == "queue":
		payload = {"command": "queue"}
	elif argv[1] == "jobs" and len(argv) > 2 and argv[2] == "history":
		payload = {"command": "history"}
	elif argv[1] == "history":
		payload = {"command": "history"}
	elif argv[1] == "shutdown":
		payload = {"command": "shutdown"}
	else:
		usage()
		return 2
	try:
		print(dumps(request(payload), indent=2, sort_keys=True, ensure_ascii=False))
		return 0
	except Exception as err:
		print(dumps({"success": False, "error": str(err)}, indent=2, sort_keys=True))
		return 1


if __name__ == "__main__":
	exit(main())
