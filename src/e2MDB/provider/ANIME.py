########################################################################################################
# Anime provider for e2MDB                                                                             #
# -----------------------------------------------------------------------------------------------------#
# Uses the public AniList GraphQL API without API key and without web parsing.                         #
########################################################################################################

from datetime import datetime
from getopt import getopt, GetoptError
from html import unescape
from json import dump
from re import sub
from sys import exit, argv
from requests import post, exceptions

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


class ProviderANIME:
	def __init__(self):
		self.base_url = "https://graphql.anilist.co"
		self.media_types = ["movie", "series", "anime", "manga"]
		self.language = "en"
		self.api_key = ""
		self.last_update = None
		self.requires_api_key = False

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language="en"):
		self.api_key = ""
		self.language = (language or "en").replace("_", "-").split("-", 1)[0].lower()
		self.last_update = datetime.now().isoformat()
		return ""

	def get_result_dicts(self, title, media_type="series", year=None):
		norm_dicts = []
		if media_type not in self.media_types:
			return f"{MODULE_NAME}ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		media_kind = "MANGA" if media_type == "manga" else "ANIME"
		query = self.search_query_graphql()
		variables = {"search": title, "type": media_kind, "perPage": 10}
		if year and media_kind == "ANIME":
			variables["seasonYear"] = int(year) if str(year).isdigit() else None
		err_msg, anime_dict = self.get_api_dicts(query, variables=variables)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			media_list = self._get(anime_dict, ("data", "Page", "media"), [])
			norm_dicts = self.create_norm_result_dicts(media_list, media_type, year=year)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, media_list, media_type, year=None, entriesmax=0):
		norm_dicts = []
		results = media_list[:entriesmax] if entriesmax else media_list
		for item in results:
			try:
				if not isinstance(item, dict) or not item.get("id"):
					continue
				result_media_type = self._media_type(item)
				if media_type not in ("anime", "manga") and media_type != result_media_type:
					continue
				if media_type == "manga" and result_media_type != "manga":
					continue
				start_year = self._get(item, ("startDate", "year"))
				if year and start_year and str(start_year) != str(year):
					continue
				norm_dict = self.create_norm_media_dict(item, media_type=result_media_type, details=False)
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		err_msg, movie_details = "", {}
		if movieId and str(movieId).isdigit() and int(movieId):
			err_msg, media_dict = self.get_media_dict(movieId)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
			else:
				movie_details = self.create_norm_media_dict(media_dict, media_type="movie", details=True)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'ANIME.get_movie_details': missing parameter 'movieId'."
		return err_msg, movie_details

	def get_manga_details(self, mangaId):
		err_msg, manga_details = "", {}
		if mangaId and str(mangaId).isdigit() and int(mangaId):
			err_msg, media_dict = self.get_media_dict(mangaId, media_kind="MANGA")
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_manga_details': {err_msg}")
			else:
				manga_details = self.create_norm_media_dict(media_dict, media_type="manga", details=True)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'ANIME.get_manga_details': missing parameter 'mangaId'."
		return err_msg, manga_details

	def get_series_details_index(self, series_id):
		err_msg, series_details, episode_index = "", {}, {}
		if series_id and str(series_id).isdigit() and int(series_id):
			err_msg, media_dict = self.get_media_dict(series_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			series_details = self.create_norm_media_dict(media_dict, media_type="series", details=True)
			episode_dict = {}
			episodes = media_dict.get("episodes", 0) or 0
			try:
				episodes = int(episodes)
			except Exception:
				episodes = 0
			if episodes and episodes <= 300:
				for episode_no in range(1, episodes + 1):
					episode_dict[f"1-{episode_no}"] = (f"{series_id}:1:{episode_no}", f"Episode {episode_no}")
			episode_index = {"provider": "anime", "episodes": episode_dict, "note": "AniList does not provide per-episode titles through the public media search; a numeric season-1 index is generated when the episode count is known."}
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'ANIME.get_series_details_index': missing parameter 'series_id'."
		return err_msg, series_details, episode_index

	def get_season_details(self, series_dict, season_no):
		season_no = str(season_no or "1")
		for season in series_dict.get(Fields.SEASONS, []) or []:
			if str(season.get(Fields.SEASON_NO, "")) == season_no:
				return "", season
		season_dict = {}
		self.set_dict_key(season_dict, Fields.PROVIDER, "anime")
		self.set_dict_key(season_dict, Fields.SERIES_ID, series_dict.get(Fields.SERIES_ID, ""))
		self.set_dict_key(season_dict, Fields.SEASON_NAME, f"Season {season_no}")
		self.set_dict_key(season_dict, Fields.SEASON_NO, season_no)
		self.set_dict_key(season_dict, Fields.COVER_URL, series_dict.get(Fields.COVER_URL, ""))
		self.set_dict_key(season_dict, Fields.COVER_SRC, "season")
		return "", season_dict

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):
		episode_dict = {}
		if episode_id and ":" in str(episode_id):
			parts = str(episode_id).split(":")
			series_id = series_id or parts[0]
			season_no = season_no or (parts[1] if len(parts) > 1 else "1")
			episode_no = episode_no or (parts[2] if len(parts) > 2 else "")
		if not (series_id and episode_no):
			return "", {}
		self.set_dict_key(episode_dict, Fields.PROVIDER, "anime")
		self.set_dict_key(episode_dict, Fields.SERIES_ID, str(series_id))
		self.set_dict_key(episode_dict, Fields.EPISODE_NAME, f"Episode {episode_no}")
		self.set_dict_key(episode_dict, Fields.EPISODE_ID, str(episode_id or f"{series_id}:{season_no or 1}:{episode_no}"))
		self.set_dict_key(episode_dict, Fields.SEASON_NO, str(season_no or "1"))
		self.set_dict_key(episode_dict, Fields.EPISODE_NO, str(episode_no))
		self.set_dict_key(episode_dict, Fields.LAST_UPDATED, self.last_update)
		return "", episode_dict

	def get_asset_details(self, category, asset_id, season_no="", episode_no=""):
		err_msg, asset_details = "", {}
		if category == "movie":
			err_msg, asset_details = self.get_movie_details(asset_id)
		elif category == "manga":
			err_msg, asset_details = self.get_manga_details(asset_id)
		elif category == "series":
			err_msg, asset_details, _episode_index = self.get_series_details_index(asset_id)
		elif category == "season":
			err_msg, series_dict, _episode_index = self.get_series_details_index(asset_id)
			if not err_msg:
				err_msg, asset_details = self.get_season_details(series_dict, season_no)
		elif category == "episode":
			err_msg, asset_details = self.get_episode_details(asset_id, "", season_no, episode_no)
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

	def get_media_dict(self, media_id, media_kind="ANIME"):
		query = self.details_query_graphql()
		variables = {"id": int(media_id), "type": media_kind}
		err_msg, anime_dict = self.get_api_dicts(query, variables=variables)
		if err_msg:
			return err_msg, {}
		media_dict = self._get(anime_dict, ("data", "Media"), {})
		if not media_dict:
			return "AniList media details unavailable", {}
		return "", media_dict

	def create_norm_media_dict(self, media_dict, media_type="", details=False):
		norm_dict = {}
		if not media_dict:
			return norm_dict
		media_type = media_type or self._media_type(media_dict)
		anime_id = str(media_dict.get("id", ""))
		norm_dict[Fields.PROVIDER] = "anime"
		self.set_dict_key(norm_dict, Fields.TITLE, self._title(media_dict))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, media_type)
		if media_type == "series":
			self.set_dict_key(norm_dict, Fields.SERIES_ID, anime_id)
		self.set_dict_key(norm_dict, Fields.COUNTRIES, media_dict.get("countryOfOrigin", ""))
		self.set_dict_key(norm_dict, Fields.RELEASED, self._date(media_dict.get("startDate", {}) or {}))
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(media_dict.get("genres", []) or []))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.html_to_text(media_dict.get("description", "")))
		self.set_dict_key(norm_dict, Fields.RUNTIME, str(media_dict.get("duration", "") or media_dict.get("chapters", "") or media_dict.get("volumes", "")))
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._score(media_dict))
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(media_dict.get("popularity", "") or ""))
		self.set_dict_key(norm_dict, Fields.COVER_URL, self._get(media_dict, ("coverImage", "extraLarge")) or self._get(media_dict, ("coverImage", "large")))
		self.set_dict_key(norm_dict, Fields.COVER_SRC, media_type)
		self.set_dict_key(norm_dict, Fields.BACKDROP_URL, media_dict.get("bannerImage", ""))
		self.set_dict_key(norm_dict, Fields.BACKDROP_SRC, media_type)
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"anime": anime_id, "anilist": anime_id})
		if details:
			crew_list, cast_list = self.get_characters(media_dict)
			self.set_dict_key(norm_dict, Fields.CREW, crew_list)
			self.set_dict_key(norm_dict, Fields.CAST, cast_list)
			if media_type == "series":
				season_dict = {}
				self.set_dict_key(season_dict, Fields.PROVIDER, "anime")
				self.set_dict_key(season_dict, Fields.SERIES_ID, anime_id)
				self.set_dict_key(season_dict, Fields.SEASON_NAME, "Season 1")
				self.set_dict_key(season_dict, Fields.SEASON_NO, "1")
				self.set_dict_key(season_dict, Fields.RELEASED, self._date(media_dict.get("startDate", {}) or {}))
				self.set_dict_key(season_dict, Fields.COVER_URL, norm_dict.get(Fields.COVER_URL, ""))
				self.set_dict_key(season_dict, Fields.COVER_SRC, "season")
				self.set_dict_key(norm_dict, Fields.SEASONS, [season_dict])
		return norm_dict

	def get_characters(self, media_dict):
		crew_list, cast_list = [], []
		for edge in self._get(media_dict, ("characters", "edges"), []) or []:
			node = edge.get("node", {}) or {}
			staff_dict = {}
			self.set_dict_key(staff_dict, Fields.JOB, "Actor")
			self.set_dict_key(staff_dict, Fields.NAME, self._get(node, ("name", "full")) or self._get(node, ("name", "userPreferred")))
			self.set_dict_key(staff_dict, Fields.CHARACTER, str(edge.get("role", "") or ""))
			self.set_dict_key(staff_dict, Fields.PROFILE_ID, str(node.get("id", "")))
			self.set_dict_key(staff_dict, Fields.PROFILE_URL, self._get(node, ("image", "large")))
			if staff_dict:
				cast_list.append(staff_dict)
		for edge in self._get(media_dict, ("staff", "edges"), []) or []:
			node = edge.get("node", {}) or {}
			staff_dict = {}
			self.set_dict_key(staff_dict, Fields.JOB, edge.get("role", "Staff"))
			self.set_dict_key(staff_dict, Fields.NAME, self._get(node, ("name", "full")) or self._get(node, ("name", "userPreferred")))
			self.set_dict_key(staff_dict, Fields.PROFILE_ID, str(node.get("id", "")))
			self.set_dict_key(staff_dict, Fields.PROFILE_URL, self._get(node, ("image", "large")))
			if staff_dict:
				crew_list.append(staff_dict)
		return crew_list, cast_list

	def search_query_graphql(self):
		return """
query ($search: String, $type: MediaType, $seasonYear: Int, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: $type, search: $search, seasonYear: $seasonYear, sort: SEARCH_MATCH) {
      id
      type
      format
      status
      title { romaji english native userPreferred }
      description(asHtml: false)
      startDate { year month day }
      endDate { year month day }
      countryOfOrigin
      genres
      episodes
      chapters
      volumes
      duration
      averageScore
      meanScore
      popularity
      coverImage { extraLarge large medium }
      bannerImage
      isAdult
    }
  }
}
"""

	def details_query_graphql(self):
		return """
query ($id: Int, $type: MediaType) {
  Media(id: $id, type: $type) {
    id
    type
    format
    status
    title { romaji english native userPreferred }
    description(asHtml: false)
    startDate { year month day }
    endDate { year month day }
    countryOfOrigin
    genres
    episodes
    chapters
    volumes
    duration
    averageScore
    meanScore
    popularity
    coverImage { extraLarge large medium }
    bannerImage
    isAdult
    characters(page: 1, perPage: 10) {
      edges {
        role
        node { id name { full userPreferred } image { large medium } }
      }
    }
    staff(page: 1, perPage: 10) {
      edges {
        role
        node { id name { full userPreferred } image { large medium } }
      }
    }
  }
}
"""

	def _media_type(self, media_dict):
		if media_dict.get("type") == "MANGA":
			return "manga"
		return "movie" if media_dict.get("format") == "MOVIE" else "series"

	def _title(self, media_dict):
		title = media_dict.get("title", {}) or {}
		if self.language == "ja":
			return title.get("native", "") or title.get("romaji", "") or title.get("english", "") or title.get("userPreferred", "")
		return title.get("english", "") or title.get("romaji", "") or title.get("userPreferred", "") or title.get("native", "")

	def _date(self, date_dict):
		year = date_dict.get("year", "")
		month = date_dict.get("month", "")
		day = date_dict.get("day", "")
		try:
			if year and month and day:
				return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
			if year and month:
				return f"{int(year):04d}-{int(month):02d}"
		except Exception:
			pass
		return str(year) if year else ""

	def _score(self, media_dict):
		score = media_dict.get("averageScore", "") or media_dict.get("meanScore", "")
		try:
			return str(round(float(score) / 10.0, 1)) if score else ""
		except Exception:
			return str(score) if score else ""

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

	def get_api_dicts(self, query, variables=None, timeout=(3.05, 8)):
		try:
			variables = variables or {}
			variables = {key: value for key, value in variables.items() if value is not None}
			response = post(self.base_url, json={"query": query, "variables": variables}, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=timeout)
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


provider_anime = ProviderANIME()


def main(argv):
	title, language, media_type, title_id = "cowboy+bebop", "en", "series", ""
	helpstring = "ANIME v0.1: try 'python ANIME.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:i:h", ["query=", "language=", "mediatype=", "id=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'ANIME v0.1': python ANIME.py [option...] <data>\n"
			"Example: python ANIME.py -q cowboy+bebop -l de -m series\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language hint\n"
			"-m, --mediatype <options>\tset media type 'movie', 'series', 'anime' or 'manga'\n"
			"-i, --id <options>\t\tget AniList media details")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-i", "--id"):
			title_id = arg
	provider_anime.start("", language)
	if title_id:
		if media_type == "movie":
			err_msg, details = provider_anime.get_movie_details(title_id)
			payload = {"details": details}
		elif media_type == "manga":
			err_msg, details = provider_anime.get_manga_details(title_id)
			payload = {"details": details}
		else:
			err_msg, details, episode_index = provider_anime.get_series_details_index(title_id)
			payload = {"details": details, "episode_index": episode_index}
		if err_msg:
			write_log(err_msg)
		else:
			with open("anime_details.json", "w") as file:
				dump(payload, file)
			write_log("Anime details JSON file 'anime_details.json' was successfully created.")
	else:
		err_msg, norm_dicts = provider_anime.get_result_dicts(title, media_type=media_type)
		if err_msg:
			write_log(err_msg)
		else:
			with open("anime_dicts.json", "w") as file:
				dump(norm_dicts, file)
			write_log("Anime normalized JSON file 'anime_dicts.json' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
