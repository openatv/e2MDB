# -*- coding: utf-8 -*-
"""
e2MDB recording sidecar parser.

Clean-start backend scanner parser for OpenATV recordings.  This module does
not use Enigma2 runtime objects and does not require the old native C EIT
parser.  It reads only the fields e2MDB needs for MediaDB/timer support and
backend enrichment:

- title
- short description
- extended description
- duration from EIT, or from CUTS as fallback

META and TXT are simple text sidecars and are read directly in Python.
"""

from os.path import exists, isfile, splitext
from struct import unpack

EIT_SHORT_EVENT_DESCRIPTOR = 0x4d
EIT_EXTENDED_EVENT_DESCRIPOR = 0x4e


class RecordingParserUnavailable(RuntimeError):
	pass


def _decode_text(data):
	"""Decode DVB/OpenATV descriptor text defensively."""
	if not data:
		return ""
	# DVB strings often carry one encoding marker byte.  The historical v16 helper
	# skipped that byte; keep this behaviour but fall back to the full payload if
	# stripping would make the text empty.
	candidates = []
	if len(data) > 1:
		candidates.append(data[1:])
	candidates.append(data)
	for candidate in candidates:
		for encoding in ("utf-8", "latin-1"):
			try:
				text = candidate.decode(encoding, errors="ignore").strip("\x00\r\n\t ")
			except Exception:
				text = ""
			if text:
				return " ".join(text.split())
	return ""


def _bcd2dec(value):
	try:
		value = int(value)
	except Exception:
		return 0
	tens = (value >> 4) & 0x0f
	units = value & 0x0f
	return tens * 10 + units


def _read_text_file(path):
	for encoding in ("utf-8", "latin-1"):
		try:
			with open(path, "r", encoding=encoding, errors="ignore") as handle:
				return handle.read().replace("\x00", "").strip()
		except Exception:
			continue
	return ""


def _sidecar_candidates(path, suffix):
	base, _ext = splitext(path)
	if suffix == ".eit":
		return (f"{base}.eit", f"{path}.eit")
	if suffix == ".meta":
		return (f"{path}.meta", f"{base}.meta")
	if suffix == ".cuts":
		return (f"{path}.cuts", f"{base}.cuts")
	if suffix == ".txt":
		return (f"{path}.txt", f"{base}.txt")
	return (f"{path}{suffix}",)


def _first_existing_sidecar(path, suffix):
	for candidate in _sidecar_candidates(path, suffix):
		if isfile(candidate):
			return candidate
	return _sidecar_candidates(path, suffix)[0]


class EITFileReader:
	def __init__(self, filename: str):
		self.filename = filename
		self.title = ""
		self.short = ""
		self.extended = ""
		self.duration = 0
		self.data = None
		self.error = ""
		self._read_file()

	def _read_file(self):
		try:
			with open(self.filename, "rb") as handle:
				self.data = handle.read()
		except OSError as error:
			self.error = f"reading '{self.filename}' / {str(error)}"
			return

		if not self.data or len(self.data) < 12:
			self.error = "file too small"
			return

		self._parse()

	def _parse(self):
		# Bytes 7-9: duration (hh:mm:ss BCD)
		duration_h = _bcd2dec(self.data[7])
		duration_m = _bcd2dec(self.data[8])
		duration_s = _bcd2dec(self.data[9])
		self.duration = duration_h * 3600 + duration_m * 60 + duration_s

		# Bytes 10-11: flags and descriptors_loop_length
		descriptors_loop_length = ((self.data[10] & 0x0f) << 8) + self.data[11]
		offset = 12
		descriptor_end = min(offset + descriptors_loop_length, len(self.data))

		while offset + 2 <= descriptor_end and offset + 2 <= len(self.data):
			tag = self.data[offset]
			offset += 1
			length = self.data[offset]
			offset += 1
			if offset + length > len(self.data):
				break
			descriptor_data = self.data[offset:offset + length]
			if tag == EIT_SHORT_EVENT_DESCRIPTOR:
				self._parse_short_descriptor(descriptor_data)
			elif tag == EIT_EXTENDED_EVENT_DESCRIPOR:
				self._parse_extended_descriptor(descriptor_data)
			offset += length

	def _parse_short_descriptor(self, data):
		if len(data) < 5:
			return
		# Bytes 0-2: language code. Byte 3: event_name_length.
		event_name_len = data[3]
		if len(data) < 4 + event_name_len:
			return
		event_name_data = data[4:4 + event_name_len]
		self.title = _decode_text(event_name_data)
		offset = 4 + event_name_len
		if offset < len(data):
			text_len = data[offset]
			if len(data) >= offset + 1 + text_len:
				self.short = _decode_text(data[offset + 1:offset + 1 + text_len])

	def _parse_extended_descriptor(self, data):
		if len(data) < 6:
			return
		# Bytes 0-2: language code. Byte 3 contains descriptor numbers.
		# Byte 4: length_of_items. After items follows text_length + text.
		items_len = data[4]
		offset = 5 + items_len
		if offset >= len(data):
			return
		text_len = data[offset]
		if len(data) >= offset + 1 + text_len:
			text = _decode_text(data[offset + 1:offset + 1 + text_len])
			if text:
				if self.extended:
					self.extended += " "
				self.extended += text

	def get_data(self):
		return {
			"title": self.title,
			"short": self.short,
			"extended": self.extended,
			"duration": self.duration,
		}


def parse_meta(path):
	meta_path = _first_existing_sidecar(path, ".meta")
	result = {"path": meta_path, "exists": isfile(meta_path), "service_ref": "", "title": "", "description": "", "recorded_at": 0, "tags": ""}
	if not result["exists"]:
		return result
	text = _read_text_file(meta_path)
	lines = [line.strip() for line in text.splitlines()]
	if len(lines) > 0:
		result["service_ref"] = lines[0]
	if len(lines) > 1:
		result["title"] = lines[1]
	if len(lines) > 2:
		result["description"] = lines[2]
	if len(lines) > 3:
		try:
			result["recorded_at"] = int(lines[3])
		except Exception:
			result["recorded_at"] = 0
	if len(lines) > 4:
		result["tags"] = lines[4]
	return result


def parse_txt(path):
	txt_path = _first_existing_sidecar(path, ".txt")
	return {"path": txt_path, "exists": isfile(txt_path), "text": _read_text_file(txt_path) if isfile(txt_path) else ""}


def parse_eit(path):
	eit_path = _first_existing_sidecar(path, ".eit")
	result = {"path": eit_path, "exists": isfile(eit_path), "eit_title": "", "eit_short_description": "", "eit_extended_description": "", "duration_seconds": 0, "error": ""}
	if not result["exists"]:
		return result
	reader = EITFileReader(eit_path)
	data = reader.get_data()
	result.update({
		"title": data.get("title", ""),
		"short": data.get("short", ""),
		"extended": data.get("extended", ""),
		"eit_title": data.get("title", ""),
		"eit_short_description": data.get("short", ""),
		"eit_extended_description": data.get("extended", ""),
		"duration_seconds": int(data.get("duration") or 0),
		"error": reader.error,
	})
	return result


def parse_cuts(path):
	cuts_path = _first_existing_sidecar(path, ".cuts")
	result = {"path": cuts_path, "exists": isfile(cuts_path), "entries": [], "duration_seconds": 0, "error": ""}
	if not result["exists"]:
		return result
	try:
		with open(cuts_path, "rb") as handle:
			while True:
				chunk = handle.read(12)
				if len(chunk) < 12:
					break
				pts, cue = unpack(">QI", chunk)
				result["entries"].append({"pts": int(pts), "type": int(cue)})
				if cue == 5 and pts > 0:
					result["duration_seconds"] = int(pts / 90000)
	except Exception as error:
		result["error"] = str(error)
	return result


def parse_recording(path):
	"""Return the scanner values e2MDB needs, independent of their sidecar source."""
	try:
		# Priority is intentionally value-based: EIT first, then META, then TXT.
		# The backend/result DB should store usable values, not provenance noise.
		eit = parse_eit(path)
		meta = parse_meta(path)
		txt = parse_txt(path)
		cuts = parse_cuts(path)
		title = (eit.get("title") or meta.get("title") or "").strip()
		short = (eit.get("short") or meta.get("description") or txt.get("text") or "").strip()
		extended = (eit.get("extended") or meta.get("description") or txt.get("text") or "").strip()
		duration_seconds = int(eit.get("duration_seconds") or 0)
		if not duration_seconds:
			duration_seconds = int(cuts.get("duration_seconds") or 0)
		return {
			"path": path,
			"title": title,
			"short": short,
			"extended": extended,
			"description": short,
			"extended_description": extended,
			"duration_seconds": duration_seconds,
			"service_ref": meta.get("service_ref") or "",
			"recorded_at": meta.get("recorded_at") or 0,
			"parse_error": eit.get("error") or cuts.get("error") or "",
		}
	except Exception as error:
		return {
			"path": path,
			"title": "",
			"short": "",
			"extended": "",
			"description": "",
			"extended_description": "",
			"duration_seconds": 0,
			"service_ref": "",
			"recorded_at": 0,
			"parse_error": str(error),
		}
