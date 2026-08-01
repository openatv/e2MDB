########################################################################################################
# e2MDB title translation search helper                                                                #
# ---------------------------------------------------------------------------------------------------- #
# Optional Google title translation used only as a temporary provider-search fallback.                  #
########################################################################################################

from json import loads
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from Components.config import config

from . import write_log, e2mdbglobals


TRANSLATE_API_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_TIMEOUT = 8

GOOGLE_LANGUAGE_ALIASES = {
	"jv": "jw",
	"he": "iw",
	"zh_cn": "zh-CN",
	"zh-cn": "zh-CN",
	"zh_hans": "zh-CN",
	"zh-hans": "zh-CN",
	"zh_tw": "zh-TW",
	"zh-tw": "zh-TW",
	"zh_hant": "zh-TW",
	"zh-hant": "zh-TW",
}


class E2MDBTitleTranslator:
	MODULE_NAME = "[E2MDBTitleTranslator]"

	def __init__(self):
		self.memory_cache = {}

	def enabled(self):
		try:
			return bool(config.plugins.e2mdb.translateTitleSearch.value)
		except Exception:
			return False

	def target_language(self):
		try:
			language = getattr(config.plugins.e2mdb, "translateTitleSearchLanguage", None)
			if language is not None:
				return self.normalize_language(language.value)
		except Exception:
			pass
		try:
			return self.normalize_language(config.plugins.e2mdb.lang.value)
		except Exception:
			return ""

	def normalize_language(self, language):
		language = str(language or "").strip().replace("_", "-")
		if not language:
			return ""
		language_key = language.lower()
		if language_key in GOOGLE_LANGUAGE_ALIASES:
			return GOOGLE_LANGUAGE_ALIASES[language_key]
		base_language = language_key.split("-", 1)[0]
		return GOOGLE_LANGUAGE_ALIASES.get(base_language, base_language)

	def _parse_google_response(self, payload, original_text):
		if payload.startswith(")]}'"):
			payload = payload.split("\n", 1)[1] if "\n" in payload else ""
		data = loads(payload)
		translated = ""
		for item in data[0] if data and isinstance(data[0], list) else []:
			if isinstance(item, list) and item:
				translated += str(item[0] or "")
		return translated.strip() or original_text

	def translate_title(self, title, target_lang=None):
		if not self.enabled():
			return ""
		title = str(title or "").strip()
		if not title:
			return ""
		target_lang = self.normalize_language(target_lang or self.target_language())
		if not target_lang:
			return ""
		cache_key = (title, target_lang)
		if cache_key in self.memory_cache:
			return self.memory_cache[cache_key]
		params = urlencode({
			"client": "gtx",
			"sl": "auto",
			"tl": target_lang,
			"dt": "t",
			"q": title,
		})
		request = Request(
			"%s?%s" % (TRANSLATE_API_URL, params),
			headers={
				"User-Agent": getattr(e2mdbglobals, "USERAGENT", "Mozilla/5.0"),
				"Accept": "application/json,text/plain,*/*",
				"Accept-Charset": "utf-8",
			},
		)
		try:
			with urlopen(request, timeout=TRANSLATE_TIMEOUT) as response:
				payload = response.read().decode("utf-8", "replace")
			translated = self._parse_google_response(payload, title)
		except (HTTPError, URLError, SocketTimeout, TimeoutError, ValueError, TypeError, IndexError) as err:
			write_log(f"{self.MODULE_NAME} title translation failed target={target_lang} title='{title}': {err}")
			translated = ""
		if translated and translated.strip().casefold() == title.casefold():
			translated = ""
		self.memory_cache[cache_key] = translated
		if translated:
			write_log(f"{self.MODULE_NAME} translated search title target={target_lang} original='{title}' translated='{translated}'")
		return translated


translator = E2MDBTitleTranslator()


def translate_title_for_search(title, target_lang=None):
	return translator.translate_title(title, target_lang=target_lang)
