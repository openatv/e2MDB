########################################################################################################
# e2MDB Live/EPG ServiceList preview support                                                           #
# ---------------------------------------------------------------------------------------------------- #
# Optional support module imported lazily by OpenATV Components.ServiceList.                            #
# It only reads already existing e2MDB DB/cache files while list entries are rendered.                  #
########################################################################################################

# PYTHON IMPORTS
from hashlib import md5
from os.path import exists, isfile, join
from re import IGNORECASE, sub
from sqlite3 import Row, connect
from time import time

# ENIGMA IMPORTS
from Components.config import config
from Tools.LoadPixmap import LoadPixmap

# PLUGIN IMPORTS
from .E2MDBDatabase import resultsdb
from .E2MDBLiveEPG import E2MDBEPGCandidate
from . import e2mdb_log_is_verbose, write_log


# These IDs are used by the optional OpenATV ServiceList integration.
# Keep them outside the native 0-11 service slots and the 50-56 progress slots.
E2MDB_SERVICE_LIST_INDICES = {
	"E2MDBPreview": 80,
	"E2MDBMeta": 81,
	"E2MDBStatus": 82,
}

_pixmap_cache = {}
_data_cache = {}
_preview_log_keys = set()
_refresh_callbacks = []
_MAX_PIXMAP_CACHE = 100
_MAX_DATA_CACHE = 300
_DATA_TTL = 300
_DATA_MISS_TTL = 2
_DATA_NO_PREVIEW_TTL = 15
_DB_TIMEOUT = 0.03




MODULE_NAME = "[e2MDB][SERVICELIST]"


def _log(message, force=False):
	try:
		write_log(MODULE_NAME, message)
	except Exception:
		pass


def _log_once(key, message, force=False):
	try:
		if callable(message) and not e2mdb_log_is_verbose():
			return
	except Exception:
		if callable(message):
			return
	try:
		if key in _preview_log_keys:
			return
		_preview_log_keys.add(key)
	except Exception:
		pass
	try:
		if callable(message):
			message = message()
	except Exception:
		message = f"log message failed for key={key}"
	_log(message, force=force)


def _path_state(path):
	path = str(path or "")
	try:
		full_path = _full_cache_path(path) if path else ""
	except Exception:
		full_path = path
	try:
		exists_flag = bool(full_path and isfile(full_path))
	except Exception:
		exists_flag = False
	return full_path, exists_flag


def _short_service(service_ref):
	try:
		return str(service_ref or "")[:120]
	except Exception:
		return ""


def _describe_data(data):
	if not isinstance(data, dict):
		return "data=invalid"
	parts = []
	for key in ("cover_path", "backdrop_path", "image_path", "preview_path", "still_path", "titlelogo_path"):
		path = data.get(key) or ""
		full_path, exists_flag = _path_state(path)
		parts.append(f"{key}='{path}' exists_{key.replace("_path", "")}={exists_flag}")
	return f"status='{data.get("status") or ""}' provider='{data.get("provider") or ""}' media_type='{data.get("media_type") or ""}' source_key='{data.get("source_key") or ""}' {" ".join(parts)}"


def e2mdbServiceListEnabled():
	try:
		return bool(config.plugins.e2mdb.epgMetaEnabled.value)
	except Exception:
		return False


def _preview_mode():
	try:
		return config.plugins.e2mdb.epgServiceListPreviewMode.value or "backdrop_preview"
	except Exception:
		return "backdrop_preview"


def _cache_path_root():
	try:
		cache_dir = config.plugins.e2mdb.cachePath.value or "/media/hdd/"
	except Exception:
		cache_dir = "/media/hdd/"
	cache_dir = cache_dir.rstrip("/")
	return "/e2MDB" if cache_dir == "" else join(cache_dir, "e2MDB")


def _full_cache_path(path):
	path = str(path or "").strip()
	if not path:
		return ""
	if path.startswith("/"):
		return path
	if path.startswith(("cover/", "backdrop/", "titlelogo/", "image/", "artwork/", "data/", "series/", "seasons/", "index/")):
		return join(_cache_path_root(), path)
	return path



def _is_portrait_artwork_path(path):
	try:
		text = str(path or "").lower()
	except Exception:
		return False
	if not text:
		return False
	try:
		from os.path import basename
		name = basename(text.split("?", 1)[0])
	except Exception:
		name = text
	portrait_markers = (
		"/poster", "poster.", "poster_", "_poster", "series_poster",
		"/cover", "cover.", "cover_", "_cover", "/covers/",
		"/artwork/poster", "/artwork/cover",
	)
	return any(marker in text for marker in portrait_markers) or name in ("poster.jpg", "poster.png", "poster.webp", "cover.jpg", "cover.png", "cover.webp", "series_poster.jpg", "series_poster.png", "series_poster.webp")


def _is_landscape_artwork_path(path):
	try:
		text = str(path or "").lower()
	except Exception:
		return False
	if not text or _is_portrait_artwork_path(text):
		return False
	landscape_markers = (
		"/backdrop", "backdrop.", "backdrop_", "_backdrop",
		"/fanart", "fanart.", "fanart_", "_fanart",
		"/image", "image.", "image_", "_image",
		"/preview", "preview.", "preview_", "_preview",
		"/still", "still.", "still_", "_still",
		"/episode", "episode.", "episode_", "_episode",
		"series_backdrop", "background", "landscape",
	)
	return any(marker in text for marker in landscape_markers)


def _landscape_artwork_path(path):
	path = _full_cache_path(path)
	if not path or _is_portrait_artwork_path(path):
		return ""
	# e2MDB DB columns such as metadata_image_path and metadata_episode_image_path
	# already describe landscape/still artwork. Some cache files are hash-named
	# and therefore do not contain markers like still/image/backdrop in the
	# basename; do not drop those valid DB paths here. _preview_path() still
	# verifies that the local file exists before loading a pixmap.
	return path

def _event_value(event, index, default=""):
	try:
		return event[index]
	except Exception:
		return default


def _normalize_text(value):
	try:
		value = (value or "").strip().lower()
		value = sub(r"[._\-]+", " ", value)
		value = sub(r"[^a-z0-9äöüß ]+", " ", value)
		return sub(r"\s+", " ", value).strip()
	except Exception:
		return ""


def _normalize_service_ref(service_ref):
	if service_ref is None:
		return ""
	try:
		if hasattr(service_ref, "toString"):
			return service_ref.toString()
	except Exception:
		pass
	try:
		if hasattr(service_ref, "ref") and hasattr(service_ref.ref, "toString"):
			return service_ref.ref.toString()
	except Exception:
		pass
	try:
		return str(service_ref or "")
	except Exception:
		return ""


def _epg_search_title(title):
	cleaned = (title or "").strip()
	if not cleaned:
		return ""
	patterns = (
		r"\s*[\(\[]\s*\d+\s*/\s*\d+\s*[\)\]]\s*$",
		r"\s+\d+\s*/\s*\d+\s*$",
		r"\s*[\(\[]\s*(?:folge|teil|episode)\s*\d+(?:\s*/\s*\d+)?\s*[\)\]]\s*$",
		r"\s*[-:]\s*(?:\d+\.\s*)?(?:folge|teil|episode)\s*\d+(?:\s*/\s*\d+)?\s*$",
		r"\s*[-:]\s*\d+\.\s*(?:folge|teil|episode)\s*$",
		r"\s*[\(\[]\s*S\d{1,2}\s*[/\- ]?\s*E\d{1,2}.*?[\)\]]\s*$",
	)
	for pattern in patterns:
		cleaned = sub(pattern, "", cleaned, flags=IGNORECASE).strip()
	# German EPG data often appends plain episode numbers, for example
	# "Rote Rosen (4341)". Keep year-like numbers as disambiguation,
	# but remove non-year trailing numbers before provider search.
	try:
		from re import search
		match = search(r"\s*[\(\[]\s*(\d{3,5})\s*[\)\]]\s*$", cleaned)
		if match:
			number = int(match.group(1))
			if number < 1900 or number > 2099:
				cleaned = cleaned[:match.start()].strip()
	except Exception:
		pass
	cleaned = sub(r"\s+", " ", cleaned).strip(" -:;,.\t")
	return cleaned or (title or "").strip()


def _source_key(service_ref, begin_time, title, event_end=0, duration=0):
	try:
		begin_value = int(begin_time or 0)
	except Exception:
		begin_value = 0
	try:
		end_value = int(event_end or 0)
	except Exception:
		end_value = 0
	if not end_value:
		try:
			duration_value = int(duration or 0)
		except Exception:
			duration_value = 0
		if begin_value and duration_value:
			end_value = begin_value + duration_value
	identity = f"{"epg"}|{service_ref or ""}|{begin_value}|{end_value}|{_normalize_text(title)}"
	return md5(identity.encode("utf-8")).hexdigest()


def _virtual_path(source_key, title):
	clean_title = _normalize_text(title).replace(" ", "_") or "event"
	return f"/epg/{source_key}_{clean_title[:80]}.ts"


def _candidate_from_values(service_ref, begin_time=0, duration=0, title="", short_desc="", extended_desc="", debug_id=""):
	service_ref = _normalize_service_ref(service_ref)
	try:
		begin_time = int(begin_time or 0)
	except Exception:
		begin_time = 0
	try:
		duration = int(duration or 0)
	except Exception:
		duration = 0
	try:
		title = str(title or "")
	except Exception:
		title = ""
	try:
		short_desc = str(short_desc or "")
	except Exception:
		short_desc = ""
	try:
		extended_desc = str(extended_desc or "")
	except Exception:
		extended_desc = ""
	event_end = begin_time + duration if begin_time and duration else 0
	source_key = _source_key(service_ref, begin_time, title, event_end=event_end, duration=duration)
	search_title = _epg_search_title(title)
	candidate = E2MDBEPGCandidate(
		source_key=source_key,
		source_type="epg",
		service_ref=service_ref,
		service_name="",
		event_id=0,
		title=title,
		search_title=search_title,
		short_desc=short_desc,
		extended_desc=extended_desc,
		begin_time=begin_time,
		duration=duration,
		event_end=event_end,
		virtual_path=_virtual_path(source_key, title),
		expires_at=int(event_end or 0),
	)
	return candidate


def _candidate_from_tuple(service_ref, event):
	# Deprecated unsafe path: do not read ServiceList event tuple/proxy here.
	# CoverImage uses buildE2MDBServiceListPixmapFromValues() with primitive values.
	return None


def _row_to_dict(row):
	if not row:
		return {}
	try:
		return dict(row)
	except Exception:
		try:
			return {key: row[key] for key in row.keys()}
		except Exception:
			return {}


def _db_path():
	try:
		path = getattr(resultsdb, "db_path", None) or ""
		return path if path and exists(path) else ""
	except Exception:
		return ""


def _lookup_best_row(candidate):
	"""Resolve a rendered EPG row with one fail-fast read-only connection."""
	db_path = _db_path()
	if not db_path or not candidate or not candidate.service_ref or not candidate.begin_time:
		return {}, "skip"
	try:
		with connect(db_path, timeout=_DB_TIMEOUT) as conn:
			conn.row_factory = Row
			try:
				conn.execute("PRAGMA query_only=ON")
			except Exception:
				pass
			row = conn.execute("""
				SELECT * FROM e2mdb_epg_events
				WHERE source_key = ?
					OR (
						source_type IN ('epg', 'live')
						AND service_ref = ?
						AND begin_time = ?
					)
				ORDER BY
					CASE
						WHEN source_key = ? THEN 0
						WHEN title = ? THEN 1
						WHEN metadata_title = ? OR search_title = ? THEN 2
						ELSE 3
					END,
					updated_at DESC
				LIMIT 1
			""", (
				candidate.source_key,
				candidate.service_ref,
				candidate.begin_time,
				candidate.source_key,
				candidate.title,
				candidate.title,
				candidate.search_title,
			)).fetchone()
			data = _row_to_dict(row)
			if data.get("source_key") == candidate.source_key:
				method = "source_key"
			elif data and data.get("title") == candidate.title:
				method = "identity"
			elif data:
				method = "service_begin"
			else:
				method = "miss"
			_log_once(f"db-best-{candidate.source_key}-{method}", f"DB_LOOKUP_BEST source_key='{candidate.source_key}' method={method} hit={bool(data)} service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} title='{candidate.title}' row_title='{data.get("title") or data.get("metadata_title") or ""}' status='{data.get("status") or ""}' provider='{data.get("metadata_provider") or ""}'", force=True)
			return data, method
	except Exception as err:
		_log_once(f"db-best-error-{getattr(candidate, "source_key", "")}", f"DB_LOOKUP_BEST_ERROR source_key='{getattr(candidate, "source_key", "")}' error={err}", force=True)
		return {}, "error"

def _build_data_from_row(candidate, row):
	if not row:
		return {}
	cover_path = _full_cache_path(row.get("metadata_cover_path") or "")
	backdrop_path = _landscape_artwork_path(row.get("metadata_backdrop_path") or row.get("artwork_backdrop_path") or row.get("artwork_series_backdrop_path") or "")
	image_path = ""
	for image_field in ("metadata_image_path", "metadata_episode_image_path", "artwork_episode_path"):
		image_path = _landscape_artwork_path(row.get(image_field) or "")
		if image_path:
			break
	logo_path = _full_cache_path(row.get("metadata_logo_path") or "")
	return {
		"source_key": row.get("source_key") or getattr(candidate, "source_key", "") or "",
		"search_title": row.get("search_title") or getattr(candidate, "search_title", "") or "",
		"json_path": row.get("json_path") or "",
		"title": row.get("metadata_title") or row.get("title") or getattr(candidate, "title", "") or "",
		"subtitle": row.get("metadata_subtitle") or row.get("short_desc") or getattr(candidate, "short_desc", "") or "",
		"overview": row.get("metadata_overview") or row.get("extended_desc") or row.get("short_desc") or getattr(candidate, "extended_desc", "") or getattr(candidate, "short_desc", "") or "",
		"status": row.get("status") or "pending",
		"expires_at": row.get("expires_at") or 0,
		"status_text": f"e2MDB: {row.get("status") or "pending"}",
		"provider": row.get("metadata_provider") or "",
		"media_type": row.get("metadata_media_type") or "",
		"genres": row.get("metadata_genres") or "",
		"runtime": row.get("metadata_runtime") or "",
		"rating": row.get("metadata_rating") or "",
		"year": row.get("metadata_year") or "",
		"cover_path": cover_path,
		"backdrop_path": backdrop_path,
		"titlelogo_path": logo_path,
		"image_path": image_path,
		"preview_path": image_path,
		"still_path": image_path,
	}


def _get_cached_data(key):
	item = _data_cache.get(key)
	if not item:
		return None
	data = item.get("data")
	status = str((data or {}).get("status") or "").lower() if isinstance(data, dict) else ""
	terminal_no_preview = status in ("no_match", "ignored", "short_skipped", "ended_skipped", "skipped")
	if item.get("has_preview") or terminal_no_preview:
		ttl = _DATA_TTL
	elif data:
		ttl = _DATA_NO_PREVIEW_TTL
	else:
		ttl = _DATA_MISS_TTL
	if int(time()) - int(item.get("timestamp") or 0) > ttl:
		try:
			del _data_cache[key]
		except Exception:
			pass
		return None
	return data


def _set_cached_data(key, data, source_key=""):
	if len(_data_cache) > _MAX_DATA_CACHE:
		try:
			items = sorted(_data_cache.items(), key=lambda item: item[1].get("timestamp") or 0)
			for old_key, _old_value in items[: _MAX_DATA_CACHE // 2]:
				del _data_cache[old_key]
		except Exception:
			_data_cache.clear()
	try:
		stored_data = dict(data) if isinstance(data, dict) else data
	except Exception:
		stored_data = data
	try:
		preview_mode = _preview_mode()
		preview_path = _preview_path(stored_data)
	except Exception:
		preview_mode = ""
		preview_path = ""
	if isinstance(stored_data, dict):
		stored_data["_e2mdb_preview_mode"] = preview_mode
		stored_data["_e2mdb_preview_path"] = preview_path
	_data_cache[key] = {
		"timestamp": int(time()),
		"data": stored_data,
		"source_key": str(source_key or (stored_data or {}).get("source_key") or ""),
		"has_preview": bool(preview_path),
	}
	return stored_data


def _get_entry_data(service_ref, event):
	debug_service = ""
	try:
		debug_service = service_ref and service_ref.toString() or str(service_ref or "")
	except Exception:
		debug_service = str(service_ref or "")
	if not event:
		return {}, None
	try:
		debug_begin = int(_event_value(event, 0, 0) or 0)
		debug_title = _event_value(event, 2, "") or ""
	except Exception:
		debug_begin = 0
		debug_title = ""
	if not e2mdbServiceListEnabled():
		return {}, None
	db_path = _db_path()
	if not db_path:
		return {}, None
	try:
		candidate = _candidate_from_tuple(service_ref, event)
	except Exception as err:
		return {}, None
	if not candidate:
		return {}, None
	if not candidate.source_key or not candidate.begin_time or not candidate.title:
		return {}, candidate
	cache_key = f"{candidate.service_ref}|{candidate.begin_time}|{candidate.duration}|{candidate.title}"
	cached = _get_cached_data(cache_key)
	if cached is not None:
		return cached, candidate
	row, _lookup_method = _lookup_best_row(candidate)
	data = _build_data_from_row(candidate, row) if row else {}
	data = _set_cached_data(cache_key, data, source_key=candidate.source_key)
	return data, candidate



def _get_entry_data_from_values(service_ref, begin_time=0, duration=0, title="", short_desc="", extended_desc=""):
	try:
		debug_service = _normalize_service_ref(service_ref)
	except Exception:
		debug_service = str(service_ref or "")
	try:
		debug_begin = int(begin_time or 0)
	except Exception:
		debug_begin = 0
	try:
		debug_title = str(title or "")
	except Exception:
		debug_title = ""
	if not debug_begin or not debug_title:
		_log_once(f"values-skip-{debug_service}-{debug_begin}-{debug_title}", f"VALUES_SKIP reason=missing-begin-or-title service='{_short_service(debug_service)}' begin={debug_begin} title='{debug_title}'", force=True)
		return {}, None
	if not e2mdbServiceListEnabled():
		_log_once(f"values-disabled-{debug_service}-{debug_begin}-{debug_title}", f"VALUES_SKIP reason=servicelist-disabled service='{_short_service(debug_service)}' begin={debug_begin} title='{debug_title}'", force=True)
		return {}, None
	db_path = _db_path()
	if not db_path:
		_log_once(f"values-nodb-{debug_service}-{debug_begin}-{debug_title}", f"VALUES_SKIP reason=no-db service='{_short_service(debug_service)}' begin={debug_begin} title='{debug_title}'", force=True)
		return {}, None
	try:
		candidate = _candidate_from_values(debug_service, debug_begin, duration, debug_title, short_desc, extended_desc, debug_id=f"values-{debug_service}-{debug_begin}-{debug_title}")
	except Exception as err:
		_log_once(f"values-candidate-error-{debug_service}-{debug_begin}-{debug_title}", f"VALUES_CANDIDATE_ERROR service='{_short_service(debug_service)}' begin={debug_begin} title='{debug_title}' error={err}", force=True)
		return {}, None
	cache_key = f"{candidate.service_ref}|{candidate.begin_time}|{candidate.duration}|{candidate.title}"
	cached = _get_cached_data(cache_key)
	if cached is not None:
		_log_once(f"values-cache-{candidate.source_key}", lambda: f"VALUES_CACHE_HIT source_key={candidate.source_key} service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} title='{candidate.title}' {_describe_data(cached)}", force=True)
		return cached, candidate
	_log_once(f"values-lookup-{candidate.source_key}", f"VALUES_LOOKUP source_key={candidate.source_key} service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} duration={candidate.duration} title='{candidate.title}' search_title='{candidate.search_title}' db='{db_path}'", force=True)
	row, lookup_method = _lookup_best_row(candidate)
	data = _build_data_from_row(candidate, row) if row else {}
	_log_once(f"values-result-{candidate.source_key}-{bool(data)}", lambda: f"VALUES_RESULT source_key={candidate.source_key} method={lookup_method} hit={bool(data)} service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} title='{candidate.title}' {_describe_data(data)}", force=True)
	data = _set_cached_data(cache_key, data, source_key=candidate.source_key)
	return data, candidate

def _valid_file(path):
	try:
		return bool(path) and isfile(path)
	except Exception:
		return False


def _preview_path(data):
	if not isinstance(data, dict):
		return ""
	mode = _preview_mode()
	# ChannelSelection preview is horizontal. Portrait poster/cover images are intentionally
	# never used here. The skin can scale the resulting landscape/FHD preview itself.
	if mode == "backdrop":
		ordered_fields = ["backdrop_path"]
	elif mode in ("preview", "image", "still"):
		ordered_fields = ["image_path", "preview_path", "still_path", "backdrop_path"]
	else:
		ordered_fields = ["backdrop_path", "image_path", "preview_path", "still_path"]
	for field in ordered_fields:
		path = data.get(field) or ""
		if not path:
			continue
		if _valid_file(path):
			return path
	return ""


def _cached_preview_path(data):
	if not isinstance(data, dict):
		return ""
	mode = _preview_mode()
	if data.get("_e2mdb_preview_mode") == mode:
		return data.get("_e2mdb_preview_path") or ""
	path = _preview_path(data)
	try:
		data["_e2mdb_preview_mode"] = mode
		data["_e2mdb_preview_path"] = path
	except Exception:
		pass
	return path


def registerE2MDBServiceListRefreshCallback(callback):
	if callback and callback not in _refresh_callbacks:
		_refresh_callbacks.append(callback)
	return True


def unregisterE2MDBServiceListRefreshCallback(callback):
	try:
		if callback in _refresh_callbacks:
			_refresh_callbacks.remove(callback)
	except Exception:
		pass
	return True


def notifyE2MDBServiceListUpdated(source_key="", reason="worker"):
	source_key = str(source_key or "")
	try:
		if source_key:
			for cache_key, item in list(_data_cache.items()):
				if str((item or {}).get("source_key") or "") == source_key:
					_data_cache.pop(cache_key, None)
		else:
			_data_cache.clear()
		# Keep pixmap cache; if a path is newly written, key changes from no-path to path.
	except Exception:
		pass
	for callback in list(_refresh_callbacks):
		try:
			callback(source_key, reason)
		except Exception:
			pass
	return True

def _normalize_size(size):
	try:
		if size and len(size) >= 2:
			w, h = int(size[0]), int(size[1])
			if w > 0 and h > 0:
				return w, h
	except Exception:
		pass
	return 240, 120


def _pixmap_cache_key(path, size):
	w, h = _normalize_size(size)
	return f"{path}|{w}x{h}"


def _load_pixmap_scaled(path, size=None):
	"""Load a ServiceList-safe pixmap like Picon.

	The ChannelSelection shows many service rows. This function only loads an
	already existing local JPG/PNG/WebP path and keeps the pixmap object alive
	in a Python cache.
	"""
	if not path:
		return None
	cache_key = _pixmap_cache_key(path, size)
	pixmap = _pixmap_cache.get(cache_key)
	if pixmap:
		_log_once(f"pixmap-cache-{cache_key}", f"PIXMAP_CACHE_HIT path='{path}' size='{size}'", force=True)
		return pixmap
	try:
		try:
			pixmap = LoadPixmap(path=path, cached=False, autoDetect=True)
		except TypeError:
			pixmap = LoadPixmap(path=path)
	except Exception as err:
		_log(f"PIXMAP_LOAD_FAILED path='{path}' error={err}", force=True)
		pixmap = None
	if pixmap:
		if len(_pixmap_cache) > _MAX_PIXMAP_CACHE:
			_pixmap_cache.clear()
		_pixmap_cache[cache_key] = pixmap
		_log_once(f"pixmap-loaded-{cache_key}", f"PIXMAP_LOADED path='{path}' size='{size}'", force=True)
	else:
		_log_once(f"pixmap-none-{cache_key}", f"PIXMAP_LOAD_NONE path='{path}' size='{size}'", force=True)
	return pixmap


def buildE2MDBServiceListMeta(service_ref, event):
	data, candidate = _get_entry_data(service_ref, event)
	return data or {}


def buildE2MDBServiceListPixmapFromValues(service_ref, begin_time=0, duration=0, title="", short_desc="", extended_desc="", size=None, event_number=0):
	try:
		service_ref = _normalize_service_ref(service_ref)
	except Exception:
		service_ref = str(service_ref or "")
	try:
		begin_time = int(begin_time or 0)
	except Exception:
		begin_time = 0
	title = str(title or "")
	data, candidate = _get_entry_data_from_values(service_ref, begin_time, duration, title, short_desc, extended_desc)
	try:
		event_number = int(event_number or 0)
	except Exception:
		event_number = 0
	reason_suffix = "now" if event_number <= 0 else "next"
	path = _cached_preview_path(data)
	mode = _preview_mode()
	if candidate:
		_log_once(f"preview-check-{candidate.source_key}-{reason_suffix}", lambda: f"PREVIEW_CHECK source_key={candidate.source_key} event={reason_suffix} mode='{mode}' service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} duration={candidate.duration} title='{candidate.title}' chosen_path='{path}' chosen_exists={bool(path)} {_describe_data(data)}", force=True)
	else:
		_log_once(f"preview-check-none-{service_ref}-{begin_time}-{title}", f"PREVIEW_CHECK_NO_CANDIDATE event={reason_suffix} mode='{mode}' service='{_short_service(service_ref)}' begin={begin_time} title='{title}'", force=True)
	if not path:
		if candidate:
			_log_once(f"preview-miss-{candidate.source_key}-{reason_suffix}", lambda: f"PREVIEW_MISS source_key={candidate.source_key} event={reason_suffix} requested=False reason=no-valid-preview-render-readonly service='{_short_service(candidate.service_ref)}' begin={candidate.begin_time} title='{candidate.title}' {_describe_data(data)}", force=True)
		return None
	pixmap = _load_pixmap_scaled(path, size=size)
	if candidate:
		_log_once(f"preview-hit-{candidate.source_key}-{reason_suffix}-{bool(pixmap)}", f"PREVIEW_HIT source_key={candidate.source_key} event={reason_suffix} pixmap={bool(pixmap)} path='{path}' provider='{data.get("provider") or ""}' title='{data.get("title") or title}'", force=True)
	return pixmap


def buildE2MDBServiceListPixmap(service_ref, event, size=None, event_number=0):
	data, candidate = _get_entry_data(service_ref, event)
	try:
		event_number = int(event_number or 0)
	except Exception:
		event_number = 0
	reason_suffix = "now" if event_number <= 0 else "next"
	path = _cached_preview_path(data)
	if candidate:
		_log_once(f"preview-check-tuple-{candidate.source_key}-{reason_suffix}", lambda: f"PREVIEW_CHECK_TUPLE source_key={candidate.source_key} event={reason_suffix} mode='{_preview_mode()}' chosen_path='{path}' chosen_exists={bool(path)} {_describe_data(data)}", force=True)
	if not path:
		if candidate:
			_log_once(f"preview-miss-tuple-{candidate.source_key}-{reason_suffix}", lambda: f"PREVIEW_MISS_TUPLE source_key={candidate.source_key} event={reason_suffix} requested=False reason=no-valid-preview-render-readonly {_describe_data(data)}", force=True)
		return None
	pixmap = _load_pixmap_scaled(path, size=size)
	if candidate:
		_log_once(f"preview-hit-tuple-{candidate.source_key}-{reason_suffix}-{bool(pixmap)}", f"PREVIEW_HIT_TUPLE source_key={candidate.source_key} event={reason_suffix} pixmap={bool(pixmap)} path='{path}' provider='{data.get("provider") or ""}'", force=True)
	return pixmap


def buildE2MDBServiceListText(service_ref, event, text_type="meta"):
	data, candidate = _get_entry_data(service_ref, event)
	if not data:
		return ""
	if text_type == "status":
		return data.get("status_text") or ""
	parts = []
	for value in (data.get("media_type"), data.get("year"), data.get("rating") and (f"★ {data.get("rating")}"), data.get("provider")):
		if value:
			parts.append(str(value))
	return " · ".join(parts)


def clearE2MDBServiceListPreviewCache():
	_pixmap_cache.clear()
	_data_cache.clear()
	_preview_log_keys.clear()
