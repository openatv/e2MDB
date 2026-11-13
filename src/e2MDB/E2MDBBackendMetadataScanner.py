########################################################################################################
# e2MDB by Mr.Servo @OpenATV and jbleyel @OpenATV (c) 2026 - skin & design by stein17 @OpenATV         #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from datetime import datetime
from os.path import basename, dirname, exists, isfile, join, normpath, splitext
from re import IGNORECASE, search, sub

# PLUGIN IMPORTS
# Only e2mdbd.py imports this module, always as a plain top-level import (no
# parent package) - so relative imports here would never resolve. Absolute
# imports only, matching how the daemon actually loads this file.
from E2MDBDatabase import mediadb
from E2MDBIgnoreConfig import E2MDBIgnorePatterns
from E2MDBRecordingParser import parse_recording as default_parse_recording
from MediaNameParser import MediaNameParser
from provider.Common import EPGTYPE_SEPAS, EXCLUDED_DIRS, FOREIGN_SEPAS, VIDEO_EXTS, guess_separator, safe_int


class E2MDBBackendMetadataScanner:
	"""Backend-safe metadata scanner facade used by e2mdbd.
	All daemon recording/media scans must enter through this class so path
	filtering, TS META/EIT/CUTS parsing and MediaNameParser handling stay in the
	same module as the historical v16 scanner logic.  The daemon only orchestrates
	jobs and stores the returned scan items.
	"""
	NON_MEDIA_SIDECAR_EXTS = (".meta", ".eit", ".cuts", ".cutsr", ".ap", ".sc", ".txt", ".nfo", ".srt", ".sub", ".idx", ".jpg", ".jpeg", ".png", ".gif", ".log", ".tmp", ".part")
	season_keys = [
#		_("season"),  # localized
		"staffel",  # DE
		"season",  # EN
		"temporada",  # ES
		"saison",  # FR
		"seizoen",  # NL
		"stagione",  # IT
		"säsong",  # SE
		"sezona",  # SI
		"sezóna",  # SK
		"сезон",  # RU
		"musim",  # ID
		"sezon",  # TR
		"موسم",  # AR
		"시즌",  # KO
		"mùa",  # VI
		"ฤดูกาล"  # TH
		]
	episode_keys = [
#		_("episode"),  # localized
		"folge",  # DE
		"episode",  # EN
		"episodio",  # ES
		"épisode",  # FR
		"aflevering",  # NL
		"episódio",  # PT
		"avsnitt",  # SE
		"epizoda",  # SI
		"epizóda",  # SK
		"эпизод",  # RU
		"bölüm",  # TR
		"حلقة",  # AR
		"회",  # KO
		"tập",  # VI
		"ตอน"  # TH
		]
	series_keys = season_keys + episode_keys + [
		"serie", "serien", "reihe", "magazin",  # DE
		"serial", "series", "soap", "talk", "show", "news", "infomercial", "sitcom",  # EN
		"telenovela", "reality", "magacín",  # ES
		"série", "télénovela",  # FR
		"novela",  # PT
		"avsnitt", "säsong",  # SE
		"serija",  # SI
		"séria",  # SK
		"сериал", "серии", "реалити", "журнал",  # RU
		"seri",  # ID
		"dizi",  # TR
		"سلسلة", "واقعي",  # AR
		"시리즈", "리얼리티",  # KO
		"chuỗi", "loạt phim"  # VI
		"ซีรีส์"  # TH
	]  # without duplicate entries. it's sufficient if 'docu' appears once (that's why a word like 'documentation' is meaningless)

	# TODO: diese Suchkriterien (oben und unten) sollten sauber zusammengefasst werden

	SERIES_FOLDER_HINTS = {
		"serie", "serien", "series", "tv series", "tv show", "tv shows", "shows", "show", "television",
		"anime series", "anime serie", "anime serien", "manga series", "manga serie", "manga serien",
		"saison", "saisons", "season", "seasons", "staffel", "staffeln", "temporada", "temporadas",
		"stagione", "stagioni", "seizoen", "seizoenen", "sezon", "sezony", "sezona", "sezone",
		"serial", "seriale", "serialy", "seria", "série", "séries", "serie tv", "reeks", "reeksen",
		"sarja", "sarjat", "sesong", "sesonger", "sasong", "sasonge", "sæson", "sæsoner",
		"säsong", "säsonger", "dizi", "diziler", "σειρα", "σειρες", "сериал", "сериалы", "серии"
	}
	MOVIE_FOLDER_HINTS = {
		"kino", "kinofilme", "cinema", "cinemas", "ciné", "cinema premieren", "premiere", "premieren",
		"movies", "movie", "movie library", "films", "filme", "filmliste", "peliculas", "películas", "pellicole",
		"anime movies", "anime movie", "anime filme", "anime films", "manga movies", "manga movie", "manga filme", "manga films",
		"long films", "feature films", "spielfilme", "feature movies"
	}
	ANIME_FOLDER_HINTS = {
		"anime", "animes", "anime series", "anime serie", "anime serien", "anime movies", "anime movie",
		"anime filme", "anime films", "japanimation", "japanese animation", "animacion japonesa",
		"animazione giapponese", "animation japonaise", "аниме", "アニメ"
	}
	MANGA_FOLDER_HINTS = {
		"manga", "mangas", "manga series", "manga serie", "manga serien", "manga movies", "manga movie", "manga filme", "manga films", "manga comics",
		"manhwa", "manhwas", "manhua", "manhuas", "webtoon", "webtoons", "doujinshi",
		"comic", "comics", "bd", "bande dessinee", "bande dessinée", "fumetti", "fumetto",
		"tebeos", "historieta", "mangá", "манга", "漫画"
	}

	def __init__(self, parse_recording=None, media_name_parser=None, recording_parser_error=None, media_name_parser_error=None):
		self.parse_recording_func = parse_recording or default_parse_recording
		self.media_name_parser = media_name_parser or MediaNameParser
		self.recording_parser_error = recording_parser_error
		self.media_name_parser_error = media_name_parser_error
		self.last_parsed = ("", {})  # (path, parse_recording result) of the last parsed recording
		self.mediadb_enabled = False
		self.mediadb_error = ""
		self.ignored_folder_names = self.load_ignored_folder_names()

	def load_ignored_folder_names(self):
		# User-configured generic library folder names (e.g. "Serien", "TV Shows")
		# that must never be used as a series title, on top of MediaNameParser's
		# own built-in IGNORED_LIBRARY_FOLDER_NAMES set. MediaNameParser expects an
		# already-normalized set (its own parse_ignored_folder_names()), not raw text.
		try:
			raw_patterns = E2MDBIgnorePatterns.parse(E2MDBIgnorePatterns.FOLDER_NAME)
			return MediaNameParser.parse_ignored_folder_names(raw_patterns)
		except Exception:
			return set()

	def configure(self, settings=None):
		settings = settings if isinstance(settings, dict) else {}
		cache = settings.get("cache", {}) if isinstance(settings.get("cache", {}), dict) else {}
		database = settings.get("database", {}) if isinstance(settings.get("database", {}), dict) else {}
		root = database.get("root", "").strip() or cache.get("root", "")
		if not root:
			db_path = database.get("path", "").strip()
			if db_path:
				root = dirname(db_path)
		if not root:
			root = "/media/hdd/e2MDB"
		self.set_mediadb_root(root)
		self.ignored_folder_names = self.load_ignored_folder_names()

	def set_mediadb_root(self, root):
		try:
			mediadb.set_path(root)
			self.mediadb_enabled = True
			self.mediadb_error = ""
		except Exception as err:
			self.mediadb_enabled = False
			self.mediadb_error = str(err)

	def upsert_mediadb(self, item):
		if not self.mediadb_enabled:
			return {"success": False, "error": self.mediadb_error or "MediaDB is not configured"}
		try:
			row_id = mediadb.upsert({
				"path": item.get("path", ""),
				"title": item.get("title", ""),
				"short_desc": item.get("short_desc", item.get("short_desc", "")),  # HOLGER: Ist Doppeltgemoppelt
				"extended_desc": item.get("extended_desc", item.get("extended_desc", ""))  # HOLGER: Ist Doppeltgemoppelt
			})
			return {"success": True, "row_id": row_id}
		except Exception as err:
			self.mediadb_error = str(err)
			return {"success": False, "error": str(err)}

	def iso_from_timestamp(self, value):
		try:
			dt_str = datetime.fromtimestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")
		except Exception:
			dt_str = ""
		return dt_str

	def media_extension(self, path):
		return splitext(str(path or ""))[1].lower()

	def is_known_media_file(self, path):
		name = basename(str(path or ""))
		if not name or name.startswith("."):
			return False
		return self.media_extension(path) in VIDEO_EXTS

	def parse_sidecar_infos(self, path):  # parse each recording only once per scan step
		if self.last_parsed[0] != path:
			self.last_parsed = (path, self.parse_recording_func(path))
		return self.last_parsed[1]

	def has_sidecar_infos(self, path):
		return self.parse_sidecar_infos(path).get("exists", False)

	def get_sidecar_title(self, path):  # merged title (EIT > META > TXT)
		return str(self.parse_sidecar_infos(path).get("title", "")).strip()

	def clean_title_from_filename(self, path):
		name = splitext(basename(path))[0].replace(".", " ")
		name = sub(r"\s+", " ", name).strip()
		return name or basename(path)

	def clean_openatv_recording_title(self, path):
		text = self.clean_title_from_filename(path)
		patterns = (
			r"^\d{8}\s+\d{3,4}\s*-\s*[^-]+\s*-\s*(.+)$",
			r"^\d{4}[-.]\d{2}[-.]\d{2}\s+\d{1,2}[:.]\d{2}\s*-\s*[^-]+\s*-\s*(.+)$"
		)
		for pattern in patterns:
			match = search(pattern, text)
			if match:
				candidate = sub(r"\s+", " ", match.group(1)).strip(" -_.")
				if candidate:
					return candidate
		return text

	def parser_path_for_recording(self, media_path):
		if not self.has_sidecar_infos(media_path):
			return media_path
		clean_title = self.clean_openatv_recording_title(media_path)
		if not clean_title:
			return media_path
		base_title = self.clean_title_from_filename(media_path)
		if clean_title == base_title:
			return media_path
		return join(dirname(media_path), f"{clean_title}{splitext(media_path)[1]}")

	def make_recording_id(self, path):
		from hashlib import md5
		reduced = str(path or "").replace("/media/hdd", "").replace("/media/autofs", "")
		return md5(reduced.encode("utf-8", "replace")).hexdigest()

	def mode_family_from_path_mode(self, mode):
		mode = safe_int(mode, 0)
		return {
			1: "movie",
			2: "series",
			3: "multi",
			4: "anime_series",
			5: "manga_series",
			6: "anime_movie",
			7: "manga_movie",
		}.get(mode, "")

	def path_mode_label(self, mode):
		mode = safe_int(mode, 0)
		return {
			0: "exclude",
			1: "movie",
			2: "series",
			3: "movie_series",
			4: "anime_series",
			5: "manga_series",
			6: "anime_movie",
			7: "manga_movie"
		}.get(mode, "unknown")

	def parse_season_episode_text(self, value):
		text = str(value or "")
		for pattern in (
			r"(?i)[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})",
			r"(?i)\b(\d{1,2})x(\d{1,3})\b",
			r"(?i)(?:staffel|season)\s*(\d{1,2}).{0,30}(?:folge|episode|ep\.?|e)\s*(\d{1,3})"
		):
			match = search(pattern, text)
			if match:
				return safe_int(match.group(1), 0), safe_int(match.group(2), 0)
		return 0, 0

	def clean_series_title(self, value):
		text = self.clean_title_from_filename(str(value or ""))
		for pattern in (
			r"(?i)\b[Ss]\d{1,2}[ ._-]*[Ee]\d{1,3}\b",
			r"(?i)\b\d{1,2}x\d{1,3}\b",
			r"(?i)\b(?:staffel|season)\s*\d{1,2}.*$"
		):
			match = search(pattern, text)
			if match:
				text = text[:match.start()]
				break
		text = sub(r"(?i)\b(german|english|multi|dubbed|subbed|720p|1080p|2160p|web|webrip|web-dl|hdtv|bluray|x264|x265|h264|h265|hevc|ac3|dts)\b.*$", "", text)
		return sub(r"\s+", " ", text).strip(" -_.")

	def guess_category(self, org_title, org_path, desc="", short_desc=""):  # don't use 'ext_desc', it might lead to incorrect results
		# all available data (title + metadata except 'ext_desc') are examined for attributes:
		# findSeasonsEpisodes, findYearTags, findSeriesKeywords, findMovieKeywords
		def findSeasonsEpisodes(text):  # search for season/episode tags
			def searchForKeys(keys):
				for key in keys:
					found = search(rf"{key}\s*(\d+)", text.lower(), IGNORECASE)
					if found:
						return found.group(1)
					found = search(rf"{key}\s*(\d+)", org_path.lower(), IGNORECASE)
					if found:
						return found.group(1)

			season_keys = ["s"] + self.season_keys + [f"{key} " for key in self.season_keys]
			episode_keys = ["e"] + self.episode_keys + [f"{key} " for key in self.episode_keys]
			season_no, episode_no = searchForKeys(season_keys), searchForKeys(episode_keys)  # with / without space and also single 'S' and 'E'
			if season_no and season_no.isdigit() and episode_no and episode_no.isdigit():
				match_reason = f"S{int(season_no):02d}E{int(episode_no):02d}"
				find_pos = text.find(match_reason)
				if find_pos > 0:
					text = text[:text.find(match_reason)].strip()  # cut off e.g. 'S02E13' and everything after that
				return "series", text, match_reason
			return "", text, ""

		def findYearTags(text):  # search for year tags
				for regex in [r"\(\d{4}\)"]:  # search for e.g. '(1997)'
					found = search(regex, text)
					if found:
						found = found.group(0)
						text = text.replace(f" {found}", "").strip()
						match_reason = found.strip()
						year = match_reason.replace("(", "").replace(")", "")
						# before 1896 or after current year it can't be a movie
						media_type = "series" if year.isdigit() and (int(year) < 1896 or int(year) > datetime.now().year) else "movie"
						return media_type, text, match_reason  # text=cleanText, match_reason='(1997)'
				return "", text, ""

		def findSeriesKeywords(text):  # search for series keywords
			lower_text = text.lower()
			for tag in self.series_keys:
				for word in lower_text.split():  # compare complete words only!
					if tag == word:
						return "series", text, tag
			return "", text, ""

		def findMovieKeywords(text):  # search for movie keywords
			movie_keys = ["film", "movie", "фильм", "кино", "ταινία", "película", "cinéma", "cine", "cinema", "filma"]
			lower_text = text.lower()
			for tag in movie_keys:
				for word in lower_text.split():  # compare complete words only!
					if tag == word:
						return "movie", text, tag
			return "", text, ""

		# start guess_category: search titles and all descriptions for typical characteristics in order to identify the media type.
		res_title, res_desc = (), ()
		search_title = org_title
		for find_helper in [findSeasonsEpisodes, findYearTags, findSeriesKeywords, findMovieKeywords]:
			media_type, search_title, match_reason = find_helper(self.trim_text(search_title))
			if media_type and not res_title:  # use first hit as result, but continue in order to clean-up title
				res_title = (media_type, search_title, match_reason)
		for find_helper in [findSeasonsEpisodes, findSeriesKeywords, findMovieKeywords]:
			for descs in [short_desc, desc]:
				if descs:
					media_type, clean_desc, match_reason = find_helper(self.trim_text(descs))
					if media_type and not res_desc:
						res_desc = (media_type, search_title, match_reason)
		if res_title:
			return res_title
		if res_desc:
			return res_desc
		else:
			return ("", search_title, "")

	def get_se_ep(self, ep_details):
		if ep_details and ep_details.success:
			season_number = ep_details.season_number
			episode_number = ep_details.episode_number
			if season_number and episode_number:
				return f"S{season_number:02d}E{episode_number:02d}"
			if season_number:
				return f"S{season_number:02d}"
			if episode_number:
				return f"E{episode_number:02d}"
		return ""

	def trim_text(self, text):
		return text.replace("_", "").replace("/", "").replace("|", "").strip()

	def divide_file_base_infos(self, text, separator):
		# 'Wir waren wie Brüder_Currahee' -> ('Wir waren wie Brüder', 'Currahee').
		path_items = [item.strip() for item in text.split(separator)]
		title_part = path_items[0].strip(".").strip("_").strip()
		desc_part = " ".join(path_items[1:])
		return title_part, desc_part

	def _path_has_folder_hint(self, org_path, hints):
		try:
			path_parts = [part for part in normpath(str(org_path or "")).split("/") if part]
		except Exception:
			path_parts = []
		for part in path_parts[:-1]:
			if MediaNameParser.normalize_folder_name(part) in hints:
				return True
		return False

	def path_suggests_series(self, org_path):
		return self._path_has_folder_hint(org_path, self.SERIES_FOLDER_HINTS)

	def path_suggests_movie(self, org_path):
		return self._path_has_folder_hint(org_path, self.MOVIE_FOLDER_HINTS)

	def path_suggests_anime(self, org_path):
		return self._path_has_folder_hint(org_path, self.ANIME_FOLDER_HINTS)

	def path_suggests_manga(self, org_path):
		return self._path_has_folder_hint(org_path, self.MANGA_FOLDER_HINTS)

	def resolve_special_media_type(self, org_path):
		if self.path_suggests_manga(org_path):
			if self.path_suggests_movie(org_path):
				return "manga_movie"
			return "manga_series" if self.path_suggests_series(org_path) else "manga"
		if self.path_suggests_anime(org_path):
			if self.path_suggests_movie(org_path):
				return "anime_movie"
			return "anime_series" if self.path_suggests_series(org_path) else "anime"
		return ""

	def media_type_from_path_mode(self, path_mode, title="", path=""):
		media_type = {
			1: "movie",
			2: "series",
			3: "multi",
			4: "anime_series",
			5: "manga_series",
			6: "anime_movie",
			7: "manga_movie"
			}.get(safe_int(path_mode, 0), "")
		return media_type

	def recording_name_info_from_clean_title(self, clean_title, path_mode=0):
		clean_title = str(clean_title or "").strip()
		path_mode = safe_int(path_mode, 0)
		season_no, episode_no = self.parse_season_episode_text(clean_title)
		if season_no or episode_no:
			series_title = self.clean_series_title(clean_title)
			return {
				"media_type": "series",
				"series_title": series_title,
				"movie_title": "",
				"season_no": season_no,
				"episode_no": episode_no,
				"year": 0,
				"episode": {"success": True, "series_name": series_title, "season_number": season_no, "episode_number": episode_no, "ending_episode_number": 0, "year": 0, "is_by_date": False, "container": "ts"},
				"movie": {}
			}
		if path_mode in (2, 4, 5):
			return {
				"media_type": "series",
				"series_title": clean_title,
				"movie_title": "",
				"season_no": 0,
				"episode_no": 0,
				"year": 0,
				"episode": {"success": True, "series_name": clean_title, "season_number": 0, "episode_number": 0, "ending_episode_number": 0, "year": 0, "is_by_date": False, "container": "ts"},
				"movie": {}
			}
		return {
			"media_type": "" if path_mode in (0, 1, 3, 6, 7) else self.media_type_from_path_mode(path_mode, clean_title, clean_title),
			"series_title": "",
			"movie_title": clean_title,
			"season_no": 0,
			"episode_no": 0,
			"year": 0,
			"episode": {},
			"movie": {"success": True, "movie_name": clean_title, "year": 0, "container": "ts"}
		}

	def _parser_dict_from_episode(self, parsed):
		if not parsed:
			return {}
		return {
			"success": bool(getattr(parsed, "success", False)),
			"series_name": getattr(parsed, "series_name", ""),
			"season_number": safe_int(getattr(parsed, "season_number", 0), 0),
			"episode_number": safe_int(getattr(parsed, "episode_number", 0), 0),
			"ending_episode_number": safe_int(getattr(parsed, "ending_episode_number", 0), 0),
			"year": safe_int(getattr(parsed, "year", 0), 0),
			"is_by_date": bool(getattr(parsed, "is_by_date", False)),
			"container": getattr(parsed, "container", "")
		}

	def _parser_dict_from_movie(self, parsed):
		if not parsed:
			return {}
		return {
			"success": bool(getattr(parsed, "success", False)),
			"movie_name": getattr(parsed, "movie_name", ""),
			"year": safe_int(getattr(parsed, "year", 0), 0),
			"container": getattr(parsed, "container", "")
		}

	def parse_media_name_for_scan(self, media_path, path_item, fallback_title=""):
		mode = safe_int(path_item.get("mode", 0), 0) if isinstance(path_item, dict) else 0
		root_path = path_item.get("path", "") if isinstance(path_item, dict) else ""
		parser_media_path = self.parser_path_for_recording(media_path)
		result = {
			"parser_available": self.media_name_parser is not None,
			"parser_error": "" if self.media_name_parser is not None else str(self.media_name_parser_error or ""),
			"media_type": self.media_type_from_path_mode(mode, fallback_title, media_path),
			"series_title": "",
			"movie_title": "",
			"season_no": 0,
			"episode_no": 0,
			"year": 0,
			"episode": {},
			"movie": {}
		}
		if self.media_name_parser is None:
			return result
		parsed_ep, parsed_movie = "", ""
		try:
			if mode in (2, 4, 5):  # is a user declared 'series folder'
				parsed_ep = self.media_name_parser(library_path=root_path, mode=2, ignored_folders=self.ignored_folder_names).parse_episode(parser_media_path)
				result["episode"] = self._parser_dict_from_episode(parsed_ep)
				if getattr(parsed_ep, "success", False):
					result["series_title"] = getattr(parsed_ep, "series_name", "")
					result["season_no"] = safe_int(getattr(parsed_ep, "season_number", 0), 0)
					result["episode_no"] = safe_int(getattr(parsed_ep, "episode_number", 0), 0)
					result["year"] = safe_int(getattr(parsed_ep, "year", 0), 0)
					return result
			if mode in (1, 6, 7):  # is a user declared 'movie folder'
				parsed_movie = self.media_name_parser(library_path=root_path, mode=1, ignored_folders=self.ignored_folder_names).parse_movie(parser_media_path)
				result["movie"] = self._parser_dict_from_movie(parsed_movie)
				if getattr(parsed_movie, "success", False):
					result["movie_title"] = getattr(parsed_movie, "movie_name", "")
					result["year"] = safe_int(getattr(parsed_movie, "year", 0), 0)
					return result
			# no results or is a user declared 'multi folder'
			if not parsed_ep:
				parsed_ep = self.media_name_parser(library_path=root_path, mode=2, ignored_folders=self.ignored_folder_names).parse_episode(parser_media_path)
			result["episode"] = self._parser_dict_from_episode(parsed_ep)
			series_name = getattr(parsed_ep, "series_name", "")
			if getattr(parsed_ep, "success", False) and series_name:
				result["media_type"] = "series"
				result["series_title"] = series_name
				result["season_no"] = safe_int(getattr(parsed_ep, "season_number", 0), 0)
				result["episode_no"] = safe_int(getattr(parsed_ep, "episode_number", 0), 0)
				result["year"] = safe_int(getattr(parsed_ep, "year", 0), 0)
				return result
			if not parsed_movie:
				parsed_movie = self.media_name_parser(library_path=root_path, mode=1, ignored_folders=self.ignored_folder_names).parse_movie(parser_media_path)
			result["movie"] = self._parser_dict_from_movie(parsed_movie)
			movie_name = getattr(parsed_movie, "movie_name", "")
			if getattr(parsed_movie, "success", False) and movie_name:
				result["media_type"] = "movie"
				result["movie_title"] = movie_name
				result["year"] = safe_int(getattr(parsed_movie, "year", 0), 0)
		except Exception as err:
			result["parser_error"] = str(err)
		return result

	def create_best_search(self, org_title, org_path, ep_details=None):
		new_desc = ""
		if ep_details and ep_details.success:
			est_media_type, search_title, match_reason = "series", ep_details.series_name, self.get_se_ep(ep_details)
		else:
			source_title = str(org_title or "").strip()
			if self.media_extension(source_title) in VIDEO_EXTS:
				source_title = splitext(source_title)[0].strip()
			est_media_type, search_title, match_reason = self.guess_category(source_title, org_path)
			clean_match = match_reason.replace("(", "").replace(")", "")
			if clean_match.isdigit():  # in cases org_title includes e.g. '(1121)'
				search_title, new_desc = search_title.replace(match_reason, "").strip(), clean_match
			if search_title:
				if self.has_sidecar_infos(org_path):  # treatment for recordings with sidecar infos (e.G. from EIT)
					if sc_title := self.get_sidecar_title(org_path):
						separator, replacement = guess_separator(sc_title, EPGTYPE_SEPAS)
						if separator:
							search_title, new_desc = self.divide_file_base_infos(sc_title, separator)
				else:  # treatment for foreign recordings (e.g. '.mp4', '.mkv', '.avi', etc.)
					search_title = search_title.replace(".", " ")
					separator, replacement = guess_separator(source_title, FOREIGN_SEPAS)
					if separator:
						search_title, new_desc = self.divide_file_base_infos(source_title, separator)
						search_title = search_title.replace(".", " ")
		return search_title, new_desc, est_media_type, match_reason

	def create_search_titles(self, org_title, org_path):  # create titles alternatives
		search_titles, episode_title = [], ""
		est_media_type, search_title, match_reason = self.guess_category(org_title, org_path)
		search_titles.append((org_title, ""))  # first search string shall be original
		search_title, new_desc, m_type, m_reason = self.create_best_search(org_title, org_path)
		est_media_type = est_media_type or m_type
		match_reason = match_reason or m_reason
		clean_match = match_reason.strip("(").strip(")")  # cleans e.g. '(2019)' but leave 'S02E03'
		if est_media_type == "series":
			episode_title, year = ("", clean_match) if clean_match.isdigit() else (clean_match, "")
		else:
			episode_title, year = (new_desc, clean_match)
		if year:
			search_titles.append((sub(r"\s*\(\d{4}\)", "", org_title).strip(), year))  # first main search with org_title
			search_titles.append((org_title, year))  # second main search using the year-adjusted org_title
		search_titles.append((search_title, year))  # first search variation
		if self.has_sidecar_infos(org_path):  # treatment for recordings with additional infos (e.g. EIT)
			for separator, replacement in EPGTYPE_SEPAS:  # create alternatives acc. EPG separators
				if separator in org_title:
					div_title, desc = self.divide_file_base_infos(org_title, separator)
					search_titles.append((f"{div_title}{replacement.strip()}", year))  # create variation like 'Wunderbar!'
					search_titles.append((div_title, year))  # create variation like 'Wunderbar'
		else:  # treatment for recordings without additional infos (e.g. EIT)
			for separator, replacement in FOREIGN_SEPAS:  # create alternatives acc. foreign separators
					if separator in org_title:
						div_title, desc = self.divide_file_base_infos(org_title, separator)
						search_titles.append((f"{div_title}{replacement.rstrip()}", year))  # create variations
						search_titles.append((div_title, year))
		search_titles = list(dict.fromkeys(search_titles[:]).keys())  # remove all duplicates from list
		return search_titles, episode_title  # e.g. [('Wunderschön', ''), ('Wunderschön!', '')], 'Vom Mont Blanc ins Aostatal'

	def unique_str_list(self, items):  # remove duplicate strings case-insensitive, e.g. ["Hallo", "hallo"] -> [Hallo]
		result, seen = [], set()
		for item in items:
			if not (text := str(item or "").strip()):
				continue
			if (key := text.lower()) in seen:
				continue
			seen.add(key)
			result.append(text)
		return result

	def unique_tuples_list(self, items):  # remove duplicates tuples case-insensitive, e.g. [(("Hallo", ""), "hallo", "")] -> [("Hallo", "")]
		result, seen = [], set()
		for item in items:
			key = tuple(value.strip().casefold() if isinstance(value, str) else value for value in item)
			if key not in seen:
				seen.add(key)
				result.append(item)
		return result

	def scan_path_diagnostics(self, scan_paths, count_files=False, checkpoint=None):
		from os import walk
		from os.path import isdir
		result = {
			"success": True,
			"count_files": bool(count_files),
			"valid_count": 0,
			"invalid_count": 0,
			"video_files": 0,
			"supported_media_files": 0,
			"ts_recordings": 0,
			"media_files": 0,
			"ignored_files": 0,
			"ignored_by_extension": {},
			"errors": [],
			"paths": []
		}
		for item in scan_paths:
			if checkpoint and callable(checkpoint):
				try:
					checkpoint()
				except Exception:
					pass
			path = item.get("path", "") if isinstance(item, dict) else str(item or "")
			mode = safe_int(item.get("mode", 0), 0) if isinstance(item, dict) else 0
			recursive = bool(item.get("recursive", True)) if isinstance(item, dict) else True
			entry = {
				"path": path,
				"mode": mode,
				"mode_label": self.path_mode_label(mode),
				"recursive": recursive,
				"exists": exists(path),
				"is_dir": isdir(path),
				"valid": bool(path and mode != 0 and exists(path) and isdir(path)),
				"reason": "",
				"video_files": 0,
				"supported_media_files": 0,
				"ts_recordings": 0,
				"media_files": 0,
				"ignored_files": 0,
				"ignored_by_extension": {},
				"errors": []
			}
			if not path:
				entry["reason"] = "empty path"
			elif mode == 0:
				entry["reason"] = "excluded"
			elif not exists(path):
				entry["reason"] = "missing"
			elif not isdir(path):
				entry["reason"] = "not a directory"
			elif count_files:
				def _onerror(err):
					message = str(err)
					entry["errors"].append(message)
					result["errors"].append({"path": path, "error": message})
				try:
					for root, dirs, files in walk(path, onerror=_onerror):
						if checkpoint and callable(checkpoint):
							try:
								checkpoint()
							except Exception:
								pass
						dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS and not name.startswith(".")]
						for filename in files:
							full_path = join(root, filename)
							if self.is_known_media_file(full_path):
								entry["video_files"] += 1
								entry["supported_media_files"] += 1
								if self.has_sidecar_infos(full_path):
									entry["ts_recordings"] += 1
								else:
									entry["media_files"] += 1
							else:
								entry["ignored_files"] += 1
								ext = self.media_extension(full_path) or "<none>"
								entry["ignored_by_extension"][ext] = entry["ignored_by_extension"].get(ext, 0) + 1
						if not recursive:
							dirs[:] = []
				except Exception as err:
					message = str(err)
					entry["errors"].append(message)
					result["errors"].append({"path": path, "error": message})
			if entry["valid"]:
				result["valid_count"] += 1
			else:
				result["invalid_count"] += 1
			for key in ("video_files", "supported_media_files", "ts_recordings", "media_files", "ignored_files"):
				result[key] += entry[key]
			for ext, count in entry["ignored_by_extension"].items():
				result["ignored_by_extension"][ext] = result["ignored_by_extension"].get(ext, 0) + count
			result["paths"].append(entry)
		return result

	def iter_media_files(self, scan_paths, checkpoint=None):
		from os import walk
		from os.path import isdir
		for item in scan_paths:
			root_path = item["path"]
			recursive = item.get("recursive", True)
			if not isdir(root_path):
				continue
			for root, dirs, files in walk(root_path):
				if checkpoint and callable(checkpoint):
					try:
						checkpoint()
					except Exception:
						pass
				dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS and not name.startswith(".")]
				for filename in files:
					media_path = join(root, filename)
					if self.is_known_media_file(media_path):
						yield media_path, item
				if not recursive:
					dirs[:] = []

	def collect_media_files(self, scan_paths, checkpoint=None):
		return list(self.iter_media_files(scan_paths, checkpoint=checkpoint))

	def native_parser_required_missing(self, files):
		# The backend scanner no longer requires the old native C EIT parser.
		# TS recordings are parsed through E2MDBRecordingParser.py from Python.
		return False

	def native_parser_missing_message(self):
		return f"E2MDBBackendMetadataScanner Python META/EIT/CUTS parser is unavailable: {self.recording_parser_error}"

	def scan_media_file(self, media_path, path_item):
		if self.parse_recording_func is None:
			sc_parsed = {"path": media_path, "parse_error": self.native_parser_missing_message()}
		else:
			try:
				sc_parsed = self.parse_recording_func(media_path)
			except Exception as err:
				sc_parsed = {"path": media_path, "parse_error": str(err)}
			self.last_parsed = (media_path, sc_parsed)
		item = self.build_scan_item(media_path, path_item, sc_parsed)
		item["mediadb"] = self.upsert_mediadb(item)
		return item

	def build_scan_item(self, media_path, path_item, sc_parsed={}):
		from os.path import getmtime, getsize
		has_sidecar_infos = self.has_sidecar_infos(media_path)
		filename_title = self.clean_openatv_recording_title(media_path) if has_sidecar_infos else self.clean_title_from_filename(media_path)
		if sc_title := self.get_sidecar_title(media_path):  # has sidecar title?
			sc_title = self.clean_openatv_recording_title(sc_title).strip()  # then clean and use it
		title = sc_title or filename_title
		size_bytes = getsize(media_path) if isfile(media_path) else 0
		mtime = safe_int(getmtime(media_path), 0) if isfile(media_path) else 0
		recorded_at = safe_int(sc_parsed.get("recorded_at"), 0)
		duration_seconds = safe_int(sc_parsed.get("duration_seconds"), 0)
		path_mode = safe_int(path_item.get("mode", 0), 0)
		name_info = self.parse_media_name_for_scan(media_path, path_item, title)
		if has_sidecar_infos:
			filename_info = self.recording_name_info_from_clean_title(filename_title, path_mode)
			if filename_info.get("media_type") in ("movie", "series", "anime_series", "manga_series", "anime_movie", "manga_movie"):
				for key, value in filename_info.items():  # fill up 'name_info'
					if key not in name_info or not name_info.get(key):
						name_info[key] = value
		estimated_media_type = name_info.get("media_type", "") or self.media_type_from_path_mode(path_mode, title=title, path=media_path)
		if special_media_type := self.resolve_special_media_type(media_path):  # is a special mediatype?
			estimated_media_type = special_media_type  # then use it
		season_no = safe_int(name_info.get("season_no"), 0)
		episode_no = safe_int(name_info.get("episode_no"), 0)
		separator, split_desc = "", ""
		sc_short_desc = sc_parsed.get("short_desc", "").strip()
		sc_extended = sc_parsed.get("extended_desc", "").strip()
		if not season_no and not episode_no:
			# No explicit S/E marker to match an episode by name against the provider's episode index
			# split the raw title on a guessed separator instead (e.g. "Show_Episode.mp4" -> "Show" + "Episode"),
			season_no, episode_no = self.parse_season_episode_text(" ".join([media_path, title, sc_short_desc]))
			separator, replacement = guess_separator(title, EPGTYPE_SEPAS if has_sidecar_infos else FOREIGN_SEPAS)
			if separator:
				split_title, split_desc = self.divide_file_base_infos(title, separator)
				if split_desc:
					if not name_info.get("series_title"):
						name_info["series_title"] = f"{split_title}{replacement.strip()}" if replacement else split_title
		series_title = name_info.get("series_title", "").strip()
		movie_title = name_info.get("movie_title", "").strip()
		if estimated_media_type in ("series", "anime_series", "manga_series"):
			if not series_title:
				series_title = self.clean_series_title(title or media_path)
			provider_title = series_title
		else:
			provider_title = movie_title or title
		if has_sidecar_infos:
			sc_title, sc_path = sc_parsed.get("title", ""), sc_parsed.get("path", "")
			if not sc_title:
				# e.g. '/media/hdd/movie/20260118 2012 - ZDF HD - Wunderschön! Der Mont Blanc.ts' -> 'Wunderschön! Der Mont Blanc'
				sc_title = splitext(basename(sc_path).split(" - ")[-1])[0]
			search_candidates, episode_title = self.create_search_titles(sc_title, sc_path)
		else:
			search_title = filename_title if separator and split_desc else (provider_title or title)
			search_candidates, episode_title = self.create_search_titles(search_title, media_path)
#		main_title, episode_title = self.create_search_titles(filename_title, media_path)
		for search_title in self.unique_str_list((filename_title, provider_title, series_title, movie_title, title)):
			search_titles, epi_title = self.create_search_titles(search_title, media_path)
			if not episode_title:
				episode_title = epi_title
			search_candidates.extend(search_titles)
		search_candidates = self.unique_tuples_list(search_candidates)  # remove duplicates case-insensitive
		# e.g. search_candidates = [('Wunderschön', ''), ('Wunderschön!', '')], tuple = ("Title", f"{year (if available)}"))
		scanner_used = "E2MDBBackendMetadataScanner.metadata_sidecar_parser" if has_sidecar_infos else "E2MDBBackendMetadataScanner.media_name_parser"
		parse_error = sc_parsed.get("parse_error", "")
		return {
			"id": self.make_recording_id(media_path),
			"version": 1,
			"type": has_sidecar_infos,  # TODO: Doppeltgemoppelt! Sollte rausfliegen
			"source_type": has_sidecar_infos,
			"scanner_used": scanner_used,
			"metadata_scanner": scanner_used,
			"path_mode": path_mode,
			"path_mode_label": self.path_mode_label(path_mode),
			"media_family": self.mode_family_from_path_mode(path_mode),
			"estimated_media_type": estimated_media_type,
			"provider_media_type": estimated_media_type,
			"series_title": series_title,
			"episode_title": episode_title,
			"movie_title": movie_title,
			"provider_title": provider_title,
			"name_parser": name_info,
			"year": safe_int(name_info.get("year"), 0),
			"season_no": season_no,
			"episode_no": episode_no,
			"path": media_path,
			"folder": dirname(media_path),
			"name": basename(media_path),
			"extension": splitext(media_path)[1].lower(),
			"size_bytes": size_bytes,
			"mtime": mtime,
			"mtime_iso": self.iso_from_timestamp(mtime),
			"mode": path_mode,
			"recursive": bool(path_item.get("recursive", True)),
			"title": title,
			"short_desc": sc_short_desc,
			"extended_desc": sc_extended,
			"manual_metadata": sc_parsed.get("manual_metadata"),
			"service_ref": sc_parsed.get("service_ref", ""),
			"recorded_at": recorded_at,
			"recorded_at_iso": self.iso_from_timestamp(recorded_at),
			"duration_seconds": duration_seconds,
			"search_candidates": search_candidates,
			"parse_error": parse_error,
			"scan_status": "error" if parse_error else "ok"
		}
