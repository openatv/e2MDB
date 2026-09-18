########################################################################################################
# e2MDB backend provider enrichment                                                                    #
# -----------------------------------------------------------------------------------------------------#
# Standalone daemon helper. It must not import Enigma2 modules.                                         #
########################################################################################################

from difflib import SequenceMatcher
from hashlib import md5
from json import dumps, loads
from os import makedirs, remove
from os.path import basename, dirname, exists, join
from re import IGNORECASE, search, sub
from time import time
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from traceback import format_exc
from urllib.request import Request, urlopen

try:
	from E2MDBProviders import providers
	from provider.Consts import Fields
except Exception as err:
	providers = None
	Fields = None
	PROVIDER_IMPORT_ERROR = err
else:
	PROVIDER_IMPORT_ERROR = None

try:
	from provider.TVSPIELFILM import provider_tvspielfilm
except Exception:
	provider_tvspielfilm = None
try:
	from provider.FERNSEHSERIEN import provider_fernsehserien
except Exception:
	provider_fernsehserien = None
try:
	from provider.WIKIMEDIA import provider_wikimedia
except Exception:
	provider_wikimedia = None


DEFAULT_SERIES_ORDER = {
	"tvdb": True,
	"tmdb": True,
	"tvmaze": False,
	"cinemeta": False,
	"anime": False,
	"kitsu": False,
	"omdb": True,
	"imdb": False,
}
DEFAULT_MOVIE_ORDER = {
	"tmdb": True,
	"cinemeta": False,
	"anime": False,
	"kitsu": False,
	"tvdb": True,
	"omdb": True,
	"imdb": False,
}


def safe_int(value, default=0):
	try:
		return int(value)
	except Exception:
		return default


def normalize_text(value):
	value = str(value or "").strip().lower()
	value = sub(r"[._\-]+", " ", value)
	value = sub(r"[^a-z0-9äöüß ]+", " ", value)
	return sub(r"\s+", " ", value).strip()


def extract_year(*values):
	for value in values:
		match = search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value or ""))
		if match:
			return match.group(1)
	return ""


# INFO: As a rule of thumb, a ratio() value over 0.6 means the sequences are close matches.
# Ported from the legacy E2MDBScanner.get_match_ratio()/create_final_dict() so the standalone
# backend qualifies provider matches the same way the old GUI scanner did.
TITLE_QUALIFY = 0.20  # minimum ratio for a title to be considered as new best
DESC_QUALIFY = 0.20  # minimum ratio for a description to be considered as new best
TITLE_LIMIT = 0.60  # minimum ratio required to accept the overall match
DESC_LIMIT = 0.60  # minimum ratio required to accept the overall match


def title_desc_ratio(pvr_title, pvr_desc, search_title, desc="", short_desc="", ext_desc=""):
	title_ratio, desc_ratio = 0.0, 0.0
	plain_org_title = str(search_title or "").replace("–", "").replace("-", "").replace("!", "").replace(":", "").replace(",", "").strip().lower()
	plain_org_title = " ".join(part for part in plain_org_title.split(" ") if part)
	plain_pvr_title = str(pvr_title or "").replace("–", "").replace("-", "").replace("!", "").replace(":", "_").replace(",", "").strip().lower()
	plain_pvr_title = " ".join(part for part in plain_pvr_title.split(" ") if part)
	if plain_pvr_title:
		title_ratio = 1.0 if plain_pvr_title in plain_org_title or plain_org_title in plain_pvr_title else SequenceMatcher(None, plain_pvr_title, plain_org_title).ratio()
		if pvr_desc:
			for curr_desc in (desc, short_desc, ext_desc):
				if curr_desc:
					desc_ratio = max(desc_ratio, SequenceMatcher(None, curr_desc, pvr_desc).ratio())
	return title_ratio, desc_ratio


def detect_media_type(item):
	# The selected path mode is the upper boundary, but for Movie/Series paths the
	# scanner parser must decide per file. Otherwise all mixed-path series are sent
	# to provider lookup as generic recordings/multi and no series artwork is saved.
	try:
		mode = safe_int(item.get("mode", item.get("path_mode")), 0)
	except Exception:
		mode = 0
	parsed_type = str(item.get("provider_media_type") or item.get("estimated_media_type") or "").strip().lower()
	valid_types = ("movie", "series", "multi", "anime_series", "anime_movie", "manga_series", "manga_movie", "anime", "manga")
	if parsed_type in valid_types and (mode in (0, 3) or parsed_type != "multi"):
		return parsed_type
	mode_map = {
		1: "movie",
		2: "series",
		3: parsed_type if parsed_type in valid_types and parsed_type != "multi" else "multi",
		4: "anime_series",
		5: "manga_series",
		6: "anime_movie",
		7: "manga_movie",
	}
	if mode in mode_map:
		return mode_map[mode]
	family = str(item.get("media_family") or "").strip()
	if family in valid_types:
		return family
	text = normalize_text(" ".join([
		str(item.get("path") or ""),
		str(item.get("title") or ""),
		str(item.get("description") or ""),
		str(item.get("extended_description") or ""),
	]))
	if "manga" in text or "comic" in text:
		return "manga_series" if search(r"\bs\d{1,2}e\d{1,3}\b|\bstaffel\b|\bseason\b|\bepisode\b|\bfolge\b", text) else "manga"
	if "anime" in text:
		return "anime_series" if search(r"\bs\d{1,2}e\d{1,3}\b|\bstaffel\b|\bseason\b|\bepisode\b|\bfolge\b", text) else "anime"
	if search(r"\bs\d{1,2}e\d{1,3}\b|\bstaffel\b|\bseason\b|\bepisode\b|\bfolge\b", text):
		return "series"
	return "multi"


def first_non_empty(mapping, *keys):
	if not isinstance(mapping, dict):
		return ""
	for key in keys:
		value = mapping.get(key)
		if value is None:
			continue
		text = str(value).strip()
		if text:
			return text
	return ""


GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
GOOGLE_TRANSLATE_TIMEOUT = 8
GOOGLE_LANGUAGE_ALIASES = {
	"jv": "jw",
	"he": "iw",
	"zh_cn": "zh-CN",
	"zh-cn": "zh-CN",
	"zh_hans": "zh-CN",
	"zh-hans": "zh-CN",
	"zh_tw": "zh-TW",
	"zh-tw": "zh-TW",
	"zh_hant": "zh-TW",
	"zh-hant": "zh-TW",
}


class BackendGoogleTranslator:
	def __init__(self):
		self.cache = {}

	def normalize_language(self, language):
		language = str(language or "").strip().replace("_", "-")
		if not language:
			return ""
		key = language.lower()
		if key in GOOGLE_LANGUAGE_ALIASES:
			return GOOGLE_LANGUAGE_ALIASES[key]
		base = key.split("-", 1)[0]
		return GOOGLE_LANGUAGE_ALIASES.get(base, base)

	def _parse_response(self, payload, original_text):
		if payload.startswith(")]}'"):
			payload = payload.split("\n", 1)[1] if "\n" in payload else ""
		data = loads(payload)
		translated = ""
		for item in data[0] if data and isinstance(data[0], list) else []:
			if isinstance(item, list) and item:
				translated += str(item[0] or "")
		return translated.strip() or original_text

	def translate(self, text, target_language, source_language="en"):
		text = str(text or "").strip()
		target_language = self.normalize_language(target_language)
		source_language = self.normalize_language(source_language) or "en"
		if not text or not target_language or target_language == source_language:
			return ""
		cache_key = (text, source_language, target_language)
		if cache_key in self.cache:
			return self.cache[cache_key]
		params = urlencode({
			"client": "gtx",
			"sl": source_language,
			"tl": target_language,
			"dt": "t",
			"q": text,
		})
		request = Request(
			f"{GOOGLE_TRANSLATE_URL}?{params}",
			headers={
				"User-Agent": "e2MDB-backend/1.0",
				"Accept": "application/json,text/plain,*/*",
				"Accept-Charset": "utf-8",
			},
		)
		try:
			with urlopen(request, timeout=GOOGLE_TRANSLATE_TIMEOUT) as response:
				payload = response.read().decode("utf-8", "replace")
			translated = self._parse_response(payload, text)
		except (HTTPError, URLError, SocketTimeout, TimeoutError, ValueError, TypeError, IndexError):
			translated = ""
		if translated and translated.strip().casefold() == text.casefold():
			translated = ""
		self.cache[cache_key] = translated
		return translated


backend_translator = BackendGoogleTranslator()


class _LiveFallbackCandidate:
	def __init__(self, item):
		item = item if isinstance(item, dict) else {}
		self.source_key = str(item.get("id") or item.get("source_key") or "").strip()
		self.source_type = str(item.get("source_type") or "epg")
		self.service_ref = str(item.get("service_ref") or "")
		self.service_name = str(item.get("service_name") or "")
		self.event_id = safe_int(item.get("event_id"), 0)
		self.title = str(item.get("title") or item.get("provider_title") or "")
		self.search_title = str(item.get("provider_title") or item.get("title") or "")
		self.short_desc = str(item.get("short_desc") or item.get("description") or "")
		self.extended_desc = str(item.get("extended_desc") or item.get("extended_description") or "")
		self.begin_time = safe_int(item.get("begin_time"), 0)
		self.event_end = safe_int(item.get("event_end"), 0)
		self.duration = max(0, self.event_end - self.begin_time) if self.begin_time and self.event_end else 0
		self.virtual_path = str(item.get("path") or (f"live://{self.source_key}"))


class BackendProviderEnricher:
	def __init__(self, settings=None):
		self.settings = settings if isinstance(settings, dict) else {}
		self.started = False
		self.error = ""
		self.cache_root = self._cache_root()
		self.artwork_root = join(self.cache_root, "artwork", "recordings")
		self.series_cache = {}
		self.provider_language, self.api_keys, self.series_order, self.movie_order = self._provider_settings()

	def _cache_root(self):
		cache = self.settings.get("cache", {}) if isinstance(self.settings.get("cache", {}), dict) else {}
		root = str(cache.get("root") or "").strip().rstrip("/")
		if root:
			return root
		database = self.settings.get("database", {}) if isinstance(self.settings.get("database", {}), dict) else {}
		root = str(database.get("root") or "").strip().rstrip("/")
		return root or "/media/hdd/e2MDB"

	def _normalize_provider_language(self, language):
		language = str(language or "").replace("_", "-").strip()
		# The existing e2MDB providers expect the short ISO-639-1 language code.
		# Passing de-DE makes TVDB fall back to English because its language map uses "de".
		# TMDB also accepts "de", so keep the daemon language provider-compatible here.
		if "-" in language:
			language = language.split("-", 1)[0]
		if len(language) > 2:
			language = language[:2]
		return language.lower() or "de"

	def _provider_settings(self):
		provider_settings = self.settings.get("provider", {}) if isinstance(self.settings.get("provider", {}), dict) else {}
		artwork_settings = self.settings.get("artwork", {}) if isinstance(self.settings.get("artwork", {}), dict) else {}
		api_keys = {
			"tmdb": provider_settings.get("tmdb_api_key", ""),
			"tvdb": provider_settings.get("tvdb_api_key", ""),
			"omdb": provider_settings.get("omdb_api_key", ""),
			"fanart": artwork_settings.get("fanart_api_key", ""),
			"fanart_active": bool(artwork_settings.get("fanart_enabled", False)),
		}
		series_order = dict(DEFAULT_SERIES_ORDER)
		movie_order = dict(DEFAULT_MOVIE_ORDER)
		series_order["tmdb"] = bool(provider_settings.get("tmdb_enabled", True))
		movie_order["tmdb"] = bool(provider_settings.get("tmdb_enabled", True))
		series_order["tvdb"] = bool(provider_settings.get("tvdb_enabled", True))
		movie_order["tvdb"] = bool(provider_settings.get("tvdb_enabled", True))
		series_order["omdb"] = bool(provider_settings.get("omdb_enabled", False))
		movie_order["omdb"] = bool(provider_settings.get("omdb_enabled", False))
		series_order["imdb"] = bool(provider_settings.get("imdb_enabled", False))
		movie_order["imdb"] = bool(provider_settings.get("imdb_enabled", False))
		series_order["tvmaze"] = bool(provider_settings.get("tvmaze_enabled", False))
		series_order["cinemeta"] = bool(provider_settings.get("cinemeta_enabled", False))
		movie_order["cinemeta"] = bool(provider_settings.get("cinemeta_enabled", False))
		series_order["anime"] = bool(provider_settings.get("anime_enabled", False))
		movie_order["anime"] = bool(provider_settings.get("anime_enabled", False))
		series_order["kitsu"] = bool(provider_settings.get("kitsu_enabled", False))
		movie_order["kitsu"] = bool(provider_settings.get("kitsu_enabled", False))
		language = self._normalize_provider_language(self.settings.get("language") or provider_settings.get("language") or "de")
		return language, api_keys, series_order, movie_order

	def start(self):
		if self.started:
			return ""
		if providers is None:
			self.error = f"provider import failed: {PROVIDER_IMPORT_ERROR}"
			return self.error
		return self._switch_provider_language(self.provider_language)

	def _switch_provider_language(self, language):
		language = self._normalize_provider_language(language)
		if self.started and language == self.provider_language:
			return ""
		try:
			self.error = providers.start(language, self.api_keys, self.series_order, self.movie_order) or ""
			self.started = True
			self.provider_language = language
			self.series_cache = {}
			return self.error
		except Exception as err:
			self.error = f"provider start failed: {err}"
			return self.error

	def candidate_titles(self, item):
		candidates = []
		for key in ("provider_title", "series_title", "movie_title"):
			candidates.append(item.get(key, ""))
		for value in item.get("search_candidates", []) if isinstance(item.get("search_candidates"), list) else []:
			candidates.append(value)
		for key in ("title", "description"):
			candidates.append(item.get(key, ""))
		# keep order while filtering duplicates/noise
		result, seen = [], set()
		for value in candidates:
			text = str(value or "").strip()
			if not text:
				continue
			# avoid full long descriptions as first-class title candidates
			if len(text) > 120:
				text = text[:120].rsplit(" ", 1)[0]
			key = normalize_text(text)
			if not key or key in seen:
				continue
			seen.add(key)
			result.append(text)
		return result[:6]

	def _score_result(self, item, result):
		wanted = item.get("provider_title") or item.get("series_title") or item.get("movie_title") or item.get("title") or basename(item.get("path") or "")
		pvr_title = result.get("title") or result.get("original_title") or result.get("episode_name") or ""
		if not str(wanted).strip() or not str(pvr_title).strip():
			return 0.0, 0.0
		desc = str(item.get("description") or "")
		short_desc = str(item.get("short_desc") or item.get("description") or "")
		ext_desc = str(item.get("extended_desc") or item.get("extended_description") or "")
		pvr_desc = str(result.get("overview") or "")
		return title_desc_ratio(pvr_title, pvr_desc, wanted, desc=desc, short_desc=short_desc, ext_desc=ext_desc)

	def _provider_option(self, key, default=False):
		provider_settings = self.settings.get("provider", {}) if isinstance(self.settings.get("provider", {}), dict) else {}
		return bool(provider_settings.get(key, default))

	def _has_metadata_text(self, best):
		if not isinstance(best, dict):
			return False
		return bool(first_non_empty(best, "overview", "description", "tagline"))

	def _translate_metadata_texts(self, best, target_language, fields=None):
		if not isinstance(best, dict) or not self._provider_option("translate_metadata_fallback", False):
			return False
		target_language = self._normalize_provider_language(target_language)
		if not target_language or target_language == "en":
			return False
		wanted_fields = set(fields or ("overview", "description", "tagline", "genres"))
		changed = []
		text_cache = {}
		for key in ("overview", "description", "tagline"):
			if key not in wanted_fields:
				continue
			value = str(best.get(key) or "").strip()
			if not value:
				continue
			translated = text_cache.get(value)
			if translated is None:
				translated = backend_translator.translate(value, target_language, source_language="en")
				text_cache[value] = translated
			if translated:
				best[key] = translated
				changed.append(key)
		genres = best.get("genres")
		if "genres" in wanted_fields and isinstance(genres, (list, tuple)):
			translated_genres = []
			for genre in genres:
				genre_text = str(genre or "").strip()
				translated_genres.append(backend_translator.translate(genre_text, target_language, source_language="en") or genre_text)
			if translated_genres and translated_genres != list(genres):
				best["genres"] = translated_genres
				changed.append("genres")
		elif "genres" in wanted_fields and isinstance(genres, str) and genres.strip():
			translated = backend_translator.translate(genres, target_language, source_language="en")
			if translated:
				best["genres"] = translated
				changed.append("genres")
		if changed:
			best["metadata_text_translated_from"] = "en"
			best["metadata_text_language"] = target_language
			best["metadata_text_translated_fields"] = ",".join(changed)
			return True
		return False

	def choose_best(self, item, matches):
		matches = [result for result in matches if isinstance(result, dict)]
		if not matches:
			return {}
		if len(matches) == 1:
			# bypass the qualify/limit gate if there is only one search result, same as the legacy scanner
			best, best_title_ratio, best_desc_ratio = matches[0], 100.0, 100.0
			title_ratio, desc_ratio = self._score_result(item, best)
			best["_title_ratio"] = round(title_ratio, 4)
			best["_desc_ratio"] = round(desc_ratio, 4)
			best["_match_score"] = round(max(title_ratio, desc_ratio), 4)
		else:
			best, best_title_ratio, best_desc_ratio, curr_is_best = {}, 0.0, 0.0, False
			for result in matches:
				title_ratio, desc_ratio = self._score_result(item, result)
				result["_title_ratio"] = round(title_ratio, 4)
				result["_desc_ratio"] = round(desc_ratio, 4)
				result["_match_score"] = round(max(title_ratio, desc_ratio), 4)
				if title_ratio > TITLE_QUALIFY and title_ratio > best_title_ratio:
					best_title_ratio, curr_is_best = title_ratio, True
				if desc_ratio > DESC_QUALIFY and desc_ratio > best_desc_ratio:
					best_desc_ratio, curr_is_best = desc_ratio, True
				if curr_is_best:
					curr_is_best = False
					best = result
				if best_title_ratio == 1.0 or best_desc_ratio == 1.0:  # was the maximum possible already achieved?
					break
		if best_title_ratio >= TITLE_LIMIT or best_desc_ratio >= DESC_LIMIT:
			return best
		return {}

	def _copy_missing_english_metadata_texts(self, best, english_best):
		if not isinstance(best, dict) or not isinstance(english_best, dict):
			return []
		changed = []
		for key in ("overview", "description", "tagline"):
			value = str(english_best.get(key) or "").strip()
			if value and not str(best.get(key) or "").strip():
				best[key] = value
				changed.append(key)
		genres = english_best.get("genres")
		if genres and not best.get("genres"):
			best["genres"] = genres
			changed.append("genres")
		if changed:
			best["metadata_text_fallback_provider"] = "tmdb"
			best["metadata_text_fallback_language"] = "en"
			best["metadata_text_fallback_fields"] = ",".join(changed)
		return changed

	def _tmdb_english_metadata_by_id(self, item, best, media_type):
		if not isinstance(best, dict) or str(best.get("provider") or "").strip().lower() != "tmdb" or providers is None:
			return [], ""
		tmdb_id = self._provider_id_from_best("tmdb", best)
		if not tmdb_id:
			return [], "missing tmdb id"
		best_media_type = str(best.get("media_type") or media_type or "").strip().lower()
		err_msg = ""
		english_best = {}
		if best_media_type == "movie":
			err_msg, english_best = providers.get_movie_details("tmdb", tmdb_id)
		elif self._is_series_type(best_media_type) or best_media_type in ("multi", ""):
			err_msg, series_details, episode_index = self._get_series_context("tmdb", tmdb_id)
			english_best = dict(series_details) if isinstance(series_details, dict) else {}
			season_no = safe_int(best.get("season_no"), 0) or 0
			episode_no = safe_int(best.get("episode_no"), 0) or 0
			if not (season_no and episode_no):
				season_no, episode_no = self._season_episode_from_item(item)
			desc = str(item.get("description") or "")
			short_desc = str(item.get("short_desc") or item.get("description") or "")
			episode_name_text = short_desc or desc
			plain = f"{season_no}-{episode_no}" if (season_no and episode_no) else ""
			if plain or episode_name_text:
				episode_id = ""
				found = ()
				try:
					found = providers.find_season_episode("tmdb", episode_index, episode_name_text, plain)
				except Exception:
					found = ()
				if found:
					episode_id = str(found[1] or "") if len(found) > 1 else ""
					plain_found = str(found[0] or "")
					if "-" in plain_found:
						season_part, episode_part = plain_found.split("-", 1)
						season_no = safe_int(season_part, season_no)
						episode_no = safe_int(episode_part, episode_no)
				if season_no and episode_no:
					episode_error, episode_details = providers.get_episode_details("tmdb", tmdb_id, episode_id, str(season_no), str(episode_no))
					if episode_error and not err_msg:
						err_msg = episode_error
					if isinstance(episode_details, dict) and episode_details:
						for key, value in episode_details.items():
							if value not in (None, "", [], {}):
								english_best[key] = value
		else:
			return [], f"unsupported tmdb media type '{best_media_type}'"
		return self._copy_missing_english_metadata_texts(best, english_best), err_msg or ""

	def _is_series_type(self, media_type):
		return str(media_type or "").strip().lower() in ("series", "anime_series", "manga_series")

	def _provider_id_from_best(self, provider_name, best):
		provider_name = str(provider_name or "").strip().lower()
		if not isinstance(best, dict):
			return ""
		for key in ("series_id", "id", "tvdb_id", "tmdb_id", "imdb_id"):
			value = best.get(key)
			if value:
				if key == "imdb_id" and provider_name not in ("imdb", "omdb"):
					continue
				return str(value)
		provider_ids = best.get("provider_ids", {}) if isinstance(best.get("provider_ids", {}), dict) else {}
		if provider_name and provider_ids.get(provider_name):
			return str(provider_ids.get(provider_name) or "")
		for key in ("tvdb", "tmdb", "imdb", "tvmaze", "anime", "anilist", "kitsu"):
			if provider_ids.get(key):
				return str(provider_ids.get(key) or "")
		return ""

	def _season_episode_from_item(self, item):
		season_no = safe_int(item.get("season_no") or item.get("scan_season_no") or item.get("metadata_season_no"), 0)
		episode_no = safe_int(item.get("episode_no") or item.get("scan_episode_no") or item.get("metadata_episode_no"), 0)
		if season_no and episode_no:
			return season_no, episode_no
		text = " ".join([str(item.get("path") or ""), str(item.get("title") or ""), str(item.get("provider_title") or "")])
		match = search(r"(?i)[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})", text)
		if not match:
			match = search(r"(?i)\b(\d{1,2})x(\d{1,3})\b", text)
		if match:
			return safe_int(match.group(1), 0), safe_int(match.group(2), 0)
		return 0, 0

	def _get_series_context(self, provider_name, series_id):
		provider_name = str(provider_name or "").strip().lower()
		series_id = str(series_id or "").strip()
		if not (provider_name and series_id):
			return "missing provider/series id", {}, {}
		cache_key = f"{self.provider_language}:{provider_name}:{series_id}"
		if cache_key in self.series_cache:
			return self.series_cache[cache_key]
		try:
			err_msg, series_details, episode_index = providers.get_series_details_index(provider_name, series_id)
		except Exception as err:
			err_msg, series_details, episode_index = str(err), {}, {}
		result = (err_msg or "", series_details if isinstance(series_details, dict) else {}, episode_index if isinstance(episode_index, dict) else {})
		self.series_cache[cache_key] = result
		return result

	def _episode_artwork_url(self, episode_details):
		# Provider modules expose episode stills with slightly different keys.
		# TMDB/TVDB use image_url for episode stills, EPG fallback providers may use still_url or preview_url.
		if not isinstance(episode_details, dict):
			return ""
		for key in ("episode_image_url", "episode_still_url", "still_url", "preview_url", "image_url"):
			value = episode_details.get(key)
			if value:
				return str(value)
		for key in ("cover", "poster", "backdrop"):
			if str(episode_details.get(f"{key}_src") or "").strip().lower() == "episode":
				value = episode_details.get(f"{key}_url")
				if value:
					return str(value)
		return ""

	def _series_artwork_url(self, best, series_details):
		series_details = series_details if isinstance(series_details, dict) else {}
		best = best if isinstance(best, dict) else {}
		return first_non_empty(
			series_details, "cover_url", "poster_url", "image_url"
		) or first_non_empty(
			best, "cover_url", "poster_url", "image_url"
		)

	def _artwork_mode(self):
		artwork_settings = self.settings.get("artwork", {}) if isinstance(self.settings.get("artwork", {}), dict) else {}
		return str(artwork_settings.get("fanart_mode") or "missing").strip().lower()

	def _apply_fanart_artwork(self, best):
		if not isinstance(best, dict) or providers is None:
			return best
		try:
			err_msg, fanart_dict = providers.get_fanart_artwork(best)
		except Exception:
			return best
		if not isinstance(fanart_dict, dict) or not fanart_dict:
			return best
		prefer = self._artwork_mode() == "prefer"
		changed = []
		for pic_type in ("cover", "backdrop", "titlelogo"):
			url_key = f"{pic_type}_url"
			src_key = f"{pic_type}_src"
			provider_key = f"{pic_type}_provider"
			new_url = fanart_dict.get(url_key)
			if new_url and (prefer or not best.get(url_key)):
				best[url_key] = new_url
				best[provider_key] = fanart_dict.get(src_key) or "fanart"
				best[src_key] = "fanart"
				best.pop(f"{pic_type}_path", None)
				changed.append(pic_type)
				if pic_type == "cover" and best.get("media_type") == "series" and (prefer or not best.get("series_cover_url")):
					best["series_cover_url"] = new_url
					best["series_poster_url"] = new_url
				elif pic_type == "backdrop" and best.get("media_type") == "series" and (prefer or not best.get("series_backdrop_url")):
					best["series_backdrop_url"] = new_url
				elif pic_type == "titlelogo" and best.get("media_type") == "series" and (prefer or not best.get("series_titlelogo_url")):
					best["series_titlelogo_url"] = new_url
		if changed:
			best["artwork_fill_provider"] = "fanart"
			best["artwork_fill_fields"] = ",".join(changed)
		return best

	def _result_identity_matches(self, left, right):
		left = left if isinstance(left, dict) else {}
		right = right if isinstance(right, dict) else {}
		left_ids = left.get("provider_ids") if isinstance(left.get("provider_ids"), dict) else {}
		right_ids = right.get("provider_ids") if isinstance(right.get("provider_ids"), dict) else {}
		for key in ("tvdb", "tmdb", "imdb", "tvmaze", "anime", "anilist", "kitsu"):
			if left_ids.get(key) and left_ids.get(key) == right_ids.get(key):
				return True
		left_title = normalize_text(first_non_empty(left, "series_title", "title", "original_title"))
		right_title = normalize_text(first_non_empty(right, "series_title", "title", "original_title"))
		if left_title and right_title and SequenceMatcher(None, left_title, right_title).ratio() >= 0.88:
			left_year = extract_year(left.get("released"), left.get("year"), left.get("firstAired"))
			right_year = extract_year(right.get("released"), right.get("year"), right.get("firstAired"))
			return not (left_year and right_year and left_year != right_year)
		return False

	def _fill_alternate_provider_artwork(self, item, best, matches):
		if not isinstance(best, dict) or not matches or providers is None:
			return best
		media_type = str(best.get("media_type") or "").strip().lower()
		if not self._is_series_type(media_type):
			return best
		has_backdrop = first_non_empty(best, "series_backdrop_url", "backdrop_url", "fanart_url", "series_backdrop_path", "backdrop_path", "fanart_path")
		need_backdrop = not has_backdrop
		need_cover = not first_non_empty(best, "series_cover_url", "series_poster_url", "cover_url", "poster_url")
		need_logo = not first_non_empty(best, "titlelogo_url", "logo_url", "clearlogo_url", "series_titlelogo_url")
		if not (need_backdrop or need_cover or need_logo):
			return best
		selected_provider = str(best.get("provider") or "").strip().lower()
		for alt in matches:
			if not isinstance(alt, dict):
				continue
			alt_provider = str(alt.get("provider") or "").strip().lower()
			if not alt_provider or alt_provider == selected_provider:
				continue
			if not self._is_series_type(str(alt.get("media_type") or "").strip().lower()):
				continue
			if not self._result_identity_matches(best, alt):
				item_title = normalize_text(first_non_empty(item, "provider_title", "series_title", "title"))
				alt_title = normalize_text(first_non_empty(alt, "series_title", "title", "original_title"))
				if not (item_title and alt_title and SequenceMatcher(None, item_title, alt_title).ratio() >= 0.88):
					continue
			alt_id = self._provider_id_from_best(alt_provider, alt)
			if not alt_id:
				continue
			_err_msg, alt_details, _episode_index = self._get_series_context(alt_provider, alt_id)
			if not isinstance(alt_details, dict):
				alt_details = {}
			alt_backdrop = first_non_empty(alt_details, "series_backdrop_url", "backdrop_url", "fanart_url") or first_non_empty(alt, "series_backdrop_url", "backdrop_url", "fanart_url")
			alt_cover = first_non_empty(alt_details, "series_cover_url", "series_poster_url", "cover_url", "poster_url", "image_url") or first_non_empty(alt, "series_cover_url", "series_poster_url", "cover_url", "poster_url")
			alt_logo = first_non_empty(alt_details, "titlelogo_url", "logo_url", "clearlogo_url") or first_non_empty(alt, "titlelogo_url", "logo_url", "clearlogo_url")
			filled = []
			if need_backdrop and alt_backdrop:
				best["series_backdrop_url"] = str(alt_backdrop)
				best["backdrop_url"] = str(alt_backdrop)
				best["backdrop_src"] = alt_provider
				best["backdrop_provider"] = alt_provider
				need_backdrop = False
				filled.append("backdrop")
			if need_cover and alt_cover:
				best["series_cover_url"] = str(alt_cover)
				best["series_poster_url"] = str(alt_cover)
				if not best.get("cover_url"):
					best["cover_url"] = str(alt_cover)
				best["cover_provider"] = alt_provider
				need_cover = False
				filled.append("cover")
			if need_logo and alt_logo:
				best["titlelogo_url"] = str(alt_logo)
				best["titlelogo_provider"] = alt_provider
				need_logo = False
				filled.append("titlelogo")
			if filled:
				best["artwork_fill_provider"] = alt_provider
				best["artwork_fill_fields"] = ",".join(filled)
			if not (need_backdrop or need_cover or need_logo):
				break
		return best

	def _fill_live_horizontal_image(self, item, best):
		if not isinstance(best, dict):
			return best
		image_src = str(best.get("image_src") or best.get("image_provider") or "").strip().lower()
		if first_non_empty(best, "episode_image_url", "episode_still_url", "still_url", "preview_url"):
			return best
		if best.get("image_url") and image_src in ("episode", "fernsehserien", "wikimedia", "tvspielfilm", "still", "preview"):
			return best
		if str(item.get("source_type") or "").strip().lower() != "live_epg":
			return best
		candidate = _LiveFallbackCandidate(item)
		language = str(self.settings.get("language") or "de").replace("_", "-").split("-", 1)[0].lower() or "de"
		for provider_name, provider_obj in (("fernsehserien", provider_fernsehserien), ("wikimedia", provider_wikimedia)):
			if provider_obj is None:
				continue
			try:
				provider_obj.start(language)
				err_msg, fallback = provider_obj.lookup_epg_event(candidate)
			except Exception:
				continue
			if not isinstance(fallback, dict) or not fallback:
				continue
			image_url = first_non_empty(fallback, "image_url", "preview_url", "still_url")
			if not image_url:
				continue
			best["image_url"] = image_url
			best["preview_url"] = image_url
			best["still_url"] = image_url
			best["image_src"] = provider_name
			best["image_provider"] = provider_name
			if fallback.get("source_url"):
				best[f"{provider_name}_url"] = fallback.get("source_url")
			provider_ids = best.get("provider_ids") if isinstance(best.get("provider_ids"), dict) else {}
			fallback_ids = fallback.get("provider_ids") if isinstance(fallback.get("provider_ids"), dict) else {}
			if fallback_ids.get(provider_name):
				provider_ids[provider_name] = fallback_ids.get(provider_name)
				best["provider_ids"] = provider_ids
			break
		return best

	def _episode_best_from_series(self, item, best, media_type):
		if not self._is_series_type(media_type):
			return best
		provider_name = str(best.get("provider") or "").strip().lower()
		series_id = self._provider_id_from_best(provider_name, best)
		if not (provider_name and series_id):
			return best
		season_no, episode_no = self._season_episode_from_item(item)
		desc = str(item.get("description") or "")
		short_desc = str(item.get("short_desc") or item.get("description") or "")
		# Ported from the legacy E2MDBHelper.get_secondary_dicts(): filenames without an
		# explicit S/E tag still resolve the episode by matching the EIT/META description
		# text against the provider's episode index.
		episode_name_text = short_desc or desc
		plain = f"{season_no}-{episode_no}" if (season_no and episode_no) else ""
		if not plain and not episode_name_text:
			return best
		err_msg, series_details, episode_index = self._get_series_context(provider_name, series_id)
		episode_id = ""
		episode_index_name = ""
		try:
			found = providers.find_season_episode(provider_name, episode_index, episode_name_text, plain)
			if found:
				episode_id = str(found[1] or "") if len(found) > 1 else ""
				episode_index_name = str(found[2] or "") if len(found) > 2 else ""
				plain_found = str(found[0] or "")
				if "-" in plain_found:
					season_part, episode_part = plain_found.split("-", 1)
					season_no = safe_int(season_part, season_no)
					episode_no = safe_int(episode_part, episode_no)
		except Exception:
			found = ()
		if not (season_no and episode_no):
			return best  # no S/E tag in filename and no text match against the episode index
		episode_details = {}
		episode_error = ""
		try:
			episode_error, episode_details = providers.get_episode_details(provider_name, series_id, episode_id, str(season_no), str(episode_no))
		except Exception as err:
			episode_error = str(err)
		if not isinstance(episode_details, dict):
			episode_details = {}
		series_title = first_non_empty(series_details, "title", "original_title", "name") or first_non_empty(best, "title", "original_title") or item.get("series_title") or item.get("provider_title") or ""
		episode_name = first_non_empty(episode_details, "episode_name", "title", "name") or episode_index_name or (f"Episode {episode_no}")
		series_cover_url = self._series_artwork_url(best, series_details)
		series_backdrop_url = first_non_empty(series_details, "backdrop_url", "fanart_url") or first_non_empty(best, "backdrop_url", "fanart_url")
		episode_image_url = self._episode_artwork_url(episode_details)
		merged = dict(best)
		# Keep selected series identity and artwork as fallback, but store episode metadata as the primary result.
		for key, value in series_details.items() if isinstance(series_details, dict) else []:
			if key not in merged or not merged.get(key):
				merged[key] = value
		for key, value in episode_details.items():
			# Every provider's per-episode payload reports that episode's guest
			# stars under the same "cast" key as the show's main cast (see e.g.
			# TMDB.get_characters(), which maps "guest_stars" straight into
			# cast_list). Keep the show-level main cast from series_details
			# instead of letting one episode's guest stars overwrite it.
			if key == "cast":
				continue
			if value not in (None, "", [], {}):
				merged[key] = value
		merged["provider"] = provider_name or merged.get("provider") or ""
		merged["media_type"] = "series"
		merged["series_id"] = series_id
		merged["series_title"] = str(series_title or "")
		merged["title"] = str(episode_name or "")
		merged["episode_name"] = str(episode_name or "")
		merged["season_no"] = str(season_no)
		merged["episode_no"] = str(episode_no)
		merged["episode_id"] = str(episode_details.get("episode_id") or episode_id or "")
		merged["series_provider_best"] = series_details
		merged["episode_provider_best"] = episode_details
		merged["episode_lookup_error"] = episode_error or err_msg or ""
		# Store series and episode artwork separately. The browser must use the episode still
		# for episode cards and the series poster for series cards.
		if series_cover_url:
			merged["series_cover_url"] = str(series_cover_url)
			merged["series_poster_url"] = str(series_cover_url)
		if series_backdrop_url:
			merged["series_backdrop_url"] = str(series_backdrop_url)
		if episode_image_url:
			merged["episode_image_url"] = str(episode_image_url)
			merged["episode_still_url"] = str(episode_image_url)
			merged["preview_url"] = str(episode_image_url)
			merged["still_url"] = str(episode_image_url)
			merged["image_url"] = str(episode_image_url)
			merged["image_src"] = "episode"
		for key in ("titlelogo_url", "logo_url"):
			series_value = series_details.get(key) if isinstance(series_details, dict) else ""
			if series_value and not merged.get(f"series_{key}"):
				merged[f"series_{key}"] = series_value
		return merged

	def _gather_provider_matches(self, item, media_type, year, searched, language):
		# Try every candidate title, not just until the first one returns any
		# results - a later, better-matching candidate could otherwise never be
		# tried. choose_best() picks the best match across the accumulated
		# results, mirroring the legacy scanner's search_variants accumulation.
		matches = []
		last_error = ""
		for title in self.candidate_titles(item):
			searched.append({"title": title, "media_type": media_type, "year": year, "language": language})
			try:
				results = providers.gather_providers_info(title, media_type, year)
				if results:
					matches.extend([dict(result) for result in results if isinstance(result, dict)])
				else:
					search_errors = getattr(providers, "last_search_errors", [])
					if search_errors:
						last_error = "; ".join(str(error) for error in search_errors if error)
			except Exception as err:
				last_error = f"{err}\n{format_exc()}"
		return matches, last_error

	def _deduplicate_matches(self, matches):
		unique = []
		seen = set()
		for result in matches:
			provider_ids = result.get("provider_ids", {}) if isinstance(result.get("provider_ids", {}), dict) else {}
			key = dumps([result.get("provider"), result.get("title"), provider_ids], sort_keys=True, ensure_ascii=False)
			if key in seen:
				continue
			seen.add(key)
			unique.append(result)
		return unique

	def _complete_best_metadata(self, item, best, media_type, matches):
		if not best:
			return best
		best = self._episode_best_from_series(item, best, media_type)
		best = self._fill_alternate_provider_artwork(item, best, matches)
		best = self._apply_fanart_artwork(best)
		best = self._fill_live_horizontal_image(item, best)
		return best

	def _strict_media_type_fallbacks(self, media_type, item):
		# Some user movie folders contain TV shows or show-like recordings without sidecar metadata.
		# If the strict movie lookup returns nothing, retry as series before declaring no_match.
		media_type = str(media_type or "").strip().lower()
		if media_type == "movie":
			return ("series",)
		return ()

	def _search_title_translation_retry(self, item, media_type, year, searched, language):
		# Same idea as the legacy GUI-side E2MDBTranslator.translate_title_for_search()
		# (not called here - that module needs live Enigma2 config and can't run in
		# the daemon): if normal search variants found nothing, translate the title
		# once via the existing backend_translator and try again with that. This is
		# a search-title fallback, not the metadata-text translation above.
		provider_settings = self.settings.get("provider", {}) if isinstance(self.settings.get("provider", {}), dict) else {}
		if not bool(provider_settings.get("translate_title_search", False)):
			return [], ""
		title = first_non_empty(item, "provider_title", "series_title", "movie_title", "title")
		if not title:
			return [], ""
		target_language = self._normalize_provider_language(provider_settings.get("translate_title_search_language") or language)
		translated = backend_translator.translate(title, target_language, source_language="auto")
		if not translated or translated.casefold() == title.casefold():
			return [], ""
		searched.append({"title": translated, "media_type": media_type, "year": year, "language": target_language, "translated_from": title})
		try:
			results = providers.gather_providers_info(translated, media_type, year)
		except Exception:
			return [], translated
		return [dict(result) for result in results if isinstance(result, dict)] if results else [], translated

	def _tvspielfilm_channel_time_fallback(self, item):
		"""TVSpielfilm has no title search - it resolves a recording/event by
		channel + EPG start time instead. Use it as a last-resort match when the
		normal title-search providers found nothing (e.g. no TMDB/TVDB/OMDB key
		configured), for both Live/EPG events and EIT-scanned recordings."""
		if provider_tvspielfilm is None or not self._provider_option("tvspielfilm_enabled", True):
			return None
		candidate = _LiveFallbackCandidate(item)
		if not candidate.service_ref or not candidate.begin_time:
			return None
		try:
			provider_tvspielfilm.start(self.provider_language)
			err_msg, final_dict = provider_tvspielfilm.lookup_epg_event(candidate)
		except Exception:
			return None
		return final_dict if isinstance(final_dict, dict) and final_dict else None

	def search_item(self, item):
		start_error = self.start()
		if start_error and providers is None:
			return {"success": False, "error": start_error, "matches": [], "best": {}}
		ready_providers = getattr(providers, "ready_providers", None)
		tvspielfilm_available = provider_tvspielfilm is not None and self._provider_option("tvspielfilm_enabled", True)
		if ready_providers is not None and not ready_providers and not tvspielfilm_available:
			return {
				"success": False,
				"error": start_error or "no enabled metadata provider is ready",
				"transient_error": True,
				"matches": [],
				"best": {},
				"updated": int(time()),
			}
		media_type = detect_media_type(item)
		year = extract_year(item.get("title"), item.get("description"), item.get("path"))
		searched = []
		last_error = start_error or ""
		target_language = self.provider_language
		matches, search_error = self._gather_provider_matches(item, media_type, year, searched, target_language)
		if search_error:
			last_error = search_error
		unique = self._deduplicate_matches(matches)
		best = self.choose_best(item, unique)
		best = self._complete_best_metadata(item, best, media_type, unique)
		strict_type_fallback_used = ""
		if not best:
			for fallback_media_type in self._strict_media_type_fallbacks(media_type, item):
				fallback_matches, fallback_error = self._gather_provider_matches(item, fallback_media_type, year, searched, target_language)
				fallback_unique = self._deduplicate_matches(fallback_matches)
				fallback_best = self.choose_best(item, fallback_unique)
				fallback_best = self._complete_best_metadata(item, fallback_best, fallback_media_type, fallback_unique)
				if fallback_best:
					unique = self._deduplicate_matches(unique + fallback_unique)
					best = fallback_best
					strict_type_fallback_used = fallback_media_type
					break
				if fallback_error and not last_error:
					last_error = fallback_error
		translated_search_title = ""
		if not best:
			translation_matches, translated_search_title = self._search_title_translation_retry(item, media_type, year, searched, target_language)
			if translation_matches:
				translation_unique = self._deduplicate_matches(translation_matches)
				translation_best = self.choose_best(item, translation_unique)
				translation_best = self._complete_best_metadata(item, translation_best, media_type, translation_unique)
				if translation_best:
					unique = self._deduplicate_matches(unique + translation_unique)
					best = translation_best
		if not best:
			tvspielfilm_best = self._tvspielfilm_channel_time_fallback(item)
			if tvspielfilm_best:
				tvspielfilm_best = self._complete_best_metadata(item, tvspielfilm_best, media_type, unique)
				if tvspielfilm_best:
					unique = self._deduplicate_matches(unique + [tvspielfilm_best])
					best = tvspielfilm_best
		english_fallback_used = False
		english_fallback_mode = ""
		metadata_translated = False
		if self._provider_option("english_text_fallback", True) and target_language != "en" and (not best or not self._has_metadata_text(best)):
			selected_provider = str(best.get("provider") or "").strip().lower() if isinstance(best, dict) else ""
			self._switch_provider_language("en")
			if best and selected_provider == "tmdb":
				fallback_fields, english_error = self._tmdb_english_metadata_by_id(item, best, media_type)
				if fallback_fields and self._has_metadata_text(best):
					english_fallback_used = True
					english_fallback_mode = "tmdb-id"
					metadata_translated = self._translate_metadata_texts(best, target_language, fields=fallback_fields)
				if english_error and not last_error:
					last_error = english_error
			else:
				english_matches, english_error = self._gather_provider_matches(item, media_type, year, searched, "en")
				english_unique = self._deduplicate_matches(english_matches)
				english_best = self.choose_best(item, english_unique)
				english_best = self._complete_best_metadata(item, english_best, media_type, english_unique)
				if english_best and (not best or self._has_metadata_text(english_best)):
					best = english_best
					unique = english_unique or unique
					english_fallback_used = True
					english_fallback_mode = "provider-search"
					metadata_translated = self._translate_metadata_texts(best, target_language)
				if english_error and not last_error:
					last_error = english_error
			self._switch_provider_language(target_language)
		artwork = self.download_artwork(item, best) if best else {}
		result_media_type = str(best.get("media_type") or strict_type_fallback_used or media_type) if isinstance(best, dict) else media_type
		result = {
			"artwork_lookup_version": 3,
			"success": bool(best),
			"error": "" if best else (last_error or "no provider match"),
			"transient_error": bool(not best and last_error),
			"recording_id": item.get("id"),
			"path": item.get("path"),
			"media_type": result_media_type,
			"requested_media_type": media_type,
			"strict_type_fallback_used": strict_type_fallback_used,
			"translated_search_title": translated_search_title,
			"year": year,
			"searched": searched,
			"matches": unique[:20],
			"best": best,
			"artwork": artwork,
			"provider_language": target_language,
			"english_text_fallback_used": english_fallback_used,
			"english_text_fallback_mode": english_fallback_mode,
			"metadata_translated": metadata_translated,
			"updated": int(time()),
		}
		result["json_path"] = self._write_provider_debug_json(item, result)
		return result

	def _download_file(self, url, target_path):
		if not url:
			return ""
		try:
			folder = dirname(target_path)
			if folder and not exists(folder):
				makedirs(folder)
			request = Request(url, headers={"User-Agent": "e2MDB-backend/1.0"})
			with urlopen(request, timeout=30) as response:
				data = response.read(20 * 1024 * 1024)
			if not data:
				return ""
			tmp_path = f"{target_path}.tmp"
			with open(tmp_path, "wb") as handle:
				handle.write(data)
			from os import rename
			rename(tmp_path, target_path)
			return target_path
		except Exception:
			return ""

	def _download_if_missing(self, url, target_path):
		# Series/season artwork paths are deterministic and shared across every
		# episode of the same show, so once one episode has downloaded the file
		# the rest just reuse it instead of re-fetching identical bytes.
		if not target_path:
			return ""
		if exists(target_path):
			return target_path
		return self._download_file(url, target_path)

	def _artwork_image_extension(self, url, fallback="jpg"):
		match = search(r"\.(jpe?g|png|gif|webp)(?=$|[/?#_;&=,])", str(url or ""), IGNORECASE)
		if match:
			ext = match.group(1).lower()
			return "jpg" if ext == "webp" else ext
		return fallback

	def _reduced_org_path(self, org_path):
		return str(org_path or "").replace("/media/hdd", "").replace("/media/autofs", "")

	def _primary_artwork_path(self, org_path, pic_type, url):
		# Per-file artwork (movies, episode-only stills): keyed by a hash of the
		# recording's own path, e.g. cache_root/image/5/59bda...jpg
		org_hash = md5(self._reduced_org_path(org_path).encode()).hexdigest()
		ext = self._artwork_image_extension(url)
		return join(self.cache_root, pic_type, org_hash[0], f"{org_hash}.{ext}")

	def _secondary_artwork_path(self, provider_name, provider_id, pic_type, url):
		# Series-level artwork: keyed by provider+series id, e.g.
		# cache_root/series/tmdb/12345/cover.jpg, shared by every episode.
		provider_name = str(provider_name or "unknown").strip().lower() or "unknown"
		provider_id = str(provider_id or "").strip()
		ext = self._artwork_image_extension(url)
		return join(self.cache_root, "series", provider_name, provider_id, f"{pic_type}.{ext}")

	def _series_artwork_target(self, item, best, pic_type, url):
		provider_name = str(best.get("provider") or "").strip().lower()
		media_type = str(best.get("media_type") or "").strip().lower()
		if self._is_series_type(media_type) and provider_name:
			provider_id = self._provider_id_from_best(provider_name, best)
			if provider_id:
				return self._secondary_artwork_path(provider_name, provider_id, pic_type, url)
		return self._primary_artwork_path(item.get("path"), pic_type, url)

	def _season_artwork_path(self, provider_name, provider_id, season_no, pic_type, url):
		# Season-level artwork: keyed by provider+series id+season, e.g.
		# cache_root/seasons/tvdb/12345/S01/cover.jpg, shared by every episode
		# of that season.
		provider_name = str(provider_name or "unknown").strip().lower() or "unknown"
		provider_id = str(provider_id or "").strip()
		season_part = f"S{safe_int(season_no, 0):02d}"
		ext = self._artwork_image_extension(url)
		return join(self.cache_root, "seasons", provider_name, provider_id, season_part, f"{pic_type}.{ext}")

	def _season_poster_url(self, best, season_no):
		seasons = best.get("seasons") if isinstance(best.get("seasons"), list) else []
		season_no = safe_int(season_no, 0)
		if not season_no:
			return ""
		for entry in seasons:
			if isinstance(entry, dict) and safe_int(entry.get("season_no"), -1) == season_no:
				return first_non_empty(entry, "cover_url", "poster_url")
		return ""

	def _debug_json_enabled(self):
		try:
			return bool(self.settings.get("debug") or self.settings.get("debug_log") or self.settings.get("debug_json"))
		except Exception:
			return False

	def _write_provider_debug_json(self, item, payload):
		item = item if isinstance(item, dict) else {}
		recording_id = str(item.get("id") or item.get("source_key") or "unknown").strip() or "unknown"
		folder = join(self.artwork_root, recording_id)
		target = join(folder, "provider_result.json")
		if not self._debug_json_enabled():
			try:
				if exists(target):
					remove(target)
			except Exception:
				pass
			return ""
		try:
			if not exists(folder):
				makedirs(folder)
			with open(target, "w") as handle:
				handle.write(dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False, sort_keys=True, indent=2))
				handle.write("\n")
			return target
		except Exception:
			return ""

	def _is_portrait_artwork_url(self, value):
		try:
			text = str(value or "").lower()
		except Exception:
			return False
		if not text:
			return False
		portrait_markers = ("/poster", "poster.", "poster_", "_poster", "series_poster", "/cover", "cover.", "cover_", "_cover", "/covers/")
		return any(marker in text for marker in portrait_markers)

	def download_artwork(self, item, best):
		artwork_settings = self.settings.get("artwork", {}) if isinstance(self.settings.get("artwork", {}), dict) else {}
		if not bool(artwork_settings.get("download_enabled", True)):
			return {}
		org_path = str(item.get("path") or "")
		result = {}
		# Episode rows may have their own still image, but this must never be
		# promoted to poster/cover artwork. Generic Live/EPG preview images are
		# stored as image/preview below, not as episode/poster. Episode stills are
		# always per-file, never shared between episodes of the same series.
		image_src = str(best.get("image_src") or best.get("image_provider") or "").strip().lower()
		cover_src = str(best.get("cover_src") or "").strip().lower()
		episode_url = first_non_empty(best, "episode_image_url", "episode_still_url")
		if not episode_url and image_src == "episode":
			episode_url = first_non_empty(best, "image_url", "still_url", "preview_url")
		if not episode_url and cover_src == "episode":
			episode_url = first_non_empty(best, "cover_url")
		if episode_url:
			path = self._download_if_missing(episode_url, self._primary_artwork_path(org_path, "image", episode_url))
			if path:
				result["episode_path"] = path
				result["episode_url"] = episode_url

		series_poster_url = first_non_empty(best, "series_cover_url", "series_poster_url")
		if series_poster_url:
			path = self._download_if_missing(series_poster_url, self._series_artwork_target(item, best, "cover", series_poster_url))
			if path:
				result["series_poster_path"] = path
				result["series_poster_url"] = series_poster_url

		series_backdrop_url = first_non_empty(best, "series_backdrop_url")
		if series_backdrop_url:
			path = self._download_if_missing(series_backdrop_url, self._series_artwork_target(item, best, "backdrop", series_backdrop_url))
			if path:
				result["series_backdrop_path"] = path
				result["series_backdrop_url"] = series_backdrop_url

		provider_name = str(best.get("provider") or "").strip().lower()
		media_type = str(best.get("media_type") or "").strip().lower()
		season_no = safe_int(best.get("season_no") or item.get("season_no"), 0)
		if self._is_series_type(media_type) and provider_name and season_no:
			series_id = self._provider_id_from_best(provider_name, best)
			season_poster_url = self._season_poster_url(best, season_no)
			if series_id and season_poster_url:
				path = self._download_if_missing(season_poster_url, self._season_artwork_path(provider_name, series_id, season_no, "cover", season_poster_url))
				if path:
					result["season_poster_path"] = path
					result["season_poster_url"] = season_poster_url

		image_url = first_non_empty(best, "image_url", "preview_url", "still_url")
		if image_url and self._is_portrait_artwork_url(image_url):
			image_url = ""
		if image_url and not result.get("episode_path"):
			path = self._download_if_missing(image_url, self._primary_artwork_path(org_path, "image", image_url))
			if path:
				result["image_path"] = path
				result["image_url"] = image_url
				result["preview_path"] = path
				result["still_path"] = path

		mapping = (
			(("cover_url", "poster_url"), "poster", "cover"),
			(("backdrop_url", "fanart_url"), "backdrop", "backdrop"),
			(("titlelogo_url", "logo_url", "clearlogo_url"), "logo", "titlelogo"),
		)
		for keys, result_name, pic_type in mapping:
			url = first_non_empty(best, *keys)
			if not url:
				continue
			if result_name == "backdrop" and str(url or "").strip() == str(result.get("series_backdrop_url") or "").strip():
				continue
			if result_name == "poster":
				url_text = str(url or "").strip()
				if url_text and url_text == str(result.get("episode_url") or "").strip():
					continue
				if str(best.get("cover_src") or "").strip().lower() == "episode" and url_text == str(best.get("cover_url") or "").strip():
					continue
				if str(best.get("poster_src") or "").strip().lower() == "episode" and url_text == str(best.get("poster_url") or "").strip():
					continue
			# Cover/backdrop/logo are show-level artwork: shared across every
			# episode of the same series instead of downloaded again per recording.
			path = self._download_if_missing(url, self._series_artwork_target(item, best, pic_type, url))
			if path:
				result[f"{result_name}_path"] = path
				result[f"{result_name}_url"] = url
		return result
