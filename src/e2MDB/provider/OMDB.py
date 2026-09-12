########################################################################################################
# OMDB by Mr.Servo @OpenATV (c) 2026                                                                   #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
# - Note: OMDB has significant API limitations (no episode/season pagination)                          #
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
	def write_log(log_text1, log_text2=""):  # if OMDB Interactive (via shell) is used
		print(f"{log_text1} {log_text2}")

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class ProviderOMDB:
	def __init__(self):
		self.base_url = "http://www.omdbapi.com/"
		self.media_types = ["movie", "series", "episode"]  # exclude from search: {nothing}
		self.api_key = ""
		self.last_update = None  # Track when data was last updated

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language=""):  # OMDB doesn't support language requests at all
		self.api_key = api_key or self.api_key
		self.last_update = datetime.now().isoformat()
		return ""  # due to consistent feedback (used in TVDB)

	def get_result_dicts(self, title, media_type="series", year=None):  # OMDB only returns a single result and does not have neither localization support nor its own episodesId
		norm_dicts = []
		if media_type not in self.media_types:
			return f"{MODULE_NAME}ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		# param 's' (search) returns a result list with useless tiny results, 't' (title) returns only one, but a complete result
		params = {"t": title, "type": media_type, "y": year, "plot": "full", "apikey": self.api_key}
		err_msg, result = self.get_api_dicts(self.base_url, params)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			norm_dicts = self.create_norm_result_dicts([result], media_type)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, result_dicts, media_type):
		norm_dicts = []
		result_dict = result_dicts[0] if result_dicts else {}  # extract first (and only) result
		if result_dict and result_dict.get("Response", "False") == "True":
			try:
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "omdb")
				self.set_dict_key(norm_dict, Fields.TITLE, result_dict.get("Title", ""))
				# OMDB don't support 'tagline' at all
				self.set_dict_key(norm_dict, Fields.COUNTRIES, result_dict.get("Country", ""))  # e.g. 'United States'
				rel_list = result_dict.get("Released", "").upper().split(" ")  # e.g. '04 Oct 1997'
				if rel_list and len(rel_list) > 2:  # necessary workaround due to fixed localisation of Enigma2 (e.g. to 'de_DE')
					month = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}.get(rel_list[1], 0)
					if month and int(rel_list[2]) and int(rel_list[0]):
						released_dt = datetime.now().replace(year=int(rel_list[2]), month=month, day=int(rel_list[0]), hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
						self.set_dict_key(norm_dict, Fields.RELEASED, released_dt.strftime('%Y-%m-%d'))
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, result_dict.get("Type", "") or media_type)
				self.set_dict_key(norm_dict, Fields.GENRES, result_dict.get("Genre", ""))  # e.g. 'Drama, Romance'
				self.set_dict_key(norm_dict, Fields.OVERVIEW, result_dict.get("Plot", "").replace("N/A", ""))  # longtext, OMDB doesn't support languages at all
				self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, result_dict.get("imdbRating", "").replace(",", ""))
				self.set_dict_key(norm_dict, Fields.VOTE_COUNT, result_dict.get("imdbVotes", "").replace(",", ""))
				self.set_dict_key(norm_dict, Fields.COVER_URL, result_dict.get("Poster", ""))
				self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)  # Add timestamp
				imdb_id = result_dict.get("imdbID", "")
				if imdb_id and imdb_id != "N/A":
					self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"imdb": imdb_id, "omdb": imdb_id})  # OMDB has no own ids
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		err_msg, movie_details = "", {}
		if movieId and not movieId.isdigit():  # OMDB uses IMDb IDs like 'tt0111161', not just digits
			params = {"i": movieId, "type": "movie", "plot": "full", "apikey": self.api_key}
			err_msg, movie_dict = self.get_api_dicts(self.base_url, params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
			else:
				movie_list = self.create_norm_result_dicts([movie_dict], "movie")
				movie_details = movie_list[0] if movie_list else {}  # extract first (and only) result
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'OMDB.get_movie_details': missing or invalid parameter 'movieId' (must be IMDb ID like 'tt0111161')."
		return err_msg, movie_details

	def find_season_episode(self, episode_index, episode_name="", plain_season_episode=""):  # OMDB do not support this function at all
		return ()

	def get_series_details_index(self, series_id):  # OMDB do only support basic series response, no episode index
		"""
		IMPROVED: Get series details from OMDB.
		Note: OMDB's episode/season support is very limited compared to TVDB/TMDB.
		Returns:
			(error_msg, series_details, episode_index) - episode_index will be empty dict
				because OMDB doesn't provide episode-level data in series queries
		"""
		err_msg, series_details = "", {}
		if series_id and not series_id.isdigit():  # OMDB uses IMDb IDs like 'tt0111161'
			params = {"i": series_id, "type": "series", "plot": "full", "apikey": self.api_key}
			err_msg, series_dict = self.get_api_dicts(self.base_url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				return err_msg, {}, {}
			else:
				series_details_list = self.create_norm_result_dicts([series_dict], "series")
				series_details = series_details_list[0] if series_details_list else {}  # extract first (and only) result
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'OMDB.getSeriesDetails': missing or invalid parameter 'series_id' (must be IMDb ID like 'tt0111161')."

		# OMDB doesn't provide episode index data
		episode_index = {"provider": "omdb", "episodes": {}, "note": "OMDB API does not support episode listing"}
		write_log(f"{MODULE_NAME}WARNING: OMDB provider has limited episode support. Use TVDB or TMDB for full episode metadata.")

		return err_msg, series_details, episode_index

	def get_season_details(self, series_details, season_no):  # OMDB do not support this function at all
		return "", {}

	def get_episode_details(self, series_id="", series_name="", episode_id="", season_no="", episode_no=""):
		err_msg, episode_details = "", {}
		if episode_id and not episode_id.isdigit():  # OMDB uses IMDb IDs like 'tt0944947'
			params = {"i": episode_id, "type": "episode", "plot": "full", "apikey": self.api_key}
			err_msg, episode_dict = self.get_api_dicts(self.base_url, params=params)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
				return err_msg, {}

			# Create normalized episode dict with all available fields
			episode_details_list = self.create_norm_result_dicts([episode_dict], "series")
			if episode_details_list:
				episode_details = episode_details_list[0]  # extract first (and only) result
				# Add additional fields if available from OMDB response
				if episode_dict.get("Season"):
					episode_details["season_no"] = episode_dict.get("Season", "")
				if episode_dict.get("Episode"):
					episode_details["episode_no"] = episode_dict.get("Episode", "")
				episode_details["seriesName"] = series_name or episode_dict.get("seriesName", "")
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'OMDB.get_episode_details': missing or invalid parameter 'episode_id' (must be IMDb ID like 'tt0944947')."

		return err_msg, episode_details

	def create_norm_episode_index(self, index_dict):  # OMDB do not support this function at all
		return {"provider": "omdb", "episodes": {}}

	def get_api_dicts(self, url, params=None, timeout=(3.05, 6)):
		headers = {"accept": "application/json"}
		response = None
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			response.raise_for_status()
			return "", response.json()
		except exceptions.RequestException as err_msg:
			return err_msg, {}
		finally:
			if response is not None:
				response.close()

	def set_dict_key(self, dictionary, key, value):
		if value and value != "N/A":
			dictionary[key] = value


provider_omdb = ProviderOMDB()


def main(argv):  # shell interface
	title, media_type, api_key = "the+blacklist", "", ""
	helpstring = "OMDB v0.1: try 'python OMDB.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:m:a:h", ["query=", "mediatype=", "api_key=", "help"])
	except GetoptError as error:
		write_log(f"{MODULE_NAME}ERROR in module 'main': {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'OMDB v0.1': python OMDB.py [option...] <data>\n"
			"Example: python OMDB.py -q the+blacklist -m series -a {your personal api-key}\n"
			"-q, --query <options>\t\tget result list from OMDB search'\n"
			"-m, --mediatype <options>\tset media type 'movie' or 'series' (default 'series')\n"
			"-a, --api_key <your Api Key>\tpersonal key for accessing the API server\n"
			"\nNote: OMDB provider has limited episode/season support. Use TVDB or TMDB for full metadata.\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-a", "--api_key"):
			api_key = arg
	if title:
		if not api_key:
			write_log("ERROR: API key is missing.")
			exit(2)
		if not media_type:
			media_type = "series"  # set fallback
		write_log(f"Search for '{title}', media_type: '{media_type}'")
		provider_omdb.start(api_key)
		err_msg, norm_dicts = provider_omdb.get_result_dicts(title, media_type=media_type, year=None)
		if err_msg:
			write_log("ERROR getting data:", err_msg)
			exit(2)
		if norm_dicts:
			results = norm_dicts[:1]
			if results:
				result = results[0] if results else {}  # get first result only
				imdb_id = result.get("provider_ids", {}).get("omdb", "")
				media_type = result.get("media_type", "")  # e.g. 'movie' or 'series'
				if imdb_id and media_type:
					file_name = f"omdb_{imdb_id}.{media_type}Details.json"
					with open(file_name, "w") as file:
						dump(norm_dicts, file)
						write_log(f"{media_type.capitalize()} details file '{file_name}' was successfully created.")

					# Try to load full series/movie details if applicable
					if media_type == "series":
						err_msg, series_details, episode_index = provider_omdb.get_series_details_index(imdb_id)
						if err_msg:
							write_log(f"Warning: Could not load full series details: {err_msg}")
						else:
							file_name = f"omdb_{imdb_id}.seriesDetails.json"
							with open(file_name, "w") as file:
								dump(series_details, file)
								write_log(f"Series details file '{file_name}' was successfully created.")
					elif media_type == "movie":
						err_msg, movie_details = provider_omdb.get_movie_details(imdb_id)
						if err_msg:
							write_log(f"Warning: Could not load full movie details: {err_msg}")
						else:
							file_name = f"omdb_{imdb_id}.movieDetails.json"
							with open(file_name, "w") as file:
								dump(movie_details, file)
								write_log(f"Movie details file '{file_name}' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
