########################################################################################################
# e2MDB Live/EPG helpers                                                                               #
# -----------------------------------------------------------------------------------------------------#
# This module contains only lightweight glue code. Provider lookup and matching must stay in            #
# E2MDBScanner/E2MDBProviders so the Live/EPG extension does not create a second metadata engine.       #
########################################################################################################

# PYTHON IMPORTS
from hashlib import md5
from re import IGNORECASE, sub
from time import time

# ENIGMA IMPORTS
from Components.config import config

# PLUGIN IMPORTS
from . import write_log
from .E2MDBDatabase import resultsdb
from .E2MDBHelper import E2MDBHelper
from .E2MDBIgnoreConfig import E2MDBIgnorePatterns


EPG_MIN_PROVIDER_DURATION_SECONDS = 15 * 60


class E2MDBEPGCandidate:
	"""Small normalized object used to feed EPG/Live events into e2MDB."""

	def __init__(self, source_key, source_type="epg", service_ref="", service_name="", event_id=0, title="", search_title="", short_desc="", extended_desc="", begin_time=0, duration=0, event_end=0, virtual_path="", expires_at=0):
		self.source_key = source_key
		self.source_type = source_type
		self.service_ref = service_ref
		self.service_name = service_name
		self.event_id = int(event_id or 0)
		self.title = title or ""
		self.search_title = search_title or self.title
		self.short_desc = short_desc or ""
		self.extended_desc = extended_desc or ""
		self.begin_time = int(begin_time or 0)
		self.duration = int(duration or 0)
		self.event_end = int(event_end or (self.begin_time + self.duration if self.begin_time and self.duration else 0))
		self.virtual_path = virtual_path or ""
		self.expires_at = int(expires_at or 0)

	def as_dict(self):
		return {
			"source_key": self.source_key,
			"source_type": self.source_type,
			"service_ref": self.service_ref,
			"service_name": self.service_name,
			"event_id": self.event_id,
			"title": self.title,
			"search_title": self.search_title,
			"short_desc": self.short_desc,
			"extended_desc": self.extended_desc,
			"begin_time": self.begin_time,
			"duration": self.duration,
			"event_end": self.event_end,
			"virtual_path": self.virtual_path,
			"expires_at": self.expires_at,
		}


class E2MDBLiveEPG(E2MDBHelper):
	"""Adapter foundation for Live-TV and EPG metadata caching."""

	SOURCE_EPG = "epg"
	SOURCE_LIVE = "live"

	def normalize_text(self, value):
		value = (value or "").strip().lower()
		value = sub(r"[._\-]+", " ", value)
		value = sub(r"[^a-z0-9äöüß ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def epg_search_title(self, title):
		"""Return a provider-friendly title for EPG events without changing the stable source key."""
		cleaned = (title or "").strip()
		if not cleaned:
			return ""
		patterns = (
			r"\s*[\(\[]\s*\d+\s*/\s*\d+\s*[\)\]]\s*$",
			r"\s+\d+\s*/\s*\d+\s*$",
			r"\s*[\(\[]\s*(?:folge|teil|episode)\s*\d+(?:\s*/\s*\d+)?\s*[\)\]]\s*$",
			r"\s*[-:]\s*(?:\d+\.\s*)?(?:folge|teil|episode)\s*\d+(?:\s*/\s*\d+)?\s*$",
			r"\s*[-:]\s*\d+\.\s*(?:folge|teil|episode)\s*$",
			r"\s*[\(\[]\s*S\d{1,2}\s*[/\- ]?\s*E\d{1,2}.*?[\)\]]\s*$",
		)
		for pattern in patterns:
			cleaned = sub(pattern, "", cleaned, flags=IGNORECASE).strip()
		# German EPG data often appends plain episode numbers, for example
		# "Rote Rosen (4341)". Keep year-like numbers as disambiguation,
		# but remove non-year trailing numbers before provider search.
		try:
			from re import search
			match = search(r"\s*[\(\[]\s*(\d{3,5})\s*[\)\]]\s*$", cleaned)
			if match:
				number = int(match.group(1))
				if number < 1900 or number > 2099:
					cleaned = cleaned[:match.start()].strip()
		except Exception:
			pass
		cleaned = sub(r"\s+", " ", cleaned).strip(" -:;,.\t")
		return cleaned or (title or "").strip()

	def _ignored_title_patterns(self):
		try:
			return E2MDBIgnorePatterns.parse(E2MDBIgnorePatterns.EPG_TITLE)
		except Exception:
			return []

	def _title_matches_ignore_pattern(self, title, search_title=""):
		text = self.normalize_text(f"{title or ''} {search_title or ''}")
		if not text:
			return ""
		for pattern in self._ignored_title_patterns():
			normalized_pattern = self.normalize_text(pattern)
			if normalized_pattern and normalized_pattern in text:
				return pattern
		return ""

	def epg_provider_skip_reason(self, candidate_or_title, duration=None, search_title=None):
		"""Return (status, reason, detail) when an EPG event should not trigger provider lookup."""
		try:
			title = candidate_or_title.title
			search = getattr(candidate_or_title, "search_title", "") or self.epg_search_title(title)
			duration_value = int(getattr(candidate_or_title, "duration", 0) or 0)
		except Exception:
			title = candidate_or_title or ""
			search = search_title or self.epg_search_title(title)
			duration_value = int(duration or 0)

		matched_pattern = self._title_matches_ignore_pattern(title, search)
		if matched_pattern:
			return "ignored", "ignored-title-pattern", matched_pattern

		minimum = EPG_MIN_PROVIDER_DURATION_SECONDS
		if minimum > 0 and duration_value > 0 and duration_value <= minimum:
			return "short_skipped", "duration-at-or-below-minimum", f"duration={duration_value} minimum={minimum}"

		return "", "", ""

	def normalize_service_ref(self, service_ref):
		if service_ref is None:
			return ""
		try:
			if hasattr(service_ref, "toString"):
				return service_ref.toString()
		except Exception:
			pass
		try:
			if hasattr(service_ref, "ref") and hasattr(service_ref.ref, "toString"):
				return service_ref.ref.toString()
		except Exception:
			pass
		return str(service_ref or "")

	def source_key(self, service_ref, event_id=0, begin_time=0, title="", source_type="epg", event_end=0, duration=0):
		"""Return the stable natural Live/EPG key.

		Do not include Enigma2's event_id here.  The same visible event can reach e2MDB
		through EventView, InfoBar, ServiceList and prefill paths, and those contexts do
		not always expose the same event_id.  The natural identity is the service, start,
		end and normalized title.  Queue reasons such as servicelist/promoted/adhoc must
		never change the key.
		"""
		try:
			begin_value = int(begin_time or 0)
		except Exception:
			begin_value = 0
		try:
			end_value = int(event_end or 0)
		except Exception:
			end_value = 0
		if not end_value:
			try:
				duration_value = int(duration or 0)
			except Exception:
				duration_value = 0
			if begin_value and duration_value:
				end_value = begin_value + duration_value
		identity = f"{source_type or "epg"}|{self.normalize_service_ref(service_ref)}|{begin_value}|{end_value}|{self.normalize_text(title)}"
		return md5(identity.encode("utf-8")).hexdigest()

	def virtual_path(self, source_key, title="", source_type="epg"):
		clean_title = self.normalize_text(title).replace(" ", "_") or "event"
		return f"/{source_type or 'epg'}/{source_key}_{clean_title[:80]}.ts"

	def default_expiry(self, event_end=0, status="unknown"):
		now = int(time())
		base = int(event_end or now)
		status = (status or "unknown").lower()
		if status == "no_match":
			return now + int(config.plugins.e2mdb.epgNoMatchRetentionHours.value) * 3600
		if status in ("short_skipped", "ignored", "skipped", "ended_skipped"):
			return base + int(config.plugins.e2mdb.epgNoMatchRetentionHours.value) * 3600
		return base + int(config.plugins.e2mdb.epgRetentionDays.value) * 86400

	def event_to_candidate(self, service_ref, event, service_name="", source_type="epg", status="unknown"):
		service_ref = self.normalize_service_ref(service_ref)
		event_id = 0
		title = ""
		short_desc = ""
		extended_desc = ""
		begin_time = 0
		duration = 0
		try:
			event_id = int(event.getEventId() or 0) if event else 0
		except Exception:
			pass
		try:
			title = event.getEventName() or "" if event else ""
		except Exception:
			pass
		try:
			short_desc = event.getShortDescription() or "" if event else ""
		except Exception:
			pass
		try:
			extended_desc = event.getExtendedDescription() or "" if event else ""
		except Exception:
			pass
		try:
			begin_time = int(event.getBeginTime() or 0) if event else 0
		except Exception:
			pass
		try:
			duration = int(event.getDuration() or 0) if event else 0
		except Exception:
			pass

		event_end = begin_time + duration if begin_time and duration else 0
		source_key = self.source_key(service_ref, event_id, begin_time, title, source_type=source_type, event_end=event_end, duration=duration)
		search_title = self.epg_search_title(title)
		return E2MDBEPGCandidate(
			source_key=source_key,
			source_type=source_type,
			service_ref=service_ref,
			service_name=service_name,
			event_id=event_id,
			title=title,
			search_title=search_title,
			short_desc=short_desc,
			extended_desc=extended_desc,
			begin_time=begin_time,
			duration=duration,
			event_end=event_end,
			virtual_path=self.virtual_path(source_key, title, source_type=source_type),
			expires_at=self.default_expiry(event_end, status=status),
		)

	def remember_candidate(self, candidate, priority=0, reason="selection"):
		"""Persist an event candidate and optionally put it into the provider fetch queue."""
		if not candidate or not candidate.source_key:
			return None
		try:
			event_id = resultsdb.upsert_epg_event(candidate.as_dict())
			resultsdb.upsert_fetch_queue({
				"source_key": candidate.source_key,
				"source_type": candidate.source_type,
				"service_ref": candidate.service_ref,
				"title": candidate.title,
				"search_title": candidate.search_title,
				"short_desc": candidate.short_desc,
				"extended_desc": candidate.extended_desc,
				"begin_time": candidate.begin_time,
				"event_end": candidate.event_end,
				"priority": int(priority or 0),
				"reason": reason or "selection",
				"state": "pending",
			})
			return event_id
		except Exception as e:
			write_log(f"[e2MDB] Error remembering EPG candidate: {e}")
			return None

	def cleanup_short_lived_data(self, now=None):
		"""Run the database side of Live/EPG cleanup. File cleanup is handled later."""
		try:
			now = int(now or time())
			deleted_events = resultsdb.delete_expired_epg_events(now)
			deleted_queue = resultsdb.cleanup_fetch_queue(now)
			resultsdb.set_cleanup_state("last_epg_cleanup", str(now))
			return {"events": deleted_events, "queue": deleted_queue}
		except Exception as e:
			write_log(f"[e2MDB] Error cleaning Live/EPG data: {e}")
			return {"events": 0, "queue": 0}
