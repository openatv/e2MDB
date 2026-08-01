########################################################################################################
# e2MDB Live/EPG prefill service configuration                                                         #
# -----------------------------------------------------------------------------------------------------#
# Stores manually selected prefill services in a separate JSON file instead of the Enigma2 settings     #
# line. This avoids long ConfigText values and keeps the settings file readable.                        #
########################################################################################################

from json import dump, load
from os import makedirs, rename
from os.path import dirname, exists, isfile
from time import time

from . import write_log


class E2MDBPrefillServices:
	"""Read and write the manual Live/EPG prefill service list as JSON."""

	MODULE_NAME = "[E2MDBPrefillServices]"
	CONFIG_FILE = "/etc/enigma2/e2mdb/prefill_services.json"
	VERSION = 1

	@classmethod
	def _log(cls, message):
		try:
			write_log(cls.MODULE_NAME, message)
		except Exception:
			print(cls.MODULE_NAME, message)

	@staticmethod
	def _unique(services):
		unique = []
		for service in services or []:
			service = (service or "").strip()
			if service and service not in unique:
				unique.append(service)
		return unique

	@staticmethod
	def _parse_text(value):
		value = (value or "").replace("\r", "\n").replace("|", "\n").replace(",", "\n")
		services = []
		for line in value.split("\n"):
			line = line.strip()
			if line and line not in services:
				services.append(line)
		return services

	@classmethod
	def _read_file(cls):
		if not isfile(cls.CONFIG_FILE):
			return None
		try:
			with open(cls.CONFIG_FILE, "r", encoding="utf-8") as handle:
				data = load(handle)
			if isinstance(data, dict):
				services = data.get("services", [])
			elif isinstance(data, list):
				services = data
			else:
				services = []
			return cls._unique(services)
		except Exception as err:
			cls._log(f"READ failed file='{cls.CONFIG_FILE}' error={err}")
			return None

	@classmethod
	def parse(cls, value=None):
		"""Return selected service references."""
		if value is not None:
			return cls._parse_text(value)

		services = cls._read_file()
		if services is not None:
			return services
		return []

	@classmethod
	def save(cls, services, reason="selection"):
		unique = cls._unique(services)
		payload = {
			"version": cls.VERSION,
			"updated": int(time()),
			"services": unique,
		}
		try:
			folder = dirname(cls.CONFIG_FILE)
			if folder and not exists(folder):
				makedirs(folder)
			tmp_path = cls.CONFIG_FILE + ".tmp"
			with open(tmp_path, "w", encoding="utf-8") as handle:
				dump(payload, handle, indent=2, sort_keys=True)
				handle.write("\n")
			rename(tmp_path, cls.CONFIG_FILE)
			cls._log(f"SAVE file='{cls.CONFIG_FILE}' selected={len(unique)} reason={reason}")
		except Exception as err:
			cls._log(f"SAVE failed file='{cls.CONFIG_FILE}' selected={len(unique)} error={err}")
		return unique

	@classmethod
	def get_storage_path(cls):
		return cls.CONFIG_FILE
