########################################################################################################
# FanArt by Mr.Servo @OpenATV (c) 2026                                                               #
# FanArt.tv Integration Provider                                                                      #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from datetime import datetime
from json import dump
from getopt import getopt, GetoptError
from requests import get, exceptions
from sys import exit, argv

try:
    from .Consts import Fields
except ImportError:
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from Consts import Fields

try:
	from .. import write_log
except ImportError:
	def write_log(log_text1, log_text2=""):
		print(f"{log_text1} {log_text2}")

MODULE_NAME = f"[{__name__.split('.')[-1]}] ".replace("[__main__] ", "")


class ProviderFanArt:
	def __init__(self):
		self.base_url = "https://webservice.fanart.tv/v3"
		self.asset_url = "https://assets.fanart.tv/fanart"
		self.media_types = ["movies", "tv"]
		self.requires_api_key = True
		self.active = False
		self.api_key = ""
		self.personalKey = ""
		self.language = "en"
		self.last_update = None

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return bool(self.active and self.personalKey)

	def stop(self):
		self.active = False

	def start(self, personal_api_key="", language="en"):
		# E2MDB uses a single personal FanArt.tv API key. No separate project key is configured.
		personal_key = (personal_api_key or "").strip()
		self.personalKey = personal_key
		self.api_key = personal_key
		self.language = self._normalize_language(language)
		self.active = bool(self.personalKey)
		self.last_update = datetime.now().isoformat()
		if not self.personalKey:
			return "ERROR: FanArt personal API key is missing. Get it from https://fanart.tv/get-an-api-key/"
		return ""

	def _normalize_language(self, language):
		language = (language or "en").replace("_", "-").lower()
		return language.split("-", 1)[0] or "en"

	def get_artwork(self, fanart_id, media_type="tv"):
		err_msg, artwork_dict = "", {}
		fanart_id = str(fanart_id or "").strip()
		if not self.is_active():
			return "FanArt provider is disabled or personal API key is missing", {}
		if not fanart_id:
			return "FanArt ID is required", {}
		if media_type not in self.media_types:
			return f"Unknown FanArt media_type '{media_type}'", {}

		url = f"{self.base_url}/{media_type}/{fanart_id}"
		params = {"api_key": self.api_key}
		err_msg, response = self.get_api_dicts(url, params)
		if err_msg:
			return err_msg, {}
		artwork_dict = self.create_norm_artwork_dict(response, media_type, fanart_id)
		return "", artwork_dict

	def get_artwork_by_provider_id(self, provider_id, provider_type="tvdb", media_type="tv"):
		return self.get_artwork(provider_id, media_type)

	def get_e2mdb_artwork(self, provider_ids, media_type="series", season_no=""):
		"""Return an e2MDB-style artwork fill dictionary.

		FanArt.tv has no episode stills. This method only fills/replaces
		cover_url, backdrop_url and titlelogo_url.
		"""
		provider_ids = provider_ids or {}
		media_type = (media_type or "").lower()
		if media_type == "movie":
			fanart_media_type = "movies"
			fanart_id = provider_ids.get("tmdb") or provider_ids.get("imdb") or ""
		elif media_type == "series":
			fanart_media_type = "tv"
			fanart_id = provider_ids.get("tvdb") or ""
		else:
			return "", {}
		if not fanart_id:
			return "", {}
		err_msg, artwork = self.get_artwork(fanart_id, fanart_media_type)
		if err_msg or not artwork:
			return err_msg, {}
		return "", self.create_e2mdb_artwork_fill(artwork, fanart_media_type, season_no)

	def create_e2mdb_artwork_fill(self, artwork_dict, fanart_media_type="tv", season_no=""):
		artwork = artwork_dict.get("artwork", {}) or {}
		fill_dict = {}
		season_no = str(season_no or "").strip()

		if fanart_media_type == "tv":
			season_posters = [item for item in artwork.get("seasonals", []) if item.get("artworkType") == "season_poster"]
			season_thumbs = [item for item in artwork.get("seasonals", []) if item.get("artworkType") in ("season_thumb", "season_banner")]
			if season_no:
				exact_season_posters = [item for item in season_posters if str(item.get("season", "")) == season_no]
				exact_season_thumbs = [item for item in season_thumbs if str(item.get("season", "")) == season_no]
			else:
				exact_season_posters = []
				exact_season_thumbs = []
			poster = self._pick_best(exact_season_posters) or self._pick_best(artwork.get("posters", []))
			backdrop = self._pick_best(exact_season_thumbs) or self._pick_best(artwork.get("backdrops", [])) or self._pick_best(artwork.get("thumbs", []))
			logo = self._pick_best(artwork.get("logos", []))
		else:
			poster = self._pick_best(artwork.get("posters", []))
			backdrop = self._pick_best(artwork.get("backdrops", [])) or self._pick_best(artwork.get("thumbs", []))
			logo = self._pick_best(artwork.get("logos", []))

		if poster.get("url"):
			fill_dict["cover_url"] = poster.get("url")
			fill_dict["cover_src"] = "fanart"
		if backdrop.get("url"):
			fill_dict["backdrop_url"] = backdrop.get("url")
			fill_dict["backdrop_src"] = "fanart"
		if logo.get("url"):
			fill_dict["titlelogo_url"] = logo.get("url")
			fill_dict["titlelogo_src"] = "fanart"
		return fill_dict

	def create_norm_artwork_dict(self, fanart_response, media_type="tv", fanart_id=""):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "fanart")
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		if media_type == "tv":
			self.set_dict_key(norm_dict, "tvdb_id", str(fanart_response.get("id", fanart_id)))
			self.set_dict_key(norm_dict, "imdb_id", fanart_response.get("imdb_id", ""))
			self.set_dict_key(norm_dict, "tmdb_id", str(fanart_response.get("tmdb_id", "")))
		else:
			self.set_dict_key(norm_dict, "tmdb_id", str(fanart_response.get("id", fanart_id)))
			self.set_dict_key(norm_dict, "imdb_id", fanart_response.get("imdb_id", ""))

		artwork = {
			"posters": [],
			"backdrops": [],
			"logos": [],
			"banners": [],
			"cleararts": [],
			"seasonals": [],
			"characters": [],
			"discs": [],
			"thumbs": []
		}

		def add_items(target, source_key, artwork_type):
			for item in fanart_response.get(source_key, []) or []:
				artwork[target].append(self._normalize_artwork_item(item, artwork_type, fanart_id or fanart_response.get("id", ""), media_type, source_key))

		if media_type == "tv":
			add_items("posters", "tvposter", "poster")
			add_items("backdrops", "showbackground", "backdrop")
			add_items("backdrops", "tvbackground", "backdrop")
			add_items("thumbs", "tvthumb", "thumb")
			add_items("logos", "hdtvlogo", "logo")
			add_items("logos", "clearlogo", "logo")
			add_items("banners", "tvbanner", "banner")
			add_items("cleararts", "hdclearart", "clearart")
			add_items("cleararts", "clearart", "clearart")
			add_items("seasonals", "seasonposter", "season_poster")
			add_items("seasonals", "seasonthumb", "season_thumb")
			add_items("seasonals", "seasonbanner", "season_banner")
			add_items("characters", "characterart", "character")
		elif media_type == "movies":
			add_items("posters", "movieposter", "poster")
			add_items("backdrops", "moviebackground", "backdrop")
			add_items("thumbs", "moviethumb", "thumb")
			add_items("logos", "hdmovielogo", "logo")
			add_items("logos", "movielogo", "logo")
			add_items("banners", "moviebanner", "banner")
			add_items("cleararts", "hdmovieclearart", "clearart")
			add_items("cleararts", "movieart", "clearart")
			add_items("cleararts", "clearart", "clearart")
			add_items("discs", "moviedisc", "disc")

		artwork = {key: value for key, value in artwork.items() if value}
		self.set_dict_key(norm_dict, "artwork", artwork)
		return norm_dict

	def _normalize_artwork_item(self, item, artwork_type, fanart_id, media_type, source_key):
		normalized = {}
		url = self._normalize_artwork_url(item.get("url", ""), fanart_id, media_type, source_key)
		self.set_dict_key(normalized, "url", url)
		self.set_dict_key(normalized, "lang", item.get("lang", ""))
		self.set_dict_key(normalized, "likes", str(item.get("likes", 0)))
		self.set_dict_key(normalized, "artworkType", artwork_type)
		self.set_dict_key(normalized, "sourceKey", source_key)
		self.set_dict_key(normalized, "width", str(item.get("width", "")))
		self.set_dict_key(normalized, "height", str(item.get("height", "")))
		if artwork_type in ("season_poster", "season_thumb", "season_banner"):
			self.set_dict_key(normalized, "season", str(item.get("season", "")))
		if artwork_type == "character":
			self.set_dict_key(normalized, "character_name", item.get("name", ""))
		return normalized

	def _normalize_artwork_url(self, raw_url, fanart_id, media_type, source_key):
		raw_url = str(raw_url or "").strip()
		if not raw_url:
			return ""
		if raw_url.startswith("http://") or raw_url.startswith("https://"):
			return raw_url
		if raw_url.startswith("//"):
			return "https:" + raw_url
		if raw_url.startswith("assets.fanart.tv/"):
			return "https://" + raw_url
		if raw_url.startswith("fanart/"):
			return "https://assets.fanart.tv/" + raw_url
		media_folder = "tv" if media_type == "tv" else "movies"
		if "/" in raw_url:
			return f"{self.asset_url}/{raw_url.lstrip('/')}"
		return f"{self.asset_url}/{media_folder}/{fanart_id}/{source_key}/{raw_url}"

	def _pick_best(self, items, season_no=""):
		items = list(items or [])
		if season_no:
			season_items = [item for item in items if str(item.get("season", "")) == str(season_no)]
			if season_items:
				items = season_items
		if not items:
			return {}
		lang = self._normalize_language(self.language)

		def score(item):
			item_lang = self._normalize_language(item.get("lang", ""))
			try:
				likes = int(item.get("likes", 0))
			except Exception:
				likes = 0
			if item_lang == lang:
				lang_score = 3000
			elif item_lang == "en":
				lang_score = 2000
			elif item_lang in ("00", "", "none"):
				lang_score = 1000
			else:
				lang_score = 0
			return lang_score + likes

		return sorted(items, key=score, reverse=True)[0]

	def get_best_artwork(self, fanart_id, media_type="tv", artwork_type="tvposter"):
		err_msg, artwork = self.get_artwork(fanart_id, media_type)
		if err_msg:
			return err_msg, {}
		all_artwork = artwork.get("artwork", {}) or {}
		best_item = None
		for category_items in all_artwork.values():
			for item in category_items:
				if best_item is None or self._pick_best([best_item, item]) == item:
					best_item = item
		if not best_item:
			return f"No artwork found for type '{artwork_type}'", {}
		return "", best_item

	def _auth_candidates(self, params=None):
		"""Return request variants for personal FanArt keys.

		E2MDB has only one configured FanArt.tv key. Try the common FanArt
		parameter/header names with that same key so no separate project key is needed.
		"""
		base_params = dict(params or {})
		key = self.personalKey or self.api_key
		if not key:
			return [({"accept": "application/json"}, base_params)]
		return [
			({"accept": "application/json", "api-key": key}, dict(base_params, api_key=key)),
			({"accept": "application/json", "client-key": key}, dict(base_params, client_key=key)),
			({"accept": "application/json", "api-key": key, "client-key": key}, dict(base_params, api_key=key, client_key=key)),
		]

	def get_api_dicts(self, url, params=None, timeout=(3.05, 8)):
		last_error = ""
		for headers, request_params in self._auth_candidates(params):
			try:
				response = get(url, params=request_params or {}, headers=headers, timeout=timeout)
				if response.ok:
					return "", response.json()
				if response.status_code == 404:
					return "No FanArt artwork found", {}
				last_error = f"API server access ERROR, response code: {response.status_code}"
				if response.status_code not in (401, 403):
					return last_error, {}
			except (exceptions.RequestException, ValueError) as err_msg:
				return str(err_msg), {}
		return last_error or "API server access ERROR", {}

	def set_dict_key(self, dictionary, key, value):
		if value:
			dictionary[key] = value


provider_fanart = ProviderFanArt()


def main(argv):
	fanart_id, media_type, api_key, language = "", "tv", "", "en"
	try:
		opts, args = getopt(argv, "i:m:a:l:h", ["id=", "media_type=", "api_key=", "language=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\nTry 'python FanArt.py -h' for more information")
		exit(2)

	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if opt == "-h" or opt == "--help":
			write_log("Usage 'FanArt': python FanArt.py -i <id> -m <tv|movies> -a <personal-api-key> [-l <language>]\n"
			"Example TV:    python FanArt.py -i 462625 -m tv -a {personal-api-key} -l de\n"
			"Example Movie: python FanArt.py -i 1241982 -m movies -a {personal-api-key} -l de\n")
			exit()
		elif opt in ("-i", "--id"):
			fanart_id = arg
		elif opt in ("-m", "--media_type"):
			media_type = arg
		elif opt in ("-a", "--api_key"):
			api_key = arg
		elif opt in ("-l", "--language"):
			language = arg

	if not fanart_id:
		write_log("ERROR: FanArt ID is required (-i option)")
		exit(2)
	if media_type not in ("tv", "movies"):
		write_log("ERROR: media_type must be 'tv' or 'movies'")
		exit(2)
	err_msg = provider_fanart.start(api_key, language)
	if err_msg:
		write_log(err_msg)
		exit(2)
	write_log(f"Fetching FanArt artwork for {media_type} ID '{fanart_id}'...")
	err_msg, artwork = provider_fanart.get_artwork(fanart_id, media_type)
	if err_msg:
		write_log(f"ERROR: {err_msg}")
		exit(2)
	file_name = f"fanart_{fanart_id}_{media_type}.json"
	with open(file_name, "w") as file:
		dump(artwork, file, indent=2)
	write_log(f"Artwork file '{file_name}' was successfully created.")
	artwork_items = artwork.get("artwork", {})
	write_log(f"Summary: {sum(len(items) for items in artwork_items.values())} artwork items in {len(artwork_items)} categories")


if __name__ == "__main__":
	main(argv[1:])
