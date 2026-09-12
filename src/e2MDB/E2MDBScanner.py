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
from gc import collect
from difflib import SequenceMatcher
from os import stat, walk
from os.path import abspath, exists, join, normpath, split, splitext, isfile, dirname, basename
from re import search, IGNORECASE, sub, escape
from struct import unpack
try:
	from twisted.internet.reactor import callInThread
except Exception:
	def callInThread(func, *args, **kwargs):
		return func(*args, **kwargs)

# ENIGMA IMPORTS
try:
	from enigma import eServiceCenter, eServiceReference, iServiceInformation
except Exception:
	eServiceCenter = None
	eServiceReference = None
	iServiceInformation = None
try:
	from Components.config import config
except Exception:
	class _DummyConfigNode:
		value = False

		def __getattr__(self, name):
			return self

	class _DummyConfig:
		plugins = _DummyConfigNode()
	config = _DummyConfig()

# PLUGIN IMPORTS
try:
	from . import write_log, _, e2mdbglobals
except Exception:
	def write_log(*args):
		try:
			print(" ".join(str(arg) for arg in args))
		except Exception:
			pass

	def _(text):
		return text

	class _DummyGlobals:
		pass
	e2mdbglobals = _DummyGlobals()
try:
	from .E2MDBProviders import providers
except Exception:
	try:
		from E2MDBProviders import providers
	except Exception:
		providers = None
try:
	from .E2MDBDatabase import mediadb, resultsdb
except Exception:
	try:
		from E2MDBDatabase import mediadb, resultsdb
	except Exception:
		class _DummyDB:
			def __getattr__(self, name):
				def _missing(*args, **kwargs):
					return None
				return _missing
		mediadb = _DummyDB()
		resultsdb = _DummyDB()
try:
	from .E2MDBHelper import E2MDBHelper
except Exception:
	try:
		from E2MDBHelper import E2MDBHelper
	except Exception:
		class E2MDBHelper:
			pass
try:
	from .E2MDBTranslator import translate_title_for_search
except Exception:
	try:
		from E2MDBTranslator import translate_title_for_search
	except Exception:
		def translate_title_for_search(title, *args, **kwargs):
			return title
try:
	from .MediaNameParser import MediaNameParser
except Exception:
	try:
		from MediaNameParser import MediaNameParser
	except Exception:
		MediaNameParser = None

try:
	from .StubInfo import justStubInfo
except Exception:
	try:
		from StubInfo import justStubInfo
	except Exception:
		justStubInfo = None
try:
	from .provider.Consts import Fields
except Exception:
	try:
		from provider.Consts import Fields
	except Exception:
		class Fields:
			PROVIDER = "provider"
			TITLE = "title"
			PROVIDER_IDS = "provider_ids"
			SERIES_ID = "series_id"
			SEASON_NO = "season_no"


class E2MDBScanner(E2MDBHelper):
	MODULE_NAME = "[E2MDBScanner]"
	PATH_MODE_MOVIE = 1
	PATH_MODE_SERIES = 2
	PATH_MODE_MOVIE_SERIES = 3
	PATH_MODE_ANIME_SERIES = 4
	PATH_MODE_MANGA_SERIES = 5
	PATH_MODE_ANIME_MOVIE = 6
	PATH_MODE_MANGA_MOVIE = 7
	PATH_MODES_SERIES = (PATH_MODE_SERIES, PATH_MODE_ANIME_SERIES, PATH_MODE_MANGA_SERIES)
	PATH_MODES_MOVIE = (PATH_MODE_MOVIE, PATH_MODE_ANIME_MOVIE, PATH_MODE_MANGA_MOVIE)
	PATH_MODES_ANIME = (PATH_MODE_ANIME_SERIES, PATH_MODE_ANIME_MOVIE)
	PATH_MODES_MANGA = (PATH_MODE_MANGA_SERIES, PATH_MODE_MANGA_MOVIE)

	def normalize_path_mode(self, path_mode):
		"""Normalize saved path mode values from JSON/config selections."""
		try:
			return int(path_mode)
		except (TypeError, ValueError):
			return 0

	def normalize_folder_key(self, folder_name):
		return MediaNameParser.normalize_folder_name(folder_name)

	def clean_media_title(self, title):
		return MediaNameParser.clean_media_title(title)

	def is_ignored_library_folder(self, folder_name, extra_folder_names=None):
		return MediaNameParser.is_ignored_library_folder(folder_name, extra_folder_names if extra_folder_names is not None else self.get_ignored_folder_names())

	def make_media_name_parser(self, library_path=None, mode=2):
		return MediaNameParser(library_path=library_path, mode=mode, ignored_folders=self.get_ignored_folder_names())

	def resolve_parser_library_path(self, selected_dir, org_path, mode=2):
		"""Resolve the library root for series and season folder scans."""
		selected_dir = normpath(str(selected_dir or ""))
		org_path = normpath(str(org_path or ""))
		if not selected_dir or mode != 2:
			return selected_dir
		base = basename(selected_dir)
		if self.is_ignored_library_folder(base) and search(r"^(staffel|season|saison|temporada|seizoen|stagione|s[aeä]song|sezon|sezona)\s*\d+$|^s\d{1,2}$", self.normalize_folder_key(base), IGNORECASE):
			return dirname(dirname(selected_dir))
		try:
			relative = org_path[len(selected_dir):].lstrip("/") if org_path.startswith(selected_dir) else ""
		except Exception:
			relative = ""
		relative_parts = [part for part in relative.split("/") if part]
		if relative_parts:
			first_rel = relative_parts[0]
			# If the selected directory is already the show folder, use its parent as parser root.
			if self.is_ignored_library_folder(first_rel) and not self.is_ignored_library_folder(base):
				return dirname(selected_dir)
		elif not self.is_ignored_library_folder(base):
			# Direct scan of a show folder with files in its root.
			return dirname(selected_dir)
		return selected_dir

	def title_suggests_episode(self, org_title, org_path=""):
		"""Return True if the filename/path contains a common episode marker."""
		text = f"{org_title or ''} {basename(str(org_path or ''))}"
		return bool(search(r"(?:^|[\s._\-\[\(])s\d{1,4}[\s._\-]*e\d{1,3}\b|(?:^|[\s._\-])\d{1,2}x\d{1,3}\b", text, IGNORECASE))

	def normalize_provider_search_title(self, search_title, org_path=""):
		"""Normalize parser/file titles before provider lookup while keeping EPG titles untouched."""
		search_title = str(search_title or "").strip()
		if not search_title:
			return ""
		if ".ts" in str(org_path or ""):
			return search_title
		return self.clean_media_title(search_title)

	def append_search_variant(self, variants, seen, title, year="", org_path=""):
		"""Append one provider search variant, including a cleaned separator variant if needed."""
		for candidate in (title, self.normalize_provider_search_title(title, org_path)):
			candidate = str(candidate or "").strip()
			if not candidate:
				continue
			key = (candidate.lower(), str(year or ""))
			if key in seen:
				continue
			seen.add(key)
			variants.append((candidate, year))

	def get_title_fallback_search_title(self, title, org_path=""):
		"""Translate a title only for a one-shot provider search retry."""
		base_title = self.normalize_provider_search_title(title, org_path)
		fallback_title = self.normalize_provider_search_title(translate_title_for_search(base_title), org_path)
		if not fallback_title or fallback_title.casefold() == base_title.casefold():
			return ""
		return fallback_title

	def append_title_fallback_search_variant(self, variants, seen, title, year="", org_path=""):
		fallback_title = self.get_title_fallback_search_title(title, org_path)
		if not fallback_title:
			return ""
		self.append_search_variant(variants, seen, fallback_title, year, org_path)
		return fallback_title

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
	season_keys = [
		_("season"),  # localized
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
		_("episode"),  # localized
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

	def __init__(self, language):
		self.language = language
		self.scanActive, self.scanStop = False, False
		self.skin_progress = None
		self.callback = None

	def get_ignored_folder_names(self):
		ignored = []
		try:
			from .E2MDBIgnoreConfig import E2MDBIgnorePatterns
			ignored += E2MDBIgnorePatterns.parse(E2MDBIgnorePatterns.FOLDER_NAME)
		except Exception:
			pass
		return ignored

	def _pathHasFolderHint(self, org_path, hints):
		try:
			path_parts = [part for part in normpath(org_path).split("/") if part]
		except Exception:
			path_parts = []
		for part in path_parts[:-1]:
			part_key = self.normalize_folder_key(part)
			if part_key in hints:
				return True
		return False

	def path_suggests_series(self, org_path):
		"""Return True if any path segment is a known series/category folder."""
		return self._pathHasFolderHint(org_path, self.SERIES_FOLDER_HINTS)

	def path_suggests_movie(self, org_path):
		"""Return True if any path segment clearly indicates a movie/cinema library."""
		return self._pathHasFolderHint(org_path, self.MOVIE_FOLDER_HINTS)

	def path_suggests_anime(self, org_path):
		"""Return True if any path segment clearly indicates an anime library."""
		return self._pathHasFolderHint(org_path, self.ANIME_FOLDER_HINTS)

	def path_suggests_manga(self, org_path):
		"""Return True if any path segment clearly indicates a manga/comic library."""
		return self._pathHasFolderHint(org_path, self.MANGA_FOLDER_HINTS)

	def resolve_special_media_type(self, org_path, path_mode):
		"""Resolve explicit and folder-name based Anime/Manga modes before generic provider search."""
		path_mode = self.normalize_path_mode(path_mode)
		if path_mode == self.PATH_MODE_MANGA_SERIES:
			return "manga_series", "manga-series-path"
		if path_mode == self.PATH_MODE_MANGA_MOVIE:
			return "manga_movie", "manga-movie-path"
		if path_mode == self.PATH_MODE_ANIME_SERIES:
			return "anime_series", "anime-series-path"
		if path_mode == self.PATH_MODE_ANIME_MOVIE:
			return "anime_movie", "anime-movie-path"
		if self.path_suggests_manga(org_path):
			if self.path_suggests_movie(org_path):
				return "manga_movie", "manga-movie-path"
			return "manga_series" if self.path_suggests_series(org_path) else "manga", "manga-path"
		if self.path_suggests_anime(org_path):
			if self.path_suggests_movie(org_path):
				return "anime_movie", "anime-movie-path"
			return "anime_series" if self.path_suggests_series(org_path) else "anime", "anime-path"
		return "", ""

	def preferSeriesSearch(self, org_path, path_mode=None):
		"""Prefer strict series matching in explicit or clearly series-like folders."""
		path_mode = self.normalize_path_mode(path_mode)
		if path_mode in self.PATH_MODES_SERIES:
			return True
		if path_mode in self.PATH_MODES_MOVIE:
			return False
		if self.path_suggests_anime(org_path) or self.path_suggests_manga(org_path):
			return self.path_suggests_series(org_path)
		return self.path_suggests_series(org_path)

	def _clean_foreign_title_part(self, text):
		text = str(text or "").replace("_", " ").strip(" ._-–:")
		text = sub(r"\s+", " ", text).strip()
		return text

	def _is_probable_episode_suffix(self, series_title, episode_title):
		series_title = self._clean_foreign_title_part(series_title)
		episode_title = self._clean_foreign_title_part(episode_title)
		if len(series_title) < 8 or len(episode_title) < 3:
			return False
		if self.is_ignored_library_folder(series_title):
			return False
		series_words = [word for word in series_title.replace(".", " ").split() if word]
		if len(series_words) < 2:
			return False
		if search(r"^(?:19|20)\d{2}$", episode_title):
			return False
		if self.is_ignored_library_folder(episode_title):
			return False
		return True

	def split_foreign_episode_title(self, org_title):
		"""Split common foreign-recording episode filenames into series title and episode text."""
		base_title = splitext(org_title)[0].strip()
		if not base_title:
			return "", "", ""
		# Examples: "Kevin Costner's The West 8. Kampf der Rinder-Barone" -> series + episode no/title
		numbered = search(r"^(.+?)\s+(\d{1,3})\.\s+(.+)$", base_title)
		if numbered:
			series_title = self._clean_foreign_title_part(numbered.group(1))
			episode_text = self._clean_foreign_title_part(f"{numbered.group(2)}. {numbered.group(3)}")
			if self._is_probable_episode_suffix(series_title, episode_text):
				return series_title, episode_text, f"E{int(numbered.group(2)):02d}"
		# Examples: "Wir waren wie Brüder-Bastogne" -> series + episode title.
		# Do not apply this in movie-only folders; the caller decides when series context is strong enough.
		hyphen = search(r"^(.+?)-([^-]+)$", base_title)
		if hyphen:
			series_title = self._clean_foreign_title_part(hyphen.group(1))
			episode_text = self._clean_foreign_title_part(hyphen.group(2))
			if self._is_probable_episode_suffix(series_title, episode_text):
				return series_title, episode_text, "episode-title"
		return "", "", ""

	def _clean_movie_recording_part(self, text):
		text = splitext(str(text or "").strip())[0]
		text = text.replace("_", " ").strip(" ._-–:")
		text = sub(r"\s+", " ", text).strip()
		return text

	def extract_recording_movie_title(self, org_title):
		"""Extract the real movie title from Enigma2/PVR recording filenames."""
		base_title = splitext(basename(str(org_title or "")))[0].strip()
		if not base_title:
			return "", ""
		# Examples: "20220805 2134 - Sender HD DE - House of Gucci" -> "House of Gucci".
		if not search(r"^\s*(?:\d{8}|\d{4}[._-]\d{2}[._-]\d{2}|\d{2}[._-]\d{2}[._-]\d{4})\s+\d{3,4}\b", base_title):
			return "", ""
		normalized = base_title.replace(" – ", " - ").replace(" | ", " - ")
		parts = [self._clean_movie_recording_part(part) for part in normalized.split(" - ") if self._clean_movie_recording_part(part)]
		if len(parts) < 2:
			return "", ""
		first_part = parts[0]
		if not search(r"^\s*(?:\d{8}|\d{4}[._-]\d{2}[._-]\d{2}|\d{2}[._-]\d{2}[._-]\d{4})\s+\d{3,4}\b", first_part):
			return "", ""
		movie_title = parts[-1].strip()
		if not movie_title or movie_title.isdigit() or self.is_ignored_library_folder(movie_title):
			return "", ""
		if search(r"^(?:19|20)\d{6}\s+\d{3,4}$", movie_title):
			return "", ""
		recording_info = " - ".join(part for part in parts[1:-1] if part)
		return movie_title, recording_info

	def title_scanner(self, paths, callback=None, skin_progress=None, quickscan=True, start_callback=None):  # threaded
		def upsert_db():
			record = {
				"path": file_dir,
				"name": file_base,
				"ref": serviceref.toString(),
				"title": org_title,
				"short": short_desc,
				"extended": ext_desc,
				"tags": tags,
				"duration": duration,
				"begin": begin,
				"size": size
			}
			mediadb.upsert(record)

		def progress_status():
			if self.skin_progress and not self.scanStop:
				header = f"{_('Scanning:')} '{file_dir}'"
				sub_line = f"{_('Processing:')} '{splitext(org_title)[0]}'"   # remove all extensions (e.g. '.mp4')
				status = f"{_('Total')}: {total_no} | {_('Ready')}: {index} | {_('Successful')}: {len(success_list)} | {_('Failed')}: {len(failure_list)} | {_('Duration')}: {duration}"
				self.skin_progress(header=header, progress=index, sub_line=sub_line, status=status)

		def iter_service_list(fast_scan=False):
			desc, short_desc, ext_desc = "", "", ""
			servicehandler = eServiceCenter.getInstance()
			seen = set()  # to avoid duplicates in case of nested folders. if a folder is already scanned, all its subfolders are automatically included and don't need to be scanned separately.
			excluded_dirs = []
			for pathObj in paths:
				if pathObj.mode == 0:
					excluded_dirs.append(pathObj.path)

			for pathObj in paths:
				if pathObj.mode == 0:
					continue
				exclude = False
				for excluded_dir in excluded_dirs:
					if pathObj.path.startswith(excluded_dir):
						exclude = True
						break
				if exclude:
					continue
				subdirs = []
				if self.scanStop:
					break
				directory = abspath(pathObj.path)
				if directory not in seen:
					subdirs.append((directory, pathObj.mode))
					seen.add(directory)
				if pathObj.recursive:  # if recursive is enabled, add bit 3 to mode (e.g. 0 -> 4, 1 -> 5, 2 -> 6), otherwise keep bit 3 unset (e.g. 0 -> 0, 1 -> 1, 2 -> 2)
					for root, dirs, files in walk(directory):
						for subdir in dirs:
							fullpath = join(root, subdir)
							if fullpath not in seen:
								subdirs.append((fullpath, pathObj.mode))
								seen.add(fullpath)

				for selected_sub_dir, mode in subdirs:
					exclude = False
					for excluded_dir in excluded_dirs:
						if selected_sub_dir.startswith(excluded_dir):
							exclude = True
							break
					if exclude:
						continue
					if self.scanStop:
						break
					root = eServiceReference(f"{e2mdbglobals.MOVIE_LIST_SREF_ROOT}{selected_sub_dir}/")
					reflist = root and servicehandler.list(root)
					if reflist is None:
						write_log(f"{self.MODULE_NAME} Listing of movies failed")
						return
					write_log(f"{self.MODULE_NAME} Scanning directory: {normpath(root.getPath())}")
					while True:
						serviceref = reflist.getNext()
						if self.scanStop or not serviceref.valid():
							break
						info = servicehandler.info(serviceref)
						if info is None:
							info = justStubInfo
						if serviceref.flags & eServiceReference.mustDescent:
							continue
						org_title = info.getName(serviceref)
						if org_title.startswith("."):
							continue
						if fast_scan:
							yield (serviceref)
							continue
						event = info.getEvent(serviceref)
						short_desc = event and event.getShortDescription() or ""
						desc = info.getInfoString(serviceref, iServiceInformation.sDescription)
						ext_desc = event and event.getExtendedDescription() or ""
						begin = info.getInfo(serviceref, iServiceInformation.sTimeCreate)
						tags = info.getInfoString(serviceref, iServiceInformation.sTags)
						org_path = serviceref.getPath()
						size = self.get_file_size(org_path)
						duration = info.getLength(serviceref)
						if duration < 0:
							duration = self.get_media_length(f"{org_path}.cuts")
						yield (serviceref, org_title, org_path, desc, short_desc, ext_desc, begin, tags, size, duration, directory, mode)

		def createStatsEntry(org_title, search_title, org_path, estimated_type, match_reason, desc="", short_desc="", ext_desc=""):
			return {
				"title": org_title,
				"search_title": search_title,
				"media_path": org_path,
				"estimated_type": estimated_type,
				"match_reason": match_reason,
				"short_desc": short_desc[:512] if short_desc else "",
				"desc": desc[:512] if desc else "",
				"ext_desc": ext_desc[:512] if ext_desc else ""
			}

		def db_row_has_display_metadata(row):
			if not isinstance(row, dict):
				return False
			for key in (
				"metadata_title", "metadata_subtitle", "metadata_overview", "metadata_genres",
				"metadata_provider", "metadata_media_type", "metadata_cover_path",
				"metadata_backdrop_path", "metadata_logo_path", "metadata_image_path",
				"metadata_released", "metadata_cast", "metadata_crew"
			):
				if str(row.get(key) or "").strip():
					return True
			return False

		# start title_scanner
		self.scanActive = True
		self.skin_progress = skin_progress
		self.callback = callback
		if start_callback:
			start_callback()
		use_mediadb = config.plugins.e2mdb.enableDatabase.value
		seconds = 0
		total_no = len(list(iter_service_list(fast_scan=True) or []))
		success_list, failure_list = [], []
		start_time_dt = datetime.now(tz=None)
		if skin_progress and not self.scanStop:
			skin_progress(range=(0, total_no), show=True)

		for index, (serviceref, org_title, org_path, desc, short_desc, ext_desc, begin, tags, size, duration, selected_dir, path_mode) in enumerate(iter_service_list() or []):  # collect all medias to be scanned
			if self.scanStop:
				break
			results_dict, final_dict = None, None
			file_dir, file_base = split(org_path)
			seconds = (datetime.now(tz=None) - start_time_dt).seconds
			duration = f"{seconds // 60:02d}:{seconds % 60:02d} min"
			progress_status()
			# phase #1: create alternative titles and try to get any results in norm_dicts
			# The primary data JSON is debug output only. Existing display metadata is
			# reused from SQLite so TS/movie recordings never use JSON for UI/cache hits.
			org_hash = self.get_reduced_org_hash(org_path)
			try:
				resultsdb.add_media(org_hash, dirname(org_path), basename(org_path), org_title)
			except Exception as err:
				write_log(f"{self.MODULE_NAME} ERROR storing media identity for '{org_title}': {err}")
			try:
				media_row = resultsdb.get_media_metadata(org_hash) or {}
			except Exception:
				media_row = {}
			if db_row_has_display_metadata(media_row):
				final_dict = resultsdb.get_media_display_data(org_hash) or {}
				best_search_list = createStatsEntry(org_title, final_dict.get("title") or org_title, org_path, final_dict.get("media_type", ""), "db", desc, short_desc, ext_desc)
				success_list.append(best_search_list)
				write_log(f"{self.MODULE_NAME} Existing media display metadata loaded from DB for '{org_title}'")
			else:
				ep_details = None  # default: don't use MediaNameParser
				path_mode_int = self.normalize_path_mode(path_mode)
				if path_mode_int in self.PATH_MODES_SERIES or (path_mode_int == self.PATH_MODE_MOVIE_SERIES and (self.path_suggests_series(org_path) or self.title_suggests_episode(org_title, org_path))):
					ep_details = self.make_media_name_parser(library_path=self.resolve_parser_library_path(selected_dir, org_path, mode=2), mode=2).parse(org_path)
				elif path_mode_int in self.PATH_MODES_MOVIE:

					# TODO: IF TS and recording name then split the name using extract_recording_movie_title and use the result as search title. This is especially important for movies recorded via EPG, which often have a lot of additional info in the filename but no episode details. The MediaNameParser is not designed to handle this kind of filename, so it should be bypassed in favor of direct extraction of the movie title.

					ep_details = self.make_media_name_parser(library_path=selected_dir, mode=1).parse(org_path)
				if ep_details and ep_details.success:  # movie or episode details have already been identified
					print(f"{self.MODULE_NAME} Parsed movie or episode details for '{org_path}': {ep_details}")
				results_dict, best_search_list = self.get_search_results(org_path, org_title, short_desc, desc, ext_desc, quickscan, ep_details, path_mode=path_mode)
				if not results_dict:
					failure_list.append(best_search_list)
					continue  # finish search of current title
				try:  # Store results in database
					org_hash = self.get_reduced_org_hash(org_path)
					media_id = resultsdb.add_media(org_hash, dirname(org_path), basename(org_path), org_title)
					if media_id:
						resultsdb.clear_results_for_media(media_id)
						resultsdb.add_results_from_json(media_id, results_dict)
					write_log(f"{self.MODULE_NAME} Results stored in database for '{org_title}'")
				except Exception as e:
					write_log(f"{self.MODULE_NAME} Error storing results in database: {e}")
				# phase #2: go through results in results_dict and find best match. In case a series was found,
				# create seriesData (inkl. pictures), create seasonData (incl. pictures),
				# create episodeData (incl. pictures) and create seriesEpisode index
				final_dict, search_marker = self.create_final_dict(results_dict, org_title, org_path, ext_desc)
				if not final_dict:
					failure_list.append(best_search_list)
					write_log(f"{self.MODULE_NAME} No matching entries found for '{org_title}'")
					continue  # finish search of current title
				final_title = final_dict.get(Fields.TITLE, "")
				write_log(f"{self.MODULE_NAME} Final result for '{final_title}': FinalDict: {final_dict}")
				success_list.append(best_search_list)
				all_results = {}  # combine dicts in list, final_dict first in line
				cleaned_results = []
				for result_item in results_dict.get("results", []):
					if isinstance(result_item, dict):
						cleaned_results.append({key: value for key, value in result_item.items() if not key.startswith("_")})
				all_results["results"] = [final_dict] + cleaned_results
				all_results["search_data"] = results_dict.get("search_data", [])
				results_path = self.get_primary_datapath(org_path, data_type="results")
				err_msg = self.write_json_file(all_results, results_path)  # also write even if results_dict is empty
				if err_msg:
					write_log(f"{self.MODULE_NAME} ERROR in module 'title_scanner': Results could not be saved: {err_msg}")
				else:
					write_log(f"{self.MODULE_NAME} Results saved for '{org_title}'")
			# phase #3: picking all images from final result and distribute them to primary or secondary cache folders
			try:
				resultsdb.add_media(org_hash, dirname(org_path), basename(org_path), org_title)
			except Exception as err:
				write_log(f"{self.MODULE_NAME} ERROR storing media identity for '{org_title}': {err}")
			pvr_name = final_dict.get(Fields.PROVIDER, "")
			series_id = final_dict.get(Fields.SERIES_ID, "")
			season_no = final_dict.get(Fields.SEASON_NO, "")
			for pic_type in ("cover", "backdrop", "titlelogo", "image"):
				if self.scanStop:
					break
				pic_url = str(final_dict.get(f"{pic_type}_url", "") or "")
				if pic_url.startswith(("http://", "https://", "//")):
					pic_path = self.get_artwork_cache_path(org_path, final_dict, pic_type, url=pic_url)
					if pic_path:
						final_dict = self.set_dict_key(final_dict, f"{pic_type}_path", self.get_reduced_cache_path(pic_path))
						if not exists(pic_path):
							write_log(f"{self.MODULE_NAME} Downloading {pic_type}: '{pic_url}' to '{pic_path}'")
							callInThread(self.image_download, pic_url, pic_path, fail=lambda error: write_log(f"{self.MODULE_NAME} ERROR in module 'createServiceList': {error}"))  # download + store image
			# phase #4: write final result and mirror display data to SQLite
			self.write_json_file(final_dict, self.get_primary_datapath(org_path))
			try:
				updated = resultsdb.update_media_metadata(org_hash, final_dict)
				write_log(f"{self.MODULE_NAME} Media display metadata stored in DB for '{org_title}' rows={updated}")
			except Exception as err:
				write_log(f"{self.MODULE_NAME} ERROR storing media display metadata for '{org_title}': {err}")
			try:
				resultsdb._mark_browser_cache_dirty()
			except Exception:
				pass
			if use_mediadb:
				upsert_db()
			write_log(f"{self.MODULE_NAME} Service: {org_title}, Path: {basename(org_path)}, Description: {desc}, Short Description: {short_desc}, Extended Description: {ext_desc}")
			results_dict, final_dict = None, None
			collect()
		canceled = bool(self.scanStop)
		self.write_scan_statistics(success_list, failure_list, start_time_dt, seconds)
		if self.skin_progress and not canceled:
			self.skin_progress(header="", progress=-1, sub_line="", status="", show=False)
		self.scanActive, self.scanStop = False, False
		if self.callback:
			self.callback(canceled)

	def get_search_results(self, org_path, org_title, short_desc, desc, ext_desc, quickscan, ep_details=None, path_mode=None, search_title_override=None, use_title_translation=True):
		results_dict, results = {}, []
		new_desc = ""
		path_mode = self.normalize_path_mode(path_mode)
		special_media_type, special_match_reason = self.resolve_special_media_type(org_path, path_mode)
		prefer_series = self.preferSeriesSearch(org_path, path_mode)
		parser_success = bool(ep_details and getattr(ep_details, "success", False))
		parsed_movie = parser_success and path_mode in self.PATH_MODES_MOVIE and getattr(ep_details, "movie_name", "")
		parsed_episode = parser_success and (path_mode in self.PATH_MODES_SERIES or (path_mode == self.PATH_MODE_MOVIE_SERIES and not getattr(ep_details, "movie_name", "")))
		if parsed_movie:
			search_title = self.normalize_provider_search_title(getattr(ep_details, "movie_name", "") or org_title, org_path)
			new_desc = ""
			if getattr(ep_details, "year", ""):
				new_desc = str(getattr(ep_details, "year", ""))
			estimated_type, match_reason = "movie", new_desc
		elif parsed_episode:  # series and episode details have already been identified
			# English comment: MediaNameParser.ParsedEpisodeInfo does not always expose "series_title".
			# Keep this defensive so a parser result can never abort the full scanner thread.
			search_title = (
				getattr(ep_details, "series_title", "")
				or getattr(ep_details, "series_name", "")
				or getattr(ep_details, "show_title", "")
				or getattr(ep_details, "title", "")
				or getattr(ep_details, "name", "")
			)
			write_log("#####ep_details.series_title:", getattr(ep_details, "series_title", ""))
			write_log("#####ep_details.series_name :", getattr(ep_details, "series_name", ""))
			write_log("#####ep_details.show_title  :", getattr(ep_details, "show_title", ""))
			write_log("#####ep_details.title       :", getattr(ep_details, "title", ""))
			write_log("#####ep_details.name        :", getattr(ep_details, "name", ""))
			search_title = self.normalize_provider_search_title(search_title, org_path)
			if search_title and not self.is_ignored_library_folder(search_title):
				estimated_type, match_reason = "series", self.get_se_ep(ep_details)
			else:
				if search_title:
					write_log(f"{self.MODULE_NAME} Ignoring generic parsed folder name as search title: '{search_title}' for '{org_path}'")
				parsed_episode = False
				search_title, new_desc, estimated_type, match_reason = self.create_best_search(org_title, org_path, desc=desc, short_desc=short_desc, prefer_series=prefer_series, path_mode=path_mode)  # fallback without parser details
		else:
			search_title, new_desc, estimated_type, match_reason = self.create_best_search(org_title, org_path, desc=desc, short_desc=short_desc, prefer_series=prefer_series, path_mode=path_mode)  # as best as possible without the server data
		search_title = self.normalize_provider_search_title(search_title, org_path)
		if search_title_override:
			search_title = self.normalize_provider_search_title(search_title_override, org_path)
		if special_media_type:
			estimated_type = special_media_type
			if special_match_reason and not match_reason:
				match_reason = special_match_reason
		if new_desc:
			short_desc = new_desc
		best_search_list = {
			"title": org_title,
			"search_title": search_title,
			"media_path": org_path,
			"estimated_type": estimated_type,
			"match_reason": match_reason,
			"short_desc": short_desc[:512] if short_desc else "",
			"desc": desc[:512] if desc else "",
			"ext_desc": ext_desc[:512] if ext_desc else ""
		}
		if not search_title:
			write_log(f"{self.MODULE_NAME} ERROR in module 'get_search_results': title is missing.")
			return results_dict, best_search_list
		last_search_title = search_title
		last_year = getattr(ep_details, "year", "") if (parsed_episode or parsed_movie) else ""
		strict_media_type = ""
		if estimated_type in ("series", "anime_series") or (prefer_series and estimated_type == "series"):
			strict_media_type = "series"
		elif estimated_type in ("movie", "anime_movie"):
			strict_media_type = "movie"
		elif estimated_type in ("manga", "manga_series", "manga_movie"):
			strict_media_type = "manga"
		search_variants, seen_variants = [], set()
		if search_title_override:
			self.append_search_variant(search_variants, seen_variants, search_title, last_year, org_path)
		elif parsed_episode or parsed_movie:  # parser details have already been identified
			self.append_search_variant(search_variants, seen_variants, search_title, last_year, org_path)
			if not quickscan:
				for fallback_title, fallback_year in self.create_search_titles(org_title, org_path, quickscan, prefer_series=prefer_series, path_mode=path_mode, desc=desc, short_desc=short_desc):
					self.append_search_variant(search_variants, seen_variants, fallback_title, fallback_year or last_year, org_path)
		else:
			for fallback_title, fallback_year in self.create_search_titles(org_title, org_path, quickscan, prefer_series=prefer_series, path_mode=path_mode, desc=desc, short_desc=short_desc):  # collect all results from alternative searches
				self.append_search_variant(search_variants, seen_variants, fallback_title, fallback_year, org_path)
		fallback_search_title = ""

		def gather_variant_results(variants, fallback_retry=False):
			nonlocal last_search_title, last_year
			variant_results = []
			for provider_title, provider_year in variants:
				last_search_title, last_year = provider_title, provider_year
				norm_dicts = providers.gather_providers_info(provider_title, estimated_type, provider_year)
				for result in norm_dicts or []:
					if isinstance(result, dict):
						result["_search_title"] = provider_title
						result["_expected_media_type"] = estimated_type
						if fallback_retry:
							result["_helper_search_title"] = provider_title
						if strict_media_type:
							result["_strict_media_type"] = strict_media_type
				if norm_dicts:
					variant_results += norm_dicts
			return variant_results

		results += gather_variant_results(search_variants)
		if not results and use_title_translation and not search_title_override:
			fallback_variants, fallback_seen = [], set()
			fallback_search_title = self.append_title_fallback_search_variant(fallback_variants, fallback_seen, search_title, last_year, org_path)
			if fallback_variants:
				write_log(f"{self.MODULE_NAME} Retry provider search with fallback title '{fallback_search_title}' for '{search_title}'")
				results += gather_variant_results(fallback_variants, fallback_retry=True)
		unique_results, seen_results = [], set()
		for result in results:
			provider_ids = result.get(Fields.PROVIDER_IDS, {})
			result_key = (result.get(Fields.PROVIDER, ""), result.get(Fields.TITLE, ""), tuple(sorted(provider_ids.items())) if isinstance(provider_ids, dict) else str(provider_ids))
			if result_key not in seen_results:
				seen_results.add(result_key)
				unique_results.append(result)
		results = unique_results
		self.set_dict_key(results_dict, "results", results)
		search_data = {"search_title": last_search_title, "short_desc": short_desc, "desc": desc, "year": last_year, "match_reason": match_reason, "estimated_type": estimated_type, "strict_media_type": strict_media_type, "fallback_search_title": fallback_search_title}
		self.set_dict_key(results_dict, "search_data", search_data)
		return results_dict, best_search_list

	def guess_separator(self, title, separators):
		char_counts = [(separator, replacement, title.count(separator)) for separator, replacement in separators]
		count_list = [item for item in char_counts if item[2]]  # remove separators that do not appear, with a counter set to 0
		return min(count_list, key=lambda item: item[2])[:2] if count_list else ("", "")  # (guessed_septor, replacement)

	def guess_category(self, org_title, org_path, desc="", short_desc=""):  # don't use 'ext_desc', it might lead to incorrect results
		def find_seasons_episodes(text):  # search for season/episode tags
			def search_for_keys(keys):
				for key in keys:
					found = search(rf"{key}\s*(\d+)", text.lower(), IGNORECASE)
					if found:
						return found.group(1)
					found = search(rf"{key}\s*(\d+)", org_path.lower(), IGNORECASE)
					if found:
						return found.group(1)

			season_keys = ["s"] + self.season_keys + [f"{key} " for key in self.season_keys]
			episode_keys = ["e"] + self.episode_keys + [f"{key} " for key in self.episode_keys]
			season_no, episode_no = search_for_keys(season_keys), search_for_keys(episode_keys)  # with / without space and also single 'S' and 'E'
			if season_no and season_no.isdigit() and episode_no and episode_no.isdigit():
				match_reason = f"S{int(season_no):02d}E{int(episode_no):02d}"
				find_pos = text.find(match_reason)
				if find_pos > 0:
					text = text[:text.find(match_reason)].strip()  # cut off e.g. 'S02E13' and everything after that
				return "series", text, match_reason
			return "", text, ""

		def find_year_tags(text):  # search for year tags
				for regex in [r"\(\d{4}\)"]:  # search for e.g. '(1997)'
					found = search(regex, text)
					if found:
						found = found.group(0)
						text = text.replace(f" {found}", "").strip()
						match_reason = found.strip()
						year = match_reason.replace("(", "").replace(")", "")
						media_type = "series" if year.isdigit() and int(year) < 1900 else "movie"  # before 1896, can't be a movie
						return media_type, text, match_reason  # text=cleanText, match_reason='(1997)'
				return "", text, ""

		def has_keyword(text_value, keywords):
			lower_text = (text_value or "").lower()
			for tag in keywords:
				needle = str(tag or "").strip().lower()
				if not needle:
					continue
				if search(r"(?<![0-9a-zäöüß])" + escape(needle) + r"(?![0-9a-zäöüß])", lower_text, IGNORECASE):
					return needle
			return ""

		def find_series_keywords(text):  # search for series keywords
			matched = has_keyword(text, self.series_keys)
			if matched:
				return "series", text, matched
			return "", text, ""

		def find_movie_keywords(text):  # search for movie keywords
			movie_keys = ["film", "films", "filme", "spielfilm", "spielfilme", "fernsehfilm", "fernsehfilme", "tv-film", "tvfilm", "kinofilm", "kinofilme", "movie", "movies", "feature", "featurefilm", "фильм", "кино", "ταινία", "película", "cinéma", "cine", "cinema", "filma"]
			matched = has_keyword(text, movie_keys)
			if matched:
				return "movie", text, matched
			return "", text, ""

		# start guess_category: search titles and all descriptions for typical characteristics in order to identify the media type.
		res_title, res_desc = (), ()
		search_title = org_title
		for find_helper in [find_seasons_episodes, find_year_tags, find_series_keywords, find_movie_keywords]:
			media_type, search_title, match_reason = find_helper(self.trim_text(search_title))
			if media_type and not res_title:  # use first hit as result, but continue in order to clean-up title
				res_title = (media_type, search_title, match_reason)
		for find_helper in [find_seasons_episodes, find_series_keywords, find_movie_keywords]:
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

	def looks_like_epg_episode_title(self, short_desc, org_title=""):
		"""Detect EPG short descriptions that are really episode/subtitle names."""
		text = self.trim_text(short_desc or "")
		if not text:
			return False
		if len(text) > 90:
			return False
		if text.lower() == self.trim_text(org_title or "").lower():
			return False
		# Full prose descriptions are not episode titles, but broadcasters often put
		# question or exclamation marks into real episode titles. Keep subtitle-like
		# short descriptions with separators eligible.
		has_subtitle_separator = ":" in text or " - " in text or " – " in text
		if text.count(". ") or text.endswith("."):
			return False
		if (text.endswith("!") or text.endswith("?")) and not has_subtitle_separator:
			return False
		word_count = len([part for part in text.replace(":", " ").replace("-", " ").split() if part])
		if word_count > 10:
			return False
		movie_markers = ["film", "spielfilm", "fernsehfilm", "tv-film", "tvfilm", "kinofilm", "movie", "featurefilm"]
		series_markers = ["serie", "staffel", "folge", "episode"]
		lower_text = text.lower()
		if any(marker in lower_text for marker in movie_markers):
			return False
		if any(marker in lower_text for marker in series_markers):
			return True
		return ":" in text or " - " in text or " – " in text

	def create_best_search(self, org_title, org_path, desc="", short_desc="", prefer_series=False, path_mode=None):
		new_desc = ""
		path_mode = self.normalize_path_mode(path_mode)
		if prefer_series:
			episode_series_title, episode_desc, episode_reason = self.split_foreign_episode_title(org_title)
			if episode_series_title:
				return episode_series_title, episode_desc, "series", episode_reason
		est_media_type, search_title, match_reason = self.guess_category(splitext(org_title)[0].strip(), org_path, desc=desc, short_desc=short_desc)  # remove all extensions (e.g. '.mp4')
		if not est_media_type and self.looks_like_epg_episode_title(short_desc, org_title):
			est_media_type, new_desc, match_reason = "series", self.trim_text(short_desc), "short-desc-episode-title"
		recording_title, recording_info = self.extract_recording_movie_title(org_title)
		if recording_title and (path_mode in self.PATH_MODES_MOVIE or est_media_type == "movie" or self.path_suggests_movie(org_path)):
			return recording_title, recording_info, "movie", match_reason or "recording-title"
		clean_match = match_reason.replace("(", "").replace(")", "")
		if clean_match.isdigit():  # in cases org_title includes e.g. '(1121)'
			search_title, new_desc = search_title.replace(match_reason, "").strip(), clean_match
		if search_title:
			if ".ts" in org_path and match_reason != "short-desc-episode-title":  # normal treatment for e2 recordings
				separator, replacement = self.guess_separator(org_title, e2mdbglobals.EPGTYPE_SEPAS)
				if separator:
					search_title, new_desc = self.divide_file_base_infos(org_title, new_desc, separator)
			else:  # special treatment for foreign recordings (e.g. '.mp4', '.mkv', '.avi', etc.)
				org_title = org_title.replace(".", " ")
				separator, replacement = self.guess_separator(org_title, e2mdbglobals.FOREIGN_SEPAS)
				if separator:
					search_title, new_desc = self.divide_file_base_infos(org_title, new_desc, separator)
		return search_title, new_desc, est_media_type, match_reason

	def create_search_titles(self, org_title, org_path, quickscan, prefer_series=False, path_mode=None, desc="", short_desc=""):  # create titles alternatives
		path_mode = self.normalize_path_mode(path_mode)
		search_titles = []
		est_media_type, search_title, match_reason = self.guess_category(org_title, org_path, desc=desc, short_desc=short_desc)
		search_title, new_desc, m_type, m_reason = self.create_best_search(org_title, org_path, desc=desc, short_desc=short_desc, prefer_series=prefer_series, path_mode=path_mode)
		est_media_type = est_media_type or m_type
		match_reason = match_reason or m_reason
		clean_match = match_reason.strip("(").strip(")")  # clean e.g. '(2019)' but leave 'S02E03'
		if est_media_type == "series":
			desc, year = ("", clean_match) if clean_match.isdigit() else (clean_match, "")
		else:
			desc, year = new_desc, clean_match
		search_title = self.normalize_provider_search_title(search_title, org_path)
		search_titles.append((search_title, year))  # first search string
		recording_title, _recording_info = self.extract_recording_movie_title(org_title)
		if recording_title and (path_mode in self.PATH_MODES_MOVIE or est_media_type == "movie" or m_type == "movie" or self.path_suggests_movie(org_path)):
			return list(dict.fromkeys(search_titles[:]).keys())
		if ".ts" in org_path and match_reason != "short-desc-episode-title":  # normal treatment for e2 recordings
			for separator, replacement in e2mdbglobals.EPGTYPE_SEPAS:  # create alternatives acc. EPG separators
				if separator in org_title:
					div_title, desc = self.divide_file_base_infos(org_title, desc, separator)
					search_titles.append((f"{div_title}{replacement.strip()}", year))  # create variations
					search_titles.append((div_title, year))
		else:  # special treatment for foreign recordings (e.g. '.mp4', '.mkv', , '.avi', etc.)
			if not quickscan:
				for separator, replacement in e2mdbglobals.FOREIGN_SEPAS:  # create alternatives acc. foreign separators
					if separator in org_title:
						div_title, desc = self.divide_file_base_infos(org_title, desc, separator)
						search_titles.append((f"{div_title}{replacement.rstrip()}", year))  # create variations
						search_titles.append((div_title, year))
		search_titles = list(dict.fromkeys(search_titles[:]).keys())  # remove all duplicates from list
		return search_titles

	# TODO: Check
	def divide_file_base_infos(self, text, desc, separator):  # reduce text, e.g. 'Wir waren wie Brüder_Currahee.mp4'
		text_without_ext = splitext(text)[0].strip()  # remove all extensions (e.g. '.mp4')
		path_items = [item.strip() for item in text_without_ext.split(separator)]
		text_without_ext = path_items[0].strip(".").strip("_").strip()    # use only the beginning part of the text/title
		desc = " ".join(path_items[1:])  # use the rest for description
		return text_without_ext, desc  # e.g. ('Wir waren wie Brüder', 'Currahee') or ('Wir waren wie Brüder', 'S01S01')

	def get_secondary_dicts(self, pvr_name, series_id, org_title, match_reason, short_desc, desc):
		def write_log_text(err_msg, content, curr_path):
			if err_msg:
				write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': {content} could not be saved: {err_msg}")
			if episode_index:
				write_log(f"{self.MODULE_NAME} {content} for '{org_title}' was successfully stored in '{curr_path}'.")
			else:
				write_log(f"{self.MODULE_NAME} Empty {content} for '{org_title}' was stored in '{curr_path}'.")

		def create_picpaths_dict(cat_dict, category):  # season or series only
			pic_dict = {}
			for pic_type in ["cover", "backdrop", "titlelogo", "image"]:
				pic_url = cat_dict.get(f"{pic_type}_url", "")
				if pic_url:
					series_id = cat_dict.get(Fields.SERIES_ID, "")
					season_no = cat_dict.get(Fields.SEASON_NO, "")
					pic_path = self.get_secondary_datapath(pvr_name, series_id, category, season_no=season_no, url=pic_url, pic_type=pic_type)
					pic_dict[f"{pic_type}_path"] = pic_path
			return pic_dict

		series_dict, season_dict, episode_dict = {}, {}, {}
		if series_id:
			series_path = self.get_secondary_datapath(pvr_name, series_id, "series")
			index_path = self.get_secondary_datapath(pvr_name, series_id, "index")
			episode_index = {}
			if isfile(index_path) and isfile(series_path):
				err_msg, series_dict = self.read_json_file(series_path)
				if err_msg:
						write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': Series details could not be loaded: {err_msg}")
				err_msg, episode_index = self.read_json_file(index_path)
				if err_msg:
						write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': Episode index could not be loaded: {err_msg}")
			if not series_dict or not episode_index:
				err_msg, series_dict, episode_index = providers.get_series_details_index(pvr_name, series_id)
				series_dict.update(create_picpaths_dict(series_dict, "series"))
				if err_msg:
					write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': Series info download for '{org_title}': {err_msg}")
					return series_dict, season_dict, episode_dict
				err_msg = self.write_json_file(series_dict, series_path)  # also write even if series_dict is empty
				write_log_text(err_msg, "Series details", series_path)
				err_msg = self.write_json_file(episode_index, index_path)  # also write even if episode_index is empty
				write_log_text(err_msg, "Episode index", index_path)
			# try to find episode in series index
			if series_dict and episode_index:
				# season_episode = ("", "", "")
				plain_season_episode = ""
				if match_reason:  # season_episode using details from file base
					season_episode_values = [str(int(value)) for value in match_reason.upper().replace("S", "").split("E") if value.isdigit()]
					if len(season_episode_values) == 1:
						# Filenames like "Show 8. Episode title" only carry an episode number.
						# TVDB/TVmaze episode indexes use season-episode keys, so assume season 1 first.
						plain_season_episode = "1-" + season_episode_values[0]
					else:
						plain_season_episode = "-".join(season_episode_values)
				write_log("plain_season_episode:", plain_season_episode)
				season_episode = providers.find_season_episode(pvr_name, episode_index, short_desc or desc, plain_season_episode)  # result: e.g. ('1-2', '283766', 'Die Warnung')
				if not season_episode and plain_season_episode.startswith("1-"):
					# Fallback: if a provider uses absolute/no-season numbering, try the original episode number too.
					season_episode = providers.find_season_episode(pvr_name, episode_index, short_desc or desc, plain_season_episode.split("-", 1)[1])
				if season_episode:
					plain_season_episode, episode_id, episode_desc = season_episode
					if plain_season_episode:
						season_no, episode_no = plain_season_episode.split("-")
						# try to find relating episode details first
						err_msg, episode_dict = providers.get_episode_details(pvr_name, series_id, episode_id, season_no, episode_no)
						if episode_dict and not err_msg:
							self.set_dict_key(episode_dict, "media_type", "series")
							season_path = self.get_secondary_datapath(pvr_name, series_id, "seasons", season_no=season_no)
							if isfile(season_path):
								season_err, season_dict = self.read_json_file(season_path)
								if season_err:
									write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': Season details could not be loaded: {season_err}")
							if not season_dict:
								season_err, season_dict = providers.get_season_details(pvr_name, series_dict, season_no)
								season_dict.update(create_picpaths_dict(season_dict, "seasons"))
								season_err = self.write_json_file(season_dict, season_path)  # also write even if season_dict is empty
								write_log_text(season_err, "Season details", season_path)
							season_number = season_dict.get("season_no", "")
							if season_number.isdigit():
								season_number = int(season_number)
								seasons = series_dict.get("seasons", [])
								if seasons and len(seasons) > season_number:
									season_detail = seasons[season_number]
									self.set_dict_key(episode_dict, "season_id", season_detail.get("season_id", ""))
									self.set_dict_key(episode_dict, "season_name", season_detail.get("season_name", ""))
						else:
							write_log(f"{self.MODULE_NAME} ERROR in module 'get_secondary_dicts': No episode details found for '{org_title}'")
		return series_dict, season_dict, episode_dict

	def get_match_ratio(self, pvr_dict, search_title, desc="", short_desc="", ext_desc=""):
		title_ratio, desc_ratio = 0.0, 0.0
		pvr_desc = pvr_dict.get("overview", "")
		plain_org_title = search_title.replace("–", "").replace("-", "",).replace("!", "").replace(":", "").replace(",", "").strip().lower()
		plain_org_title = " ".join([part for part in plain_org_title.split(" ") if part])  # remove all duplicate spaces
		plain_pvr_title = pvr_dict.get("title", "").replace("–", "").replace("-", "").replace("!", "").replace(":", "_").replace(",", "").strip().lower()
		plain_pvr_title = " ".join([part for part in plain_pvr_title.split(" ") if part])  # remove all duplicate spaces
		if plain_pvr_title:
			title_ratio = 1.0 if plain_pvr_title in plain_org_title or plain_org_title in plain_pvr_title else SequenceMatcher(None, plain_pvr_title, plain_org_title).ratio()
			descs_list = [desc, short_desc, ext_desc]
			for curr_desc in descs_list:
				if pvr_desc:
					desc_ratio = max(desc_ratio, SequenceMatcher(None, curr_desc, pvr_desc).ratio())
		return title_ratio, desc_ratio

	def write_scan_statistics(self, success_list, failure_list, start_time_dt, duration):
		for dict_list, dict_type in [(success_list, "succeeded"), (failure_list, "failed")]:
			result_list = []
			for item in dict_list:
				org_title = item.get("title", "")
				search_title = item.get("search_title", "")
				desc = item.get("desc", "")
				short_desc = item.get("short_desc", "")
				ext_desc = item.get("ext_desc", "")
				org_path = item.get("media_path", "")
				estimated_type = item.get("estimated_type", "")
				match_reason = item.get("match_reason", "")
				if short_desc in org_title or desc == short_desc:
					desc = ""
				result_dict = {}
				for key, value in (
					("title", org_title),
					("search_title", search_title),
					("estimated_type", estimated_type),
					("match_reason", match_reason),
					("short_desc", short_desc),
					("desc", desc),
					("ext_desc", ext_desc),
					("media_path", org_path),
					("data_path", self.get_primary_datapath(org_path)),
				):
					self.set_dict_key(result_dict, key, value)
				result_list.append(result_dict)
			result_dict = {}
			self.set_dict_key(result_dict, "results", result_list)
			self.set_dict_key(result_dict, "start_scan", start_time_dt.isoformat()[:19])  # remove microseconds
			self.set_dict_key(result_dict, "duration_sec", duration)
			result_path = f"{self.get_cache_dir()}/scan_{dict_type}.json"
			err_msg = self.write_json_file(result_dict, result_path)
			if err_msg:
				write_log(f"{self.MODULE_NAME} ERROR in module 'write_scan_statistics': {err_msg}")

	def run_in_background(self, finsihed_callback):
		self.skin_progress = None
		self.callback = finsihed_callback

	def run_in_forground(self, finsihed_callback, skin_progress):
		print("run_in_forground called", finsihed_callback, skin_progress)
		self.skin_progress = skin_progress
		self.callback = finsihed_callback

	def get_file_size(self, file_dir):
		try:
			file_size = stat(file_dir).st_size
		except OSError as err_msg:
			file_size = -1
			write_log(f"{self.MODULE_NAME} ERROR in module 'get_file_size': {err_msg}!")
		return file_size

	def get_media_length(self, file_base):
		if exists(file_base):
			try:
				with open(file_base, "rb") as fd:
					while True:
						chunk = fd.read(12)
						if len(chunk) < 12:
							break
						cue = unpack(">QI", chunk)
						if cue[1] == 5:
							movie_len = cue[0] / 90000
							return movie_len
			except Exception as err_msg:
				write_log(f"{self.MODULE_NAME} ERROR in module 'get_media_length': Failure at getting movie length from cut list: {err_msg}!")
		return -1

	def init_providers(self):
		omdb = bytes.fromhex("39383734653564F"[:-1]).decode()
		tvdb = bytes.fromhex("66616633353133312D613531632D343636632D626264612D343566623665393135366535A"[:-1]).decode()
		tmdb = bytes.fromhex("64343265366238323061313534316363363963653738393637316665626133393"[:-1]).decode()
		api_keys = {
			"tmdb": config.plugins.e2mdb.tmdbapikey.value or tmdb,
			"tvdb": config.plugins.e2mdb.tvdbapikey.value or tvdb,
			"omdb": config.plugins.e2mdb.omdbapikey.value or omdb,
			# "imdb": "",  # IMDB provider disabled, keep provider/IMDB.py in place
			"tvmaze": "",
			"cinemeta": "",
			"anime": "",
			"kitsu": "",
			"fanart": config.plugins.e2mdb.fanartapikey.value,
			"fanart_active": config.plugins.e2mdb.fanartactive.value
		}
		series_search_order = {
			"tvdb": config.plugins.e2mdb.tvdbactive.value,
			"tmdb": config.plugins.e2mdb.tmdbactive.value,
			"tvmaze": config.plugins.e2mdb.tvmazeactive.value,
			"cinemeta": config.plugins.e2mdb.cinemetaactive.value,
			"anime": config.plugins.e2mdb.animeactive.value,
			"kitsu": config.plugins.e2mdb.kitsuactive.value,
			"omdb": config.plugins.e2mdb.omdbactive.value,
			# "imdb": config.plugins.e2mdb.imdbactive.value,  # IMDB provider disabled, keep provider/IMDB.py in place
		}
		movie_search_order = {
			"tmdb": config.plugins.e2mdb.tmdbactive.value,
			"cinemeta": config.plugins.e2mdb.cinemetaactive.value,
			"anime": config.plugins.e2mdb.animeactive.value,
			"kitsu": config.plugins.e2mdb.kitsuactive.value,
			"omdb": config.plugins.e2mdb.omdbactive.value,
			"tvdb": config.plugins.e2mdb.tvdbactive.value,
			# "imdb": config.plugins.e2mdb.imdbactive.value,  # IMDB provider disabled, keep provider/IMDB.py in place
		}
		return providers.start(self.language, api_keys, series_search_order, movie_search_order)  # start all providers with default language
