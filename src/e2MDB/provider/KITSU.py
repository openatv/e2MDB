########################################################################################################
# Kitsu provider for e2MDB                                                                             #
# -----------------------------------------------------------------------------------------------------#
# Uses the public Kitsu JSON:API without API key and without web parsing.                              #
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


class ProviderKITSU:
	def __init__(self):
		self.base_url = "https://kitsu.io/api/edge"
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
		self.api_key = api_key
		self.language = (language or "en").replace("_", "-").split("-", 1)[0].lower()
		self.last_update = datetime.now().isoformat()
		return ""

	def get_result_dicts(self, title, media_type="series", year=None):
		norm_dicts = []
		if media_type not in self.media_types:
			return f"{MODULE_NAME}ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		resource_type = "manga" if media_type == "manga" else "anime"
		url = f"{self.base_url}/{resource_type}"
		params = {
			"filter[text]": title,
			"page[limit]": 10,
			"sort": "-user_count"
		}
		err_msg, kitsu_dict = self.get_api_dicts(url, params=params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts(kitsu_dict.get("data", []) or [], media_type, year=year)
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
				start_year = self._year(self._attrs(item).get("startDate", ""))
				if year and start_year and str(start_year) != str(year):
					continue
				norm_dict = self.create_norm_media_dict(item, media_type=result_media_type, details=False)
				if norm_dict:
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
			err_msg = f"{MODULE_NAME}ERROR in module 'KITSU.get_movie_details': missing parameter 'movieId'."
		return err_msg, movie_details

	def get_manga_details(self, mangaId):
		err_msg, manga_details = "", {}
		if mangaId and str(mangaId).isdigit() and int(mangaId):
			err_msg, media_dict = self.get_media_dict(mangaId, resource_type="manga")
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_manga_details': {err_msg}")
			else:
				manga_details = self.create_norm_media_dict(media_dict, media_type="manga", details=True)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'KITSU.get_manga_details': missing parameter 'mangaId'."
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
			episodes = self._attrs(media_dict).get("episodeCount", 0) or 0
			try:
				episodes = int(episodes)
			except Exception:
				episodes = 0
			if episodes and episodes <= 300:
				for episode_no in range(1, episodes + 1):
					episode_dict[f"1-{episode_no}"] = (f"{series_id}:1:{episode_no}", f"Episode {episode_no}")
			episode_index = {"provider": "kitsu", "episodes": episode_dict, "note": "Kitsu does not provide localized per-episode titles through the public anime search; a numeric season-1 index is generated when the episode count is known."}
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'KITSU.get_series_details_index': missing parameter 'series_id'."
		return err_msg, series_details, episode_index

	def get_season_details(self, series_dict, season_no):
		season_no = str(season_no or "1")
		for season in series_dict.get("seasons", []) or []:
			if str(season.get("season_no", "")) == season_no:
				return "", season
		season_dict = {}
		self.set_dict_key(season_dict, Fields.PROVIDER, "kitsu")
		self.set_dict_key(season_dict, Fields.SERIES_ID, series_dict.get("series_id", ""))
		self.set_dict_key(season_dict, Fields.SEASON_NAME, f"Season {season_no}")
		self.set_dict_key(season_dict, Fields.SEASON_NO, season_no)
		self.set_dict_key(season_dict, Fields.COVER_URL, series_dict.get("cover_url", ""))
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
		self.set_dict_key(episode_dict, Fields.PROVIDER, "kitsu")
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

	def get_media_dict(self, media_id, resource_type="anime"):
		url = f"{self.base_url}/{resource_type}/{media_id}"
		params = {"include": "genres,categories"}
		err_msg, kitsu_dict = self.get_api_dicts(url, params=params)
		if err_msg:
			return err_msg, {}
		media_dict = kitsu_dict.get("data", {}) or {}
		if not media_dict:
			return "Kitsu media details unavailable", {}
		media_dict["included"] = kitsu_dict.get("included", []) or []
		return "", media_dict

	def create_norm_media_dict(self, media_dict, media_type="", details=False):
		norm_dict = {}
		if not media_dict:
			return norm_dict
		attrs = self._attrs(media_dict)
		media_type = media_type or self._media_type(media_dict)
		kitsu_id = str(media_dict.get("id", ""))
		self.set_dict_key(norm_dict, Fields.PROVIDER, "kitsu")
		self.set_dict_key(norm_dict, Fields.TITLE, self._title(attrs))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, media_type)
		if media_type == "series":
			self.set_dict_key(norm_dict, Fields.SERIES_ID, kitsu_id)
		self.set_dict_key(norm_dict, Fields.RELEASED, attrs.get("startDate", ""))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, attrs.get("ageRating", ""))
		self.set_dict_key(norm_dict, Fields.GENRES, self._genres(media_dict))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self.html_to_text(attrs.get("synopsis", "")))
		self.set_dict_key(norm_dict, Fields.RUNTIME, str(attrs.get("episodeLength", "") or attrs.get("chapterCount", "") or attrs.get("volumeCount", "")))
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._score(attrs))
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(attrs.get("userCount", "") or attrs.get("favoritesCount", "") or ""))
		self.set_dict_key(norm_dict, Fields.COVER_URL, self._image(attrs.get("posterImage", {}) or {}))
		self.set_dict_key(norm_dict, Fields.COVER_SRC, media_type)
		self.set_dict_key(norm_dict, Fields.BACKDROP_URL, self._image(attrs.get("coverImage", {}) or {}))
		self.set_dict_key(norm_dict, Fields.BACKDROP_SRC, media_type)
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"kitsu": kitsu_id})
		if details and media_type == "series":
			season_dict = {}
			self.set_dict_key(season_dict, Fields.PROVIDER, "kitsu")
			self.set_dict_key(season_dict, Fields.SERIES_ID, kitsu_id)
			self.set_dict_key(season_dict, Fields.SEASON_NAME, "Season 1")
			self.set_dict_key(season_dict, Fields.SEASON_NO, "1")
			self.set_dict_key(season_dict, Fields.RELEASED, attrs.get("startDate", ""))
			self.set_dict_key(season_dict, Fields.COVER_URL, norm_dict.get("cover_url", ""))
			self.set_dict_key(season_dict, Fields.COVER_SRC, "season")
			self.set_dict_key(norm_dict, Fields.SEASONS, [season_dict])
		return norm_dict

	def _attrs(self, media_dict):
		return media_dict.get("attributes", {}) or {}

	def _media_type(self, media_dict):
		if media_dict.get("type") == "manga":
			return "manga"
		attrs = self._attrs(media_dict)
		subtype = (attrs.get("subtype") or attrs.get("showType") or "").lower()
		return "movie" if subtype == "movie" else "series"

	def _title(self, attrs):
		titles = attrs.get("titles", {}) or {}
		if self.language == "ja":
			return titles.get("ja_jp", "") or attrs.get("canonicalTitle", "") or titles.get("en_jp", "") or titles.get("en", "")
		if self.language == "en":
			return titles.get("en", "") or attrs.get("canonicalTitle", "") or titles.get("en_jp", "") or titles.get("ja_jp", "")
		return attrs.get("canonicalTitle", "") or titles.get("en", "") or titles.get("en_jp", "") or titles.get("ja_jp", "")

	def _year(self, date_text):
		if date_text and len(str(date_text)) >= 4 and str(date_text)[:4].isdigit():
			return str(date_text)[:4]
		return ""

	def _score(self, attrs):
		score = attrs.get("averageRating", "")
		try:
			return str(round(float(score) / 10.0, 1)) if score else ""
		except Exception:
			return str(score) if score else ""

	def _image(self, image_dict):
		if not isinstance(image_dict, dict):
			return ""
		return image_dict.get("original", "") or image_dict.get("large", "") or image_dict.get("medium", "") or image_dict.get("small", "") or image_dict.get("tiny", "")

	def _genres(self, media_dict):
		genres = []
		for item in media_dict.get("included", []) or []:
			if not isinstance(item, dict):
				continue
			if item.get("type") not in ("genres", "categories"):
				continue
			attrs = item.get("attributes", {}) or {}
			name = attrs.get("name", "") or attrs.get("title", "") or attrs.get("slug", "")
			if name and name not in genres:
				genres.append(name)
		return ", ".join(genres)

	def html_to_text(self, html):
		if not html:
			return ""
		if isinstance(html, bytes):
			html = html.decode("utf-8", "replace")
		return unescape(sub(r"<br\s*/?>", "\n", sub(r"<.*?>", "", html))).strip()

	def get_api_dicts(self, url, params=None, timeout=(3.05, 8)):
		try:
			response = get(url, params=params or {}, headers={"Accept": "application/vnd.api+json, application/json", "Content-Type": "application/vnd.api+json"}, timeout=timeout)
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


provider_kitsu = ProviderKITSU()


def main(argv):
	title, language, media_type, title_id = "cowboy+bebop", "en", "series", ""
	helpstring = "KITSU v0.1: try 'python KITSU.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:i:h", ["query=", "language=", "mediatype=", "id=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'KITSU v0.1': python KITSU.py [option...] <data>\n"
			"Example: python KITSU.py -q cowboy+bebop -l de -m series\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language hint\n"
			"-m, --mediatype <options>\tset media type 'movie', 'series', 'anime' or 'manga'\n"
			"-i, --id <options>\t\tget Kitsu media details")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-i", "--id"):
			title_id = arg
	provider_kitsu.start("", language)
	if title_id:
		if media_type == "movie":
			err_msg, details = provider_kitsu.get_movie_details(title_id)
			payload = {"details": details}
		elif media_type == "manga":
			err_msg, details = provider_kitsu.get_manga_details(title_id)
			payload = {"details": details}
		else:
			err_msg, details, episode_index = provider_kitsu.get_series_details_index(title_id)
			payload = {"details": details, "episode_index": episode_index}
		if err_msg:
			write_log(err_msg)
		else:
			with open("kitsu_details.json", "w") as file:
				dump(payload, file)
			write_log("Kitsu details JSON file 'kitsu_details.json' was successfully created.")
	else:
		err_msg, norm_dicts = provider_kitsu.get_result_dicts(title, media_type=media_type)
		if err_msg:
			write_log(err_msg)
		else:
			with open("kitsu_dicts.json", "w") as file:
				dump(norm_dicts, file)
			write_log("Kitsu normalized JSON file 'kitsu_dicts.json' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
