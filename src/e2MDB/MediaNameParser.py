########################################################################################################
# e2MDB by jbleyel @OpenATV (c) 2026                                                                   #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from dataclasses import dataclass
from re import compile, IGNORECASE, sub
from os import walk
from os.path import normpath, splitext, isdir, join, sep
from typing import Optional, Union
from unicodedata import combining, normalize as unicode_normalize


@dataclass
class ParsedMovieInfo:  # Result of parsing a movie file
	success: bool = False
	path: str = ""
	movie_name: Optional[str] = None
	year: Optional[int] = None
	container: Optional[str] = None

	def __str__(self):
		if self.success:
			if self.movie_name and self.year:
				return f"{self.movie_name} ({self.year})"
			elif self.movie_name:
				return self.movie_name
		return f"Failed: {self.path}"


@dataclass
class ParsedEpisodeInfo:  # Result of parsing an episode path
	success: bool = False
	path: str = ""
	series_name: Optional[str] = None
	season_number: Optional[int] = None
	episode_number: Optional[int] = None
	ending_episode_number: Optional[int] = None
	year: Optional[int] = None
	month: Optional[int] = None
	day: Optional[int] = None
	is_by_date: bool = False
	container: Optional[str] = None
	is_stub: bool = False
	stub_type: Optional[str] = None
	is_3d: bool = False
	format_3d: Optional[str] = None
	is_named: bool = False
	is_optimistic: bool = False
	supports_absolute: bool = False

	def __str__(self):
		if self.success:
			if self.is_by_date:
				return f"{self.series_name} - {self.year:04d}-{self.month:02d}-{self.day:02d}" if self.series_name else f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
			else:
				if self.season_number is not None and self.episode_number is not None:
					ep_str = f"{self.episode_number:02d}"
					if self.ending_episode_number:
						ep_str += f"-{self.ending_episode_number:02d}"
					return f"{self.series_name} S{self.season_number:02d}E{ep_str}" if self.series_name else f"S{self.season_number:02d}E{ep_str}"
				elif self.season_number is not None:
					return f"{self.series_name} S{self.season_number:02d}" if self.series_name else f"S{self.season_number:02d}"
				elif self.episode_number is not None:
					return f"{self.series_name} E{self.episode_number:02d}" if self.series_name else f"E{self.episode_number:02d}"
				elif self.series_name:
					return self.series_name
		return f"Failed: {self.path}"


class MediaNameParser:  # Media name parser with comprehensive Emby.Naming episode patterns
	# Generic library/category folders that must not be used as a movie or series title.
	# Keep this list conservative: exact folder matches only, normalized by case, accents and separators.
	IGNORED_LIBRARY_FOLDER_NAMES = {
		# Generic roots and technical folders
		"archive", "archives", "aufnahme", "aufnahmen", "autofs", "cache", "download", "downloads", "hdd", "library", "media", "mnt", "mount", "mounts", "net", "network", "pvr", "recording", "recordings", "sample", "samples", "scan", "scan test", "scantest", "test", "tests", "usb", "video", "videos",
		# Quality / resolution folders
		"3d", "4k", "8k", "720p", "1080i", "1080p", "2160p", "bluray", "blu ray", "dvd", "dvdrip", "fullhd", "hd", "hdr", "hdtv", "sd", "uhd", "web", "webdl", "web dl", "webrip",
		# Language folders and language codes often used as category folders
		"cz", "cs", "da", "danish", "de", "deutsch", "dk", "en", "eng", "english", "es", "fi", "finnish", "fr", "french", "german", "gr", "greek", "hu", "hungarian", "it", "italian", "nl", "no", "norwegian", "pl", "polish", "pt", "ro", "romanian", "sk", "sl", "spanish", "sv", "swedish",
		# Multi-language / audio folders
		"dubbed", "dual audio", "dual", "multi", "multi audio", "multilanguage", "multilingual", "ov", "sub", "subbed", "subs", "subtitle", "subtitles", "untertitel", "vost", "vostfr",
		# English
		"anime", "cartoon", "cartoons", "children", "documentaries", "documentary", "episode", "episodes", "film", "films", "kids", "movie", "movies", "season", "seasons", "series", "show", "shows", "tv", "tv series", "tv show", "tv shows", "television",
		# German
		"doku", "dokus", "dokumentation", "dokumentationen", "fernsehen", "film", "filme", "folge", "folgen", "kino", "reihe", "reihen", "sendung", "sendungen", "serie", "serien", "staffel", "staffeln",
		# French
		"documentaire", "documentaires", "emission", "emissions", "episode", "episodes", "film", "films", "saison", "saisons", "serie", "series", "tele", "telefilm", "telefilms", "television",
		# Spanish / Catalan
		"capitulo", "capitulos", "cine", "documental", "documentales", "episodio", "episodios", "pelicula", "peliculas", "programa", "programas", "serie", "series", "temporada", "temporadas", "television",
		# Italian
		"cartoni", "cinema", "documentari", "documentario", "episodi", "episodio", "film", "programma", "programmi", "serie", "serie tv", "stagione", "stagioni", "televisione",
		# Portuguese
		"cinema", "documentario", "documentarios", "episodio", "episodios", "filme", "filmes", "programa", "programas", "serie", "series", "temporada", "temporadas", "televisao",
		# Dutch / Flemish
		"aflevering", "afleveringen", "documentaire", "documentaires", "film", "films", "programma", "programmas", "reeks", "reeksen", "seizoen", "seizoenen", "serie", "series", "televisie",
		# Polish
		"dokument", "dokumentalne", "dokumenty", "film", "filmy", "odcinek", "odcinki", "program", "programy", "sezon", "sezony", "serial", "seriale", "telewizja",
		# Czech / Slovak / Slovenian
		"dokument", "dokumentarni", "dokumenty", "epizoda", "epizody", "film", "filmy", "oddaja", "oddaje", "porad", "porady", "relacia", "relacie", "sezona", "sezony", "serial", "seriale", "serialy", "seria", "serie", "televize", "televizia",
		# Nordic languages
		"avsnitt", "dokumentar", "dokumentarer", "dokumentarfilm", "dokumentarer", "elokuva", "elokuvat", "film", "filmer", "jakso", "jaksot", "kausi", "kaudet", "ohjelma", "ohjelmat", "sarja", "sarjat", "sasong", "sasonge", "sesong", "sesonger", "serie", "serier", "sæson", "sæsoner", "säsong", "säsonger", "tv",
		# Balkan / Romanian / Hungarian
		"documentar", "documentare", "dokumentumfilm", "emisija", "emisije", "epizod", "epizoda", "epizode", "film", "filme", "filmek", "műsor", "műsorok", "sezon", "sezona", "sezoane", "serial", "seriale", "serija", "serije", "sorozat", "sorozatok", "televizija",
		# Greek / Cyrillic / Turkish
		"bolum", "bolumler", "dizi", "diziler", "film", "filmler", "sezon", "sezonlar", "ταινια", "ταινιες", "σειρα", "σειρες", "σεζον", "επεισοδιο", "επεισοδια", "сериал", "сериалы", "серии", "серия", "сезон", "сезоны", "фильм", "фильмы"
	}

	SEASON_FOLDER_PATTERN = compile(
		r"^(?:s|season|seasons|staffel|staffeln|saison|saisons|temporada|temporadas|stagione|stagioni|seizoen|seizoenen|sezon|sezony|sezona|sezony|serie|series|sesong|sesonger|sasong|sasonge|sæson|sæsoner|kausi|kaudet|sarja|säsong|säsonger|сезон|сезоны|σεζον|temporada)\s*\d{1,4}$",
		IGNORECASE
	)
	SXX_FOLDER_PATTERN = compile(r"^s\d{1,4}$", IGNORECASE)

	@classmethod
	def normalize_folder_name(cls, value):
		"""Return a stable key for comparing technical/category folder names."""
		text = unicode_normalize("NFKD", str(value or "")).lower()
		text = "".join(char for char in text if not combining(char))
		text = sub(r"[._\-]+", " ", text)
		text = sub(r"\s+", " ", text).strip()
		return text

	@classmethod
	def clean_media_title(cls, value):
		"""Clean a folder or filename fragment for provider searches without changing its meaning."""
		text = str(value or "")
		text = text.replace("_", " ").replace(".", " ")
		text = text.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
		text = sub(r"\s+", " ", text).strip(" -_.")
		return text

	@classmethod
	def parse_ignored_folder_names(cls, folder_names):
		"""Normalize a user supplied comma/semicolon/pipe separated folder ignore list."""
		if not folder_names:
			return set()
		if isinstance(folder_names, (list, tuple, set)):
			items = folder_names
		else:
			items = str(folder_names).replace(";", ",").replace("|", ",").split(",")
		folder_keys = set()
		for item in items:
			folder_key = cls.normalize_folder_name(item)
			if folder_key:
				folder_keys.add(folder_key)
		return folder_keys

	@classmethod
	def is_ignored_library_folder(cls, folder_name, extra_folder_names=None):
		"""Return True if a folder is only a generic library/category marker."""
		folder_key = cls.normalize_folder_name(folder_name)
		if not folder_key:
			return True
		if folder_key in cls.IGNORED_LIBRARY_FOLDER_NAMES or bool(cls.SEASON_FOLDER_PATTERN.match(folder_key) or cls.SXX_FOLDER_PATTERN.match(folder_key)):
			return True
		if extra_folder_names:
			extra_folder_keys = extra_folder_names if isinstance(extra_folder_names, set) else cls.parse_ignored_folder_names(extra_folder_names)
			return folder_key in extra_folder_keys
		return False

	def __init__(self, library_path: Optional[str] = None, mode: int = 2, ignored_folders=None):
		"""Initialize parser
		Args:
			library_path: Optional library root path. If provided, series name is extracted from the first folder after this path.
			mode: 1 for movies, 2 for series (default: 2)
			ignored_folders: Optional extra folder names that should never be used as media titles.
		"""
		self.library_path = library_path
		self.mode = mode
		self.extra_ignored_library_folder_names = self.parse_ignored_folder_names(ignored_folders)

		# Movie patterns (from Emby.Naming CleanDateTimes regex)
		# Pattern: Name (Year) - matches: Movie Name (2020), Movie.Name.2020, Movie_Name.2020
		self.movie_patterns = [
			(compile(r'^(.+[^_\,.(\)\[\]\-])[_\.\(\)\[\]\-](19[0-9][0-9]|20[0-1][0-9])([_\,.(\)\[\]\-][^0-9]|)'), 'clean_year'),
		]

		# Compile all episode patterns (from Emby.Naming)
		# Order matters: more specific patterns first, greedy patterns last
		self.episode_patterns = [
			# S##E## format with optional separators: S01E02, s04e03, S4E3, S01 - E02, S01.E02
			(compile(r'[sS](\d{1,4})[][ ._-]*[eE](\d{1,3})'), 'standard'),
			# S##x## or [sS]##[xX]## format (e.g., S01x02)
			(compile(r'[sS](\d{1,4})[xX](\d{1,3})', IGNORECASE), 'alternate'),
			# E## format (episode only, no season): .E01, -E05, _E10
			(compile(r'[\\.\\s_-][eE](\d{1,3})'), 'episode_only'),
			# ep## or EP_## or EP.## format
			(compile(r'[Ee][Pp][._]?(\d{1,3})', IGNORECASE), 'episode_only'),
			# Date patterns (yyyy.mm.dd, yyyy-mm-dd)
			(compile(r'(\d{4})[\\.-](\d{2})[\\.-](\d{2})'), 'date_ymd'),
			# Date patterns (dd.mm.yyyy, dd-mm-yyyy)
			(compile(r'(\d{2})[\\.-](\d{2})[\\.-](\d{4})'), 'date_dmy'),
			# ##x## format: 01x02, 4x3 (at END - most greedy, easily false-positive)
			(compile(r'[\\/\\._ \[\\(-](\d{1,2})[xX](\d{1,2}(?:(?:[a-i]|\.[1-9])(?![0-9]))?)', IGNORECASE), 'absolute'),
			# 3-digit episode at end of filename: tvs-name-101.mkv or tvs-name-101_AC3.mkv
			(compile(r'-(\d{3,4})(?:[_.])', IGNORECASE), 'episode_sequence'),
		]

	def parse(self, file_path: str, is_directory: bool = False) -> Union[ParsedMovieInfo, ParsedEpisodeInfo]:
		"""Parse media file to extract info based on mode
		Args:
			file_path: Path to media file
			is_directory: If True, treat as directory
		Returns:
			ParsedMovieInfo for mode 1, ParsedEpisodeInfo for mode 2
		"""
		if self.mode == 1:
			return self.parse_movie(file_path, is_directory)
		else:
			return self.parse_episode(file_path, is_directory)

	def parse_movie(self, file_path: str, is_directory: bool = False) -> ParsedMovieInfo:
		"""Parse movie file to extract movie name and year
		Strategy:
		1. Extract year from filename using pattern: Name (YYYY) or Name.YYYY or Name_YYYY
		2. Extract movie name by removing year, release groups, and quality info
		Args:
			file_path: Path to media file
			is_directory: If True, treat as directory
		Returns:
			ParsedMovieInfo with parsed data
		"""
		result = ParsedMovieInfo(path=file_path)

		# Get filename without extension
		if not is_directory:
			filename = splitext(normpath(file_path))[0]
			_, ext = splitext(file_path)
			result.container = ext.lstrip('.')
		else:
			filename = normpath(file_path)

		# Get just the filename part without path
		base_name = filename.split(sep)[-1]

		# Look for year pattern: (19|20)xx with separators or at word boundaries
		# Match: Name[._()-]YYYY[._()-Rest] or variations
		year_match = compile(r'[_\.\(\)\[\]\-]?(19[0-9]{2}|20[0-2][0-9])(?:[_\.\(\)\[\]\-\s]|$)').search(base_name)

		if year_match:
			try:
				year_str = year_match.group(1)
				year = int(year_str)

				# Validate year (realistic movie years)
				if 1900 <= year <= 2100:
					# Get the name part (everything before the year match)
					name = base_name[:year_match.start()].rstrip('_.([])-')

					if not name or name.isdigit():
						# Year might be at the beginning or the name is only digits
						# Try to get name after year
						rest_after_year = base_name[year_match.end():].lstrip('_.([])-')
						if rest_after_year and not rest_after_year[0].isdigit():
							name = rest_after_year
						elif name:
							pass  # Keep the name we have
						else:
							name = base_name

					# Clean up the name: replace separators with spaces
					name = name.replace('_', ' ').replace('.', ' ').replace('[', '').replace(']', '').replace('(', '').replace(')', '').replace('-', ' ')
					# Remove multiple spaces
					name = ' '.join(name.split())

					if name:
						result.movie_name = name
						result.year = year
						result.success = True
						return result
			except (ValueError, IndexError, TypeError):
				pass

		# If no year found, just use the base name as movie name (cleaned up)
		if base_name:
			name = base_name.replace('[', '').replace(']', '').replace('_', ' ').replace('.', ' ').replace('(', '').replace(')', '')
			name = ' '.join(name.split())
			result.movie_name = name
			result.success = True

		return result

	def parse_episode(self, file_path: str, is_directory: bool = False) -> ParsedEpisodeInfo:
		"""Parse media file to extract series name and episode info
		Strategy:
		1. Extract season/episode from filename or path using Emby.Naming patterns
		2. Extract series name from first folder after library_path
		Args:
			file_path: Path to media file
			is_directory: If True, treat as directory
		Returns:
			ParsedEpisodeInfo with parsed data
		"""
		result = ParsedEpisodeInfo(path=file_path)
		# Get relative path if library_path is set
		parse_path = file_path
		if self.library_path:
			lib_normalized = normpath(self.library_path)
			file_normalized = normpath(file_path)
			if file_normalized.startswith(lib_normalized):
				relative = file_normalized[len(lib_normalized):].lstrip(sep)
				parse_path = relative if relative else file_normalized
		# Extract file extension
		if not is_directory:
			_, ext = splitext(parse_path)
			result.container = ext.lstrip('.')
		# ============ EXTRACT EPISODE INFO ============
		# Try each pattern in order
		for pattern, pattern_type in self.episode_patterns:
			match = pattern.search(parse_path)
			if not match:
				continue
			try:
				if pattern_type == 'date_ymd':
					# yyyy.mm.dd format
					year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
					result.year = year
					result.month = month
					result.day = day
					result.is_by_date = True
					result.success = True
					break
				elif pattern_type == 'date_dmy':
					# dd.mm.yyyy format
					day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
					result.year = year
					result.month = month
					result.day = day
					result.is_by_date = True
					result.success = True
					break
				elif pattern_type == 'episode_only':
					# ep## format (no season)
					episode = int(match.group(1))
					result.episode_number = episode
					result.success = True
					break
				elif pattern_type == 'episode_sequence':
					# 3-digit sequence like 101 (S01E01), 222 (S02E22), etc.
					# First digit(s) = season, last digits = episode
					seq = match.group(1)
					if len(seq) == 3:
						# 101 -> Season 1, Episode 01
						season = int(seq[0])
						episode = int(seq[1:])
						if not ((200 <= season < 1928) or season > 2500):
							result.season_number = season
							result.episode_number = episode
							result.success = True
							break
					elif len(seq) == 4:
						# 1301 -> Season 13, Episode 01
						season = int(seq[0:2])
						episode = int(seq[2:])
						if not ((200 <= season < 1928) or season > 2500):
							result.season_number = season
							result.episode_number = episode
							result.success = True
							break
				else:
					# standard, absolute, alternate formats with season and episode
					season = int(match.group(1))
					episode = int(match.group(2))

					# Validate season number (Emby ignores seasons 200-1927 and >2500)
					if (200 <= season < 1928) or season > 2500:
						continue
					result.season_number = season
					result.episode_number = episode
					result.success = True
					break
			except (ValueError, IndexError):
				continue

		# ============ EXTRACT SEASON FROM PATH (if no episode found) ============
		# If we didn't find an episode in the filename but there's a Season/Staffel in the path
		# try to extract season number (e.g., "Season 03" or "Staffel 4")
		if result.season_number is None and result.episode_number is None:
			season_pattern = compile(r'[sS](?:taffel|eason)[\s._-]*(\d{1,2})', IGNORECASE)
			season_match = season_pattern.search(file_path)
			if season_match:
				try:
					season = int(season_match.group(1))
					# Validate season number (Emby ignores seasons 200-1927 and >2500)
					if not ((200 <= season < 1928) or season > 2500):
						result.season_number = season
				except (ValueError, IndexError):
					pass

		# ============ EXTRACT SERIES NAME ============
		# Strategy: Use first folder after library_path as series name
		# Examples:
		#   /Serien/Prison Break/Staffel 4/.../file.mkv → "Prison Break"
		#   /Shows/The Walking Dead/Season 1/.../file.mkv → "The Walking Dead"

		if self.library_path:
			# Get the part after library_path and use the first meaningful subfolder as the series name.
			# Generic category folders such as "series", "serien", "film", "movie" or language folders must be skipped.
			lib_normalized = normpath(self.library_path)
			file_normalized = normpath(file_path)

			if file_normalized.startswith(lib_normalized):
				# Remove library path
				after_lib = file_normalized[len(lib_normalized):].lstrip(sep)
				path_parts = [part for part in after_lib.split(sep) if part]
				folder_parts = path_parts if is_directory else path_parts[:-1]
				for folder_name in folder_parts:
					if folder_name.startswith('.') or self.is_ignored_library_folder(folder_name, self.extra_ignored_library_folder_names):
						continue
					series_name = self.clean_media_title(folder_name)
					if series_name and not self.is_ignored_library_folder(series_name, self.extra_ignored_library_folder_names):
						result.series_name = series_name
						break

		if not result.series_name:
			# If the configured library path points directly at a series or season folder,
			# recover the title from the nearest meaningful parent folder.
			path_parts = [part for part in normpath(file_path).split(sep) if part]
			folder_parts = path_parts if is_directory else path_parts[:-1]
			for folder_name in reversed(folder_parts):
				if folder_name.startswith('.') or self.is_ignored_library_folder(folder_name, self.extra_ignored_library_folder_names):
					continue
				series_name = self.clean_media_title(folder_name)
				if series_name and not self.is_ignored_library_folder(series_name, self.extra_ignored_library_folder_names):
					result.series_name = series_name
					break

		if not result.series_name and (result.season_number is not None or result.episode_number is not None):
			# Last fallback for flat series folders: derive the title from the filename before SxxEyy/1x02.
			base_name = splitext(normpath(file_path))[0].split(sep)[-1]
			for title_pattern in (
				compile(r'^(.+?)[\s._-]+[sS]\d{1,4}[][ ._-]*[eE]\d{1,3}'),
				compile(r'^(.+?)[\s._-]+\d{1,2}[xX]\d{1,3}', IGNORECASE),
			):
				title_match = title_pattern.search(base_name)
				if not title_match:
					continue
				series_name = self.clean_media_title(title_match.group(1))
				if series_name and not self.is_ignored_library_folder(series_name, self.extra_ignored_library_folder_names):
					result.series_name = series_name
					break

		# Mark as successful if we have season+series (even without episode)
		if result.series_name:
			if result.season_number is None:
				result.season_number = 1  # Default to season 1 if we have series but no season
			result.success = True

		return result

	def scan_directory(self, directory: str, recursive: bool = True, output_file: Optional[str] = None) -> list:
		"""Scan directory and parse all video files

		Args:
			directory: Root directory to scan
			recursive: If True, scan recursively; if False, only scan root directory
			output_file: Optional file to write results to

		Returns:
			List of ParsedEpisodeInfo results
		"""
		results = []
		video_extensions = {'.mp4', '.mkv', '.avi', '.flv', '.mov', '.ts', '.m2ts', '.mts', '.wmv', '.webm', '.ogv'}

		print(f"Scanning directory: {directory}")

		if recursive:
			walk_iter = walk(directory)
		else:
			walk_iter = [(directory, [], [])]
			if isdir(directory):
				_, _, files = next(iter(walk(directory)))
				walk_iter = [(directory, [], files)]

		for root, dirs, files in walk_iter:
			for file in files:
				_, ext = splitext(file)
				if ext.lower() not in video_extensions:
					continue

				file_path = join(root, file)
				result = self.parse(file_path)
				results.append(result)

		print(f"Found {len(results)} video files")

		# Write to output file if specified
		if output_file:
			output_lines = [f"Scanning directory: {directory}\n", f"Initialized MediaNameParser with library_path='{self.library_path}'"]
			for result in results:
				output_lines.append(f"\n{result.path}")
				if result.success:
					output_lines.append(f"  -> {result}")
				else:
					output_lines.append(f"  -> Failed: {result.path}")

			with open(output_file, 'w', encoding='utf-8') as f:
				f.write('\n'.join(output_lines))

			print(f"Results written to {output_file}")

		return results


if __name__ == "__main__":
	import sys

	# If path argument provided, scan that directory
	if len(sys.argv) > 1:
		path = sys.argv[1]
		if isdir(path):
			print(f"\nScanning directory: {path}\n")
			parser = MediaNameParser(library_path=path)
			results = parser.scan_directory(path, recursive=True)
			for result in results:
				print(f"{result.path}")
				print(f"  -> {result}\n")
			print(f"Found {len(results)} episodes")
		else:
			print(f"Error: Path is not a directory: {path}")
			sys.exit(1)
	else:
		# Default: run test suite
		parser = MediaNameParser()

		# Test cases: (path, library_path, expected_series, expected_season, expected_episode)
		test_cases = [
			# Prison Break case with release group folder
			("/media/net/nas181/Videos/Serien/Prison Break/Staffel 4/P.B.S04E03-FREAKS/Prison.Break.S04E03.German.dubbed.DL.WS.HDTVRiP.XviD-FREAKS/mdk-reaper-113-dl-hdtv.avi",
			"/media/net/nas181/Videos/Serien/",
			"Prison Break", 4, 3),

			# Fortitude with release group prefix and S##E## in release name
			("/Shows/Fortitude/Staffel 1/tvs-fortitude-s01e01-sed-dl-ithd-x264-101.mkv",
			"/Shows/",
			"Fortitude", 1, 1),

			# Walking Dead with standard notation
			("/TV/The Walking Dead/Season 01/The.Walking.Dead.S01E01.mkv",
			"/TV/",
			"The Walking Dead", 1, 1),

			# Magna Aura with flexible separator
			("/Series/Magna Aura/Staffel 1/Magna.Aura.s01e06.avi",
			"/Series/",
			"Magna Aura", 1, 6),

			# ##x## format (Emby pattern)
			("/TV/Breaking Bad/Season 1/Breaking.Bad.1x05.mkv",
			"/TV/",
			"Breaking Bad", 1, 5),

			# S##-E## format with dash
			("/TV/Game of Thrones/S01-E05.mkv",
			"/TV/",
			"Game of Thrones", 1, 5),

			# UPPERCASE S##E## format
			("/TV/Friends/FRIENDS.S01E10.mkv",
			"/TV/",
			"Friends", 1, 10),

			("/Serien/Overlord/Overlord.Ep.06.German.DTS.5.1.DL.1080p.BluRay.x264-AST4u.mkv",
			"/Serien/",
			"Overlord", 1, 6)
		]

		print("=" * 70)
		print("Testing Simple Media Name Parser with Emby.Naming Patterns")
		print("=" * 70)
		print()

		passed = 0
		failed = 0

		for path, lib_path, expected_series, expected_season, expected_episode in test_cases:
			parser = MediaNameParser(library_path=lib_path, mode=2)
			result = parser.parse(path)

			is_correct = (
				result.series_name == expected_series and
				result.season_number == expected_season and
				result.episode_number == expected_episode
			)

			status = "✓ PASS" if is_correct else "✗ FAIL"
			if is_correct:
				passed += 1
			else:
				failed += 1

			print(f"{status}: {expected_series} S{expected_season:02d}E{expected_episode:02d}")
			print(f"  Path: .../{'/'.join(path.split('/')[-4:])}")
			if not is_correct:
				result_str = f"{result.series_name} S{result.season_number:02d}E{result.episode_number:02d}" if result.success and result.season_number and result.episode_number else "Failed to parse"
				print(f"  Got:  {result_str}")
			print()
		print("=" * 70)
		print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
		print("=" * 70)

		# ========== MOVIE TESTS ==========
		print()
		print("=" * 70)
		print("Testing Movie Name Parser (Mode 1)")
		print("=" * 70)
		print()

		movie_test_cases = [
			("Movie.Name.2020.1080p.BluRay.x264-GROUP.mkv", "Movie Name", 2020),
			("The.Matrix.1999.mkv", "The Matrix", 1999),
			("Inception(2010).mkv", "Inception", 2010),
			("Interstellar_2014_720p.mkv", "Interstellar", 2014),
			("Unknown.Movie.mkv", "Unknown Movie", None),  # No year found
			("[2011.Odysee.im.Weltraum].mkv", "Odysee im Weltraum", 2011),  # Year at start, name after
			("Avatar-2009.mkv", "Avatar", 2009),
		]

		passed_movies = 0
		failed_movies = 0

		for filename, expected_name, expected_year in movie_test_cases:
			parser = MediaNameParser(mode=1)
			result = parser.parse(filename)

			is_correct = result.movie_name == expected_name and result.year == expected_year

			status = "✓ PASS" if is_correct else "✗ FAIL"
			if is_correct:
				passed_movies += 1
			else:
				failed_movies += 1

			year_str = f"({expected_year})" if expected_year else "(no year)"
			print(f"{status}: {expected_name} {year_str}")
			print(f"  File: {filename}")
			if not is_correct:
				year_str_got = f"({result.year})" if result.year else "(no year)"
				print(f"  Got:  {result.movie_name} {year_str_got}")
			print()

		print("=" * 70)
		print(f"Results: {passed_movies} passed, {failed_movies} failed out of {passed_movies + failed_movies} tests")
		print("=" * 70)
