########################################################################################################
# e2MDB Wikimedia/Wikipedia Live/EPG image fallback provider                                           #
# -----------------------------------------------------------------------------------------------------#
# Uses MediaWiki APIs as an international Live/EPG fallback for horizontal preview/image artwork and   #
# as an optional portrait cover fallback.                                                             #
########################################################################################################

# PYTHON IMPORTS
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from re import IGNORECASE, S, sub
from time import time

# THIRD PARTY IMPORTS
from requests import exceptions, get

# PLUGIN IMPORTS
try:
	from .. import write_log
except Exception:
	def write_log(log_text1, log_text2=""):
		print(f"{log_text1} {log_text2}")


MODULE_NAME = "[WIKIMEDIA]"


class WikimediaProvider:
	"""Small Wikimedia/Wikipedia adapter for Live/EPG image and cover fallback."""

	COMMONS_API = "https://commons.wikimedia.org/w/api.php"
	WIKIPEDIA_API_TEMPLATE = "https://%s.wikipedia.org/w/api.php"
	WIKIPEDIA_PAGE_TEMPLATE = "https://%s.wikipedia.org/wiki/%s"
	USERAGENTS = [
		"Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.89 Safari/537.36",
	]
	BAD_TITLE_MARKERS = (
		"poster", "cover", "dvd", "blu-ray", "bluray", "vhs", "book cover", "album cover",
		"soundtrack", "screenshot of", "screen shot of", "fair use", "non-free",
		"locator map", "location map", "route map", "coat of arms", "flag of",
	)
	BAD_COVER_MARKERS = (
		"soundtrack", "screenshot of", "screen shot of", "locator map", "location map", "route map",
		"coat of arms", "flag of",
	)
	GOOD_TITLE_MARKERS = ("logo", "title card", "screenshot", "scene", "set", "cast", "film", "series", "television")
	GOOD_COVER_MARKERS = ("poster", "cover", "dvd", "blu-ray", "bluray", "title card", "promotional", "key art")
	SUPPORTED_WIKI_CODES = set((
		"ar", "bg", "ca", "cs", "da", "de", "el", "en", "es", "et", "fa", "fi", "fr", "he", "hi",
		"hr", "hu", "id", "it", "ja", "ko", "lt", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl",
		"sr", "sv", "th", "tr", "uk", "vi", "zh",
	))

	def __init__(self):
		self.language = "en"
		self.active = False
		self.disabled_until = 0
		self.rate_limit_hits = 0
		self.last_rate_limit_log = 0

	def start(self, language="en"):
		language = str(language or "en").replace("_", "-").lower().split("-")[0]
		self.language = language if language in self.SUPPORTED_WIKI_CODES else "en"
		self.active = True
		return ""

	def _log(self, text, force=False):
		try:
			write_log(MODULE_NAME, text)
		except TypeError:
			write_log(f"{MODULE_NAME} {text}")

	def _headers(self):
		# Keep a conservative, identifiable User-Agent ready for future tests.
		return {
			"User-Agent": "e2MDB/3.0 (Enigma2 Live EPG image fallback; mailto:openatv@gmail.com) requests",
			"Accept": "application/json,text/javascript,*/*;q=0.8",
			"Accept-Language": f"{self.language},en;q=0.8",
		}

	def is_paused(self):
		return int(time()) < int(self.disabled_until or 0)

	def pause_reason(self):
		if not self.is_paused():
			return ""
		return f"rate-limited-until-{int(self.disabled_until or 0)}"

	def _retry_after_seconds(self, response):
		try:
			value = response.headers.get("Retry-After", "") if response is not None else ""
		except Exception:
			value = ""
		value = str(value or "").strip()
		if not value:
			return 0
		try:
			return max(0, int(value))
		except Exception:
			pass
		try:
			retry_date = parsedate_to_datetime(value)
			return max(0, int(retry_date.timestamp() - time()))
		except Exception:
			return 0

	def _pause_after_http_error(self, status_code, response=None):
		try:
			status_code = int(status_code or 0)
		except Exception:
			status_code = 0
		if status_code not in (429, 503):
			return
		retry_after = self._retry_after_seconds(response)
		if retry_after <= 0:
			self.rate_limit_hits += 1
			if status_code == 503:
				steps = (60, 300, 900)
			else:
				steps = (300, 900, 1800, 3600)
			retry_after = steps[min(len(steps) - 1, max(0, self.rate_limit_hits - 1))]
		else:
			self.rate_limit_hits = max(1, self.rate_limit_hits)
		pause_seconds = max(5, int(retry_after) + 2)
		self.disabled_until = max(int(self.disabled_until or 0), int(time()) + pause_seconds)
		now = int(time())
		if now - int(self.last_rate_limit_log or 0) >= 60:
			self.last_rate_limit_log = now
			self._log(f"RATE_LIMIT status={status_code} pause={pause_seconds}s until={self.disabled_until}", force=True)

	def _api_get(self, api_url, params, timeout=(3.05, 7)):
		if self.is_paused():
			return self.pause_reason(), {}
		request_params = dict(params or {})
		request_params["format"] = "json"
		request_params["formatversion"] = "2"
		try:
			response = get(api_url, params=request_params, headers=self._headers(), timeout=timeout)
			try:
				status_code = int(response.status_code or 0)
			except Exception:
				status_code = 0
			if status_code in (429, 503):
				self._pause_after_http_error(status_code, response=response)
				return f"http-{status_code}-rate-limited", {}
			response.raise_for_status()
			self.rate_limit_hits = 0
			return "", response.json()
		except ValueError as err:
			self._log(f"ERROR json api='{api_url}' error={err}")
			return str(err), {}
		except exceptions.RequestException as err:
			response = getattr(err, "response", None)
			try:
				status_code = int(response.status_code or 0) if response is not None else 0
			except Exception:
				status_code = 0
			if status_code in (429, 503):
				self._pause_after_http_error(status_code, response=response)
				return f"http-{status_code}-rate-limited", {}
			self._log(f"ERROR api='{api_url}' error={err}")
			return str(err), {}

	def _clean_text(self, value):
		value = unescape(str(value or ""))
		value = sub(r"<script.*?</script>", " ", value, flags=IGNORECASE | S)
		value = sub(r"<style.*?</style>", " ", value, flags=IGNORECASE | S)
		value = sub(r"<.*?>", " ", value, flags=S)
		value = value.replace("&amp;", "&")
		return sub(r"\s+", " ", value).strip()

	def _normalize(self, value):
		value = self._clean_text(value).lower()
		value = value.replace("&", " and ")
		value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
		value = sub(r"[._\-:|/]+", " ", value)
		value = sub(r"[^a-z0-9 ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def _title_variants(self, candidate):
		values = []
		for value in (
			getattr(candidate, "search_title", ""),
			getattr(candidate, "title", ""),
		):
			value = self._clean_text(value).strip()
			if value and value not in values:
				values.append(value)
		return values

	def _wiki_languages(self):
		languages = []
		for language in (self.language, "en", "de"):
			if language and language in self.SUPPORTED_WIKI_CODES and language not in languages:
				languages.append(language)
		return languages

	def _token_overlap(self, left, right):
		left_tokens = set([token for token in self._normalize(left).split() if len(token) >= 4])
		right_tokens = set([token for token in self._normalize(right).split() if len(token) >= 4])
		if not left_tokens or not right_tokens:
			return 0.0
		return float(len(left_tokens.intersection(right_tokens))) / float(max(1, len(left_tokens)))

	def _image_url_from_info(self, info):
		if not isinstance(info, dict):
			return ""
		for key in ("thumburl", "url", "source"):
			url = str(info.get(key) or "").strip()
			if url:
				if url.startswith("//"):
					url = "https:" + url
				return url
		return ""

	def _image_size_from_info(self, info):
		width = 0
		height = 0
		for width_key, height_key in (("thumbwidth", "thumbheight"), ("width", "height")):
			try:
				width = int(info.get(width_key) or 0)
				height = int(info.get(height_key) or 0)
			except Exception:
				width = 0
				height = 0
			if width > 0 and height > 0:
				break
		return width, height

	def _usable_horizontal_image(self, url, width, height, title=""):
		url = str(url or "").strip()
		lower_url = url.lower()
		lower_title = self._normalize(title)
		if not url or "upload.wikimedia.org" not in lower_url:
			return False
		if not any(marker in lower_url for marker in (".jpg", ".jpeg", ".png", ".webp")):
			return False
		if width < 160 or height < 60:
			return False
		if float(width) / float(max(1, height)) < 1.20:
			return False
		for marker in self.BAD_TITLE_MARKERS:
			if marker in lower_title:
				return False
		return True

	def _usable_portrait_cover_image(self, url, width, height, title=""):
		url = str(url or "").strip()
		lower_url = url.lower()
		lower_title = self._normalize(title)
		if not url or "upload.wikimedia.org" not in lower_url:
			return False
		if not any(marker in lower_url for marker in (".jpg", ".jpeg", ".png", ".webp")):
			return False
		if width < 120 or height < 180:
			return False
		if float(height) / float(max(1, width)) < 1.20:
			return False
		for marker in self.BAD_COVER_MARKERS:
			if marker in lower_title:
				return False
		return True

	def _score_result(self, search_title, result_title, width, height, source, image_kind="image"):
		score = 0.20
		title_norm = self._normalize(result_title)
		search_norm = self._normalize(search_title)
		if search_norm and title_norm:
			if search_norm == title_norm:
				score += 0.45
			elif search_norm in title_norm or title_norm in search_norm:
				score += 0.30
			score += min(0.25, self._token_overlap(search_title, result_title) * 0.25)
		if width and height:
			if image_kind == "cover":
				ratio = float(height) / float(max(1, width))
				if 1.20 <= ratio <= 1.90:
					score += 0.10
				elif ratio > 1.90:
					score += 0.06
			else:
				ratio = float(width) / float(max(1, height))
				if 1.20 <= ratio <= 2.80:
					score += 0.10
				elif ratio > 2.80:
					score += 0.04
		marker_list = self.GOOD_COVER_MARKERS if image_kind == "cover" else self.GOOD_TITLE_MARKERS
		for marker in marker_list:
			if marker in title_norm:
				score += 0.04
				break
		if source in ("wikipedia-pageimage", "wikipedia-pageimage-cover"):
			score += 0.08
		return min(0.99, score)

	def _result_dict(self, search_title, title, image_url, width, height, provider_id, source_url, source, description="", image_kind="image"):
		return {
			"image_url": image_url,
			"image_width": width,
			"image_height": height,
			"image_title": title,
			"provider_id": provider_id,
			"source_url": source_url,
			"description": description,
			"confidence": self._score_result(search_title, title, width, height, source, image_kind=image_kind),
			"reason": source,
			"image_kind": image_kind,
		}

	def _search_wikipedia_pageimages(self, title):
		best = {}
		best_score = 0.0
		for language in self._wiki_languages():
			api_url = self.WIKIPEDIA_API_TEMPLATE % language
			err_msg, data = self._api_get(api_url, {
				"action": "query",
				"generator": "search",
				"gsrsearch": title,
				"gsrnamespace": "0",
				"gsrlimit": "6",
				"prop": "pageimages|pageterms",
				"piprop": "thumbnail|original|name",
				"pithumbsize": "640",
				"wbptterms": "description",
				"redirects": "1",
			})
			if err_msg or not isinstance(data, dict):
				continue
			pages = data.get("query", {}).get("pages", [])
			if isinstance(pages, dict):
				pages = list(pages.values())
			for page in pages:
				if not isinstance(page, dict):
					continue
				thumbnail = page.get("thumbnail") or {}
				image_url = self._image_url_from_info(thumbnail)
				width, height = self._image_size_from_info(thumbnail)
				page_title = page.get("title") or ""
				if not self._usable_horizontal_image(image_url, width, height, page.get("pageimage") or page_title):
					continue
				description = ""
				try:
					description = (page.get("terms") or {}).get("description", [""])[0]
				except Exception:
					description = ""
				source_url = self.WIKIPEDIA_PAGE_TEMPLATE % (language, page_title.replace(" ", "_"))
				result = self._result_dict(
					title,
					page_title,
					image_url,
					width,
					height,
					f"{language}:{page.get("pageid") or page_title}",
					source_url,
					"wikipedia-pageimage",
					description=description,
				)
				if result.get("confidence", 0.0) > best_score:
					best = result
					best_score = float(result.get("confidence") or 0.0)
			if best_score >= 0.70:
				break
		return best

	def _search_wikipedia_cover_pageimages(self, title):
		best = {}
		best_score = 0.0
		for language in self._wiki_languages():
			api_url = self.WIKIPEDIA_API_TEMPLATE % language
			err_msg, data = self._api_get(api_url, {
				"action": "query",
				"generator": "search",
				"gsrsearch": title,
				"gsrnamespace": "0",
				"gsrlimit": "6",
				"prop": "pageimages|pageterms",
				"piprop": "thumbnail|original|name",
				"pithumbsize": "640",
				"wbptterms": "description",
				"redirects": "1",
			})
			if err_msg or not isinstance(data, dict):
				continue
			pages = data.get("query", {}).get("pages", [])
			if isinstance(pages, dict):
				pages = list(pages.values())
			for page in pages:
				if not isinstance(page, dict):
					continue
				thumbnail = page.get("thumbnail") or {}
				image_url = self._image_url_from_info(thumbnail)
				width, height = self._image_size_from_info(thumbnail)
				page_title = page.get("title") or ""
				pageimage = page.get("pageimage") or page_title
				if not self._usable_portrait_cover_image(image_url, width, height, pageimage):
					continue
				description = ""
				try:
					description = (page.get("terms") or {}).get("description", [""])[0]
				except Exception:
					description = ""
				source_url = self.WIKIPEDIA_PAGE_TEMPLATE % (language, page_title.replace(" ", "_"))
				result = self._result_dict(
					title,
					page_title,
					image_url,
					width,
					height,
					f"{language}:{page.get("pageid") or page_title}",
					source_url,
					"wikipedia-pageimage-cover",
					description=description,
					image_kind="cover",
				)
				if result.get("confidence", 0.0) > best_score:
					best = result
					best_score = float(result.get("confidence") or 0.0)
			if best_score >= 0.70:
				break
		return best

	def _commons_queries(self, title):
		queries = []
		base = self._clean_text(title)
		for query in (base, f"{base} television", f"{base} film"):
			query = query.strip()
			if query and query not in queries:
				queries.append(query)
		return queries[:3]

	def _search_commons_images(self, title):
		best = {}
		best_score = 0.0
		for query in self._commons_queries(title):
			err_msg, data = self._api_get(self.COMMONS_API, {
				"action": "query",
				"generator": "search",
				"gsrsearch": query,
				"gsrnamespace": "6",
				"gsrlimit": "8",
				"prop": "imageinfo",
				"iiprop": "url|size|mime|mediatype",
				"iiurlwidth": "640",
			})
			if err_msg or not isinstance(data, dict):
				continue
			pages = data.get("query", {}).get("pages", [])
			if isinstance(pages, dict):
				pages = list(pages.values())
			for page in pages:
				if not isinstance(page, dict):
					continue
				info_list = page.get("imageinfo") or []
				if not info_list:
					continue
				info = info_list[0]
				mime = str(info.get("mime") or "").lower()
				media_type = str(info.get("mediatype") or "").lower()
				if mime and not mime.startswith("image/"):
					continue
				if media_type and media_type not in ("bitmap", "drawing"):
					continue
				image_url = self._image_url_from_info(info)
				width, height = self._image_size_from_info(info)
				page_title = page.get("title") or ""
				if not self._usable_horizontal_image(image_url, width, height, page_title):
					continue
				source_url = f"https://commons.wikimedia.org/wiki/{page_title.replace(" ", "_")}"
				result = self._result_dict(
					title,
					page_title.replace("File:", ""),
					image_url,
					width,
					height,
					f"commons:{page.get("pageid") or page_title}",
					source_url,
					"commons-image",
				)
				if result.get("confidence", 0.0) > best_score:
					best = result
					best_score = float(result.get("confidence") or 0.0)
			if best_score >= 0.70:
				break
		return best

	def _search_commons_cover_images(self, title):
		best = {}
		best_score = 0.0
		for query in self._commons_queries(title):
			err_msg, data = self._api_get(self.COMMONS_API, {
				"action": "query",
				"generator": "search",
				"gsrsearch": query,
				"gsrnamespace": "6",
				"gsrlimit": "8",
				"prop": "imageinfo",
				"iiprop": "url|size|mime|mediatype",
				"iiurlheight": "900",
			})
			if err_msg or not isinstance(data, dict):
				continue
			pages = data.get("query", {}).get("pages", [])
			if isinstance(pages, dict):
				pages = list(pages.values())
			for page in pages:
				if not isinstance(page, dict):
					continue
				info_list = page.get("imageinfo") or []
				if not info_list:
					continue
				info = info_list[0]
				mime = str(info.get("mime") or "").lower()
				media_type = str(info.get("mediatype") or "").lower()
				if mime and not mime.startswith("image/"):
					continue
				if media_type and media_type not in ("bitmap", "drawing"):
					continue
				image_url = self._image_url_from_info(info)
				width, height = self._image_size_from_info(info)
				page_title = page.get("title") or ""
				if not self._usable_portrait_cover_image(image_url, width, height, page_title):
					continue
				source_url = f"https://commons.wikimedia.org/wiki/{page_title.replace(" ", "_")}"
				result = self._result_dict(
					title,
					page_title.replace("File:", ""),
					image_url,
					width,
					height,
					f"commons:{page.get("pageid") or page_title}",
					source_url,
					"commons-cover",
					image_kind="cover",
				)
				if result.get("confidence", 0.0) > best_score:
					best = result
					best_score = float(result.get("confidence") or 0.0)
			if best_score >= 0.70:
				break
		return best

	def build_final_dict(self, candidate, selected):
		begin_time = int(getattr(candidate, "begin_time", 0) or 0)
		released = ""
		try:
			released = datetime.fromtimestamp(begin_time).strftime("%Y-%m-%d") if begin_time else ""
		except Exception:
			pass
		image_url = selected.get("image_url") or ""
		image_kind = str(selected.get("image_kind") or "image").lower()
		final_dict = {
			"provider": "wikimedia",
			"provider_ids": {"wikimedia": selected.get("provider_id") or selected.get("image_title") or image_url},
			"title": getattr(candidate, "title", "") or getattr(candidate, "search_title", "") or selected.get("image_title") or "",
			"original_title": getattr(candidate, "search_title", "") or getattr(candidate, "title", ""),
			"media_type": "series",
			"countries": "",
			"released": released,
			"overview": selected.get("description") or getattr(candidate, "extended_desc", "") or getattr(candidate, "short_desc", ""),
			"description": selected.get("description") or getattr(candidate, "short_desc", "") or "",
			"title_ratio": float(selected.get("confidence") or 0.50),
			"desc_ratio": float(selected.get("confidence") or 0.50),
			"source_url": selected.get("source_url") or "",
			"source_provider": "wikimedia",
			"source_reason": selected.get("reason") or "",
			"image_width": selected.get("image_width") or 0,
			"image_height": selected.get("image_height") or 0,
		}
		if image_kind == "cover":
			final_dict["cover_url"] = image_url
			final_dict["cover_src"] = "wikimedia"
		else:
			final_dict["image_url"] = image_url
			final_dict["image_src"] = "wikimedia"
			final_dict["preview_url"] = image_url
			final_dict["still_url"] = image_url
		return final_dict

	def lookup_epg_event(self, candidate):
		if not self.active:
			return "provider-not-started", {}
		variants = self._title_variants(candidate)
		if not variants:
			return "missing-title", {}
		best = {}
		best_score = 0.0
		for title in variants:
			for selected in (self._search_wikipedia_pageimages(title), self._search_commons_images(title)):
				if not selected or not selected.get("image_url"):
					continue
				score = float(selected.get("confidence") or 0.0)
				if score > best_score:
					best = selected
					best_score = score
			if best_score >= 0.70:
				break
		if best and best.get("image_url"):
			self._log(f"MATCH confidence={best_score:.2f} reason={best.get("reason") or ""} title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}' image='{best.get("image_url") or ""}'", force=True)
			return "", self.build_final_dict(candidate, best)
		self._log(f"NO_MATCH title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}'")
		return "no-match", {}

	def lookup_epg_cover(self, candidate):
		if not self.active:
			return "provider-not-started", {}
		variants = self._title_variants(candidate)
		if not variants:
			return "missing-title", {}
		best = {}
		best_score = 0.0
		for title in variants:
			for selected in (self._search_wikipedia_cover_pageimages(title), self._search_commons_cover_images(title)):
				if not selected or not selected.get("image_url"):
					continue
				score = float(selected.get("confidence") or 0.0)
				if score > best_score:
					best = selected
					best_score = score
			if best_score >= 0.70:
				break
		if best and best.get("image_url"):
			self._log(f"COVER_MATCH confidence={best_score:.2f} reason={best.get("reason") or ""} title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}' image='{best.get("image_url") or ""}'", force=True)
			return "", self.build_final_dict(candidate, best)
		self._log(f"NO_COVER_MATCH title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}'")
		return "no-match", {}


provider_wikimedia = WikimediaProvider()
