########################################################################################################
# e2MDB fernsehserien.de Live/EPG image fallback provider                                               #
# -----------------------------------------------------------------------------------------------------#
# Uses fernsehserien.de only as a German Live/EPG fallback for horizontal preview/still artwork.        #
# It is intentionally not used for generic provider searches and never returns portrait covers.         #
########################################################################################################

# PYTHON IMPORTS
from datetime import datetime
from html import unescape
from re import IGNORECASE, S, findall, search, sub
from secrets import choice
from urllib.parse import quote_plus

# THIRD PARTY IMPORTS
from requests import get, exceptions

# PLUGIN IMPORTS
try:
	from .. import write_log
except Exception:
	def write_log(log_text1, log_text2="", level=None):
		print(f"{log_text1} {log_text2}")


MODULE_NAME = "[FERNSEHSERIEN]"


class FernsehserienProvider:
	"""Small fernsehserien.de adapter for German Live/EPG image fallback.

	The provider deliberately returns only horizontal preview/still artwork through
	image_url. It must never fill cover_url because the ServiceList preview must not
	use portrait artwork.
	"""

	WEBURL = "https://www.fernsehserien.de"
	IMG_HOST = "bilder.fernsehserien.de"
	USERAGENTS = [
		"Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.89 Safari/537.36",
	]
	ALIASES = {
		"punkt 12": "punkt-12",
		"punkt 12 das rtl mittagsjournal": "punkt-12",
		"alles was zählt": "alles-was-zaehlt",
		"alles was zaehlt": "alles-was-zaehlt",
		"berlin tag und nacht": "berlin-tag-und-nacht",
		"berlin tag nacht": "berlin-tag-und-nacht",
		"berlin - tag und nacht": "berlin-tag-und-nacht",
		"berlin - tag & nacht": "berlin-tag-und-nacht",
		"gzsz": "gute-zeiten-schlechte-zeiten",
		"gute zeiten schlechte zeiten": "gute-zeiten-schlechte-zeiten",
		"in aller freundschaft": "in-aller-freundschaft",
		"in aller freundschaft die jungen ärzte": "in-aller-freundschaft-die-jungen-aerzte",
		"in aller freundschaft die jungen aerzte": "in-aller-freundschaft-die-jungen-aerzte",
		"köln 50667": "koeln-50667",
		"koeln 50667": "koeln-50667",
		"rote rosen": "rote-rosen",
		"sturm der liebe": "sturm-der-liebe",
		"unter uns": "unter-uns",
	}
	CHANNEL_ALIASES = {
		"rtl": "rtl",
		"rtl hd": "rtl",
		"rtl television": "rtl",
		"rtl television hd": "rtl",
		"3sat": "3sat",
		"3sat hd": "3sat",
		"zdf": "zdf",
		"zdf hd": "zdf",
		"zdfinfo": "zdfinfo",
		"zdfinfo hd": "zdfinfo",
		"arte": "arte",
		"arte hd": "arte",
		"sat 1": "sat1",
		"sat1": "sat1",
		"sat 1 hd": "sat1",
		"sat1 hd": "sat1",
		"pro sieben": "prosieben",
		"pro7": "prosieben",
		"prosieben": "prosieben",
		"kabel eins": "kabel-eins",
		"kabeleins": "kabel-eins",
		"vox": "vox",
		"vox hd": "vox",
		"rtl zwei": "rtl-zwei",
		"rtl2": "rtl-zwei",
		"rtl zwei hd": "rtl-zwei",
	}
	WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

	def __init__(self):
		self.language = ""
		self.active = False

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
		return {
			"User-Agent": choice(self.USERAGENTS),
			"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
			"Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
		}

	def _get_html(self, url, timeout=(3.05, 7)):
		try:
			response = get(url, headers=self._headers(), timeout=timeout)
			if response.status_code == 404:
				return "not-found", ""
			response.raise_for_status()
			return "", response.text
		except exceptions.RequestException as err:
			self._log(f"FETCH_MISS get_html url='{url}' error={err}", level="warning")
			return str(err), ""

	def _clean_text(self, value):
		value = unescape(str(value or ""))
		value = sub(r"<script.*?</script>", " ", value, flags=IGNORECASE | S)
		value = sub(r"<style.*?</style>", " ", value, flags=IGNORECASE | S)
		value = sub(r"<br\s*/?>", " ", value, flags=IGNORECASE)
		value = sub(r"<.*?>", " ", value, flags=S)
		value = value.replace("&amp;", "&")
		return sub(r"\s+", " ", value).strip()

	def _normalize(self, value):
		value = self._clean_text(value).lower()
		value = value.replace("&", " und ")
		value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
		value = sub(r"[._\-:|/]+", " ", value)
		value = sub(r"[^a-z0-9 ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def _slugify(self, value):
		norm = self._normalize(value)
		if not norm:
			return ""
		return sub(r"\s+", "-", norm).strip("-")

	def _full_url(self, url):
		url = unescape(str(url or "").strip())
		if not url:
			return ""
		if url.startswith("//"):
			return "https:" + url
		if url.startswith("/"):
			return self.WEBURL + url
		return url

	def _image_url_from_value(self, value):
		url = self._full_url(value.split()[0].strip("'\" ,"))
		if not url:
			return ""
		lower = url.lower()
		if self.IMG_HOST not in lower:
			return ""
		if not (".jpg" in lower or ".jpeg" in lower or ".png" in lower or ".webp" in lower):
			return ""
		# Keep editorial EPG/still images and reject logos, buttons and app artwork.
		if "/epg/" not in lower and "/news/" not in lower and "/serien/" not in lower:
			return ""
		for marker in ("logo", "lupe", "stream", "ansehen", "app", "button", "icon"):
			if marker in lower:
				return ""
		return url

	def _extract_images_with_context(self, html):
		items = []
		seen = set()
		items_by_url = {}
		for tag_match in findall(r"<[^>]+(?:src|href|data-src|srcset)=[^>]+>", html or "", flags=IGNORECASE | S):
			urls = []
			for attr in ("src", "href", "data-src", "data-original", "data-lazy-src"):
				for raw in findall(r"%s\s*=\s*['\"]([^'\"]+)['\"]" % attr, tag_match, flags=IGNORECASE):
					urls.append(raw)
			for raw in findall(r"srcset\s*=\s*['\"]([^'\"]+)['\"]", tag_match, flags=IGNORECASE):
				for part in raw.split(","):
					urls.append(part.strip().split()[0])
			alt = self._clean_text(self._attr_value(tag_match, "alt"))
			if self._normalize(alt) in ("jetzt online streamen", "jetzt ansehen", "meinen serien hinzufuegen"):
				continue
			pos = html.find(tag_match)
			for raw_url in urls:
				url = self._image_url_from_value(raw_url)
				if not url:
					continue
				start = max(0, pos - 1800)
				end = min(len(html), pos + 3200)
				if url in seen:
					item = items_by_url.get(url)
					if item and alt and not item.get("alt"):
						item["alt"] = alt
					continue
				seen.add(url)
				item = {
					"url": url,
					"alt": alt,
					"context": html[start:end],
				}
				items.append(item)
				items_by_url[url] = item
		return items

	def _attr_value(self, tag, attr):
		found = search(r"%s\s*=\s*['\"]([^'\"]*)['\"]" % attr, tag or "", flags=IGNORECASE | S)
		return found.group(1) if found else ""

	def _date_variants(self, begin_time):
		try:
			begin_dt = datetime.fromtimestamp(int(begin_time or 0))
		except Exception:
			return []
		if not begin_dt:
			return []
		weekday = self.WEEKDAYS_DE[begin_dt.weekday()]
		return [
			begin_dt.strftime("%d.%m.%Y"),
			begin_dt.strftime("%-d.%m.%Y") if hasattr(begin_dt, "strftime") else begin_dt.strftime("%d.%m.%Y"),
			begin_dt.strftime("%d.%m."),
			begin_dt.strftime("%-d.%m.") if hasattr(begin_dt, "strftime") else begin_dt.strftime("%d.%m."),
			f"{weekday}. {begin_dt.strftime("%d.%m.%Y")}",
			f"{weekday}. {begin_dt.strftime("%-d.%m.%Y") if hasattr(begin_dt, "strftime") else begin_dt.strftime("%d.%m.%Y")}",
		]

	def _sendetermin_suffix(self, begin_time):
		try:
			begin_dt = datetime.fromtimestamp(int(begin_time or 0))
		except Exception:
			return ""
		try:
			return begin_dt.strftime("%d.%m.%Y-%H:%M-Uhr")
		except Exception:
			return ""

	def _channel_slug(self, candidate):
		values = []
		for attr in ("service_name", "channel", "service"):
			value = getattr(candidate, attr, "")
			if value:
				values.append(value)
		for value in values:
			norm = self._normalize(value)
			if not norm:
				continue
			if norm in self.CHANNEL_ALIASES:
				return self.CHANNEL_ALIASES[norm]
			# Common Enigma service names often contain suffixes such as HD or provider words.
			short_norm = sub(r"\b(hd|uhd|sd|television|deutschland)\b", " ", norm)
			short_norm = sub(r"\s+", " ", short_norm).strip()
			if short_norm in self.CHANNEL_ALIASES:
				return self.CHANNEL_ALIASES[short_norm]
			for key, slug in self.CHANNEL_ALIASES.items():
				if len(key) >= 3 and (norm == key or norm.startswith(key + " ") or (" " + key + " ") in (" " + norm + " ")):
					return slug
		return ""

	def _token_overlap(self, left, right):
		left_tokens = set([token for token in self._normalize(left).split() if len(token) >= 4])
		right_tokens = set([token for token in self._normalize(right).split() if len(token) >= 4])
		if not left_tokens or not right_tokens:
			return 0.0
		return float(len(left_tokens.intersection(right_tokens))) / float(max(1, len(left_tokens)))

	def _episode_title_from_context(self, context):
		headings = findall(r"<h[23][^>]*>(.*?)</h[23]>", context or "", flags=IGNORECASE | S)
		for heading in reversed(headings):
			value = self._clean_text(heading).strip(" -:|\t")
			if value and "folge" not in self._normalize(value):
				return value[:100]
		plain = self._clean_text(context)
		found = search(r"Folge\s+\d+\s+([A-ZÄÖÜ][^\.]{3,80})", plain, flags=IGNORECASE)
		if found:
			value = found.group(1).strip(" -:|\t")
			if not value.lower().startswith(("deutsche", "tv", "free-tv")):
				return value[:100]
		return ""

	def _episode_number_from_context(self, context):
		plain = self._clean_text(context)
		found = search(r"Folge\s+(\d+)", plain, flags=IGNORECASE)
		return found.group(1) if found else ""

	def _score_image(self, candidate, item):
		context_text = self._clean_text(item.get("context") or "")
		alt_text = item.get("alt") or ""
		score = 0.05
		reason = []
		for date_text in self._date_variants(getattr(candidate, "begin_time", 0)):
			if date_text and date_text in context_text:
				score += 0.55
				reason.append("date")
				break
		short_desc = getattr(candidate, "short_desc", "") or ""
		ext_desc = getattr(candidate, "extended_desc", "") or ""
		if short_desc:
			overlap = max(self._token_overlap(short_desc, alt_text), self._token_overlap(short_desc, context_text))
			if overlap >= 0.20:
				score += min(0.25, overlap * 0.25)
				reason.append("short")
		if ext_desc:
			overlap = max(self._token_overlap(ext_desc, alt_text), self._token_overlap(ext_desc, context_text))
			if overlap >= 0.12:
				score += min(0.20, overlap * 0.20)
				reason.append("extended")
		if "/epg/" in (item.get("url") or ""):
			score += 0.10
			reason.append("epg-image")
		return min(0.99, score), "+".join(reason) or "first-image"

	def _select_best_image(self, candidate, html):
		images = self._extract_images_with_context(html)
		best = {}
		best_score = 0.0
		best_reason = ""
		for item in images:
			score, reason = self._score_image(candidate, item)
			if score > best_score:
				best = item
				best_score = score
				best_reason = reason
		if not best:
			return {}
		context_text = self._clean_text(best.get("context") or "")
		return {
			"image_url": best.get("url") or "",
			"image_alt": best.get("alt") or "",
			"episode_title": self._episode_title_from_context(best.get("context") or ""),
			"episode_number": self._episode_number_from_context(best.get("context") or ""),
			"overview": context_text[:900],
			"confidence": best_score,
			"reason": best_reason,
		}

	def _title_variants(self, candidate):
		values = []
		for value in (
			getattr(candidate, "search_title", ""),
			getattr(candidate, "title", ""),
		):
			value = str(value or "").strip()
			if value and value not in values:
				values.append(value)
		return values

	def _slugs_for_candidate(self, candidate):
		slugs = []
		seen = set()
		for title in self._title_variants(candidate):
			norm = self._normalize(title)
			for slug in (self.ALIASES.get(norm, ""), self._slugify(title)):
				if slug and slug not in seen:
					seen.add(slug)
					slugs.append(slug)
		return slugs

	def _search_slug(self, title):
		if not title:
			return ""
		url = f"{self.WEBURL}/suche.html?q={quote_plus(title)}"
		err_msg, html = self._get_html(url)
		if err_msg or not html:
			return ""
		title_norm = self._normalize(title)
		for href, label in findall(r"<a[^>]+href=['\"](/[^'\"#?]+)['\"][^>]*>(.*?)</a>", html, flags=IGNORECASE | S):
			label_norm = self._normalize(label)
			if not label_norm or title_norm not in label_norm and label_norm not in title_norm:
				continue
			path = href.strip("/")
			parts = path.split("/")
			if not parts:
				continue
			# Movie pages use /filme/<slug>. Keep the prefix so candidate URLs
			# are built against the correct fernsehserien.de namespace.
			if parts[0] == "filme" and len(parts) > 1 and parts[1]:
				return f"filme/{parts[1]}"
			slug = parts[0]
			if slug and slug not in ("suche.html", "news", "streaming", "serien", "filme"):
				return slug
		return ""

	def _candidate_urls(self, candidate, include_search=False):
		urls = []
		seen = set()
		slugs = self._slugs_for_candidate(candidate)
		if not slugs:
			return urls
		if include_search:
			for title in self._title_variants(candidate):
				search_slug = self._search_slug(title)
				if search_slug and search_slug not in slugs:
					slugs.append(search_slug)
		channel_slug = self._channel_slug(candidate)
		sendetermin_suffix = self._sendetermin_suffix(getattr(candidate, "begin_time", 0))
		for slug in slugs:
			# Exact broadcast pages often contain the best landscape EPG image, e.g.
			# /punkt-12/sendetermine/rtl/15.05.2026-12:00-Uhr.
			if channel_slug and sendetermin_suffix and not slug.startswith("filme/"):
				url = f"{self.WEBURL}/{slug}/sendetermine/{channel_slug}/{sendetermin_suffix}"
				if url not in seen:
					seen.add(url)
					urls.append((slug, url, f"sendetermin:{channel_slug}"))

			# Normal series namespace.
			if not slug.startswith("filme/"):
				for suffix in ("spoiler-vorschau", "episodenguide", ""):
					url = f"{self.WEBURL}/{slug}"
					if suffix:
						url += "/" + suffix
					if url not in seen:
						seen.add(url)
						urls.append((slug, url, suffix or "series"))

			# Movie/documentary pages live below /filme/<slug>. The direct
			# slugified title often exists there even when the series namespace
			# returns 404.
			movie_slug = slug[6:] if slug.startswith("filme/") else slug
			if movie_slug:
				url = f"{self.WEBURL}/filme/{movie_slug}"
				if url not in seen:
					seen.add(url)
					urls.append((f"filme/{movie_slug}", url, "movie"))
		return urls

	def build_final_dict(self, candidate, slug, page_url, selected):
		begin_time = int(getattr(candidate, "begin_time", 0) or 0)
		released = ""
		try:
			released = datetime.fromtimestamp(begin_time).strftime("%Y-%m-%d") if begin_time else ""
		except Exception:
			pass
		episode_number = selected.get("episode_number") or ""
		provider_id = f"{slug}:{episode_number}" if episode_number else slug
		image_url = selected.get("image_url") or ""
		media_type = "movie" if slug.startswith("filme/") or "/filme/" in page_url else "series"
		final_dict = {
			"provider": "fernsehserien",
			"provider_ids": {"fernsehserien": provider_id},
			"title": getattr(candidate, "title", "") or getattr(candidate, "search_title", "") or slug.replace("filme/", "").replace("-", " "),
			"original_title": getattr(candidate, "search_title", "") or getattr(candidate, "title", ""),
			"episode_name": selected.get("episode_title") or "",
			"media_type": media_type,
			"countries": "DE",
			"released": released,
			"overview": selected.get("image_alt") or getattr(candidate, "extended_desc", "") or getattr(candidate, "short_desc", ""),
			"description": selected.get("image_alt") or getattr(candidate, "short_desc", "") or "",
			"image_url": image_url,
			"image_src": "fernsehserien",
			"preview_url": image_url,
			"still_url": image_url,
			"title_ratio": float(selected.get("confidence") or 0.55),
			"desc_ratio": float(selected.get("confidence") or 0.55),
			"source_url": page_url,
			"source_provider": "fernsehserien",
			"source_reason": selected.get("reason") or "",
		}
		return final_dict

	def lookup_epg_event(self, candidate):
		if not self.active:
			return "language-not-german", {}
		if not getattr(candidate, "title", "") and not getattr(candidate, "search_title", ""):
			return "missing-title", {}
		seen_urls = set()
		for include_search in (False, True):
			for slug, url, page_type in self._candidate_urls(candidate, include_search=include_search):
				if url in seen_urls:
					continue
				seen_urls.add(url)
				self._log(f"TRY slug={slug} page={page_type} url='{url}' title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}'")
				err_msg, html = self._get_html(url)
				if err_msg or not html:
					self._log(f"URL_MISS slug={slug} page={page_type} reason={err_msg or "empty-html"} url='{url}'", level="warning")
					continue
				selected = self._select_best_image(candidate, html)
				if not selected.get("image_url"):
					self._log(f"IMAGE_MISS slug={slug} page={page_type} url='{url}'")
					continue
				final_dict = self.build_final_dict(candidate, slug, url, selected)
				self._log(f"MATCH slug={slug} page={page_type} confidence={float(selected.get("confidence") or 0.0):.2f} reason={selected.get("reason") or ""} title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}' episode='{selected.get("episode_title") or ""}' alt='{selected.get("image_alt") or ""}' image='{selected.get("image_url") or ""}' source_url='{url}'", force=True)
				return "", final_dict
		self._log(f"NO_MATCH title='{getattr(candidate, "title", "") or getattr(candidate, "search_title", "")}' slugs='{",".join(self._slugs_for_candidate(candidate))}'")
		return "no-match", {}


provider_fernsehserien = FernsehserienProvider()
