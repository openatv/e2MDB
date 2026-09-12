########################################################################################################
# TVMAZE provider for e2MDB                                                                            #
# -----------------------------------------------------------------------------------------------------#
# Uses the public TVmaze REST API without API key and without web parsing.                             #
########################################################################################################

from datetime import datetime
from getopt import getopt, GetoptError
from html import unescape
from json import dump
from re import sub
from sys import exit, argv
from requests import get, exceptions

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


class ProviderTVMAZE:
	def __init__(self):
		self.base_url = "https://api.tvmaze.com"
		self.media_types = ["series", "movie"]
		self.language = "en"
		self.api_key = ""
		self.last_update = None
		self.requires_api_key = False

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language="en"):
		self.api_key = api_key
		self.language = (language or "en").replace("_", "-").split("-", 1)[0].lower()
		self.last_update = datetime.now().isoformat()
		return ""

	def get_result_dicts(self, title, media_type="series", year=None):
		norm_dicts = []
		if media_type not in self.media_types:
			return f"{MODULE_NAME}ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		if media_type != "series":
			return "", []
		url = f"{self.base_url}/search/shows"
		params = {"q": title}
		err_msg, tvmaze_dicts = self.get_api_dicts(url, params=params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts(tvmaze_dicts, year=year)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, result_dicts, year=None, entriesmax=0):
		norm_dicts = []
		results = result_dicts[:entriesmax] if entriesmax else result_dicts
		for item in results:
			try:
				show = item.get("show", item) if isinstance(item, dict) else {}
				if not isinstance(show, dict) or not show.get("id"):
					continue
				premiered = show.get("premiered", "") or ""
				if year and premiered and str(premiered)[:4] != str(year):
					continue
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "tvmaze")
				self.set_dict_key(norm_dict, Fields.TITLE, show.get("name", ""))
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "series")
				self.set_dict_key(norm_dict, Fields.COUNTRIES, self._country(show))
				self.set_dict_key(norm_dict, Fields.RELEASED, premiered)
				self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(show.get("genres", []) or []))
				self.set_dict_key(norm_dict, Fields.OVERVIEW, self.html_to_text(show.get("summary", "")))
				self.set_dict_key(norm_dict, Fields.RUNTIME, str(show.get("averageRuntime", "") or show.get("runtime", "")))
				self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._rating(show))
				self.set_dict_key(norm_dict, Fields.COVER_URL, self._image(show))
				provider_ids = {"tvmaze": str(show.get("id", ""))}
				provider_ids.update(self._externals(show))
				self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, provider_ids)
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		return f"{MODULE_NAME}ERROR in module 'TVMAZE.get_movie_details': TVmaze is a series provider and does not provide movie details.", {}

	def get_series_details_index(self, series_id):
		err_msg, series_details, episode_index = "", {}, {}
		if series_id and str(series_id).isdigit() and int(series_id):
			url = f"{self.base_url}/shows/{series_id}"
			params = [("embed[]", "seasons"), ("embed[]", "cast")]
			err_msg, show_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			series_details = self.create_norm_series_dict(show_dict)
			err_msg, episodes = self.get_all_episodes(series_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR loading episodes: {err_msg}")
				return err_msg, series_details, {}
			episode_dict = {}
			for episode in episodes:
				season_no = episode.get("season", "")
				episode_no = episode.get("number", "")
				episode_id = str(episode.get("id", ""))
				episode_name = episode.get("name", "") or f"Episode {episode_no}"
				if season_no and episode_no and episode_id:
					episode_dict[f"{season_no}-{episode_no}"] = (episode_id, episode_name)
			episode_index = {"provider": "tvmaze", "episodes": episode_dict}
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TVMAZE.get_series_details_index': missing parameter 'series_id'."
		return err_msg, series_details, episode_index

	def create_norm_series_dict(self, show_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tvmaze")
		self.set_dict_key(norm_dict, Fields.TITLE, show_dict.get("name", ""))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "series")
		series_id = str(show_dict.get("id", ""))
		self.set_dict_key(norm_dict, Fields.SERIES_ID, series_id)
		self.set_dict_key(norm_dict, Fields.COUNTRIES, self._country(show_dict))
		self.set_dict_key(norm_dict, Fields.RELEASED, show_dict.get("premiered", ""))
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(show_dict.get("genres", []) or []))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.html_to_text(show_dict.get("summary", "")))
		self.set_dict_key(norm_dict, Fields.RUNTIME, str(show_dict.get("averageRuntime", "") or show_dict.get("runtime", "")))
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._rating(show_dict))
		self.set_dict_key(norm_dict, Fields.COVER_URL, self._image(show_dict))
		self.set_dict_key(norm_dict, Fields.COVER_SRC, "series")
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		provider_ids = {"tvmaze": series_id}
		provider_ids.update(self._externals(show_dict))
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, provider_ids)
		self.set_dict_key(norm_dict, Fields.CAST, self.get_cast(show_dict))
		seasons = []
		for season in show_dict.get("_embedded", {}).get("seasons", []) or []:
			season_dict = {}
			season_no = str(season.get("number", ""))
			self.set_dict_key(season_dict, Fields.PROVIDER, "tvmaze")
			self.set_dict_key(season_dict, Fields.SERIES_ID, series_id)
			self.set_dict_key(season_dict, Fields.SEASON_NAME, season.get("name", "") or f"Season {season_no}")
			self.set_dict_key(season_dict, "season_id", str(season.get("id", "")))
			self.set_dict_key(season_dict, Fields.SEASON_NO, season_no)
			self.set_dict_key(season_dict, Fields.RELEASED, season.get("premiereDate", ""))
			self.set_dict_key(season_dict, Fields.OVERVIEW, self.html_to_text(season.get("summary", "")))
			self.set_dict_key(season_dict, Fields.COVER_URL, self._image(season))
			self.set_dict_key(season_dict, Fields.COVER_SRC, "season")
			seasons.append(season_dict)
		self.set_dict_key(norm_dict, Fields.SEASONS, seasons)
		return norm_dict

	def get_all_episodes(self, series_id):
		url = f"{self.base_url}/shows/{series_id}/episodes"
		params = {"specials": 1}
		return self.get_api_dicts(url, params=params)

	def get_season_details(self, series_dict, season_no):
		season_no = str(season_no)
		for season in series_dict.get("seasons", []) or []:
			if str(season.get("season_no", "")) == season_no:
				return "", season
		return "", {}

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):
		err_msg, episode_details = "", {}
		if episode_id:
			url = f"{self.base_url}/episodes/{episode_id}"
			err_msg, episode_dict = self.get_api_dicts(url)
		elif series_id and season_no and episode_no:
			url = f"{self.base_url}/shows/{series_id}/episodebynumber"
			err_msg, episode_dict = self.get_api_dicts(url, params={"season": season_no, "number": episode_no})
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TVMAZE.get_episode_details': missing parameter 'episode_id' or season/episode numbers."
			return err_msg, {}
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
		else:
			episode_details = self.create_norm_episode_dict(episode_dict, series_id=series_id)
		return err_msg, episode_details

	def create_norm_episode_dict(self, episode_dict, series_id=""):
		norm_dict = {}
		if episode_dict:
			self.set_dict_key(norm_dict, Fields.PROVIDER, "tvmaze")
			self.set_dict_key(norm_dict, Fields.SERIES_ID, str(series_id or self._get(episode_dict, ("_links", "show", "href"), "").rstrip("/").split("/")[-1]))
			self.set_dict_key(norm_dict, Fields.EPISODE_NAME, episode_dict.get("name", ""))
			self.set_dict_key(norm_dict, Fields.EPISODE_ID, str(episode_dict.get("id", "")))
			self.set_dict_key(norm_dict, Fields.SEASON_NO, str(episode_dict.get("season", "")))
			self.set_dict_key(norm_dict, Fields.EPISODE_NO, str(episode_dict.get("number", "")))
			self.set_dict_key(norm_dict, Fields.RUNTIME, str(episode_dict.get("runtime", "")))
			self.set_dict_key(norm_dict, Fields.RELEASED, episode_dict.get("airdate", ""))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, self.html_to_text(episode_dict.get("summary", "")))
			self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._rating(episode_dict))
			self.set_dict_key(norm_dict, "image_url", self._image(episode_dict))
			self.set_dict_key(norm_dict, "image_src", "episode")
			self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		return norm_dict

	def get_asset_details(self, category, asset_id, season_no="", episode_no=""):
		err_msg, asset_details = "", {}
		if category == "series":
			err_msg, asset_details, _episode_index = self.get_series_details_index(asset_id)
		elif category == "episode":
			err_msg, asset_details = self.get_episode_details("", asset_id, season_no, episode_no)
		elif category == "season":
			err_msg, series_dict, _episode_index = self.get_series_details_index(asset_id)
			if not err_msg:
				err_msg, asset_details = self.get_season_details(series_dict, season_no)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_details': unsupported category '{category}'."
		return err_msg, asset_details

	def find_season_episode(self, episode_index, episode_name="", plain_season_episode=""):
		if episode_index:
			if plain_season_episode:
				for episode in episode_index.get("episodes", {}).items():
					if episode[0] == plain_season_episode:
						return tuple((episode[0], episode[1][0], episode[1][1]))
				if str(plain_season_episode).isdigit():
					for episode in episode_index.get("episodes", {}).items():
						if episode[0].split("-")[-1] == str(int(plain_season_episode)):
							return tuple((episode[0], episode[1][0], episode[1][1]))
			elif episode_name:
				for episode in episode_index.get("episodes", {}).items():
					index_name, search_name = episode[1][1].lower(), episode_name.lower()
					if search_name and (index_name in search_name or search_name in index_name):
						return tuple((episode[0], episode[1][0], episode[1][1]))
		return ()

	def get_cast(self, show_dict):
		cast_list = []
		for cast_item in show_dict.get("_embedded", {}).get("cast", []) or []:
			person = cast_item.get("person", {}) or {}
			character = cast_item.get("character", {}) or {}
			staff_dict = {}
			self.set_dict_key(staff_dict, Fields.JOB, "Actor")
			self.set_dict_key(staff_dict, Fields.NAME, person.get("name", ""))
			self.set_dict_key(staff_dict, Fields.CHARACTER, character.get("name", ""))
			self.set_dict_key(staff_dict, Fields.PROFILE_ID, str(person.get("id", "")))
			self.set_dict_key(staff_dict, Fields.PROFILE_URL, self._image(person))
			if staff_dict:
				cast_list.append(staff_dict)
		return cast_list

	def _country(self, show_dict):
		for path in (("network", "country", "code"), ("webChannel", "country", "code")):
			country = self._get(show_dict, path)
			if country:
				return str(country).upper()
		return str(show_dict.get("language", "") or "").upper()

	def _externals(self, show_dict):
		provider_ids = {}
		externals = show_dict.get("externals", {}) or {}
		if externals.get("imdb"):
			provider_ids["imdb"] = str(externals.get("imdb"))
		if externals.get("thetvdb"):
			provider_ids["tvdb"] = str(externals.get("thetvdb"))
		return provider_ids

	def _image(self, data):
		image = data.get("image", {}) or {}
		return image.get("original", "") or image.get("medium", "")

	def _rating(self, data):
		rating = self._get(data, ("rating", "average"))
		try:
			return str(round(float(rating), 1)) if rating else ""
		except Exception:
			return str(rating) if rating else ""

	def _get(self, json_obj, path, default=""):
		if not isinstance(path, (list, tuple)):
			path = (path,)
		for key in path:
			if json_obj in (None, ""):
				return default
			if isinstance(json_obj, list):
				if not json_obj:
					return default
				json_obj = json_obj[0]
			if not isinstance(json_obj, dict) or key not in json_obj:
				return default
			json_obj = json_obj[key]
		return json_obj if json_obj is not None else default

	def html_to_text(self, html):
		if not html:
			return ""
		if isinstance(html, bytes):
			html = html.decode("utf-8", "replace")
		return unescape(sub(r"<br\s*/?>", "\n", sub(r"<.*?>", "", html))).strip()

	def get_api_dicts(self, url, params=None, timeout=(3.05, 6)):
		try:
			response = get(url, params=params, timeout=timeout)
			if response.ok:
				return "", response.json()
			return f"API server access ERROR, response code: {response.status_code}", {}
		except exceptions.RequestException as err_msg:
			return err_msg, {}
		except ValueError as err_msg:
			return err_msg, {}

	def set_dict_key(self, dictionary, key, value):
		if value and value != "N/A":
			dictionary[key] = value


provider_tvmaze = ProviderTVMAZE()


def main(argv):
	title, language, media_type, title_id = "the+blacklist", "en", "series", ""
	helpstring = "TVMAZE v0.1: try 'python TVMAZE.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:i:h", ["query=", "language=", "mediatype=", "id=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'TVMAZE v0.1': python TVMAZE.py [option...] <data>\n"
			"Example: python TVMAZE.py -q the+blacklist -l de -m series\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language hint\n"
			"-m, --mediatype <options>\tset media type 'series'\n"
			"-i, --id <options>\t\tget show details for a TVmaze ID")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-i", "--id"):
			title_id = arg
	provider_tvmaze.start("", language)
	if title_id:
		err_msg, details, episode_index = provider_tvmaze.get_series_details_index(title_id)
		if err_msg:
			write_log(err_msg)
		else:
			with open("tvmaze_details.json", "w") as file:
				dump({"details": details, "episode_index": episode_index}, file)
			write_log("TVmaze details JSON file 'tvmaze_details.json' was successfully created.")
	else:
		err_msg, norm_dicts = provider_tvmaze.get_result_dicts(title, media_type=media_type)
		if err_msg:
			write_log(err_msg)
		else:
			with open("tvmaze_dicts.json", "w") as file:
				dump(norm_dicts, file)
			write_log("TVmaze normalized JSON file 'tvmaze_dicts.json' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
