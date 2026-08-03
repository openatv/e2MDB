########################################################################################################
# e2MDB by Mr.Servo @OpenATV and jbleyel @OpenATV (c) 2026 - skin & design by stein17 @OpenATV         #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from os.path import basename, dirname, exists, isfile, join, splitext
from re import search, sub

# PLUGIN IMPORTS
# Only e2mdbd.py imports this module, always as a plain top-level import (no
# parent package) - so relative imports here would never resolve. Absolute
# imports only, matching how the daemon actually loads this file.
from E2MDBDatabase import mediadb
from MediaNameParser import MediaNameParser
from E2MDBRecordingParser import parse_recording as default_parse_recording


class E2MDBBackendMetadataScanner:
	"""Backend-safe metadata scanner facade used by e2mdbd.

	All daemon recording/media scans must enter through this class so path
	filtering, TS META/EIT/CUTS parsing and MediaNameParser handling stay in the
	same module as the historical v16 scanner logic.  The daemon only orchestrates
	jobs and stores the returned scan items.
	"""

	TS_RECORDING_EXTS = (".ts", ".stream")
	MEDIA_FILE_EXTS = (".mkv", ".avi", ".mp4", ".m4v", ".mpg", ".mpeg", ".mov", ".wmv", ".flv", ".iso", ".m2ts", ".mts")
	VIDEO_EXTS = TS_RECORDING_EXTS + MEDIA_FILE_EXTS
	NON_MEDIA_SIDECAR_EXTS = (".meta", ".eit", ".cuts", ".cutsr", ".ap", ".sc", ".txt", ".nfo", ".srt", ".sub", ".idx", ".jpg", ".jpeg", ".png", ".gif", ".log", ".tmp", ".part")
	EXCLUDED_SCAN_DIRS = ("__pycache__", ".Trash", ".Trash-1000", "trash", "Trash", "trashcan", ".trashcan", "@eaDir", "lost+found")

	def __init__(self, parse_recording=None, media_name_parser=None, recording_parser_error=None, media_name_parser_error=None):
		self.parse_recording_func = parse_recording or default_parse_recording
		self.media_name_parser = media_name_parser or MediaNameParser
		self.recording_parser_error = recording_parser_error
		self.media_name_parser_error = media_name_parser_error
		self.mediadb_enabled = False
		self.mediadb_error = ""

	def configure(self, settings=None):
		settings = settings if isinstance(settings, dict) else {}
		cache = settings.get("cache", {}) if isinstance(settings.get("cache", {}), dict) else {}
		database = settings.get("database", {}) if isinstance(settings.get("database", {}), dict) else {}
		root = str(cache.get("root") or database.get("root") or "").strip()
		if not root:
			db_path = str(database.get("path") or "").strip()
			if db_path:
				root = dirname(db_path)
		if not root:
			root = "/media/hdd/e2MDB"
		self.set_mediadb_root(root)

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
				"short": item.get("short", item.get("description", "")),
				"extended": item.get("extended", item.get("extended_description", "")),
			})
			return {"success": True, "row_id": row_id}
		except Exception as err:
			self.mediadb_error = str(err)
			return {"success": False, "error": str(err)}

	def safe_int(self, value, default=0):
		try:
			return int(value)
		except Exception:
			return default

	def iso_from_timestamp(self, value):
		from time import gmtime, strftime
		try:
			value = int(value)
		except Exception:
			value = 0
		if value <= 0:
			return ""
		return strftime("%Y-%m-%dT%H:%M:%SZ", gmtime(value))

	def media_extension(self, path):
		return splitext(str(path or ""))[1].lower()

	def is_known_media_file(self, path):
		name = basename(str(path or ""))
		if not name or name.startswith("."):
			return False
		return self.media_extension(path) in self.VIDEO_EXTS

	def is_ts_recording_file(self, path):
		return self.media_extension(path) in self.TS_RECORDING_EXTS

	def media_scan_kind(self, path):
		if self.is_ts_recording_file(path):
			return "ts_recording"
		if self.is_known_media_file(path):
			return "media_file"
		return "ignored"

	def clean_title_from_filename(self, path):
		name = splitext(basename(path))[0]
		name = sub(r"[._]+", " ", name)
		name = sub(r"\s+", " ", name).strip()
		return name or basename(path)

	def clean_openatv_recording_title(self, path):
		text = self.clean_title_from_filename(path)
		patterns = (
			r"^\d{8}\s+\d{3,4}\s*-\s*[^-]+\s*-\s*(.+)$",
			r"^\d{4}[-.]\d{2}[-.]\d{2}\s+\d{1,2}[:.]\d{2}\s*-\s*[^-]+\s*-\s*(.+)$",
		)
		for pattern in patterns:
			match = search(pattern, text)
			if match:
				candidate = sub(r"\s+", " ", match.group(1)).strip(" -_.")
				if candidate:
					return candidate
		return text

	def parser_path_for_recording(self, media_path):
		if not self.is_ts_recording_file(media_path):
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
		mode = self.safe_int(mode, 0)
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
		mode = self.safe_int(mode, 0)
		return {
			0: "exclude",
			1: "movie",
			2: "series",
			3: "movie_series",
			4: "anime_series",
			5: "manga_series",
			6: "anime_movie",
			7: "manga_movie",
		}.get(mode, "unknown")

	def parse_season_episode_text(self, value):
		text = str(value or "")
		for pattern in (
			r"(?i)[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})",
			r"(?i)\b(\d{1,2})x(\d{1,3})\b",
			r"(?i)(?:staffel|season)\s*(\d{1,2}).{0,30}(?:folge|episode|ep\.?|e)\s*(\d{1,3})",
		):
			match = search(pattern, text)
			if match:
				return self.safe_int(match.group(1), 0), self.safe_int(match.group(2), 0)
		return 0, 0

	def clean_series_title(self, value):
		text = self.clean_title_from_filename(str(value or ""))
		for pattern in (
			r"(?i)\b[Ss]\d{1,2}[ ._-]*[Ee]\d{1,3}\b",
			r"(?i)\b\d{1,2}x\d{1,3}\b",
			r"(?i)\b(?:staffel|season)\s*\d{1,2}.*$",
		):
			match = search(pattern, text)
			if match:
				text = text[:match.start()]
				break
		text = sub(r"(?i)\b(german|english|multi|dubbed|subbed|720p|1080p|2160p|web|webrip|web-dl|hdtv|bluray|x264|x265|h264|h265|hevc|ac3|dts)\b.*$", "", text)
		return sub(r"\s+", " ", text).strip(" -_.")

	def media_type_from_path_mode(self, path_mode, title="", path=""):
		path_mode = self.safe_int(path_mode, 0)
		if path_mode == 1:
			return "movie"
		if path_mode == 2:
			return "series"
		if path_mode == 4:
			return "anime_series"
		if path_mode == 5:
			return "manga_series"
		if path_mode == 6:
			return "anime_movie"
		if path_mode == 7:
			return "manga_movie"
		text = " ".join([str(title or ""), str(path or "")])
		if self.parse_season_episode_text(text) != (0, 0):
			return "series"
		return "multi"

	def recording_name_info_from_clean_title(self, clean_title, path_mode=0):
		clean_title = str(clean_title or "").strip()
		path_mode = self.safe_int(path_mode, 0)
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
				"movie": {},
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
				"movie": {},
			}
		return {
			"media_type": "movie" if path_mode in (0, 1, 3, 6, 7) else self.media_type_from_path_mode(path_mode, clean_title, clean_title),
			"series_title": "",
			"movie_title": clean_title,
			"season_no": 0,
			"episode_no": 0,
			"year": 0,
			"episode": {},
			"movie": {"success": True, "movie_name": clean_title, "year": 0, "container": "ts"},
		}

	def _parser_dict_from_episode(self, parsed):
		if not parsed:
			return {}
		return {
			"success": bool(getattr(parsed, "success", False)),
			"series_name": getattr(parsed, "series_name", None) or "",
			"season_number": self.safe_int(getattr(parsed, "season_number", 0), 0),
			"episode_number": self.safe_int(getattr(parsed, "episode_number", 0), 0),
			"ending_episode_number": self.safe_int(getattr(parsed, "ending_episode_number", 0), 0),
			"year": self.safe_int(getattr(parsed, "year", 0), 0),
			"is_by_date": bool(getattr(parsed, "is_by_date", False)),
			"container": getattr(parsed, "container", None) or "",
		}

	def _parser_dict_from_movie(self, parsed):
		if not parsed:
			return {}
		return {
			"success": bool(getattr(parsed, "success", False)),
			"movie_name": getattr(parsed, "movie_name", None) or "",
			"year": self.safe_int(getattr(parsed, "year", 0), 0),
			"container": getattr(parsed, "container", None) or "",
		}

	def parse_media_name_for_scan(self, media_path, path_item, fallback_title=""):
		mode = self.safe_int(path_item.get("mode", 0), 0) if isinstance(path_item, dict) else 0
		root_path = str(path_item.get("path") or "") if isinstance(path_item, dict) else ""
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
			"movie": {},
		}
		if self.media_name_parser is None:
			return result
		try:
			if mode in (2, 4, 5):
				parsed_ep = self.media_name_parser(library_path=root_path, mode=2).parse_episode(parser_media_path)
				result["episode"] = self._parser_dict_from_episode(parsed_ep)
				if getattr(parsed_ep, "success", False):
					result["series_title"] = getattr(parsed_ep, "series_name", None) or ""
					result["season_no"] = self.safe_int(getattr(parsed_ep, "season_number", 0), 0)
					result["episode_no"] = self.safe_int(getattr(parsed_ep, "episode_number", 0), 0)
					result["year"] = self.safe_int(getattr(parsed_ep, "year", 0), 0)
					return result
			if mode in (1, 6, 7):
				parsed_movie = self.media_name_parser(library_path=root_path, mode=1).parse_movie(parser_media_path)
				result["movie"] = self._parser_dict_from_movie(parsed_movie)
				if getattr(parsed_movie, "success", False):
					result["movie_title"] = getattr(parsed_movie, "movie_name", None) or ""
					result["year"] = self.safe_int(getattr(parsed_movie, "year", 0), 0)
					return result
			parsed_ep = self.media_name_parser(library_path=root_path, mode=2).parse_episode(parser_media_path)
			result["episode"] = self._parser_dict_from_episode(parsed_ep)
			if getattr(parsed_ep, "success", False) and getattr(parsed_ep, "series_name", None):
				result["media_type"] = "series"
				result["series_title"] = getattr(parsed_ep, "series_name", None) or ""
				result["season_no"] = self.safe_int(getattr(parsed_ep, "season_number", 0), 0)
				result["episode_no"] = self.safe_int(getattr(parsed_ep, "episode_number", 0), 0)
				result["year"] = self.safe_int(getattr(parsed_ep, "year", 0), 0)
				return result
			parsed_movie = self.media_name_parser(library_path=root_path, mode=1).parse_movie(parser_media_path)
			result["movie"] = self._parser_dict_from_movie(parsed_movie)
			if getattr(parsed_movie, "success", False):
				result["media_type"] = "movie"
				result["movie_title"] = getattr(parsed_movie, "movie_name", None) or ""
				result["year"] = self.safe_int(getattr(parsed_movie, "year", 0), 0)
		except Exception as err:
			result["parser_error"] = str(err)
		return result

	def unique_list(self, items):
		result = []
		seen = set()
		for item in items:
			text = str(item or "").strip()
			if not text:
				continue
			key = text.lower()
			if key in seen:
				continue
			seen.add(key)
			result.append(text)
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
			"paths": [],
		}
		for item in scan_paths:
			if checkpoint and callable(checkpoint):
				try:
					checkpoint()
				except Exception:
					pass
			path = str(item.get("path") or "") if isinstance(item, dict) else str(item or "")
			mode = self.safe_int(item.get("mode", 0), 0) if isinstance(item, dict) else 0
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
				"errors": [],
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
						dirs[:] = [name for name in dirs if name not in self.EXCLUDED_SCAN_DIRS and not name.startswith(".")]
						for filename in files:
							full_path = join(root, filename)
							if self.is_known_media_file(full_path):
								entry["video_files"] += 1
								entry["supported_media_files"] += 1
								if self.is_ts_recording_file(full_path):
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
				dirs[:] = [name for name in dirs if name not in self.EXCLUDED_SCAN_DIRS and not name.startswith(".")]
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
		# META/EIT/CUTS/TXT sidecars are not TS-only.  Every known media file
		# enters the same metadata parser; the extension only decides source_type.
		if self.parse_recording_func is None:
			parsed = {"path": media_path, "parse_error": self.native_parser_missing_message()}
		else:
			try:
				parsed = self.parse_recording_func(media_path)
			except Exception as err:
				parsed = {"path": media_path, "parse_error": str(err)}
		item = self.build_scan_item(media_path, path_item, parsed)
		item["mediadb"] = self.upsert_mediadb(item)
		return item

	def build_scan_item(self, media_path, path_item, parsed):
		from os.path import getmtime, getsize
		parsed = parsed if isinstance(parsed, dict) else {}
		source_type = "recording" if self.is_ts_recording_file(media_path) else "media_file"
		filename_title = self.clean_openatv_recording_title(media_path) if source_type == "recording" else self.clean_title_from_filename(media_path)
		parsed_title = str(parsed.get("title") or "").strip()
		if source_type == "recording" and parsed_title:
			parsed_title = self.clean_openatv_recording_title(parsed_title)
		title = str(parsed_title or filename_title or basename(media_path)).strip()
		description = str(parsed.get("short") or parsed.get("description") or "").strip()
		extended_description = str(parsed.get("extended") or parsed.get("extended_description") or description).strip()
		size_bytes = getsize(media_path) if isfile(media_path) else 0
		mtime = self.safe_int(getmtime(media_path), 0) if isfile(media_path) else 0
		recorded_at = self.safe_int(parsed.get("recorded_at"), 0)
		duration_seconds = self.safe_int(parsed.get("duration_seconds"), 0)
		path_mode = self.safe_int(path_item.get("mode", 0), 0)
		name_info = self.parse_media_name_for_scan(media_path, path_item, title)
		if source_type == "recording":
			filename_info = self.recording_name_info_from_clean_title(filename_title, path_mode)
			if filename_info.get("media_type") in ("movie", "series", "anime_series", "manga_series", "anime_movie", "manga_movie"):
				for key, value in filename_info.items():
					if key not in name_info or not name_info.get(key):
						name_info[key] = value
		estimated_media_type = str(name_info.get("media_type") or self.media_type_from_path_mode(path_mode, title=title, path=media_path))
		season_no = self.safe_int(name_info.get("season_no"), 0)
		episode_no = self.safe_int(name_info.get("episode_no"), 0)
		if not season_no and not episode_no:
			season_no, episode_no = self.parse_season_episode_text(" ".join([media_path, title, description]))
		series_title = str(name_info.get("series_title") or "").strip()
		movie_title = str(name_info.get("movie_title") or "").strip()
		provider_title = series_title if estimated_media_type in ("series", "anime_series", "manga_series") and series_title else (movie_title or title)
		if estimated_media_type in ("series", "anime_series", "manga_series") and not series_title:
			series_title = self.clean_series_title(title or media_path)
		search_candidates = self.unique_list((provider_title, series_title, movie_title, title, filename_title, description, extended_description))
		scanner_used = "E2MDBBackendMetadataScanner.metadata_sidecar_parser" if source_type == "recording" else "E2MDBBackendMetadataScanner.media_name_parser"
		parse_error = str(parsed.get("parse_error") or "")
		return {
			"id": self.make_recording_id(media_path),
			"version": 1,
			"type": source_type,
			"source_type": source_type,
			"scanner_used": scanner_used,
			"metadata_scanner": scanner_used,
			"path_mode": path_mode,
			"path_mode_label": self.path_mode_label(path_mode),
			"media_family": self.mode_family_from_path_mode(path_mode),
			"estimated_media_type": estimated_media_type,
			"provider_media_type": estimated_media_type,
			"series_title": series_title,
			"movie_title": movie_title,
			"provider_title": provider_title,
			"name_parser": name_info,
			"year": self.safe_int(name_info.get("year"), 0),
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
			"short": description,
			"extended": extended_description,
			"description": description,
			"extended_description": extended_description,
			"service_ref": parsed.get("service_ref") or "",
			"recorded_at": recorded_at,
			"recorded_at_iso": self.iso_from_timestamp(recorded_at),
			"duration_seconds": duration_seconds,
			"search_candidates": search_candidates,
			"parse_error": parse_error,
			"scan_status": "error" if parse_error else "ok",
		}
