########################################################################################################
# e2MDB backend configuration helpers                                                                  #
# -----------------------------------------------------------------------------------------------------#
# Centralizes persistent JSON configuration below /etc/enigma2/e2mdb and runtime status below /tmp.     #
########################################################################################################

from json import dump, load
from os import fsync, makedirs, rename
from os.path import dirname, exists, isfile, join
from time import time

from Components.config import config

from . import write_log


CONFIG_DIR = "/etc/enigma2/e2mdb"
RUNTIME_DIR = "/var/run/e2mdb"
SETTINGS_FILE = join(CONFIG_DIR, "settings.json")
API_KEYS_FILE = join(CONFIG_DIR, "api_keys.json")
PROVIDERS_FILE = join(CONFIG_DIR, "providers.json")
PROVIDER_STATE_FILE = join(CONFIG_DIR, "provider_state.json")
PATHS_FILE = join(CONFIG_DIR, "paths.json")
WEBUI_FILE = join(CONFIG_DIR, "webui.json")
SCANNER_FILE = join(CONFIG_DIR, "scanner.json")
ARTWORK_FILE = join(CONFIG_DIR, "artwork.json")
SCAN_STATE_FILE = join(CONFIG_DIR, "scan_state.json")
STATUS_FILE = join(RUNTIME_DIR, "status.json")
ENIGMA_STATE_FILE = join(RUNTIME_DIR, "enigma_state.json")
COMMAND_SOCKET = join(RUNTIME_DIR, "e2mdbd.sock")
GUI_NOTIFY_SOCKET = join(RUNTIME_DIR, "gui_notify.sock")


def ensure_backend_dirs():
	for path in (CONFIG_DIR, RUNTIME_DIR):
		try:
			if not exists(path):
				makedirs(path)
		except Exception as err:
			write_log("[e2MDB][BACKEND-CONFIG]", "DIR failed path='%s' error=%s" % (path, err))


def atomic_write_json(path, payload):
	folder = dirname(path)
	if folder and not exists(folder):
		makedirs(folder)
	tmp_path = "%s.tmp" % path
	with open(tmp_path, "w", encoding="utf-8") as handle:
		dump(payload, handle, indent=2, sort_keys=True)
		handle.write("\n")
		handle.flush()
		try:
			fsync(handle.fileno())
		except Exception:
			pass
	rename(tmp_path, path)


def _get_value(config_entry, default=None):
	try:
		return config_entry.value
	except Exception:
		return default


def _cache_root():
	cache_path = str(_get_value(config.plugins.e2mdb.cachePath, "/media/hdd/") or "/media/hdd/").rstrip("/")
	return "/e2MDB" if not cache_path else "%s/e2MDB" % cache_path


API_KEY_CONFIG_FIELDS = {
	"tmdb": "tmdbapikey",
	"tvdb": "tvdbapikey",
	"omdb": "omdbapikey",
	"fanart": "fanartapikey",
}


def build_settings_payload():
	cache_root = _cache_root()
	return {
		"version": 1,
		"updated": int(time()),
		"language": _get_value(config.plugins.e2mdb.lang, "en"),
		"debug_log": _get_value(config.plugins.e2mdb.debugLog, 1),
		"log_target": _get_value(config.plugins.e2mdb.logTarget, "file"),
		"cache": {
			"root": cache_root,
		},
		"database": {
			"root": cache_root,
			"path": join(cache_root, "results.db"),
			"journal_mode": "wal",
			"busy_timeout_ms": 5000,
			"single_writer": True,
		},
		"webserver": {
			"enabled": True,
			"host": "0.0.0.0",
			"port": int(_get_value(config.plugins.e2mdb.webPort, 6066) or 6066),
		},
		"scanner": {
			"parse_meta": True,
			"parse_eit": True,
			"parse_cuts": True,
			"rescan_existing": bool(_get_value(config.plugins.e2mdb.scannerRescanExisting, False)),
			"status_file": STATUS_FILE,
		},
		"provider": {
			"tmdb_enabled": bool(_get_value(config.plugins.e2mdb.tmdbactive, True)),
			"tmdb_api_key": _get_value(config.plugins.e2mdb.tmdbapikey, ""),
			"tvdb_enabled": bool(_get_value(config.plugins.e2mdb.tvdbactive, True)),
			"tvdb_api_key": _get_value(config.plugins.e2mdb.tvdbapikey, ""),
			"omdb_enabled": bool(_get_value(config.plugins.e2mdb.omdbactive, False)),
			"omdb_api_key": _get_value(config.plugins.e2mdb.omdbapikey, ""),
			# "imdb_enabled": bool(_get_value(config.plugins.e2mdb.imdbactive, False)),  # IMDB provider disabled, keep provider/IMDB.py in place
			"tvmaze_enabled": bool(_get_value(config.plugins.e2mdb.tvmazeactive, False)),
			"cinemeta_enabled": bool(_get_value(config.plugins.e2mdb.cinemetaactive, False)),
			"tvspielfilm_enabled": bool(_get_value(config.plugins.e2mdb.tvspielfilmactive, True)),
			"fernsehserien_enabled": bool(_get_value(config.plugins.e2mdb.fernsehserienactive, True)),
			"wikimedia_enabled": bool(_get_value(config.plugins.e2mdb.wikimediaactive, False)),
			"anime_enabled": bool(_get_value(config.plugins.e2mdb.animeactive, False)),
			"kitsu_enabled": bool(_get_value(config.plugins.e2mdb.kitsuactive, False)),
			"english_text_fallback": bool(_get_value(config.plugins.e2mdb.providerEnglishTextFallback, True)),
			"translate_metadata_fallback": bool(_get_value(config.plugins.e2mdb.translateMetadataFallback, False)),
		},
		"artwork": {
			"download_enabled": True,
			"fanart_enabled": bool(_get_value(config.plugins.e2mdb.fanartactive, False)),
			"fanart_api_key": _get_value(config.plugins.e2mdb.fanartapikey, ""),
			"fanart_mode": _get_value(config.plugins.e2mdb.fanartmode, "missing"),
		},
		"live_epg": {
			"enabled": bool(_get_value(config.plugins.e2mdb.epgMetaEnabled, False)),
			"backend_worker_enabled": True,
			"backend_ad_hoc_enabled": True,
			"backend_batch_limit": 50,
			"backend_interval_seconds": 30,
			"backend_ad_hoc_poll_seconds": 1,
			"backend_active_wait_seconds": 1,
			"daemon_auto_worker_enabled": True,
			"daemon_worker_batch_limit": 50,
			"daemon_worker_interval_seconds": 30,
			"daemon_worker_active_wait_seconds": 1,
			"preempt_min_priority": 80,
			"preempt_max_items": 2,
			"daemon_reset_running_on_start": True,
			"enigma_proxy_batch_enabled": False,
			"retention_days": int(_get_value(config.plugins.e2mdb.epgRetentionDays, 3) or 3),
			"no_match_retry_hours": int(_get_value(config.plugins.e2mdb.epgNoMatchRetentionHours, 1) or 1),
		},
		"cleanup": {
			"enabled": True,
			"epg_meta_enabled": bool(_get_value(config.plugins.e2mdb.epgMetaEnabled, False)),
			"log_enabled": True,
			"check_interval_seconds": 24 * 3600,
			"queue_done_retention_seconds": 24 * 3600,
			"expired_event_limit": 1000,
			"remove_primary_cache": False,
			"prefill_state_retention_seconds": 14 * 86400,
			"sqlite_maintenance": True,
			"sqlite_vacuum": bool(_get_value(config.plugins.e2mdb.epgCleanupSqliteVacuum, True)),
			"sqlite_reindex": bool(_get_value(config.plugins.e2mdb.epgCleanupSqliteReindex, False)),
		},
	}


def export_enigma_settings(reason="sessionstart"):
	ensure_backend_dirs()
	payload = build_settings_payload()
	try:
		atomic_write_json(SETTINGS_FILE, payload)
		write_log("[e2MDB][BACKEND-CONFIG]", "EXPORT settings file='%s' reason=%s" % (SETTINGS_FILE, reason))
	except Exception as err:
		write_log("[e2MDB][BACKEND-CONFIG]", "EXPORT failed file='%s' error=%s" % (SETTINGS_FILE, err))
	return payload


def ensure_default_json_files():
	ensure_backend_dirs()
	defaults = (
		(PROVIDERS_FILE, {"version": 1, "updated": int(time()), "providers": {}}),
		(WEBUI_FILE, {"version": 1, "updated": int(time()), "enabled": True, "port": 6066}),
		(SCANNER_FILE, {"version": 1, "updated": int(time()), "recording_paths": [], "rescan_existing": False}),
		(ARTWORK_FILE, {"version": 1, "updated": int(time()), "jobs": {}}),
		(SCAN_STATE_FILE, {"version": 1, "updated": 0, "total": 0, "errors": 0, "paths": []}),
		(PROVIDER_STATE_FILE, {"version": 1, "updated": 0, "total": 0, "success": 0, "errors": 0}),
	)
	for path, payload in defaults:
		try:
			if not isfile(path):
				atomic_write_json(path, payload)
		except Exception as err:
			write_log("[e2MDB][BACKEND-CONFIG]", "DEFAULT failed file='%s' error=%s" % (path, err))
	# Data dumps that grow with the library (recording catalog, job history)
	# belong next to the database under cache_root/results, not the small-config
	# directory /etc/enigma2/e2mdb.
	results_dir = join(_cache_root(), "results")
	results_defaults = (
		(join(results_dir, "recordings.json"), {"version": 1, "updated": 0, "total": 0, "items": []}),
		(join(results_dir, "job_history.json"), {"version": 1, "updated": 0, "items": []}),
	)
	for path, payload in results_defaults:
		try:
			if not isfile(path):
				atomic_write_json(path, payload)
		except Exception as err:
			write_log("[e2MDB][BACKEND-CONFIG]", "DEFAULT failed file='%s' error=%s" % (path, err))


def init_backend_config(reason="sessionstart"):
	def apply_api_keys_from_json():
		if isfile(API_KEYS_FILE):
			try:
				with open(API_KEYS_FILE, "r", encoding="utf-8") as handle:
					payload = load(handle)
			except Exception as err:
				write_log("[e2MDB][BACKEND-CONFIG]", "API-KEYS read failed file='%s' error=%s" % (API_KEYS_FILE, err))
				return
			keys = payload.get("keys", {}) if isinstance(payload, dict) else {}
			if isinstance(keys, dict):
				for provider_name, field_name in API_KEY_CONFIG_FIELDS.items():
					value = str(keys.get(provider_name) or "").strip()
					if value:
						configItem = getattr(config.plugins.e2mdb, field_name)
						if value != configItem.value:
							configItem.value = value
							configItem.saved_value = value

	def save_api_keys_to_json():
		keys = {}
		for provider_name, field_name in API_KEY_CONFIG_FIELDS.items():
			keys[provider_name] = str(_get_value(getattr(config.plugins.e2mdb, field_name), "") or "").strip()
		try:
			atomic_write_json(API_KEYS_FILE, {"version": 1, "updated": int(time()), "keys": keys})
		except Exception as err:
			write_log("[e2MDB][BACKEND-CONFIG]", "API-KEYS write failed file='%s' error=%s" % (API_KEYS_FILE, err))

	if reason == "sessionstart":
		apply_api_keys_from_json()
	elif reason == "setup-save":
		save_api_keys_to_json()
	ensure_default_json_files()
	return export_enigma_settings(reason=reason)
