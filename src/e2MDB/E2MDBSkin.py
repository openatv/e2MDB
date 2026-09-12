########################################################################################################
# e2MDB Live/EPG skin integration                                                                      #
# -----------------------------------------------------------------------------------------------------#
# Provides lightweight Source objects that can be attached to OpenATV EPG screens and updated from      #
# e2MDB Live/EPG database rows.                                                                         #
########################################################################################################

# PYTHON IMPORTS
from json import loads
from os.path import join

# ENIGMA IMPORTS
from Components.config import config
from Components.Element import cached
from Components.Sources.Source import Source
from Tools.LoadPixmap import LoadPixmap
try:
	from Components.Renderer.Picon import getPiconName
except Exception:
	getPiconName = None

# PLUGIN IMPORTS
from . import write_log


class E2MDBSkinSource(Source):
	"""Text and pixmap-capable source for embedded e2MDB EventView skin widgets."""

	def __init__(self, value=""):
		Source.__init__(self)
		self._value = str(value or "")

	def setText(self, value):
		value = str(value or "")
		if value == self._value:
			return False
		self._value = value
		try:
			self.changed((self.CHANGED_ALL if self._value else self.CHANGED_CLEAR,))
		except Exception:
			pass
		return True

	@cached
	def getText(self):
		return self._value

	text = property(getText)

	@cached
	def getBoolean(self):
		return bool(self._value)

	boolean = property(getBoolean)

	@cached
	def getPixmap(self):
		path = self._value
		try:
			if path:
				return LoadPixmap(path=path, cached=False, autoDetect=True)
		except Exception:
			pass
		return None

	pixmap = property(getPixmap)


_EPG_SKIN_SOURCE_NAMES = (
	"e2mdb_title",
	"e2mdb_subtitle",
	"e2mdb_overview",
	"e2mdb_description",
	"e2mdb_infoline",
	"e2mdb_status",
	"e2mdb_provider",
	"e2mdb_media_type",
	"e2mdb_genres",
	"e2mdb_runtime",
	"e2mdb_rating",
	"e2mdb_year",
	"e2mdb_cast_short",
	"e2mdb_crew_short",
	"e2mdb_cover",
	"e2mdb_backdrop",
	"e2mdb_backdrop_gradient",
	"e2mdb_titlelogo",
	"e2mdb_image",
	"e2mdb_imageOrPicon",
)


def ensure_epg_skin_sources(screen):
	"""Ensure all e2MDB Live/EPG skin sources exist before the skin is rendered."""
	for source_name in _EPG_SKIN_SOURCE_NAMES:
		try:
			source = screen[source_name]
			if not hasattr(source, "pixmap") or not hasattr(source, "setText"):
				raise TypeError("source is not pixmap-capable")
		except Exception:
			try:
				screen[source_name] = E2MDBSkinSource("")
			except Exception as err:
				write_log(f"[e2MDB][SKIN] source attach failed source={source_name} error={err}")


def _set_screen_source_text(screen, source_name, value):
	value = str(value or "")
	try:
		source = screen[source_name]
	except Exception:
		try:
			screen[source_name] = E2MDBSkinSource("")
			source = screen[source_name]
		except Exception:
			return False
	try:
		if hasattr(source, "setText"):
			source.setText(value)
			return True
	except Exception:
		pass
	try:
		source.text = value
		try:
			source.changed((source.CHANGED_ALL,))
		except Exception:
			pass
		return True
	except Exception:
		return False


def clear_epg_skin_sources(screen):
	"""Clear e2MDB skin source values without touching normal EPG widgets."""
	ensure_epg_skin_sources(screen)
	for source_name in _EPG_SKIN_SOURCE_NAMES:
		_set_screen_source_text(screen, source_name, "")


def apply_epg_skin_data(screen, skin_data):
	"""Apply SQLite-backed e2MDB display data to embedded EventView/EPG sources."""
	skin_data = skin_data or {}
	ensure_epg_skin_sources(screen)
	mapping = {
		"e2mdb_title": "title",
		"e2mdb_subtitle": "subtitle",
		"e2mdb_overview": "overview",
		"e2mdb_description": "overview",
		"e2mdb_infoline": "infoline",
		"e2mdb_status": "status_text",
		"e2mdb_provider": "provider",
		"e2mdb_media_type": "media_type",
		"e2mdb_genres": "genres",
		"e2mdb_runtime": "runtime",
		"e2mdb_rating": "rating",
		"e2mdb_year": "year",
		"e2mdb_cast_short": "cast_short",
		"e2mdb_crew_short": "crew_short",
		"e2mdb_cover": "cover_path",
		"e2mdb_backdrop": "backdrop_path",
		"e2mdb_backdrop_gradient": "backdrop_gradient",
		"e2mdb_titlelogo": "titlelogo_path",
		"e2mdb_image": "image_path",
		"e2mdb_imageOrPicon": "image_or_picon_path",
	}
	for source_name, data_key in mapping.items():
		_set_screen_source_text(screen, source_name, skin_data.get(data_key) or "")
	try:
		if hasattr(screen, "updateE2MDBDescription"):
			screen.updateE2MDBDescription()
	except Exception as err:
		write_log(f"[e2MDB][SKIN] description update failed error={err}")


def _cache_path_root():
	try:
		cache_dir = config.plugins.e2mdb.cachePath.value or "/media/hdd/"
	except Exception:
		cache_dir = "/media/hdd/"
	cache_dir = cache_dir.rstrip("/")
	return "/e2MDB" if cache_dir == "" else join(cache_dir, "e2MDB")


def _full_cache_path(path):
	"""Resolve cache-relative e2MDB paths to absolute filesystem paths."""
	path = str(path or "").strip()
	if not path:
		return ""
	if path.startswith("/"):
		return path
	if path.startswith(("cover/", "backdrop/", "titlelogo/", "image/", "artwork/", "data/", "series/", "seasons/", "index/")):
		return join(_cache_path_root(), path)
	return path


def _artwork_basename(path):
	try:
		from os.path import basename
		return basename(str(path or "").split("?", 1)[0]).lower()
	except Exception:
		return str(path or "").lower()


def _is_portrait_artwork_path(path):
	"""Return True for known poster/cover paths that must not be used as landscape art."""
	text = str(path or "").lower()
	name = _artwork_basename(text)
	if not text:
		return False
	portrait_markers = (
		"/poster", "poster.", "poster_", "_poster", "series_poster",
		"/cover", "cover.", "cover_", "_cover", "/covers/",
		"/artwork/poster", "/artwork/cover",
	)
	return any(marker in text for marker in portrait_markers) or name in ("poster.jpg", "poster.png", "poster.webp", "cover.jpg", "cover.png", "cover.webp", "series_poster.jpg", "series_poster.png", "series_poster.webp")


def _is_landscape_artwork_path(path):
	"""Return True only for known landscape/preview paths."""
	text = str(path or "").lower()
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
	return path if path and _is_landscape_artwork_path(path) else ""


def _portrait_artwork_path(path):
	return _full_cache_path(path)


def _text_list(value):
	if not value:
		return ""
	if isinstance(value, (list, tuple)):
		parts = []
		for item in value:
			if isinstance(item, dict):
				text = item.get("name") or item.get("title") or ""
			else:
				text = str(item or "")
			if text:
				parts.append(text)
		return ", ".join(parts)
	return str(value or "")


def _loads_people(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return list(value)
	if isinstance(value, str):
		try:
			data = loads(value)
		except Exception:
			return []
		return data if isinstance(data, list) else []
	return []


def _people_short(value, max_items=5):
	parts = []
	for item in _loads_people(value):
		if isinstance(item, dict):
			name = item.get("name") or item.get("title") or item.get("person") or ""
		else:
			name = str(item or "")
		name = str(name or "").strip()
		if name and name not in parts:
			parts.append(name)
		if len(parts) >= int(max_items or 5):
			break
	return ", ".join(parts)


def _year_from_released(value):
	value = str(value or "")
	return value[:4] if len(value) >= 4 and value[:4].isdigit() else ""


def _status_text(status, json_path=""):
	status = str(status or "unknown").lower()
	if status in ("matched", "done"):
		return "e2MDB: matched"
	if status == "no_match":
		return "e2MDB: no match"
	if status == "ignored":
		return "e2MDB: ignored"
	if status == "short_skipped":
		return "e2MDB: short skipped"
	if status == "ended_skipped":
		return "e2MDB: ended skipped"
	if status in ("pending", "running"):
		return f"e2MDB: {status}"
	return "e2MDB: pending"


def _service_picon_path(candidate=None, event_row=None):
	"""Return the current service picon path if available."""
	if getPiconName is None:
		return ""
	service_ref = ""
	try:
		service_ref = getattr(candidate, "service_ref", "") or ""
	except Exception:
		service_ref = ""
	if not service_ref and event_row:
		try:
			service_ref = event_row.get("service_ref") or ""
		except Exception:
			service_ref = ""
	if not service_ref:
		return ""
	try:
		picon_path = getPiconName(str(service_ref))
	except Exception:
		picon_path = ""
	return picon_path or ""


def build_epg_skin_data(candidate=None, event_row=None):
	"""Build a flat data dict for all Live/EPG skin sources.

	Display data must come from SQLite. JSON files are kept only as optional
	debug/provider-cache artifacts and are intentionally not parsed here.
	"""
	event_row = event_row or {}
	json_path = event_row.get("json_path") or ""

	title = event_row.get("metadata_title") or event_row.get("title") or getattr(candidate, "title", "") or ""
	subtitle = event_row.get("metadata_subtitle") or event_row.get("short_desc") or getattr(candidate, "short_desc", "") or ""
	overview = event_row.get("metadata_overview") or event_row.get("extended_desc") or event_row.get("short_desc") or getattr(candidate, "extended_desc", "") or getattr(candidate, "short_desc", "") or ""
	media_type = event_row.get("metadata_media_type") or ""
	provider = event_row.get("metadata_provider") or ""
	runtime = str(event_row.get("metadata_runtime") or "")
	if runtime and runtime.isdigit():
		runtime = f"{runtime} min"
	rating = str(event_row.get("metadata_rating") or "")
	year = event_row.get("metadata_year") or _year_from_released(event_row.get("metadata_released") or "")
	genres = _text_list(event_row.get("metadata_genres") or "")
	cast_short = _people_short(event_row.get("metadata_cast") or "")
	crew_short = _people_short(event_row.get("metadata_crew") or "")
	status = event_row.get("status") or "unknown"

	infoline_parts = []
	for part in (media_type, year, runtime, rating and (f"Rating {rating}"), provider):
		if part:
			infoline_parts.append(str(part))

	cover_path = _portrait_artwork_path(event_row.get("metadata_cover_path") or "")
	backdrop_path = _landscape_artwork_path(event_row.get("metadata_backdrop_path") or "")
	titlelogo_path = _full_cache_path(event_row.get("metadata_logo_path") or "")
	image_path = _landscape_artwork_path(event_row.get("metadata_image_path") or "")
	image_or_picon_path = image_path or _service_picon_path(candidate=candidate, event_row=event_row)
	backdrop_gradient = "1" if backdrop_path else ""

	return {
		"source_key": event_row.get("source_key") or getattr(candidate, "source_key", "") or "",
		"search_title": event_row.get("search_title") or getattr(candidate, "search_title", "") or "",
		"json_path": json_path,
		"title": title,
		"subtitle": subtitle,
		"overview": overview,
		"infoline": "  |  ".join(infoline_parts),
		"status_text": _status_text(status, json_path),
		"provider": provider,
		"media_type": media_type,
		"genres": genres,
		"cast_short": cast_short,
		"crew_short": crew_short,
		"runtime": runtime,
		"rating": rating,
		"year": year,
		"cover_path": cover_path,
		"backdrop_path": backdrop_path,
		"backdrop_gradient": backdrop_gradient,
		"titlelogo_path": titlelogo_path,
		"image_path": image_path,
		"image_or_picon_path": image_or_picon_path,
	}


def build_eventview_final_dict_from_db(candidate=None, event_row=None):
	"""Return a final_dict-like display dict using only SQLite columns."""
	event_row = event_row or {}
	skin_data = build_epg_skin_data(candidate=candidate, event_row=event_row)

	def _loads_list(value):
		if not value:
			return []
		try:
			from json import loads
			data = loads(value) if isinstance(value, str) else value
			return data if isinstance(data, list) else []
		except Exception:
			return []
	return {
		"title": skin_data.get("title") or "",
		"episode_name": skin_data.get("subtitle") or "",
		"overview": skin_data.get("overview") or "",
		"media_type": skin_data.get("media_type") or "",
		"runtime": str(event_row.get("metadata_runtime") or ""),
		"age_rating": str(event_row.get("metadata_age_rating") or ""),
		"vote_average": skin_data.get("rating") or "",
		"provider": skin_data.get("provider") or "",
		"countries": event_row.get("metadata_countries") or "",
		"released": event_row.get("metadata_released") or skin_data.get("year") or "",
		"genres": skin_data.get("genres") or "",
		"season_no": str(event_row.get("metadata_season_no") or ""),
		"episode_no": str(event_row.get("metadata_episode_no") or ""),
		"cover_path": _portrait_artwork_path(event_row.get("metadata_cover_path") or ""),
		"backdrop_path": _landscape_artwork_path(event_row.get("metadata_backdrop_path") or ""),
		"titlelogo_path": _full_cache_path(event_row.get("metadata_logo_path") or ""),
		"image_path": _landscape_artwork_path(event_row.get("metadata_image_path") or ""),
		"cast": _loads_list(event_row.get("metadata_cast") or ""),
		"crew": _loads_list(event_row.get("metadata_crew") or ""),
	}
