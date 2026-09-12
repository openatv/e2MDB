########################################################################################################
# TMDB by Mr.Servo @OpenATV (c) 2026                                                                   #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from json import dump
from getopt import getopt, GetoptError
from requests import get, exceptions
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
	def write_log(log_text1, log_text2=""):  # if TMDB Interactive (via shell) is used
		print(f"{log_text1} {log_text2}")

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class ProviderTMDB:
	def __init__(self):
		# HINT: API V4 requires a monthly changing bearer token that cannot be generated automatically using apikey
		self.base_url = "https://api.themoviedb.org/3"  # using API V3
		self.img_url = "https://image.tmdb.org/t/p/original"  # reduced size 500 'https://image.tmdb.org/t/p/w500'
		self.media_types = ["multi", "movie", "series"]  # exclude from search: 'collection', 'company', 'keyword', 'person'
		self.language, self.api_key = "", ""
		self.movie_rating_dict, self.series_rating_dict = {}, {}
		self.last_update = None  # Track when data was last updated

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language="en"):
		self.api_key = api_key or self.api_key
		self.language = language
		self.all_genres = {"movie": self.get_genre_list("movie"), "series": self.get_genre_list("series")}  # needed for result_dicts only
		self.last_update = datetime.now().isoformat()
		return ""  # due to consistent feedback (used in TVDB)

	def get_images_dict(self, tmdb_id, media_type):
		url = f"{self.base_url}/{media_type.replace("series", "tv")}/{tmdb_id}/images"
		params = {
					"api_key": self.api_key,
					"include_image_language": "en-US,null",  # additional languages
					"language": self.language,  # e.g. "de"
				}
		err_msg, images_dict = self.get_api_dicts(url, params=params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_images_dict': {err_msg}")
		else:
			for imageType in ["backdrops", "logos", "posters"]:
				for image_dict in images_dict.get(imageType, []):
					file_path = image_dict.get("file_path", "")
					if file_path:
						image_dict["url"] = f"{self.img_url}{file_path}"
						image_dict.pop("file_path")
		return err_msg, images_dict

	def get_result_dicts(self, title, media_type="multi", year=None):
		norm_dicts = []
		if media_type not in self.media_types:  # exclude from results: 'collection', 'company', 'keyword', 'person'
			return f"ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		url = f"{self.base_url}/search/{media_type.replace("series", "tv")}"  # e.g. 'movie' or 'series', TMDB uses 'tv' instead of 'series'
		params = {
					"query": title,
					"primary_release_year": year,
					"api_key": self.api_key,
					"include_adult": True,
					"language": self.language,  # e.g. "de"
					"page": 1,
					"append_to_response": "videos,images",
					"accept": "application/json"
				}
		err_msg, tmdb_dicts = self.get_api_dicts(url, params=params)
		with open("tmdb_dicts.json", "w") as file:
			dump(tmdb_dicts, file)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts(tmdb_dicts.get("results", {}), media_type)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, result_dicts, media_type):
		norm_dicts = []
		for result_dict in result_dicts:  # There are other series with similar titles, but they are being limited here by [:maxentries]
			try:
				media_type = result_dict.get("media_type", "").replace("tv", "series") or media_type  # TMDB uses 'tv' instead of 'series'
				if media_type not in self.media_types:  # e.g. media_type 'person'
					continue
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "tmdb")
				title = result_dict.get("title", "") or result_dict.get("name", "")  # 'multi' & 'movie' uses 'title', 'tv' uses 'name'
				if title:
					language = self.language
				else:
					title = result_dict.get("original_title", "") or result_dict.get("original_name", "")  # 'multi' & 'movie' uses 'title', 'tv' uses 'name'
					language = result_dict.get("original_language", "")
					if not language:
						language = "en"  # fallback
				self.set_dict_key(norm_dict, Fields.TITLE, title)
				countries = "/".join(result_dict.get("origin_country", []) or [result_dict.get("original_language", "")])
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, media_type)
				self.set_dict_key(norm_dict, Fields.COUNTRIES, [country.upper() for country in countries.split(", ")][0])
				self.set_dict_key(norm_dict, Fields.RELEASED, result_dict.get("release_date", 0))  # e.g. '1970-11-29'
				genres = []
				for genreId in result_dict.get("genre_ids", []):  # [28, 18]
					for genre in self.all_genres.get(media_type, []):  # {'movie': [(28, 'Action'), (12, 'Abenteuer'), (16, 'Animation'), (18, 'Drama'),...}
						if genreId == genre[0]:
							genres.append(genre[1])
					self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(genres if genres else []))
				self.set_dict_key(norm_dict, Fields.OVERVIEW, result_dict.get("overview", ""))  # longtext
				vote_average = result_dict.get("vote_average", "")
				self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(round(vote_average, 1)) if vote_average else "")
				cover = result_dict.get("poster_path", "")
				self.set_dict_key(norm_dict, Fields.COVER_URL, f"{self.img_url}{cover}" if cover else "")
				backdrop = result_dict.get("backdrop_path", "")
				self.set_dict_key(norm_dict, Fields.BACKDROP_URL, f"{self.img_url}{backdrop}" if backdrop else "")
				image = result_dict.get("still_path", "")
				self.set_dict_key(norm_dict, "image_url", f"{self.img_url}{image}" if image else "")
				tmdb_id = str(result_dict.get("id", 0))
				err_msg, images_dict = self.get_images_dict(tmdb_id, media_type)
				if not err_msg:
					logo_url, fallback = "", ""
					for logo_dict in images_dict.get("logos", []):
						if not fallback:
							fallback = logo_dict.get("url", "")
						if logo_dict.get("iso_639_1", "") == self.language[:2]:
							logo_url = logo_dict.get("url", "")
							break
					self.set_dict_key(norm_dict, "titlelogo_url", logo_url if logo_url else fallback)
				self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"tmdb": tmdb_id})  # TMDB don't support foreign provider ids at all (e.g. 'tt0120338' for IMDB)
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		err_msg, movie_details = "", {}
		if movieId and movieId.isdigit() and int(movieId):
			url = f"{self.base_url}/movie/{movieId}"
			params = {"language": self.language, "api_key": self.api_key}
			err_msg, movie_dict = self.get_api_dicts(url, params=params)  # get all seasons
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
			else:
				url = f"{self.base_url}/movie/{movieId}/credits"
				err_msg, credits_dict = self.get_api_dicts(url, params=params)
				if err_msg:
					write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
				else:
					movie_dict.update(credits_dict)  # add cast & crew
				url = f"{self.base_url}/movie/{movieId}/images"
				params = {
					"language": self.language,  # acc. ISO 3166-1 alpha-2
					"include_image_language": f"en-US, {self.language}",
					"api_key": self.api_key
					}
				err_msg, images_dict = self.get_api_dicts(url, params=params)
				if err_msg:
					write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
				else:
					movie_dict.update(images_dict)  # add pictures (cover, backdrop & images)
				url = f"{self.base_url}/movie/{movieId}/release_dates"
				params = {"api_key": self.api_key}
				err_msg, tmdb_dict = self.get_api_dicts(url, params=params)
				if err_msg:
					write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
				else:
					certification = ""
					for result in tmdb_dict.get("results", []):
						if result.get("iso_3166_1", "").lower() == self.language:
							for release_date in result.get("release_dates", []):
								certification = release_date.get("certification")
								if certification:
									break
					movie_dict.update({"age_rating": certification})  # add age ratings
				movie_details = self.create_norm_movie_dict(movie_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TMDB.get_movie_details': missing parameter 'movieId'."
		return err_msg, movie_details

	def create_norm_movie_dict(self, movie_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tmdb")
		self.set_dict_key(norm_dict, Fields.TITLE, movie_dict.get("title", "") or movie_dict.get("original_title", ""))
		self.set_dict_key(norm_dict, Fields.TAGLINE, movie_dict.get("tagline", ""))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "movie")
		countries = "/".join(movie_dict.get("origin_country", []) or [movie_dict.get("original_language", "")])
		self.set_dict_key(norm_dict, Fields.COUNTRIES, countries)
		self.set_dict_key(norm_dict, Fields.RELEASED, movie_dict.get("release_date", ""))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, movie_dict.get("age_rating", ""))
		vote_average = movie_dict.get("vote_average", "")
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(round(vote_average, 1)) if vote_average else "")
		vote_count = movie_dict.get("vote_count", "")
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(vote_count) if vote_count else "")
		genres = self.get_all_genres(movie_dict)
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(genres if genres else []))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, movie_dict.get("overview", ""))  # longtext
		self.set_dict_key(norm_dict, Fields.RUNTIME, str(movie_dict.get("runtime", "")))
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
		for pic_type, pic_url in self.get_pictures_list(movie_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "movie")
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"tmdb": str(movie_dict.get("id", 0))})  # TMDB don't support foreign provider ids at all (e.g. 'tt0120338' for IMDB)
		crew_list, cast_list = self.get_characters(movie_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		return norm_dict

	def find_season_episode(self, episode_index, episode_name="", plain_season_episode=""):
		if episode_index:
			if plain_season_episode:
				for episode in episode_index.get("episodes", {}).items():
					if episode[0] == plain_season_episode:
						return tuple((episode[0], episode[1][0], episode[1][1]))
				if str(plain_season_episode).isdigit():
					for episode in episode_index.get("episodes", {}).items():
						if episode[0].split("-")[-1] == str(int(plain_season_episode)):
							return tuple((episode[0], episode[1][0], episode[1][1]))  # season_episode, e.g. ('1-2', '283766', 'Die Warnung')
			elif episode_name:
				for episode in episode_index.get("episodes", {}).items():
					index_name, episode_name = episode[1][1].lower(), episode_name.lower()
					if episode_name and (index_name in episode_name or episode_name in index_name):
						return tuple((episode[0], episode[1][0], episode[1][1]))  # season_episode, e.g. ('1-2', '283766', 'Die Warnung')
		return ()

	def get_all_episodes_by_season_paginated(self, series_id, specific_season=None):
		err_msg, all_episodes = "", {}
		episode_count = 0
		if not (series_id and series_id.isdigit() and int(series_id)):
			return f"ERROR: Invalid series_id '{series_id}'", {}
		url = f"{self.base_url}/tv/{series_id}"
		params = {"language": self.language, "api_key": self.api_key}
		err_msg, series_dict = self.get_api_dicts(url, params=params)  # first get the series to know how many seasons exist
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_all_episodes_by_season_paginated': {err_msg}")
			return err_msg, {}
		seasons = series_dict.get("seasons", [])
		for season in seasons:
			season_no = str(season.get("season_number", ""))
			if specific_season and season_no != str(specific_season):
				continue  # skip if specific_season is set and doesn't match
			if not season_no:
				continue
			url = f"{self.base_url}/tv/{series_id}/season/{season_no}"
			params = {"language": self.language, "api_key": self.api_key}
			err_msg, season_dict = self.get_api_dicts(url, params=params)  # load all episodes for this season
			if err_msg:
				write_log(f"{MODULE_NAME}WARNING: Could not load season {season_no}: {err_msg}")
				continue
			for episode in season_dict.get("episodes", []):
				season_no_resp = episode.get("season_number", "")
				episode_no = episode.get("episode_number", "")
				episode_name = episode.get("name", "") or f"Episode {episode_no}"
				episode_id = str(episode.get("id", ""))
				if season_no_resp and episode_no:
					key = f"{season_no_resp}-{episode_no}"
					all_episodes[key] = (episode_id, episode_name)
					episode_count += 1
		write_log(f"{MODULE_NAME}INFO: Loaded {episode_count} episodes from {len(seasons)} seasons")
		return "", all_episodes

	def get_series_details_index(self, series_id):
		err_msg, series_details, episode_index = "", {}, {}
		if series_id and series_id.isdigit() and int(series_id):
			url = f"{self.base_url}/tv/{series_id}"  # load series metadata
			params = {"language": self.language, "api_key": self.api_key}
			err_msg, series_dict = self.get_api_dicts(url, params=params)

			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			url = f"{self.base_url}/tv/{series_id}/credits"
			params = {"language": self.language, "api_key": self.api_key}
			err_msg, credits_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
			else:
				series_dict.update(credits_dict)
			url = f"{self.base_url}/tv/{series_id}/images"
			params = {
				"language": self.language,
				"include_image_language": f"en-US, {self.language}",
				"api_key": self.api_key
			}
			err_msg, images_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
			else:
				series_dict.update(images_dict)
			url = f"{self.base_url}/tv/{series_id}/content_ratings"
			params = {"api_key": self.api_key}
			err_msg, tmdb_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
			else:
				certification = ""
				for result in tmdb_dict.get("results", []):
					if result.get("iso_3166_1", "") == self.language[3:]:
						certification = result.get("rating")
						if certification:
							break
				series_dict.update({"age_rating": certification})
			series_details = self.create_norm_series_dict(series_dict)
			err_msg, episode_dict = self.get_all_episodes_by_season_paginated(series_id)  # load ALL episodes with pagination (not just first season!)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR loading episodes: {err_msg}")
				return err_msg, series_details, {}
			episode_index = {"provider": "tmdb", "episodes": episode_dict}  # create normalized episode index
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TMDB.getSeriesDetails': missing parameter 'series_id'."

		return err_msg, series_details, episode_index

	def create_norm_series_dict(self, series_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tmdb")
		series_name = series_dict.get("name", "")
		self.set_dict_key(norm_dict, Fields.TITLE, series_name)
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, "series")
		series_id = str(series_dict.get("id", 0))
		self.set_dict_key(norm_dict, Fields.SERIES_ID, series_id)
		self.set_dict_key(norm_dict, Fields.COUNTRIES, series_dict.get("originalCountry", "").upper())
		self.set_dict_key(norm_dict, Fields.RELEASED, series_dict.get("first_air_date", ""))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, series_dict.get("age_rating", ""))
		vote_average = series_dict.get("vote_average", "")
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, str(round(vote_average, 1)) if vote_average else "")
		vote_count = series_dict.get("vote_count", "")
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(vote_count) if vote_count else "")
		genres = self.get_all_genres(series_dict)
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(genres if genres else []))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, series_dict.get("overview", ""))  # longtext
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
		for pic_type, pic_url in self.get_pictures_list(series_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "series")
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"tmdb": str(series_dict.get("id", 0))})  # TMDB don't support foreign provider ids at all (e.g. 'tt0120338' for IMDB)
		season_details = []
		norm_dict[Fields.SEASONS] = {}
		for season in series_dict.get("seasons", []):
			season_dict = {}
			self.set_dict_key(season_dict, Fields.SEASON_NAME, season.get("name", ""))
			self.set_dict_key(season_dict, "season_id", str(season.get("id", "")))
			self.set_dict_key(season_dict, Fields.SEASON_NO, str(season.get("season_number", "")))
			self.set_dict_key(season_dict, Fields.RELEASED, season.get("air_date", ""))
			self.set_dict_key(season_dict, Fields.OVERVIEW, season.get("overview", ""))  # longtext
			for pic_type, pic_url in self.get_pictures_list(season):
				self.set_dict_key(season_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(season_dict, f"{pic_type}_src", "season")
			season_details.append(season_dict)
		crew_list, cast_list = self.get_characters(series_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		self.set_dict_key(norm_dict, Fields.SEASONS, season_details)
		return norm_dict

	def create_norm_episode_index(self, index_dict):
		norm_dict = {}
		self.set_dict_key(norm_dict, "provider", "tmdb")
		self.set_dict_key(norm_dict, "title", index_dict.get("name", ""))
		self.set_dict_key(norm_dict, "series_id", index_dict.get("id", ""))
		norm_dict["episodes"] = {}
		series_id = index_dict.get("id", "")
		params = {"language": self.language, "api_key": self.api_key}
		episode_count = 0
		for season_dict in index_dict.get("seasons", []):
			season_no = str(season_dict.get("season_number", ""))
			if season_no:
				url = f"{self.base_url}/tv/{series_id}/season/{season_no}"  # get all episodes
				err_msg, tmdb_dict = self.get_api_dicts(url, params=params)
				if err_msg:
					write_log(f"{MODULE_NAME}WARNING in module 'create_norm_episode_index' for season {season_no}: {err_msg}")
					continue
				for episode in tmdb_dict.get("episodes", []):
					season_no_resp = episode.get("season_number", "")
					episode_no = episode.get("episode_number", "")
					name = episode.get("name", "") or f"Episode {episode_no}"  # in case create a episode name
					entry = (str(episode.get("id", "")), name)
					self.set_dict_key(norm_dict["episodes"], f"{season_no_resp}-{episode_no}", entry)
					episode_count += 1
		write_log(f"{MODULE_NAME}INFO: Created episode index with {episode_count} episodes")
		return norm_dict

	def get_season_details(self, series_details, season_no):  # TMDB has a internal 'season_id' but don't accept a search with their 'season_id'
		err_msg, season_details = "", {}
		series_name = series_details.get("title", "")
		series_id = series_details.get("series_id", "")
		if series_id and season_no:
			url = f"{self.base_url}/tv/{series_id}/season/{season_no}"
			params = {
						"api_key": self.api_key,
						"append_to_response": "en-US",  # additional languages
						"language": self.language,  # acc. ISO 3166-1 alpha-2
					}
			err_msg, season_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_season_details': {err_msg}")
			else:
				season_details = self.create_norm_season_dict(season_dict, series_name=series_name, series_id=series_id)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TMDB.get_season_details': missing parameter {'season_id' if series_id else 'series_id'}."
		return err_msg, season_details

	def create_norm_season_dict(self, season_dict, series_name="", series_id=""):  # creates season details in a normalized form
		# Unfortunately, the TMDB 'season' dictionary does not include a 'series_name' or 'series_id', so these must be provided separately if available
		norm_dict = {}
		self.set_dict_key(norm_dict, Fields.PROVIDER, "tmdb")
		self.set_dict_key(norm_dict, Fields.TITLE, series_name or season_dict.get("title", ""))  # try to get it
		self.set_dict_key(norm_dict, Fields.SERIES_ID, series_id or season_dict.get("series_id", ""))  # try to get it
		self.set_dict_key(norm_dict, Fields.SEASON_NAME, season_dict.get("name", ""))
		self.set_dict_key(norm_dict, "season_id", season_dict.get("_id", ""))
		self.set_dict_key(norm_dict, Fields.SEASON_NO, str(season_dict.get("season_number", "")))
		self.set_dict_key(norm_dict, Fields.RELEASED, season_dict.get("air_date", ""))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, season_dict.get("overview", ""))  # longtext
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
		for pic_type, pic_url in self.get_pictures_list(season_dict):
			self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
			self.set_dict_key(norm_dict, f"{pic_type}_src", "season")
		episodes = []
		for episode in season_dict.get("episodes", []):
			episode_dict = {}
			self.set_dict_key(episode_dict, Fields.EPISODE_NAME, episode.get("name", ""))
			self.set_dict_key(episode_dict, Fields.EPISODE_ID, str(episode.get("id", "")))
			self.set_dict_key(episode_dict, Fields.EPISODE_NO, str(episode.get("episode_number", "")))
			self.set_dict_key(episode_dict, Fields.RELEASED, episode.get("air_date", ""))
			self.set_dict_key(episode_dict, Fields.OVERVIEW, episode.get("overview", ""))  # longtext
			self.set_dict_key(episode_dict, Fields.RUNTIME, str(episode.get("runtime", "")))
			for pic_type, pic_url in self.get_pictures_list(episode):
				self.set_dict_key(episode_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(episode_dict, f"{pic_type}_src", "episode")
			episodes.append(episode_dict)
		crew_list, cast_list = self.get_characters(season_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		self.set_dict_key(norm_dict, "episodes", episodes)
		return norm_dict

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):  # instead of episode_id, TMDB only uses series_id, season_no and episode_no
		err_msg, episode_details = "", {}
		if series_id:
			url = f"{self.base_url}/tv/{series_id}/season/{season_no}/episode/{episode_no}"
			params = {"language": self.language, "api_key": self.api_key}
			err_msg, episode_dict = self.get_api_dicts(url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
			else:
				episode_details = self.create_norm_episode_dict(episode_dict)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'TMDB.get_episode_details': missing parameters 'series_id', 'season_no' or 'episode_no'."
		return err_msg, episode_details

	def create_norm_episode_dict(self, episode_dict):  # creates episode details in a normalized form
		norm_dict = {}
		if episode_dict:
			self.set_dict_key(norm_dict, Fields.PROVIDER, "tmdb")
			# TMDB don't support "series_id" in episode results
			self.set_dict_key(norm_dict, Fields.EPISODE_NAME, episode_dict.get("name", ""))
			self.set_dict_key(norm_dict, Fields.EPISODE_ID, str(episode_dict.get("id", "")))
			self.set_dict_key(norm_dict, Fields.SEASON_NO, str(episode_dict.get("season_number", "")))
			self.set_dict_key(norm_dict, Fields.EPISODE_NO, str(episode_dict.get("episode_number", "")))
			self.set_dict_key(norm_dict, Fields.RELEASED, episode_dict.get("air_date", ""))
			self.set_dict_key(norm_dict, Fields.OVERVIEW, episode_dict.get("overview", ""))  # longtext
			self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, episode_dict.get("vote_average", ""))
			self.set_dict_key(norm_dict, Fields.VOTE_COUNT, episode_dict.get("vote_count", ""))
			self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # add timestamp
			for pic_type, pic_url in self.get_pictures_list(episode_dict):
				self.set_dict_key(norm_dict, f"{pic_type}_url", pic_url)
				self.set_dict_key(norm_dict, f"{pic_type}_src", "episode")
			crew_list, cast_list = self.get_characters(episode_dict)
			self.set_dict_key(norm_dict, Fields.CREW, crew_list)
			self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		return norm_dict

	def get_asset_details(self, category, asset_id, season_no="", episode_no=""):  # get asset infos acc. category, assetId or (asetId+SeasonNo+EpisodeNo)
		err_msg, asset_details = "", {}
		if asset_id:
			err_msg, asset_dict = self.get_asset_dict(category, asset_id, season_no=season_no, episode_no=episode_no)
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
		err_msg, tmdb_dict = "", {}
		urlpart, add_params = "", {}
		if category == "series":
			urlpart, add_params = f"/tv/{asset_id}", {}
		elif category == "season":
			if season_no:
				urlpart, add_params = f"/tv/{asset_id}/season/{season_no}", {"append_to_response": "en"}
			else:
				err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_dict': missing parameter 'season_no'"
		elif category == "episode":
			if season_no and episode_no:
				urlpart, add_params = f"/tv/{asset_id}/season/{season_no}/episode/{episode_no}", {}
			else:
				err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_dict': missing parameters 'season_no' and/or 'episode_no'"
		elif category == "movie":
			urlpart, add_params = f"/movie/{asset_id}", {}
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_dict': unknown or missing parameter 'category': '{category}'"
		if urlpart and not err_msg:
			url = f"{self.base_url}{urlpart if str(urlpart).startswith('/') else '/' + str(urlpart)}"
			params = {"language": self.language, "api_key": self.api_key} | add_params
			err_msg, tmdb_dict = self.get_api_dicts(url, params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_asset_dict': {err_msg}")
		return err_msg, tmdb_dict

	def get_genre_list(self, media_type):
		genre_list = []
		if media_type not in self.media_types:  # exclude 'people', 'all'
			write_log(f"{MODULE_NAME}ERROR in module 'get_genre_list': unknown media_type '{media_type}'. Supported is '{', '.join(self.media_types)}'")
			return []
		url = f"{self.base_url}/genre/{media_type.replace("series", "tv")}/list"  # TMDB uses 'tv' instead of 'series'
		params = {"language": self.language, "api_key": self.api_key}
		err_msg, genre_dict = self.get_api_dicts(url, params=params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_genre_list': {err_msg}")
		else:
			genre_list = [(entry.get("id", 0), entry.get("name", "")) for entry in genre_dict.get("genres", [])]
		return genre_list

	def get_all_genres(self, tmdb_dict):
		genres = []
		for genre_dict in tmdb_dict.get("genres", []):
			genre_name = genre_dict.get("name", "")
			if genre_name:
				genres.append(genre_name)
		return genres

	def get_titlelogo_url(self, tmdb_dict):  # check for localized titlelogos
		titlelogo_url = ""
		logos = tmdb_dict.get("logos", [])
		for logo_dict in logos:
			if logo_dict.get("iso_639_1") in self.language:
				logo = logo_dict.get("file_path", "")
				if logo:
					titlelogo_url = logo
					break
		if not titlelogo_url and logos:  # fallback, get the first found
			titlelogo_url = logos[0].get('file_path', '')
		return titlelogo_url

	def get_characters(self, tmdb_dict):
		crew_list, cast_list = [], []
		for staff in [("crew", crew_list), ("guest_stars", cast_list), ("cast", cast_list)]:  # (originalKey, staffList)
			for profile_dict in tmdb_dict.get(staff[0], []):
				staff_dict = {}
				self.set_dict_key(staff_dict, Fields.JOB, profile_dict.get("job", ""))
				self.set_dict_key(staff_dict, Fields.NAME, profile_dict.get("name", ""))
				self.set_dict_key(staff_dict, Fields.CHARACTER, profile_dict.get("character", ""))
				self.set_dict_key(staff_dict, Fields.PROFILE_ID, str(profile_dict.get("id", "")))
				image = profile_dict.get("profile_path", "")
				self.set_dict_key(staff_dict, Fields.PROFILE_URL, f"{self.img_url}{image}" if image else "")  # e.g. '/eZgBiSDTc25mEjMoyRKZTa2ggbm.jpg'
				staff[1].append(staff_dict)
		return crew_list, cast_list

	def get_pictures_list(self, tmdb_dict):
		pic_list = []
		cover = tmdb_dict.get("poster_path", "")
		if cover:
			pic_list.append(("cover", f"{self.img_url}{cover}"))
		backdrop = tmdb_dict.get("backdrop_path", "")
		if backdrop:
			pic_list.append(("backdrop", f"{self.img_url}{backdrop}"))
		titlelogo = self.get_titlelogo_url(tmdb_dict)
		if titlelogo:
			pic_list.append(("titlelogo", f"{self.img_url}{titlelogo}"))
		image = tmdb_dict.get("still_path", "")
		if image:
			pic_list.append(("image", f"{self.img_url}{image}"))
		return pic_list

	def get_api_dicts(self, url, params=None, timeout=(3.05, 6)):
		headers = {"accept": "application/json"}
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			err_msg, api_dicts = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			return err_msg, api_dicts
		except exceptions.RequestException as err_msg:
			return err_msg, {}

	def set_dict_key(self, dictionary, key, value):
		if value:
			dictionary[key] = value


provider_tmdb = ProviderTMDB()


def main(argv):  # shell interface
	title, language, media_type, asset_id, api_key, season_no, episode_no = "the+blacklist", "en", "", "", "", "", ""
	helpstring = "TMDB v0.1: try 'python TMDB.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:s:e:l:m:a:h", ["query=", "season_no=", "episode_no=", "language=", "mediatype=", "api_key=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip().strip()
		if not opts or opt == "-h":
			write_log("Usage 'TMDB v0.1': python TMDB.py [option...] <data>\n"
			"Example: python TMDB.py -q the+blacklist -l de-DE -s 1 -e 2 -m series -a {your personal api-key}\n"
			"-q, --query <options>\t\tget result list from TMDB search'\n"
			"-s, --season_no <digit>\t\tseason Number as digit\n"
			"-e, --episode_no <digit>\t\tepisode number as digit\n"
			"-l, --language <options>\tset language formatted like 'en'\n"
			"-m, --media_type <options>\tset media type 'multi', 'movie' or 'series' (default 'multi')\n"
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
			media_type = "multi"  # set fallback
		write_log(f"Search for '{title.replace("+", " ")}', media_type: '{media_type}'")
		provider_tmdb.start(api_key, language)
		err_msg, norm_dicts = provider_tmdb.get_result_dicts(title, media_type=media_type, year=None)
		if err_msg:
			write_log(f"ERROR getting data: {err_msg}")
			exit(2)
		if norm_dicts:
			results = norm_dicts[:1]  # get first result only
			if results:
				result = results[0]  # get first result only
				asset_id = str(result.get("provider_ids", {}).get("tmdb", ""))  # e.g. '1368'
				media_type = result.get("media_type", "").replace("tv", "series")  # e.g. 'movie' or 'series', TMDB uses 'tv' instead of 'series'
				if asset_id:
					filePart = f"tmdb_{asset_id}"
					if media_type == "series":
						write_log("Download requested data...")
						# series details with ALL episodes (improved!)
						err_msg, series_details, episode_index = provider_tmdb.get_series_details_index(asset_id)
						if err_msg:
							write_log(f"Error downloading series details and index: {err_msg}")
							exit(2)
						if series_details:
							file_name = f"{filePart}.seriesDetails.json"
							with open(file_name, "w") as file:
								dump(series_details, file)
							write_log(f"Series details file '{file_name}' was successfully created.")
						if episode_index:
							file_name = f"{filePart}.episodeIndex.json"
							with open(file_name, "w") as file:
								dump(episode_index, file)
							episode_count = len(episode_index.get("episodes", {}))
							write_log(f"Episode index file '{file_name}' created with {episode_count} episodes.")
						# episode or season details
						if season_no:
							err_msg, season_dict = provider_tmdb.get_season_details(series_details, season_no)
							if err_msg:
								write_log(f"Error downloading season details: {err_msg}")
								exit(2)
							if season_dict:
								file_name = f"{filePart}.seasonDetails.json"
								with open(file_name, "w") as file:
									dump(season_dict, file)
								write_log(f"Season details file '{file_name}' was successfully created.")
							if episode_no:
								err_msg, episode_dict = provider_tmdb.get_episode_details(series_id=asset_id, season_no=season_no, episode_no=episode_no)
								if err_msg:
									write_log(f"Error downloading episode details: {err_msg}")
									exit(2)
								if episode_dict:
									file_name = f"{filePart}.episodeDetails.json"
									with open(file_name, "w") as file:
										dump(episode_dict, file)
									write_log(f"Episode details file '{file_name}' was successfully created.")
					else:  # means 'movie'
						err_msg, movie_dict = provider_tmdb.get_movie_details(asset_id)
						if err_msg:
							write_log(f"Error downloading episode details: {err_msg}")
							exit(2)
						if movie_dict:
							file_name = f"{filePart}.movieDetails.json"
							with open(file_name, "w") as file:
								dump(movie_dict, file)
							write_log(f"Movie details file '{file_name}' was successfully created.")
				if norm_dicts:
					file_name = "tmdb_searchResults.json"
					with open(file_name, "w") as file:
						dump(norm_dicts, file)
					write_log(f"Result details file '{file_name}' was successfully created.")
	else:
		err_msg = "'Title' or 'language' is missing"
		write_log("ERROR getting data:", err_msg)


if __name__ == "__main__":
	main(argv[1:])
