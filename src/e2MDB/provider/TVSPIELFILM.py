########################################################################################################
# e2MDB TVSpielfilm Live/EPG provider                                                                  #
# -----------------------------------------------------------------------------------------------------#
# Uses TVSpielfilm as a German Live/EPG metadata source. It is deliberately limited to Live/EPG/ad-hoc #
# lookups and is ignored when the global e2MDB language is not German.                                  #
########################################################################################################

# PYTHON IMPORTS
from datetime import datetime, timedelta
from hashlib import md5
from html import unescape
from json import load
from os.path import dirname, exists, join
from re import compile, findall, IGNORECASE, match, search, S, sub
from secrets import choice
from time import time

# THIRD PARTY IMPORTS
from requests import get, exceptions

# PLUGIN IMPORTS
try:
	from .. import write_log
except Exception:
	def write_log(log_text1, log_text2="", level=None):
		print(f"{log_text1} {log_text2}")


MODULE_NAME = "[TVSPIELFILM]"


class TVSpielfilmProvider:
	"""Small TVSpielfilm adapter for e2MDB Live/EPG events.

	TVSpielfilm is not a generic movie/series provider. It needs a TV channel and
	an EPG start time, so it is only used by the Live/EPG worker and ad-hoc path.
	"""

	WEBURL = bytes.fromhex("687474703a2f2f7777772e7476737069656c66696c6d2e64653"[:-1]).decode()
	MWEBURL = bytes.fromhex("68747470733a2f2f6d2e7476737069656c66696c6d2e64653"[:-1]).decode()
	USERAGENTS = [
		"Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/129.0.2792.65",
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 15.0; rv:130.0) Gecko/20100101 Firefox/130.0",
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.89 Safari/537.36",
	]
	LINES_PER_PAGE = 20
	CATEGORY_MEDIA_TYPES = {
		"SP": "movie",
		"SE": "series",
		"KIN": "series",
		"SPO": "tv",
		"RE": "tv",
		"U": "tv",
		"AND": "tv",
	}
	TIME_SPANS = (
		(5, 14, "5"),
		(14, 18, "14"),
		(18, 20, "18"),
		(20, 22, "20"),
		(22, 24, "22"),
		(0, 5, "0"),
	)

	def __init__(self):
		self.language = ""
		self.active = False
		self.mapping = None
		self.imported = None
		self.supported = None
		self._last_skip_log = 0

	def start(self, language="de"):
		self.language = str(language or "").replace("_", "-").lower()
		self.active = self.language.split("-")[0] == "de"
		return ""

	def is_language_enabled(self):
		return self.active

	def _log(self, text, force=False, level=None):
		try:
			write_log(MODULE_NAME, text, level=level)
		except TypeError:
			write_log(f"{MODULE_NAME} {text}")

	def _headers(self):
		return {"User-Agent": choice(self.USERAGENTS)}

	def _get_html(self, url, params=None, timeout=(3.05, 6)):
		try:
			response = get(url, params=params, headers=self._headers(), timeout=timeout)
			response.raise_for_status()
			return "", response.text
		except exceptions.RequestException as err:
			self._log(f"FETCH_MISS get_html url='{url}' error={err}", level="warning")
			return str(err), ""

	def _search_one(self, regex, text, fallback="", flags=None):
		found = search(regex, text, flags=flags) if flags else search(regex, text)
		return found.group(1) if found else fallback

	def _clean_text(self, value):
		value = unescape(str(value or ""))
		value = sub(r"<br\s*/?>", "\n", value, flags=IGNORECASE)
		value = sub(r"<.*?>", " ", value, flags=S)
		value = value.replace("&amp;", "&")
		return sub(r"\s+", " ", value).strip()

	def _normalize(self, value):
		value = self._clean_text(value).lower()
		value = sub(r"[._\-:|]+", " ", value)
		value = sub(r"[^a-z0-9äöüß ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def _ratio(self, left, right):
		try:
			from difflib import SequenceMatcher
			left_norm = self._normalize(left)
			right_norm = self._normalize(right)
			if not left_norm or not right_norm:
				return 0.0
			if left_norm == right_norm:
				return 1.0
			if left_norm in right_norm or right_norm in left_norm:
				return 0.92
			return SequenceMatcher(None, left_norm, right_norm).ratio()
		except Exception:
			return 0.0

	def _full_url(self, url):
		url = (url or "").strip()
		if not url:
			return ""
		if url.startswith("//"):
			return "https:" + url
		if url.startswith("/"):
			return self.WEBURL + url
		return url.replace("https://m.", "https://")

	def _candidate_channel_name(self, candidate):
		return self._normalize(getattr(candidate, "service_name", "") or getattr(candidate, "service_ref", ""))

	def _mapping_paths(self):
		return (
			"/etc/enigma2/TVSpielfilm/tvs_mapping.txt",
			"/etc/enigma2/tvspielfilm/tvs_mapping.txt",
			join(dirname(__file__), "tvs_mapping.txt"),
		)

	def _read_mapping(self):
		if self.mapping is not None:
			return self.mapping
		items = []
		for path in self._mapping_paths():
			if not exists(path):
				continue
			try:
				with open(path, "r", encoding="utf-8", errors="ignore") as handle:
					for raw_line in handle.read().replace(",", "").splitlines():
						line = raw_line.strip()
						if not line or line.startswith("#") or ": " not in line:
							continue
						channel_id, pattern = line.split(": ", 1)
						channel_id = channel_id.strip().lower()
						pattern = pattern.strip().lower()
						if channel_id and pattern:
							items.append((channel_id, pattern))
			except Exception as err:
				self._log(f"MAPPING read failed path='{path}' error={err}")
			if items:
				break
		self.mapping = items
		return self.mapping

	def _read_json_dict(self, paths):
		for path in paths:
			if not exists(path):
				continue
			try:
				with open(path, "r", encoding="utf-8", errors="ignore") as handle:
					data = load(handle)
					return data if isinstance(data, dict) else {}
			except Exception as err:
				self._log(f"JSON read failed path='{path}' error={err}")
		return {}

	def _read_imported(self):
		if self.imported is None:
			self.imported = self._read_json_dict((
				"/etc/enigma2/TVSpielfilm/tvs_imported.json",
				"/etc/enigma2/tvspielfilm/tvs_imported.json",
			))
		return self.imported

	def _read_supported(self):
		if self.supported is None:
			self.supported = self._read_json_dict((
				"/etc/enigma2/TVSpielfilm/tvs_supported.json",
				"/etc/enigma2/tvspielfilm/tvs_supported.json",
			))
		return self.supported

	def resolve_channel_id(self, candidate):
		service_ref = str(getattr(candidate, "service_ref", "") or "").strip()
		service_name = str(getattr(candidate, "service_name", "") or "").strip()
		service_name_norm = self._candidate_channel_name(candidate)
		for source_name, source in (("imported", self._read_imported()), ("supported", self._read_supported())):
			for channel_id, detail in source.items():
				try:
					stored_ref = str((detail or ["", ""])[0] or "").strip()
					stored_name = str((detail or ["", ""])[1] or "").strip()
				except Exception:
					continue
				if service_ref and stored_ref and (service_ref == stored_ref or service_ref.startswith(stored_ref) or stored_ref.startswith(service_ref)):
					return str(channel_id or "").lower(), source_name
				if service_name_norm and stored_name and self._normalize(stored_name) == service_name_norm:
					return str(channel_id or "").lower(), source_name
		if service_name_norm:
			for channel_id, pattern in self._read_mapping():
				try:
					if match(compile(pattern), service_name_norm):
						return channel_id, "mapping"
				except Exception:
					continue
		return "", ""

	def _time_code(self, begin_time, event_end=0):
		try:
			begin_ts = int(begin_time or time())
			begin_dt = datetime.fromtimestamp(begin_ts)
		except Exception:
			begin_ts = int(time())
			begin_dt = datetime.now(tz=None)
		try:
			end_ts = int(event_end or 0)
		except Exception:
			end_ts = 0
		now_ts = int(time())
		if begin_ts and end_ts and begin_ts - 600 <= now_ts <= end_ts + 600:
			return begin_dt, "now"
		if begin_dt.hour == 20 and begin_dt.minute <= 30:
			return begin_dt, "prime"
		for start, end, code in self.TIME_SPANS:
			if start <= begin_dt.hour < end:
				return begin_dt, code
		return begin_dt, "day"

	def parse_channel_page(self, channel_id, curr_date_dt, time_code=None):
		url = f"{self.MWEBURL}{bytes.fromhex('2f73756368652e68746d6c1'[:-1]).decode()}"
		curr_date_str = (datetime.now(tz=None) if time_code == "now" else curr_date_dt).strftime("%F")
		curr_date_int = int(f"{curr_date_dt.hour:02d}{curr_date_dt.minute:02d}")
		if 0 <= curr_date_int < 500:
			curr_date_str = (curr_date_dt - timedelta(days=1)).strftime("%F")
		assets = []
		offset = 0
		while True:
			params = {
				"offset": offset,
				"filter": None,
				"order": None,
				"date": curr_date_str,
				"tips": None,
				"cat[]": [],
				"time": time_code or "prime",
				"channel": channel_id,
			}
			err, html = self._get_html(url, params=params)
			if err:
				return err, []
			extract = html[html.find('<div class="row component tv-tip-list">'):html.find('<div class="row component category-select">')]
			limit = 5 if time_code == "now" else 0
			for index, entry in enumerate(findall(r'<li class="tv-tip time-listing js-tv-show"(.*?)</li>', extract, S)):
				if limit and index > limit:
					return "", assets
				asset = {}
				asset["id"] = self._search_one(r'data-id="(.*?)"', entry, "")
				asset["title"] = self._clean_text(self._search_one(r'<span class="title">(.*?)</span>', entry, ""))
				genretime = self._search_one(r'<span class="genre-time">(.*?)</span>', entry, "").split(" | ")
				asset["countryYear"] = self._clean_text(genretime[0]).upper() if genretime else ""
				asset["genre"] = self._clean_text(genretime[1]) if len(genretime) > 1 else ""
				itholder = self._search_one(r'<div class="image-text-holder">(.*?)</a>', entry, "", flags=S)
				page_element = self._search_one(r'"pageElementCreative":"(.*?)"', itholder, "").split("|")
				if len(page_element) > 2:
					asset["channelId"] = page_element[1].lower()
					asset["category"] = page_element[2].upper()
				thumb = self._search_one(r'<span class="listing-icon rating-(.*?)"></span>', itholder, "0")
				asset["thumbIdNumeric"] = int(thumb) if thumb.isdigit() else 0
				asset["isTip"] = itholder.find('<span class="add-info icon-tip">TIPP</span>') > -1
				asset["isNew"] = itholder.find('<span class="add-info icon-new">NEU</span>') > -1
				asset["isLive"] = itholder.find('<span class="add-info icon-tip">Live</span>') > -1
				asset["channelName"] = self._clean_text(self._search_one(r'<span class="c">(.*?)</span>', itholder, ""))
				start_raw = self._search_one(r'data-start-time="(.*?)"', entry, "")
				end_raw = self._search_one(r'data-end-time="(.*?)"', entry, "")
				asset["start_ts"] = int(start_raw) if start_raw.isdigit() else 0
				asset["end_ts"] = int(end_raw) if end_raw.isdigit() else 0
				asset["assetUrl"] = self._full_url(self._search_one(r'<div class="image-text-holder">\s*<a href="(.*?)"', entry, "", flags=S))
				assets.append(asset)
			if extract.find('<span>Weitere Sendungen</span>') == -1:
				break
			next_offset = self._search_one(r'data-ajax=.*?offset=(.*?)&amp', extract, "", flags=S)
			if next_offset and next_offset.isdigit():
				offset = int(next_offset)
			else:
				offset += self.LINES_PER_PAGE
			if offset > 200:
				break
		return "", assets

	def parse_single_asset(self, asset_url):
		asset_url = self._full_url(asset_url)
		if not asset_url:
			return "missing-asset-url", {}
		err, html = self._get_html(asset_url)
		if err:
			return err, {}
		extract = html[html.find('<div class="content-area">'):]
		extract = extract[:extract.find('<div class="schedule-widget__tabs">')]
		asset = {}
		asset["title"] = self._clean_text(self._search_one(r'<h1 class="headline headline--article broadcast stage-heading">(.*?)</h1>', extract, ""))
		block = self._search_one(r'<span class="text-row">(.*?)</span></div>', extract, "").split(" | ")
		if block and len(block) > 1:
			asset["countryYear"] = self._clean_text(block[0])
			asset["genre"] = self._clean_text(block[1])
		asset["category"] = self._search_one(r'"epgCategory1" : "(.*?)",', html, "").upper()
		serialinfo = self._search_one(r'<section class="serial-info">\s*<span>(.*?)</span>', extract, "").split(",")
		if len(serialinfo) > 1:
			asset["seasonNumber"] = self._clean_text(serialinfo[0]).replace("Staffel", "").strip()
		if serialinfo and serialinfo[-1]:
			asset["episodeNumber"] = self._clean_text(serialinfo[-1]).replace("Folge", "").strip()
		asset["conclusion"] = self._clean_text(self._search_one(r'<blockquote class="content-rating__rating-genre__conclusion-quote">(.*?)</blockquote>', extract, "", flags=S))
		img_url = self._search_one(r'<picture class=".*?">\s*<img src="(.*?)" width', extract, "", flags=S)
		if not img_url:
			img_url = self._search_one(r'--tv-detail ">\s*<img src="(.*?)" alt', extract, "", flags=S)
		if not img_url:
			img_url = self._search_one(r'<div class="tips-teaser__image">\s*<img src="(.*?)"\s*width', extract, "", flags=S)
		asset["imgUrl"] = self._full_url(img_url)
		asset["imgCredits"] = self._clean_text(self._search_one(r'<span class="credit">(.*?)</span>', extract, ""))
		descblock = self._search_one(r'<section class="broadcast-detail__description">(.*?)</section>', extract, "", flags=S)
		asset["preview"] = self._clean_text(self._search_one(r'<p class="headline">(.*?)</p>', descblock, ""))
		asset["text"] = self._clean_text(self._search_one(r'<p>(.*?)</p>', descblock, ""))
		infoblock = self._search_one(r'<p class="headline">Infos</p>(.*?)<p class="headline headline--spacing">', extract, "", flags=S)
		infodict = {self._clean_text(k): self._clean_text(v) for k, v in findall(r'<dt>(.*?)</dt>\s*<dd>(.*?)</dd>', infoblock, flags=S)}
		asset["country"] = infodict.get("Land", "")
		asset["firstYear"] = infodict.get("Jahr", "")
		asset["length"] = infodict.get("Länge", "")
		fsk = infodict.get("FSK", "-1")[:2]
		asset["fsk"] = int(fsk) if fsk.isdigit() else -1
		crew = {}
		for block_name, key in (("Crew", "crew"), ("Cast", "cast")):
			if block_name == "Crew":
				section = self._search_one(r'<p class="headline headline--spacing">Crew</p>(.*?)</div>', extract, "", flags=S)
			else:
				section = self._search_one(r'<p class="headline">Cast</p>(.*?)</dl>', extract, "", flags=S)
			items = findall(r'<dt>(.*?)</dt>\s*<dd>\s*(.*?)\s*</dd>', section, flags=S)
			values = []
			for role, raw_name in items:
				name = self._clean_text(self._search_one(r'title="(.*?)"', raw_name, "") or raw_name)
				role = self._clean_text(role)
				if name and role:
					values.append(f"{name} ({role})")
				elif name:
					values.append(name)
			if values:
				crew[key] = values
		asset.update(crew)
		thumb = self._search_one(r'<div class="content-rating__rating-genre__thumb rating-(.*?)"></div>', extract, "0")
		asset["thumbIdNumeric"] = int(thumb) if thumb.isdigit() else 0
		asset["imdbRating"] = self._clean_text(self._search_one(r'<div class="content-rating__imdb-rating__rating-value">(.*?)</div>', extract, ""))
		asset["assetUrl"] = asset_url
		return "", asset

	def _select_asset(self, candidate, assets):
		if not assets:
			return {}, 0.0, "no-assets"
		begin = int(getattr(candidate, "begin_time", 0) or 0)
		end = int(getattr(candidate, "event_end", 0) or 0)
		title = getattr(candidate, "search_title", "") or getattr(candidate, "title", "") or ""
		best = {}
		best_score = 0.0
		best_reason = ""
		for asset in assets:
			asset_title = asset.get("title") or ""
			title_ratio = self._ratio(title, asset_title)
			start = int(asset.get("start_ts") or 0)
			asset_end = int(asset.get("end_ts") or 0)
			time_score = 0.0
			if begin and start:
				diff = abs(begin - start)
				if diff <= 10 * 60:
					time_score = 1.0
				elif diff <= 30 * 60:
					time_score = 0.85
				elif diff <= 60 * 60:
					time_score = 0.55
			if begin and end and start and asset_end and max(begin, start) < min(end, asset_end):
				time_score = max(time_score, 0.75)
			score = (title_ratio * 0.70) + (time_score * 0.30)
			if title_ratio >= 0.92 and time_score >= 0.55:
				score = max(score, 0.94)
			if score > best_score:
				best = asset
				best_score = score
				best_reason = f"title={round(title_ratio * 100)} time={round(time_score * 100)}"
		return best, best_score, best_reason

	def _asset_id(self, asset):
		if asset.get("id"):
			return str(asset.get("id"))
		if asset.get("assetUrl"):
			return md5(asset.get("assetUrl").encode("utf-8")).hexdigest()
		return ""

	def _category_media_type(self, asset):
		category = str(asset.get("category") or "").upper()
		return self.CATEGORY_MEDIA_TYPES.get(category, "tv")

	def _year_from_asset(self, asset):
		for key in ("firstYear", "countryYear"):
			text = str(asset.get(key) or "")
			found = search(r"(19\d{2}|20\d{2})", text)
			if found:
				return found.group(1)
		return ""

	def _runtime_minutes(self, asset):
		length = str(asset.get("length") or "")
		found = search(r"(\d+)", length)
		return found.group(1) if found else ""

	def build_final_dict(self, candidate, list_asset, details, confidence):
		asset = dict(list_asset or {})
		asset.update({k: v for k, v in (details or {}).items() if v not in (None, "", [], {})})
		asset_id = self._asset_id(asset)
		img_url = self._full_url(asset.get("imgUrl") or "")
		overview = asset.get("text") or asset.get("preview") or getattr(candidate, "extended_desc", "") or getattr(candidate, "short_desc", "") or ""
		preview = asset.get("preview") or getattr(candidate, "short_desc", "") or ""
		year = self._year_from_asset(asset)
		rating = str(asset.get("imdbRating") or "").replace(",", ".")
		try:
			vote_average = str(float(rating)) if rating else ""
		except Exception:
			vote_average = ""
		genres = []
		for key in ("genre", "category"):
			value = self._clean_text(asset.get(key) or "")
			if value and value not in genres:
				genres.append(value)
		final_dict = {
			"provider": "tvspielfilm",
			"provider_ids": {"tvspielfilm": asset_id},
			"id": asset_id,
			"title": asset.get("title") or getattr(candidate, "title", ""),
			"original_title": asset.get("title") or getattr(candidate, "title", ""),
			"media_type": self._category_media_type(asset),
			"genres": ", ".join(genres),
			"overview": overview,
			"short_desc": preview,
			"description": overview,
			"countries": asset.get("country") or asset.get("countryYear") or "",
			"released": year,
			"year": year,
			"runtime": self._runtime_minutes(asset),
			"vote_average": vote_average,
			"vote_count": "0",
			# TVSpielfilm exposes one editorial/listing image. Treat it as a preview/still,
			# not as a poster cover. Poster/backdrop artwork is filled from the normal
			# providers by the Live/EPG worker when available.
			"image_url": img_url,
			"preview_url": img_url,
			"still_url": img_url,
			"image_src": "tvspielfilm",
			"preview_src": "tvspielfilm",
			"asset_url": asset.get("assetUrl") or "",
			"channel_id": asset.get("channelId") or "",
			"channel_name": asset.get("channelName") or getattr(candidate, "service_name", ""),
			"category": asset.get("category") or "",
			"preview": preview,
			"conclusion": asset.get("conclusion") or "",
			"fsk": str(asset.get("fsk")) if asset.get("fsk", "") != "" else "",
			"thumb_id": str(asset.get("thumbIdNumeric") or ""),
			"season_no": str(asset.get("seasonNumber") or ""),
			"episode_no": str(asset.get("episodeNumber") or ""),
			"title_ratio": str(float(confidence or 0.0)),
			"desc_ratio": "1.0" if overview else "0.0",
		}
		if asset.get("cast"):
			final_dict["cast"] = asset.get("cast")
		if asset.get("crew"):
			final_dict["crew"] = asset.get("crew")
		return {key: value for key, value in final_dict.items() if value not in (None, "", [], {})}

	def lookup_epg_event(self, candidate):
		if not self.is_language_enabled():
			now = int(time())
			if now - self._last_skip_log > 3600:
				self._last_skip_log = now
				self._log("SKIP reason=language-not-german")
			return "language-not-german", {}
		channel_id, channel_source = self.resolve_channel_id(candidate)
		if not channel_id:
			return "missing-channel-mapping", {}
		begin_dt, time_code = self._time_code(getattr(candidate, "begin_time", 0), getattr(candidate, "event_end", 0))
		err, assets = self.parse_channel_page(channel_id, begin_dt, time_code=time_code)
		if err:
			return err, {}
		selected, confidence, reason = self._select_asset(candidate, assets)
		if not selected or confidence < 0.55:
			self._log("NO_MATCH channel=%s source=%s time_code=%s count=%s title='%s' best='%s' score=%.2f reason=%s" % (
				channel_id,
				channel_source,
				time_code,
				len(assets),
				getattr(candidate, "search_title", "") or getattr(candidate, "title", ""),
				selected.get("title", "") if selected else "",
				confidence,
				reason,
			))
			return "no-match", {}
		detail_err, details = "", {}
		if selected.get("assetUrl"):
			detail_err, details = self.parse_single_asset(selected.get("assetUrl"))
			if detail_err:
				self._log("DETAIL failed channel=%s asset='%s' error=%s" % (channel_id, selected.get("assetUrl"), detail_err), level="warning")
		final_dict = self.build_final_dict(candidate, selected, details, confidence)
		self._log("MATCH channel=%s source=%s time_code=%s confidence=%.2f title='%s' asset='%s' image='%s'" % (
			channel_id,
			channel_source,
			time_code,
			confidence,
			getattr(candidate, "title", ""),
			final_dict.get("title", ""),
			final_dict.get("image_url", ""),
		))
		return "", final_dict


provider_tvspielfilm = TVSpielfilmProvider()
