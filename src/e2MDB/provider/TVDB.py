########################################################################################################
# TVDB by Mr.Servo @OpenATV (c) 2026                                                                   #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from json import dump
from getopt import getopt, GetoptError
from requests import get, post, exceptions
from sys import exit, argv
from datetime import datetime

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
	def write_log(log_text1, log_text2=""):  # if TVDB Interactive (via shell) is used
		print(f"{log_text1} {log_text2}")

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class ProviderTVDB:
	def __init__(self):
		self.base_url = "https://api4.thetvdb.com/v4"
		self.img_url = "https://artworks.thetvdb.com"
		self.media_types = ["movie", "series"]  # exclude from search: 'person', 'company'
		self.lang_code, self.api_key, self.token = "", "", ""
		self.artwork_type_names = {}
		self.last_update = None  # track when data was last updated

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language="en"):
		self.api_key = api_key or self.api_key
		self.language = language
		langMap = {
			"aa": "aar", "af": "afr", "am": "amh", "ar": "ara", "ay": "aym", "az": "aze", "be": "bel", "bn": "ben",
			"bi": "bis", "bs": "bos", "bg": "bul", "byn": "byn", "ca": "cat", "cs": "ces", "ch": "cha", "da": "dan",
			"de": "deu", "dv": "div", "dz": "dzo", "el": "ell", "en": "eng", "et": "est", "fan": "fan", "fo": "fao",
			"fa": "fas", "fj": "fij", "fi": "fin", "fr": "fra", "ff": "ful", "ga": "gle", "gv": "glv", "gn": "grn",
			"ht": "hat", "he": "heb", "hif": "hif", "hi": "hin", "hr": "hrv", "hu": "hun", "hy": "hye", "id": "ind",
			"is": "isl", "it": "ita", "ja": "jpn", "kl": "kal", "ka": "kat", "kk": "kaz", "km": "khm", "rw": "kin",
			"ky": "kir", "kg": "kon", "ko": "kor", "kun": "kun", "ku": "kur", "lo": "lao", "la": "lat", "lv": "lav",
			"ln": "lin", "lt": "lit", "lb": "ltz", "lu": "lub", "mh": "mah", "mk": "mkd", "mg": "mlg", "mt": "mlt",
			"mn": "mon", "mi": "mri", "ms": "msa", "my": "mya", "na": "nau", "nr": "nbl", "nd": "nde", "ne": "nep",
			"nl": "nld", "nn": "nno", "nb": "nob", "no": "nor", "nrb": "nrb", "ny": "nya", "pa": "pan", "pl": "pol",
			"pt": "por", "ps": "pus", "qu": "que", "rar": "rar", "rm": "roh", "ro": "ron", "rtm": "rtm", "rn": "run",
			"ru": "rus", "sg": "sag", "si": "sin", "sk": "slk", "sl": "slv", "sm": "smo", "sn": "sna", "so": "som",
			"st": "sot", "es": "spa", "sq": "sqi", "sr": "srp", "ss": "ssw", "ssy": "ssy", "sw": "swa", "sv": "swe",
			"ta": "tam", "tg": "tgk", "th": "tha", "tig": "tig", "ti": "tir", "to": "ton", "tn": "tsn", "ts": "tso",
			"tk": "tuk", "tr": "tur", "uk": "ukr", "ur": "urd", "uz": "uzb", "ve": "ven", "vi": "vie", "xh": "xho",
			"zh": "zho", "zu": "zul"}  # 'localeCode' to 'ISO 639-2', source: 'https://simplelocalize.io/data/locales/'
		if not self.token:
			err_msg, self.token = self.get_token()
			if err_msg:
				return err_msg
		lang_code = langMap.get(language, "")  # e.g. 'deu' in case of 'de'
		err_msg, languages = self.get_languages()
		if not err_msg:
			codes = [code.get("id", "") for code in languages if lang_code == code.get("id", "")]
			if codes:
				self.lang_code = codes[0]
			else:
				self.lang_code = "eng"
				write_log(f"{MODULE_NAME}INFO in module 'start': language '{language}' is not supported. Continue with English language...")
		else:
			self.lang_code = "eng"
			write_log(f"{MODULE_NAME}INFO in module 'start': Language table could not be downloaded, continue with English language....")
		self.last_update = datetime.now().isoformat()
		return err_msg

	def get_result_dicts(self, title, media_type="series", year=None):
		norm_dicts = []
		if media_type not in self.media_types:
			return f"ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		url = f"{self.base_url}/search"
		params = {
			"query": title,
			"type": media_type,
			"year": year,
			"language": self.lang_code,
			"limit": 10,
			"page": 0
		}
		err_msg, tvdb_dict = self.get_api_dicts(url, params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts(tvdb_dict.get("data", {}))
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, tvdb_dicts, entriesmax=0):
		norm_dicts = []
		results = tvdb_dicts[:entriesmax] if entriesmax else tvdb_dicts
		for result in results:
			try:
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
				self.set_dict_key(norm_dict, Fields.TITLE, self.get_title(result))
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, result.get("primary_type", "") or result.get("type", ""))
				self.set_dict_key(norm_dict, Fields.COUNTRIES, "/".join([x[:2].upper() for x in result.get("country", "").split(", ")]))
				self.set_dict_key(norm_dict, Fields.RELEASED, result.get("first_air_time", ""))  # e.g. '1970-11-29'
					# TVDB don't support 'genres' in search results
				self.set_dict_key(norm_dict, Fields.OVERVIEW, result.get("overviews", {}).get(self.lang_code, ""))  # longtext
				# TVDB don't support 'vote_average' and 'vote_count' in search results
				cover_url = result.get("image_url", "")
				if "missing" in cover_url:  # ignore dummy pictures for missing movie/series covers
					cover_url = ""
				self.set_dict_key(norm_dict, Fields.COVER_URL, cover_url)
				tvdb_id = {"tvdb": result.get("id", "").replace("series-", "").replace("episode-", "").replace("movie-", "")}
				provider_ids = tvdb_id | self.get_remote_ids(result, "remote_ids")
				self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, provider_ids)
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movie_id):
		err_msg, movie_details = "", {}
		if movie_id and movie_id.isdigit() and int(movie_id):
			err_msg, asset_dict = self.get_asset_dict("movie", movie_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
			else:
				movie_details = self.create_norm_movie_dict(asset_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TVDB.get_movie_details': missing parameter 'movie_id'."
		return err_msg, movie_details

	def create_norm_movie_dict(self, movie_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
		self.set_dict_key(norm_dict, Fields.TITLE, self.get_title(movie_dict))
		#  TVDB don't support 'tagline' in movie data
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "movie")
		self.set_dict_key(norm_dict, Fields.COUNTRIES, movie_dict.get("originalCountry", "").upper())
		self.set_dict_key(norm_dict, Fields.RELEASED, movie_dict.get("first_release", {}).get("date", "") or movie_dict.get("year", ""))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, self.get_age_rating(movie_dict))
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(movie_dict.get("vote_average", "")))
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(movie_dict.get("vote_count", "")))
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(self.get_all_genres(movie_dict)))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.get_overview(movie_dict))  # longtext
		self.set_dict_key(norm_dict, Fields.RUNTIME, str(movie_dict.get("runtime", "")))
		for pic_type, pic_url in self.get_pictures_list(movie_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "movie")
		tvdb_id = {"tvdb": str(movie_dict.get("id", ""))}
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, tvdb_id | self.get_remote_ids(movie_dict, "remoteIds"))
		crew_list, cast_list = self.get_characters(movie_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		return norm_dict

	def get_token(self):
		err_msg, auth_dict = "", {}
		url = f"{self.base_url}/login"
		headers = {"accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
		json = {"apikey": self.api_key, "pin": ""}
		try:
			response = post(url, json=json, headers=headers, timeout=(3.05, 6))
			response.raise_for_status()
			err_msg, auth_dict = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			del response
			if err_msg:
				return err_msg, {}
		except exceptions.RequestException as err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_token': {err_msg}")
			return err_msg, {}
		return ("", auth_dict.get("data", {}).get("token", "")) if auth_dict.get("status", "") == "success" else ("{unknown error}", "")

	def get_languages(self):
		url = f"{self.base_url}/languages"
		err_msg, tvdb_dict = self.get_api_dicts(url)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_languages': {err_msg}")
		return err_msg, tvdb_dict.get("data", {})

	def find_season_episode(self, episode_index, episode_name="", plain_season_episode=""):
		if episode_index:
			if plain_season_episode:
				for episode in episode_index.get("episodes", {}).items():
					if episode[0] == plain_season_episode:
						return (episode[0], episode[1][0], episode[1][1])
				if str(plain_season_episode).isdigit():
					for episode in episode_index.get("episodes", {}).items():
						if episode[0].split("-")[-1] == str(int(plain_season_episode)):
							return (episode[0], episode[1][0], episode[1][1])  # season_episode, e.g. ('1-2', '283766', 'Die Warnung')
			elif episode_name:
				for episode in episode_index.get("episodes", {}).items():
					index_name, episode_name = episode[1][1].lower(), episode_name.lower()
					if episode_name and (index_name in episode_name or episode_name in index_name):
						return (episode[0], episode[1][0], episode[1][1])  # season_episode, e.g. ('1-2', '283766', 'Die Warnung')
		return ()

	def get_all_episodes_by_series(self, series_id, max_pages=None):
		err_msg, all_episodes = "", {}
		page = 0
		total_pages = 1
		episode_count = 0
		if not (series_id and series_id.isdigit() and int(series_id)):
			return f"ERROR: Invalid series_id '{series_id}'", {}
		while page < total_pages and (max_pages is None or page < max_pages):
			url = f"{self.base_url}/series/{series_id}/episodes/default/{self.lang_code}"
			params = {"page": page}
			err_msg, tvdb_dict = self.get_api_dicts(url, params)
			if err_msg:
				if page == 0:
					write_log(f"{MODULE_NAME}ERROR in module 'get_all_episodes_by_series': {err_msg}")
					return err_msg, {}
				else:
					write_log(f"{MODULE_NAME}WARNING: Stopped at page {page}: {err_msg}")
					break
			for episode in tvdb_dict.get("data", {}).get("episodes", []):  # extract episodes from this page
				season_no = episode.get("seasonNumber", "")
				episode_no = episode.get("number", "")
				episode_name = episode.get("name", "")
				episode_id = str(episode.get("id", ""))
				if season_no and episode_no:
					key = f"{season_no}-{episode_no}"
					all_episodes[key] = (episode_id, episode_name or f"Episode {episode_no}")
					episode_count += 1
			links = tvdb_dict.get("links", {})  # check if there are more pages
			total_pages = links.get("last_page", page + 1)
			page += 1
		write_log(f"{MODULE_NAME}INFO: Loaded {episode_count} episodes across {page} pages")
		return "", all_episodes

	def get_episodes_by_season_paginated(self, series_id, season_no=None):
		err_msg, all_episodes = "", {}
		page = 0
		total_pages = 1
		episode_count = 0
		if not (series_id and series_id.isdigit() and int(series_id)):
			return f"ERROR: Invalid series_id '{series_id}'", {}
		while page < total_pages:
			url = f"{self.base_url}/series/{series_id}/episodes/default/{self.lang_code}"
			params = {"page": page}
			if season_no:
				params["seasonNumber"] = season_no
			err_msg, tvdb_dict = self.get_api_dicts(url, params)
			if err_msg:
				if page == 0:
					return err_msg, {}
				break
			for episode in tvdb_dict.get("data", {}).get("episodes", []):
				season_no_resp = episode.get("seasonNumber", "")
				episode_no = episode.get("number", "")
				episode_name = episode.get("name", "")
				episode_id = str(episode.get("id", ""))
				if season_no_resp and episode_no:
					key = f"{season_no_resp}-{episode_no}"
					all_episodes[key] = (episode_id, episode_name or f"Episode {episode_no}")
					episode_count += 1
			links = tvdb_dict.get("links", {})
			total_pages = links.get("last_page", page + 1)
			page += 1
		return "", all_episodes

	def get_series_details_index(self, series_id):
		err_msg, series_index, episode_index = "", {}, {}
		if series_id and series_id.isdigit() and int(series_id):
			err_msg, asset_dict = self.get_asset_dict("series", series_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			series_index = self.create_norm_series_dict(asset_dict)
			err_msg, episode_dict = self.get_all_episodes_by_series(series_id)  # load ALL episodes with pagination
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR loading episodes: {err_msg}")
				return err_msg, series_index, {}
			episode_index = {"provider": "tvdb", "episodes": episode_dict}  # create normalized episode index
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'get_series_details_index': missing parameter 'series_id'."
		return err_msg, series_index, episode_index

	def create_norm_series_dict(self, series_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
		self.set_dict_key(norm_dict, Fields.TITLE, self.get_title(series_dict))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "series")
		self.set_dict_key(norm_dict, Fields.SERIES_ID, str(series_dict.get("id", 0)))
		self.set_dict_key(norm_dict, Fields.COUNTRIES, series_dict.get("originalCountry", "").upper())
		self.set_dict_key(norm_dict, Fields.RELEASED, series_dict.get("firstAired", ""))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, self.get_age_rating(series_dict))
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(self.get_all_genres(series_dict)))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.get_overview(series_dict))  # longtext
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
		for pic_type, pic_url in self.get_pictures_list(series_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "series")
		tvdb_id = {"tvdb": str(series_dict.get("id", ""))}
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, tvdb_id | self.get_remote_ids(series_dict, "remoteIds"))
		season_details = []
		norm_dict["seasons"] = {}
		for season in series_dict.get("seasons", []):
			season_dict = {}
			season_no = str(season.get("number", ""))
			self.set_dict_key(season_dict, Fields.SEASON_NAME, self.get_title(season) or f"Season {season_no}")
			self.set_dict_key(season_dict, "season_id", str(season.get("id", "")))
			self.set_dict_key(season_dict, Fields.SEASON_NO, season_no)
			# TVDB don't support 'released' in season list of series
			self.set_dict_key(season_dict, Fields.OVERVIEW, self.get_overview(season))
			for pic_type, pic_url in self.get_pictures_list(season):
				self.set_dict_key(season_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(season_dict, f"{pic_type}_src", "season")
			crew_list, cast_list = self.get_characters(season_dict)
			self.set_dict_key(season_dict, Fields.CREW, crew_list)
			self.set_dict_key(season_dict, Fields.CAST, cast_list)
			season_details.append(season_dict)
		self.set_dict_key(norm_dict, Fields.SEASONS, season_details)
		crew_list, cast_list = self.get_characters(series_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		return norm_dict

	def create_norm_episode_index(self, index_dict):  # get episodes index only
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
		self.set_dict_key(norm_dict, Fields.EPISODE_NAME, self.get_title(index_dict))
		self.set_dict_key(norm_dict, Fields.SERIES_ID, str(index_dict.get("id", 0)))
		norm_dict["episodes"] = {}
		for episode in index_dict.get("episodes", []):
			name = episode.get("name", "").split(" - ")
			name = name[2] if len(name) > 2 else name[0]  # might be 'Odenthal - 15 - Mordfieber', so reduce to 'Mordfieber'
			season_no = episode.get("seasonNumber", "")
			episode_no = episode.get("number", "")
			if not name:  # in case create a episode name
				name = f"Episode {episode_no}"
			self.set_dict_key(norm_dict["episodes"], f"{season_no}-{episode_no}", (str(episode.get("id", 0)), name))
		return norm_dict

	def get_season_details(self, series_index, season_no):
		err_msg, season_dict = "", {}
		series_id = series_index.get("series_id", "")
		if series_id and season_no and season_no.isdigit():
			season_int = int(season_no)
			seasons = series_index.get("seasons", [])
			season_id = ""
			for season in seasons:
				curr_season_no = season.get("season_no", "")
				if curr_season_no.isdigit() and int(curr_season_no) == season_int:
					season_id = season.get("season_id", "")
					break
			if season_id and season_id.isdigit():
				err_msg, asset_dict = self.get_asset_dict("season", season_id)
				if err_msg:
					write_log(f"{MODULE_NAME}ERROR in module 'get_season_details': {err_msg}")
				else:
					season_dict = self.create_norm_season_dict(asset_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TVDB.get_season_details': missing parameter {'season_no' if series_id else 'series_id'}."
		return err_msg, season_dict

	def create_norm_season_dict(self, season_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
		self.set_dict_key(norm_dict, Fields.SERIES_ID, str(season_dict.get("series_id", "")))
		season_no = str(season_dict.get("number", ""))
		self.set_dict_key(norm_dict, Fields.SEASON_NAME, self.get_title(season_dict) or f"Season {season_no}")
		self.set_dict_key(norm_dict, "season_id", str(season_dict.get("id", "")))
		self.set_dict_key(norm_dict, Fields.SEASON_NO, season_no)
		self.set_dict_key(norm_dict, Fields.RELEASED, season_dict.get("year", ""))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.get_overview(season_dict))  # longtext
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
		for pic_type, pic_url in self.get_pictures_list(season_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "season")
		crew_list, cast_list = self.get_characters(season_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		episodes = []
		for episode in season_dict.get("episodes", []):
			episode_dict = {}
			self.set_dict_key(episode_dict, Fields.EPISODE_NAME, episode.get("name", ""))
			self.set_dict_key(episode_dict, Fields.EPISODE_ID, str(episode.get("id", "")))
			self.set_dict_key(episode_dict, Fields.EPISODE_NO, str(episode.get("number", "")))
			self.set_dict_key(episode_dict, Fields.RELEASED, episode.get("aired", ""))
			self.set_dict_key(episode_dict, Fields.OVERVIEW, episode.get("overview", ""))  # longtext
			self.set_dict_key(episode_dict, Fields.RUNTIME, str(episode.get("runtime", "")))
			for pic_type, pic_url in self.get_pictures_list(episode):
				self.set_dict_key(episode_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(episode_dict, f"{pic_type}_src", "episode")
			crew_list, cast_list = self.get_characters(episode_dict)
			self.set_dict_key(episode_dict, Fields.CREW, crew_list)
			self.set_dict_key(episode_dict, Fields.CAST, cast_list)
			episodes.append(episode_dict)
		self.set_dict_key(norm_dict, "episodes", episodes)
		return norm_dict

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):  # TVDB only uses 'episode_id'
		err_msg, episode_dict = "", {}
		if episode_id:
			err_msg, asset_dict = self.get_asset_dict("episode", episode_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
			else:
				episode_dict = self.create_norm_episode_dict(asset_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TVDB.get_episode_details': missing parameter 'episode_id'."
		return err_msg, episode_dict

	def create_norm_episode_dict(self, episode_dict):
		norm_dict = {}
		if episode_dict:
			self.set_dict_key(norm_dict, Fields.PROVIDER, "tvdb")
			episode_name = self.get_title(episode_dict)
			episode_name = episode_name.split(" - ")  # might be 'Odenthal - 15 - Mordfieber', so reduce to 'Mordfieber'
			episode_name = episode_name[2] if len(episode_name) > 2 else episode_name[0]
			self.set_dict_key(norm_dict, Fields.SERIES_ID, str(episode_dict.get("series_id", "")))
			self.set_dict_key(norm_dict, Fields.EPISODE_NAME, episode_name)
			self.set_dict_key(norm_dict, Fields.EPISODE_ID, str(episode_dict.get("id", "")))
			self.set_dict_key(norm_dict, Fields.SEASON_NO, str(episode_dict.get("seasonNumber", "")))
			self.set_dict_key(norm_dict, Fields.EPISODE_NO, str(episode_dict.get("number", "")))
			self.set_dict_key(norm_dict, Fields.RUNTIME, str(episode_dict.get("runtime", "")))
			self.set_dict_key(norm_dict, Fields.RELEASED, episode_dict.get("aired", ""))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, self.get_overview(episode_dict))  # longtext
			# TVDB don't support 'vote_average' and 'vote_count' in episode results
			self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
			for pic_type, pic_url in self.get_pictures_list(episode_dict):
				self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(norm_dict, f"{pic_type}_src", "episode")
			crew_list, cast_list = self.get_characters(episode_dict)
			self.set_dict_key(norm_dict, Fields.CREW, crew_list)
			self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		return norm_dict

	def get_asset_details(self, category, asset_id, season_no="", episode_no=""):  # get asset infos acc. category, assetId (season_no and episode_no are not used here)
		err_msg, asset_details = "", {}
		if asset_id:
			err_msg, asset_dict = self.get_asset_dict(category, asset_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_asset_details': {err_msg}")
			else:
				if category == "series":
					asset_details = self.create_norm_series_dict(asset_dict)
				elif category == "season":
					asset_details = self.create_norm_season_dict(asset_dict)
				elif category == "episode":
					asset_details = self.create_norm_episode_dict(asset_dict)
				elif category == "movie":
					asset_details = self.create_norm_movie_dict(asset_dict)
				else:
					err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_details': unknown or missing parameter 'category': '{category}'"
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_details': missing parameter 'asset_id'"
		return err_msg, asset_details

	def get_asset_dict(self, category, asset_id, season_no="", episode_no=""):
		err_msg, tvdb_dict = "", {}
		urlpart, params, = {
			"series": ("series", {"meta": "translations", "short": "false"}),
			"season": ("seasons", {"meta": "translations", "short": "false"}),
			"episode": ("episodes", {"meta": "translations", "short": "false"}),
			"movie": ("movies", {"meta": "translations", "short": "false"})
			}.get(category)
		if urlpart and params:
			url = f"{self.base_url}/{urlpart}/{asset_id}/extended"
			err_msg, tvdb_dict = self.get_api_dicts(url, params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_asset_dict': {err_msg}")
		asset_dict = tvdb_dict.get("data", {})
		if category == "series" and asset_dict:
			existing_types = {pic_type for pic_type, _pic_url in self.get_pictures_list(asset_dict)}
			if "backdrop" not in existing_types:
				artwork_err, extra_artworks = self.get_series_artworks(asset_id)
				if artwork_err:
					write_log(f"{MODULE_NAME}WARNING in module 'get_asset_dict': series artwork lookup failed for '{asset_id}': {artwork_err}")
				elif extra_artworks:
					current = asset_dict.get("artworks") or asset_dict.get("artwork") or []
					if not isinstance(current, list):
						current = []
					asset_dict["artworks"] = list(current) + list(extra_artworks)
		return err_msg, asset_dict

	def get_title(self, tvdb_dict):
		title, fallback = "", ""
		for name_dict in tvdb_dict.get("translations", {}).get("nameTranslations", []):
			language = name_dict.get("language", "")
			if not fallback and language == "eng":
				fallback = name_dict.get("name")
			if language == self.lang_code:
				title = name_dict.get("name")
			if fallback and title:
				break
		if not title:
			title = tvdb_dict.get("name", "") or fallback
		return title

	def get_overview(self, tvdb_dict):
		overview = ""
		for overview_dict in tvdb_dict.get("translations", {}).get("overviewTranslations", []):
			if overview_dict.get("language", "") == self.lang_code:
				overview = overview_dict.get("overview", "")
				break
		return overview

	def get_age_rating(self, tvdb_dict):
		rating = ""
		for content_rating in tvdb_dict.get("contentRatings", []):
			if content_rating.get("country", "") == self.lang_code:
				rating = content_rating.get("name", "").replace("+", "")
				break
		return rating

	def get_remote_ids(self, tvdb_dict, key):
		provider_ids = {}
		for remote_id in tvdb_dict.get(key, []):
			sourceName = remote_id.get("sourceName", "").replace("TheMovieDB.com", "tmdb").lower()
			if sourceName in ["imdb", "tmdb"]:
				self.set_dict_key(provider_ids, sourceName, remote_id.get("id", ""))
		return provider_ids

	def get_all_genres(self, tvdb_dict):
		genres = []
		for genre_dict in tvdb_dict.get("genres", []):
			genre_name = genre_dict.get("name", "")
			if genre_name:
				genres.append(genre_name)
		return genres

	def get_characters(self, tvdb_dict):
		crew_list, cast_list = [], []
		for profile_dict in tvdb_dict.get("characters", []):
			staff_dict = {}
			job = profile_dict.get("peopleType", "")
			self.set_dict_key(staff_dict, Fields.JOB, job)
			self.set_dict_key(staff_dict, Fields.NAME, profile_dict.get("personName", ""))  # real name of actor
			self.set_dict_key(staff_dict, Fields.CHARACTER, profile_dict.get("name", ""))  # role name in movie/series
			self.set_dict_key(staff_dict, Fields.PROFILE_ID, str(profile_dict.get("id", "")))
			image_path = profile_dict.get("personImgURL", "")
			if image_path and self.img_url not in image_path:
				image_path = f"{self.img_url}{image_path}"
			self.set_dict_key(staff_dict, Fields.PROFILE_URL, image_path)  # e.g. '/eZgBiSDTc25mEjMoyRKZTa2ggbm.jpg'
			if job in ["Actor", "Guest Star"]:
				cast_list.append(staff_dict)
			else:
				crew_list.append(staff_dict)
		return crew_list, cast_list

	def get_artwork_type_names(self):
		if self.artwork_type_names:
			return self.artwork_type_names
		url = f"{self.base_url}/artwork/types"
		err_msg, type_dict = self.get_api_dicts(url)
		if err_msg:
			return {}
		for item in type_dict.get("data", []) or []:
			if not isinstance(item, dict):
				continue
			type_id = str(item.get("id") or item.get("type") or "").strip()
			if not type_id:
				continue
			labels = []
			for key in ("name", "slug", "type", "recordType", "subType", "description"):
				value = item.get(key)
				if value not in (None, ""):
					labels.append(str(value))
			self.artwork_type_names[type_id] = " ".join(labels).lower()
		return self.artwork_type_names

	def get_series_artworks(self, series_id):
		if not (series_id and str(series_id).isdigit() and int(series_id)):
			return "missing series_id", []
		collected = []
		seen = set()
		queries = []
		if self.lang_code:
			queries.append({"lang": self.lang_code})
		queries.append({})
		last_error = ""
		for params in queries:
			url = f"{self.base_url}/series/{series_id}/artworks"
			err_msg, artwork_dict = self.get_api_dicts(url, params or None)
			if err_msg:
				last_error = str(err_msg)
				continue
			data = artwork_dict.get("data", {})
			artworks = []
			if isinstance(data, list):
				artworks = data
			elif isinstance(data, dict):
				for key in ("artworks", "artwork"):
					value = data.get(key)
					if isinstance(value, list):
						artworks.extend(value)
			for item in artworks:
				if not isinstance(item, dict):
					continue
				url_value = self._tvdb_artwork_url(item)
				key = str(item.get("id") or url_value or item)
				if key in seen:
					continue
				seen.add(key)
				collected.append(item)
		return ("" if collected else last_error), collected

	def _tvdb_artwork_url(self, pic_dict):
		for key in ("image", "imageUrl", "url", "thumbnail"):
			value = str(pic_dict.get(key, "") or "").strip()
			if not value:
				continue
			if value.startswith("//"):
				value = "https:" + value
			elif value.startswith("/"):
				value = f"{self.img_url}{value}"
			return value
		return ""

	def _tvdb_artwork_dimension(self, pic_dict, *keys):
		for key in keys:
			text = str(pic_dict.get(key, 0) or "").strip()
			if text.isdigit():
				value = int(text)
				if value > 0:
					return value
		return 0

	def _tvdb_artwork_marker(self, pic_dict, pic_url):
		values = [pic_url]
		artwork_type_names = None
		for key in ("type", "typeName", "imageType", "artworkType", "name", "slug", "tagName", "subKey"):
			value = pic_dict.get(key, "")
			if isinstance(value, dict):
				values.extend([str(v) for v in value.values()])
			elif isinstance(value, (list, tuple)):
				values.extend([str(v) for v in value])
			elif value not in (None, ""):
				text = str(value)
				values.append(text)
				if key in ("type", "imageType", "artworkType") and text.strip().isdigit():
					if artwork_type_names is None:
						artwork_type_names = self.get_artwork_type_names()
					resolved = artwork_type_names.get(text.strip(), "") if artwork_type_names else ""
					if resolved:
						values.append(resolved)
		return " ".join(values).lower()

	def _tvdb_artwork_context(self, tvdb_dict):
		if tvdb_dict.get("seasonNumber") or tvdb_dict.get("aired") or tvdb_dict.get("runtime") and tvdb_dict.get("series_id"):
			return "episode"
		if tvdb_dict.get("series_id") and tvdb_dict.get("number") and not tvdb_dict.get("seasons"):
			return "episode"
		if tvdb_dict.get("seasons") or tvdb_dict.get("latestNetwork") or tvdb_dict.get("originalNetwork"):
			return "series"
		return ""

	def _tvdb_classify_artwork(self, tvdb_dict, pic_dict, pic_url):
		marker = self._tvdb_artwork_marker(pic_dict, pic_url)
		context = self._tvdb_artwork_context(tvdb_dict)
		if "clearlogo" in marker or "clear logo" in marker or "titlelogo" in marker or "logo" in marker:
			return "titlelogo"
		if "episode" in marker or "episodes" in marker or "still" in marker or "screenshot" in marker:
			return "image"
		if "background" in marker or "backgrounds" in marker or "backdrop" in marker or "fanart" in marker or "landscape" in marker:
			return "backdrop"
		if "poster" in marker or "posters" in marker or "cover" in marker:
			return "cover"
		width = self._tvdb_artwork_dimension(pic_dict, "width", "imageWidth", "thumbnailWidth")
		height = self._tvdb_artwork_dimension(pic_dict, "height", "imageHeight", "thumbnailHeight")
		if width and height:
			if width >= int(height * 1.20):
				return "image" if context == "episode" else "backdrop"
			if height >= int(width * 1.10):
				return "cover"
		if context == "episode":
			return "image"
		return ""

	def get_pictures_list(self, tvdb_dict):
		pic_list = []
		seen_types = set()
		artworks = tvdb_dict.get("artwork", []) or tvdb_dict.get("artworks", []) or []
		if not isinstance(artworks, list):
			artworks = []
		# Some TVDB responses expose the primary image directly on the object. Keep this
		# as the last fallback; artwork/artworks entries are more precise because they
		# can carry backdrop/episode/titlelogo metadata.
		artwork_candidates = list(artworks)
		if tvdb_dict.get("image") or tvdb_dict.get("imageUrl") or tvdb_dict.get("image_url"):
			artwork_candidates.append({
				"image": tvdb_dict.get("image") or tvdb_dict.get("imageUrl") or tvdb_dict.get("image_url"),
				"width": tvdb_dict.get("imageWidth", 0),
				"height": tvdb_dict.get("imageHeight", 0),
			})
		for pic_dict in artwork_candidates:
			if not isinstance(pic_dict, dict):
				continue
			pic_url = self._tvdb_artwork_url(pic_dict)
			if not pic_url:
				continue
			pic_type = self._tvdb_classify_artwork(tvdb_dict, pic_dict, pic_url)
			if not pic_type or pic_type in seen_types:
				continue
			if "missing" in pic_url.lower():
				continue
			pic_list.append((pic_type, pic_url))
			seen_types.add(pic_type)
		# Compatibility fallback for older TVDB URL layouts. This preserves the v16
		# behaviour but no longer depends exclusively on URL substrings.
		if not {kind for kind, _url in pic_list}.issuperset({"cover", "backdrop", "image"}):
			for url_marker, pic_type in [("posters", "cover"), ("backgrounds", "backdrop"), ("clearlogo", "titlelogo"), ("episodes", "image")]:
				if pic_type in seen_types:
					continue
				for pic_dict in artwork_candidates or [tvdb_dict]:
					if not isinstance(pic_dict, dict):
						continue
					pic_url = self._tvdb_artwork_url(pic_dict)
					if pic_url and url_marker in pic_url and "missing" not in pic_url.lower():
						pic_list.append((pic_type, pic_url))
						seen_types.add(pic_type)
						break
		return pic_list

	def get_api_dicts(self, url, params=None, timeout=(3.05, 6)):
		def remove_nones(dictionary):  # get rid of keys with 'None' values
			keys_to_delete = [key for key, value in dictionary.items() if value is None]
			for key in keys_to_delete:
				del dictionary[key]
			for value in dictionary.values():
				if isinstance(value, dict):
					remove_nones(value)
				elif isinstance(value, list):
					for item in value:
						if isinstance(item, dict):
							remove_nones(item)
			return dictionary

		headers = {"accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			err_msg, api_dicts = ("", remove_nones(response.json())) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			return err_msg, api_dicts
		except exceptions.RequestException as err_msg:
			return err_msg, {}

	def set_dict_key(self, dictionary, key, value):
		if value:
			dictionary[key] = value


provider_tvdb = ProviderTVDB()


def main(argv):  # shell interface
	title, language, media_type, asset_id, api_key, season_no, episode_no = "the+blacklist", "en", "", "", "", "", ""
	helpstring = "TVDB v0.1: try 'python TVDB.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:s:e:l:m:a:h", ["query=", "season_no=", "episode_no=", "language=", "mediatype=", "api_key=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'TVDB v0.1': python TVDB.py [option...] <data>\n"
			"Example: python TVDB.py -q the+blacklist -l de -s 1 -e 2 -m series -a {your personal api-key}\n"
			"-q, --query <options>\t\tget result list from tvdb search'\n"
			"-s, --season_no <digit>\t\tseason Number as digit\n"
			"-e, --episode_no <digit>\t\tepisode number as digit\n"
			"-l, --language <options>\tset language formatted like 'en'\n"
			"-m, --media_type <options>\tset media type 'series' or 'movie' (default 'series')\n"
			"-a, --api_key <your api key>\tpersonal key for accessing the AP server\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-s", "--season_no"):
			season_no = arg
		elif opt in ("-e", "--episode_no"):
			episode_no = arg
		elif opt in ("-l", "--language"):
			language = arg
		elif opt in ("-m", "--media_type"):
			media_type = arg
		elif opt in ("-a", "--api_key"):
			api_key = arg
	if title and language:
		if not api_key:
			write_log("ERROR: API key is missing.")
			exit(2)
		if not media_type:
			media_type = "series"  # set fallback
		write_log(f"Search for '{title.replace("+", " ")}', media_type: '{media_type}'")
		provider_tvdb.start(api_key, language)
		err_msg, norm_dicts = provider_tvdb.get_result_dicts(title, media_type=media_type, year=None)
		if err_msg:
			write_log("ERROR getting data:", err_msg)
			exit(2)
		if norm_dicts:
			results = norm_dicts[:1]
			if results:
				result = results[0]  # get first result only
				asset_id = result.get("provider_ids", {}).get("tvdb", "")
				media_type = result.get("media_type", "")  # e.g. 'movie' or 'series'
				if asset_id:
					filePart = f"tvdb_{asset_id}"
					if media_type == "series":
						write_log("Download requested data...")
						# series details with ALL episodes (improved!)
						err_msg, series_index, episode_index = provider_tvdb.get_series_details_index(asset_id)
						if err_msg:
							write_log(f"Error downloading series details and index: {err_msg}")
							exit(2)
						if series_index:
							file_name = f"{filePart}.seriesDetails.json"
							with open(file_name, "w") as file:
								dump(series_index, file)
							write_log(f"Series details file '{file_name}' was successfully created.")
						if episode_index:
							file_name = f"{filePart}.episodeIndex.json"
							with open(file_name, "w") as file:
								dump(episode_index, file)
							episode_count = len(episode_index.get("episodes", {}))
							write_log(f"Episode index file '{file_name}' created with {episode_count} episodes.")
						# episode or season details
						if season_no.isdigit():
								err_msg, season_dict = provider_tvdb.get_season_details(series_index, season_no)
								if err_msg:
									write_log(f"Error downloading season details: {err_msg}")
									exit(2)
								if season_dict:
									file_name = f"{filePart}.seasonDetails.json"
									with open(file_name, "w") as file:
										dump(season_dict, file)
									write_log(f"Season details file '{file_name}' was successfully created.")
						if episode_no.isdigit():
							season_episode = provider_tvdb.find_season_episode(episode_index, plain_season_episode=f"{season_no}-{episode_no}")
							if season_episode:
								episode_id = season_episode[1]
								err_msg, episode_dict = provider_tvdb.get_episode_details(episode_id=episode_id)
								if err_msg:
									write_log(f"Error downloading episode details: {err_msg}")
									exit(2)
								if episode_dict:
									file_name = f"{filePart}.episodeDetails.json"
									with open(file_name, "w") as file:
										dump(episode_dict, file)
									write_log(f"Episode details file '{file_name}' was successfully created.")
					else:  # means 'movie'
						err_msg, movie_dict = provider_tvdb.get_movie_details(asset_id)
						if err_msg:
							write_log(f"Error downloading episode details: {err_msg}")
							exit(2)
						if movie_dict:
							file_name = f"{filePart}.movieDetails.json"
							with open(file_name, "w") as file:
								dump(movie_dict, file)
							write_log(f"Movie details file '{file_name}' was successfully created.")
				if norm_dicts:
					file_name = "tvdb_searchResults.json"
					with open(file_name, "w") as file:
						dump(norm_dicts, file)
					write_log(f"Result details file '{file_name}' was successfully created.")

	else:
		err_msg = "'Title' or 'language' is missing"
		write_log("ERROR getting data:", err_msg)


if __name__ == "__main__":
	main(argv[1:])
