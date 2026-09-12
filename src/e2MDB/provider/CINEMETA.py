########################################################################################################
# CINEMETA provider for e2MDB                                                                          #
# -----------------------------------------------------------------------------------------------------#
# Uses the public Cinemeta Stremio addon API (https://v3-cinemeta.strem.io) without API key and         #
# without web parsing. Cinemeta is keyed by IMDb id: series_id/movieId here is always the IMDb id       #
# (e.g. 'tt1520211'). There is no per-episode endpoint - episode/season data only comes from the full   #
# series meta lookup, so get_episode_details() re-fetches that and looks the episode up in 'videos'.    #
# Cinemeta has no language parameter, all metadata is English only.                                     #
########################################################################################################

from datetime import datetime
from getopt import getopt, GetoptError
from json import dump
from sys import exit, argv
from urllib.parse import quote
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


class ProviderCINEMETA:
	def __init__(self):
		self.base_url = "https://v3-cinemeta.strem.io"
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
		url = f"{self.base_url}/catalog/{media_type}/top/search={quote(title)}.json"
		err_msg, result_dict = self.get_api_dicts(url)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts(result_dict.get("metas", []) or [], media_type, year=year)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, result_dicts, media_type, year=None, entriesmax=0):
		norm_dicts = []
		results = result_dicts[:entriesmax] if entriesmax else result_dicts
		for item in results:
			try:
				if not isinstance(item, dict) or not item.get("id"):
					continue
				release_year = str(item.get("year") or item.get("releaseInfo") or "")[:4]
				if year and release_year and release_year != str(year):
					continue
				imdb_id = str(item.get("imdb_id") or item.get("id") or "")
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "cinemeta")
				self.set_dict_key(norm_dict, Fields.TITLE, item.get("name", ""))
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, media_type)
				self.set_dict_key(norm_dict, Fields.RELEASED, item.get("releaseInfo") or item.get("released", ""))
				self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(item.get("genre", []) or []))
				self.set_dict_key(norm_dict, Fields.OVERVIEW, item.get("description", ""))
				self.set_dict_key(norm_dict, Fields.RUNTIME, str(item.get("runtime", "")))
				self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(item.get("imdbRating", "")))
				self.set_dict_key(norm_dict, Fields.COVER_URL, item.get("poster", ""))
				self.set_dict_key(norm_dict, Fields.BACKDROP_URL, item.get("background", ""))
				self.set_dict_key(norm_dict, Fields.TITLELOGO_URL, item.get("logo", ""))
				if media_type == "series":
					self.set_dict_key(norm_dict, Fields.SERIES_ID, imdb_id)
				if imdb_id:
					self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"imdb": imdb_id})
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		err_msg, movie_details = "", {}
		if movieId:
			err_msg, meta_dict = self._get_meta("movie", movieId)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
			else:
				movie_details = self.create_norm_movie_dict(meta_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'CINEMETA.get_movie_details': missing parameter 'movieId'."
		return err_msg, movie_details

	def create_norm_movie_dict(self, meta_dict):
		norm_dict = {}
		if meta_dict:
			imdb_id = str(meta_dict.get("imdb_id") or meta_dict.get("id") or "")
			self.set_dict_key(norm_dict, Fields.PROVIDER, "cinemeta")
			self.set_dict_key(norm_dict, Fields.TITLE, meta_dict.get("name", ""))
			self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "movie")
			self.set_dict_key(norm_dict, Fields.RELEASED, meta_dict.get("releaseInfo") or meta_dict.get("released", ""))
			self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(meta_dict.get("genre", []) or meta_dict.get("genres", []) or []))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, meta_dict.get("description", ""))
			self.set_dict_key(norm_dict, Fields.RUNTIME, str(meta_dict.get("runtime", "")))
			self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(meta_dict.get("imdbRating", "")))
			self.set_dict_key(norm_dict, Fields.COVER_URL, meta_dict.get("poster", ""))
			self.set_dict_key(norm_dict, Fields.COVER_SRC, "movie")
			self.set_dict_key(norm_dict, Fields.BACKDROP_URL, meta_dict.get("background", ""))
			self.set_dict_key(norm_dict, Fields.BACKDROP_SRC, "movie")
			self.set_dict_key(norm_dict, Fields.TITLELOGO_URL, meta_dict.get("logo", ""))
			self.set_dict_key(norm_dict, Fields.CAST, self.get_cast(meta_dict))
			self.set_dict_key(norm_dict, Fields.CREW, self.get_crew(meta_dict))
			if imdb_id:
				self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"imdb": imdb_id})
			self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		return norm_dict

	def get_series_details_index(self, series_id):
		err_msg, series_details, episode_index = "", {}, {}
		series_id = str(series_id or "").strip()
		if series_id:
			err_msg, meta_dict = self._get_meta("series", series_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			series_details = self.create_norm_series_dict(meta_dict)
			episode_dict = {}
			for video in meta_dict.get("videos", []) or []:
				season_no = video.get("season", "")
				episode_no = video.get("number", video.get("episode", ""))
				episode_id = str(video.get("id", ""))
				episode_name = video.get("name", "") or f"Episode {episode_no}"
				if season_no and episode_no and episode_id:
					episode_dict[f"{season_no}-{episode_no}"] = (episode_id, episode_name)
			episode_index = {"provider": "cinemeta", "episodes": episode_dict}
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'CINEMETA.get_series_details_index': missing parameter 'series_id'."
		return err_msg, series_details, episode_index

	def _get_meta(self, media_type, provider_id):
		url = f"{self.base_url}/meta/{media_type}/{provider_id}.json"
		err_msg, response_dict = self.get_api_dicts(url)
		if err_msg:
			return err_msg, {}
		return "", (response_dict.get("meta", response_dict) or {}) if isinstance(response_dict, dict) else {}

	def create_norm_series_dict(self, meta_dict):
		norm_dict = {}
		if meta_dict:
			series_id = str(meta_dict.get("imdb_id") or meta_dict.get("id") or "")
			self.set_dict_key(norm_dict, Fields.PROVIDER, "cinemeta")
			self.set_dict_key(norm_dict, Fields.TITLE, meta_dict.get("name", ""))
			self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "series")
			self.set_dict_key(norm_dict, Fields.SERIES_ID, series_id)
			self.set_dict_key(norm_dict, Fields.RELEASED, meta_dict.get("releaseInfo") or meta_dict.get("released", ""))
			self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(meta_dict.get("genre", []) or meta_dict.get("genres", []) or []))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, meta_dict.get("description", ""))
			self.set_dict_key(norm_dict, Fields.RUNTIME, str(meta_dict.get("runtime", "")))
			self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(meta_dict.get("imdbRating", "")))
			self.set_dict_key(norm_dict, Fields.COVER_URL, meta_dict.get("poster", ""))
			self.set_dict_key(norm_dict, Fields.COVER_SRC, "series")
			self.set_dict_key(norm_dict, Fields.BACKDROP_URL, meta_dict.get("background", ""))
			self.set_dict_key(norm_dict, Fields.BACKDROP_SRC, "series")
			self.set_dict_key(norm_dict, Fields.TITLELOGO_URL, meta_dict.get("logo", ""))
			self.set_dict_key(norm_dict, Fields.TITLELOGO_SRC, "series")
			self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
			provider_ids = {"imdb": series_id} if series_id else {}
			if meta_dict.get("tvdb_id"):
				provider_ids["tvdb"] = str(meta_dict.get("tvdb_id"))
			if meta_dict.get("moviedb_id"):
				provider_ids["tmdb"] = str(meta_dict.get("moviedb_id"))
			self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, provider_ids)
			self.set_dict_key(norm_dict, Fields.CAST, self.get_cast(meta_dict))
			self.set_dict_key(norm_dict, Fields.CREW, self.get_crew(meta_dict))
			seasons = []
			season_numbers = sorted({video.get("season") for video in meta_dict.get("videos", []) or [] if video.get("season") not in (None, "")})
			for season_no in season_numbers:
				season_dict = {}
				self.set_dict_key(season_dict, Fields.PROVIDER, "cinemeta")
				self.set_dict_key(season_dict, Fields.SERIES_ID, series_id)
				self.set_dict_key(season_dict, Fields.SEASON_NAME, f"Season {season_no}")
				self.set_dict_key(season_dict, Fields.SEASON_NO, str(season_no))
				seasons.append(season_dict)
			self.set_dict_key(norm_dict, Fields.SEASONS, seasons)
		return norm_dict

	def get_season_details(self, series_dict, season_no):
		season_no = str(season_no)
		for season in series_dict.get("seasons", []) or []:
			if str(season.get("season_no", "")) == season_no:
				return "", season
		return "", {}

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):
		series_id = str(series_id or "").strip()
		episode_id = str(episode_id or "").strip()
		if not series_id and episode_id and ":" in episode_id:
			series_id = episode_id.split(":", 1)[0]  # Cinemeta episode ids are 'ttXXXXXXX:season:episode'
		if not series_id:
			return f"{MODULE_NAME}ERROR in module 'CINEMETA.get_episode_details': missing parameter 'series_id'.", {}
		err_msg, meta_dict = self._get_meta("series", series_id)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
			return err_msg, {}
		video = {}
		for candidate in meta_dict.get("videos", []) or []:
			if episode_id and str(candidate.get("id", "")) == episode_id:
				video = candidate
				break
			if season_no and episode_no and str(candidate.get("season", "")) == str(season_no) and str(candidate.get("number", candidate.get("episode", ""))) == str(episode_no):
				video = candidate
				break
		if not video:
			return f"{MODULE_NAME}ERROR in module 'CINEMETA.get_episode_details': episode not found.", {}
		return "", self.create_norm_episode_dict(video, series_id=series_id)

	def create_norm_episode_dict(self, video_dict, series_id=""):
		norm_dict = {}
		if video_dict:
			self.set_dict_key(norm_dict, Fields.PROVIDER, "cinemeta")
			self.set_dict_key(norm_dict, Fields.SERIES_ID, str(series_id or ""))
			self.set_dict_key(norm_dict, Fields.EPISODE_NAME, video_dict.get("name", ""))
			self.set_dict_key(norm_dict, Fields.EPISODE_ID, str(video_dict.get("id", "")))
			self.set_dict_key(norm_dict, Fields.SEASON_NO, str(video_dict.get("season", "")))
			self.set_dict_key(norm_dict, Fields.EPISODE_NO, str(video_dict.get("number", video_dict.get("episode", ""))))
			self.set_dict_key(norm_dict, Fields.RELEASED, video_dict.get("released") or video_dict.get("firstAired", ""))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, video_dict.get("overview") or video_dict.get("description", ""))
			self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(video_dict.get("rating", "") or ""))
			self.set_dict_key(norm_dict, "image_url", video_dict.get("thumbnail", ""))
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
		elif category == "movie":
			err_msg, asset_details = self.get_movie_details(asset_id)
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

	def get_cast(self, meta_dict):
		cast_list = []
		for actor_name in meta_dict.get("cast", []) or []:
			staff_dict = {}
			self.set_dict_key(staff_dict, Fields.JOB, "Actor")
			self.set_dict_key(staff_dict, Fields.NAME, actor_name)
			if staff_dict:
				cast_list.append(staff_dict)
		return cast_list

	def get_crew(self, meta_dict):
		crew_list = []
		for job, names in (("Director", meta_dict.get("director", [])), ("Writer", meta_dict.get("writer", []))):
			for person_name in names or []:
				staff_dict = {}
				self.set_dict_key(staff_dict, Fields.JOB, job)
				self.set_dict_key(staff_dict, Fields.NAME, person_name)
				if staff_dict:
					crew_list.append(staff_dict)
		return crew_list

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


provider_cinemeta = ProviderCINEMETA()


def main(argv):
	title, language, media_type, title_id = "the+walking+dead", "en", "series", ""
	helpstring = "CINEMETA v0.1: try 'python CINEMETA.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:i:h", ["query=", "language=", "mediatype=", "id=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'CINEMETA v0.1': python CINEMETA.py [option...] <data>\n"
			"Example: python CINEMETA.py -q the+walking+dead -l en -m series\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language hint (ignored, Cinemeta is English only)\n"
			"-m, --mediatype <options>\tset media type 'series' or 'movie'\n"
			"-i, --id <options>\t\tget series/movie details for an IMDb id")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-i", "--id"):
			title_id = arg
	provider_cinemeta.start("", language)
	if title_id:
		if media_type == "movie":
			err_msg, details = provider_cinemeta.get_movie_details(title_id)
		else:
			err_msg, details, episode_index = provider_cinemeta.get_series_details_index(title_id)
			details = {"details": details, "episode_index": episode_index}
		if err_msg:
			write_log(err_msg)
		else:
			with open("cinemeta_details.json", "w") as file:
				dump(details, file)
			write_log("Cinemeta details JSON file 'cinemeta_details.json' was successfully created.")
	else:
		err_msg, norm_dicts = provider_cinemeta.get_result_dicts(title, media_type=media_type)
		if err_msg:
			write_log(err_msg)
		else:
			with open("cinemeta_dicts.json", "w") as file:
				dump(norm_dicts, file)
			write_log("Cinemeta normalized JSON file 'cinemeta_dicts.json' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
