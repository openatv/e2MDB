########################################################################################################
# e2MDB Live/EPG ignore pattern configuration                                                          #
# -----------------------------------------------------------------------------------------------------#
# Stores ignore pattern lists in JSON files under /etc/enigma2/e2mdb instead of the Enigma2 settings file.    #
########################################################################################################

from json import dump, load
from os import makedirs, rename
from os.path import dirname, exists, isfile
from time import time

from . import write_log


class E2MDBIgnorePatterns:
	"""Read and write JSON-backed Live/EPG ignore pattern lists."""

	MODULE_NAME = "[E2MDBIgnorePatterns]"
	VERSION = 1
	EPG_TITLE = "epg-title"
	SERVICE_NAME = "service-name"
	FOLDER_NAME = "folder-name"
	CONFIG_FILES = {
		EPG_TITLE: "/etc/enigma2/e2mdb/ignore_epg_titles.json",
		SERVICE_NAME: "/etc/enigma2/e2mdb/ignore_service_names.json",
		FOLDER_NAME: "/etc/enigma2/e2mdb/ignore_folder_names.json",
	}
	DEFAULTS = {
		EPG_TITLE: [],
		SERVICE_NAME: [],
		FOLDER_NAME: [],
	}

	@classmethod
	def _log(cls, message):
		try:
			write_log(cls.MODULE_NAME, message)
		except Exception:
			print(cls.MODULE_NAME, message)

	@classmethod
	def _config_file(cls, kind):
		return cls.CONFIG_FILES.get(kind) or cls.CONFIG_FILES[cls.EPG_TITLE]

	@classmethod
	def _unique(cls, patterns):
		unique = []
		for pattern in patterns or []:
			pattern = str(pattern or "").strip()
			if pattern and pattern not in unique:
				unique.append(pattern)
		return unique

	@classmethod
	def _parse_text(cls, value):
		value = str(value or "").replace("\r", "\n").replace("|", "\n").replace(";", "\n").replace(",", "\n")
		return cls._unique([line.strip() for line in value.split("\n")])

	@classmethod
	def _read_file(cls, kind):
		path = cls._config_file(kind)
		if not isfile(path):
			return None
		try:
			with open(path, "r", encoding="utf-8") as handle:
				data = load(handle)
			if isinstance(data, dict):
				patterns = data.get("patterns", [])
			elif isinstance(data, list):
				patterns = data
			else:
				patterns = []
			return cls._unique(patterns)
		except Exception as err:
			cls._log(f"READ failed kind='{kind}' file='{path}' error={err}")
			return None

	@classmethod
	def parse(cls, kind, value=None):
		if value is not None:
			return cls._parse_text(value)

		patterns = cls._read_file(kind)
		if patterns is not None:
			return patterns

		defaults = cls.DEFAULTS.get(kind, [])
		if defaults:
			return cls.save(kind, defaults, reason="defaults")
		return []

	@classmethod
	def save(cls, kind, patterns, reason="selection"):
		unique = cls._unique(patterns)
		path = cls._config_file(kind)
		payload = {
			"version": cls.VERSION,
			"kind": kind,
			"updated": int(time()),
			"patterns": unique,
		}
		try:
			folder = dirname(path)
			if folder and not exists(folder):
				makedirs(folder)
			tmp_path = path + ".tmp"
			with open(tmp_path, "w", encoding="utf-8") as handle:
				dump(payload, handle, indent=2, sort_keys=True)
				handle.write("\n")
			rename(tmp_path, path)
			cls._log(f"SAVE kind='{kind}' file='{path}' patterns={len(unique)} reason={reason}")
		except Exception as err:
			cls._log(f"SAVE failed kind='{kind}' file='{path}' patterns={len(unique)} error={err}")
		return unique

	@classmethod
	def get_storage_path(cls, kind):
		return cls._config_file(kind)
