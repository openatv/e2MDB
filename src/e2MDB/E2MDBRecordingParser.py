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

from os.path import isfile, splitext
from struct import unpack
from unicodedata import normalize

EIT_SHORT_EVENT_DESCRIPTOR = 0x4d
EIT_EXTENDED_EVENT_DESCRIPOR = 0x4e

# ETSI EN 300 468 Annex A: single leading control byte selects the character
# table for the rest of the descriptor text. Table ids 0x01-0x0B map to
# ISO/IEC 8859-x; the id is table number + 4 (e.g. 0x05 -> ISO 8859-9).
_ISO8859_TABLE_CODECS = {
	1: "iso8859-5", 2: "iso8859-6", 3: "iso8859-7", 4: "iso8859-8", 5: "iso8859-9", 6: "iso8859-10",
	7: "iso8859-11", 9: "iso8859-13", 10: "iso8859-14", 11: "iso8859-15"
}
# 0x10 is followed by a 2-byte table id addressing ISO/IEC 8859-1..16 directly.
_ISO8859_TRIPLET_CODECS = {n: f"iso8859-{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16)}

# ISO/IEC 6937 (the DVB default table when no control byte is present),
# single byte values 0xA0-0xFF -> Unicode code point. 0 marks unused slots.
# Ported from Enigma2's own lib/base/estring.cpp (iso6937[]).
_ISO6937_TABLE = (
	0x00A0, 0x00A1, 0x00A2, 0x00A3, 0x20AC, 0x00A5, 0x0000, 0x00A7, 0x00A4, 0x2018, 0x201C, 0x00AB, 0x2190, 0x2191, 0x2192, 0x2193,
	0x00B0, 0x00B1, 0x00B2, 0x00B3, 0x00D7, 0x00B5, 0x00B6, 0x00B7, 0x00F7, 0x2019, 0x201D, 0x00BB, 0x00BC, 0x00BD, 0x00BE, 0x00BF,
	0x0000, 0xE002, 0xE003, 0xE004, 0xE005, 0xE006, 0xE007, 0xE008, 0xE009, 0xE00C, 0xE00A, 0xE00B, 0x0000, 0xE00D, 0xE00E, 0xE00F,
	0x2015, 0x00B9, 0x00AE, 0x00A9, 0x2122, 0x266A, 0x00AC, 0x00A6, 0x0000, 0x0000, 0x0000, 0x0000, 0x215B, 0x215C, 0x215D, 0x215E,
	0x2126, 0x00C6, 0x0110, 0x00AA, 0x0126, 0x0000, 0x0132, 0x013F, 0x0141, 0x00D8, 0x0152, 0x00BA, 0x00DE, 0x0166, 0x014A, 0x0149,
	0x0138, 0x00E6, 0x0111, 0x00F0, 0x0127, 0x0131, 0x0133, 0x0140, 0x0142, 0x00F8, 0x0153, 0x00DF, 0x00FE, 0x0167, 0x014B, 0x00AD
)

# ISO/IEC 6937 non-spacing accents (0xC1-0xCF): the accent byte plus the
# following base-letter byte together select the precomposed code point
# (e.g. 0xC8 diaeresis + 'o' -> 'ö'). Also ported from estring.cpp
# (doVideoTexSuppl()); this is what was missing and broke German umlauts.
_ISO6937_DIACRITICS = {
	0xC1: {0x61: 224, 0x41: 192, 0x65: 232, 0x45: 200, 0x69: 236, 0x49: 204, 0x6f: 242, 0x4f: 210, 0x75: 249, 0x55: 217},
	0xC2: {0x20: 180, 0x61: 225, 0x41: 193, 0x65: 233, 0x45: 201, 0x69: 237, 0x49: 205, 0x6f: 243, 0x4f: 211, 0x75: 250, 0x55: 218,
		0x79: 253, 0x59: 221, 0x63: 263, 0x43: 262, 0x6c: 314, 0x4c: 313, 0x6e: 324, 0x4e: 323, 0x72: 341, 0x52: 340,
		0x73: 347, 0x53: 346, 0x7a: 378, 0x5a: 377},
	0xC3: {0x61: 226, 0x41: 194, 0x65: 234, 0x45: 202, 0x69: 238, 0x49: 206, 0x6f: 244, 0x4f: 212, 0x75: 251, 0x55: 219,
		0x79: 375, 0x59: 374, 0x63: 265, 0x43: 264, 0x67: 285, 0x47: 284, 0x68: 293, 0x48: 292, 0x6a: 309, 0x4a: 308,
		0x73: 349, 0x53: 348, 0x77: 373, 0x57: 372},
	0xC4: {0x61: 227, 0x41: 195, 0x6e: 241, 0x4e: 209, 0x69: 297, 0x49: 296, 0x6f: 245, 0x4f: 213, 0x75: 361, 0x55: 360},
	0xC5: {0x20: 175, 0x41: 256, 0x61: 257, 0x45: 274, 0x65: 275, 0x49: 298, 0x69: 299, 0x4f: 332, 0x6f: 333},
	0xC6: {0x20: 728, 0x61: 259, 0x41: 258, 0x67: 287, 0x47: 286, 0x75: 365, 0x55: 364},
	0xC7: {0x20: 729, 0x63: 267, 0x43: 266, 0x65: 279, 0x45: 278, 0x67: 289, 0x47: 288, 0x5a: 379, 0x49: 304, 0x7a: 380},
	0xC8: {0x20: 168, 0x61: 228, 0x41: 196, 0x65: 235, 0x45: 203, 0x69: 239, 0x49: 207, 0x6f: 246, 0x4f: 214,
		0x75: 252, 0x55: 220, 0x79: 255, 0x59: 376},
	0xCA: {0x20: 730, 0x61: 229, 0x41: 197, 0x75: 367, 0x55: 366},
	0xCB: {0x63: 231, 0x43: 199, 0x67: 291, 0x47: 290, 0x6b: 311, 0x4b: 310, 0x6c: 316, 0x4c: 315, 0x6e: 326, 0x4e: 325,
		0x72: 343, 0x52: 342, 0x73: 351, 0x53: 350, 0x74: 355, 0x54: 354},
	0xCD: {0x20: 733, 0x6f: 337, 0x4f: 336, 0x75: 369, 0x55: 368},
	0xCE: {0x20: 731, 0x61: 261, 0x41: 260, 0x65: 281, 0x45: 280, 0x69: 303, 0x49: 302, 0x75: 371, 0x55: 370},
	0xCF: {0x20: 711, 0x63: 269, 0x43: 268, 0x64: 271, 0x44: 270, 0x65: 283, 0x45: 282, 0x6c: 318, 0x4c: 317,
		0x6e: 328, 0x4e: 327, 0x72: 345, 0x52: 344, 0x73: 353, 0x53: 352, 0x74: 357, 0x54: 356, 0x7a: 382, 0x5a: 381}
}


class RecordingParserUnavailable(RuntimeError):
	pass


def _decode_iso6937(data):
	"""Decode DVB default-table text (ISO/IEC 6937, EN 300 468 Annex A.2)."""
	chars = []
	i = 0
	length = len(data)
	while i < length:
		byte = data[i]
		if byte < 0xA0:
			if byte:
				chars.append(chr(byte))
			i += 1
			continue
		combo = _ISO6937_DIACRITICS.get(byte)
		code = combo.get(data[i + 1]) if combo and i + 1 < length else None
		if code:
			chars.append(chr(code))
			i += 2
			continue
		code = _ISO6937_TABLE[byte - 0xA0]
		if code:
			chars.append(chr(code))
		i += 1
	return "".join(chars)


def _decode_text(data):
	"""Decode DVB/OpenATV descriptor text (EN 300 468 Annex A encoding rules)."""
	if not data:
		return ""

	marker = data[0]
	payload = data
	codec = None
	iso6937 = False

	if 0x01 <= marker <= 0x0B:
		codec = _ISO8859_TABLE_CODECS.get(marker)
		payload = data[1:]
	elif marker == 0x10 and len(data) >= 3:
		codec = _ISO8859_TRIPLET_CODECS.get((data[1] << 8) | data[2])
		payload = data[3:]
	elif marker == 0x11 or marker == 0x16:
		codec = "utf-16-be"
		payload = data[1:]
	elif marker == 0x15:
		codec = "utf-8"
		payload = data[1:]
	elif marker == 0x17:
		codec = "utf-16-le"
		payload = data[1:]
	elif marker < 0x20:
		# Other/reserved control bytes: nothing sane to decode, only drop the marker.
		payload = data[1:]
		iso6937 = True
	else:
		# No control byte: DVB default table is ISO/IEC 6937, not Latin-1/UTF-8.
		iso6937 = True

	try:
		if codec:
			text = payload.decode(codec, errors="ignore")
		elif iso6937:
			text = _decode_iso6937(payload)
		else:
			text = payload.decode("latin-1", errors="ignore")
	except Exception:
		text = payload.decode("latin-1", errors="ignore")

	text = normalize("NFC", text).strip("\x00\r\n\t ")
	return " ".join(text.split())


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
	candidates = {
		".eit": (f"{base}.eit", f"{path}.eit"),
		".meta": (f"{path}.meta", f"{base}.meta"),
		".cuts": (f"{path}.cuts", f"{base}.cuts"),
		".txt": (f"{path}.txt", f"{base}.txt"),
	}
	return candidates.get(suffix, (f"{path}{suffix}",))


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
		if self.data:
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
		title = _decode_text(event_name_data)
		if title:
			self.title = title
		offset = 4 + event_name_len
		if offset < len(data):
			text_len = data[offset]
			if len(data) >= offset + 1 + text_len:
				short = _decode_text(data[offset + 1:offset + 1 + text_len])
				if short:
					self.short = short

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
			"short_desc": self.short,
			"extended_desc": self.extended,
			"duration": self.duration
		}


def parse_meta(path):
	meta_path = _first_existing_sidecar(path, ".meta")
	meta_exists = isfile(meta_path)
	result = {"path": meta_path, "exists": meta_exists}
	if meta_exists:
		text = _read_text_file(meta_path)
		lines = [line.strip() for line in text.splitlines()]
		if len(lines) > 0:
			result["service_ref"] = lines[0]
		if len(lines) > 1:
			result["title"] = lines[1]
		if len(lines) > 2:
			result["short_desc"] = lines[2]
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
	txt_exists = isfile(txt_path)
	result = {"path": txt_path, "exists": txt_exists}
	if txt_exists:
		result.update({"short_desc": _read_text_file(txt_path)})  # HOLGER: ist das short_desc oder extended_desc? Danach bitte key-Namen anpassen
	return result


def parse_eit(path):
	eit_path = _first_existing_sidecar(path, ".eit")
	eit_exists = isfile(eit_path)
	result = {"path": eit_path, "exists": eit_exists}
	if eit_exists:
		reader = EITFileReader(eit_path)
		data = reader.get_data()
		result.update({
			"title": data.get("title", ""),
			"short_desc": data.get("short_desc", ""),
			"extended_desc": data.get("extended_desc", ""),
			"duration_seconds": int(data.get("duration", "0")),
			"error": reader.error
			})
	return result


def parse_cuts(path):
	cuts_path = _first_existing_sidecar(path, ".cuts")
	cuts_exists = isfile(cuts_path)
	result = {"path": cuts_path, "exists": cuts_exists, "entries": []}
	if cuts_exists:
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
		result["exists"] = cuts_exists
	return result


def parse_recording(path):  # HOLGER: Habe ich komplett umgeschrieben, damit nicht schon hier ausgefiltert wird. Das sollen dann nachfolgend die einzelnen Funktionen machen.
	"""Return the scanner values e2MDB needs, independent of their sidecar source."""
	try:
		# Priority is intentionally value-based: EIT first, then META, then TXT and cuts.
		# The backend/result DB should store usable values, not provenance noise.
		eit = parse_eit(path)
		meta = parse_meta(path)
		txt = parse_txt(path)
		cuts = parse_cuts(path)
		result = {"path": path}
		for key, dict in [("eit", eit), ("meta", meta), ("txt", txt), ("cuts", cuts)]:
			result[key] = {}
			if dict.get("exists", False):  # gather the information that is typically available
				result[key].update({
					"title": dict.get("title", "").strip(),
					"short_desc": dict.get("short_desc", "").strip(),
					"extended_desc": dict.get("extended_desc", "").strip(),
					"duration_seconds": int(dict.get("duration_seconds") or "0"),
					"parse_error": dict.get("error", "")
					})
				if key == "meta":  # additional info only available in 'meta'
					result[key].update({
						"service_ref": dict.get("service_ref", ""),
						"recorded_at": dict.get("recorded_at", 0)
						})
		return result
	except Exception as error:
		return {"path": path, "parse_error": str(error)}
