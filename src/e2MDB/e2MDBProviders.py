########################################################################################################
# E2MDBProviders by Mr.Servo @OpenATV (c) 2026                                                         #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from json import dump, loads
from getopt import getopt, GetoptError
from re import search
from sys import exit, argv

# PLUGIN IMPORTS
try:
	from .provider.TMDB import provider_tmdb
	from .provider.TVDB import provider_tvdb
	from .provider.OMDB import provider_omdb
	from .provider.IMDB import provider_imdb
	from .provider.TVMAZE import provider_tvmaze
	from .provider.ANIME import provider_anime
	from .provider.KITSU import provider_kitsu
	from .provider.FanArt import provider_fanart
except ImportError:
	from provider.TMDB import provider_tmdb
	from provider.TVDB import provider_tvdb
	from provider.OMDB import provider_omdb
	from provider.IMDB import provider_imdb
	from provider.TVMAZE import provider_tvmaze
	from provider.ANIME import provider_anime
	from provider.KITSU import provider_kitsu
	from provider.FanArt import provider_fanart

try:
	from . import write_log
except ImportError:
	def write_log(log_text1, log_text2=""):  # in order using E2MDBProviders interactive
		print(f"{log_text1} {log_text2}")

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class E2MDBProviders:
	def __init__(self):
		self.series_search_order = {"tvdb": True, "tmdb": True, "tvmaze": False, "anime": False, "kitsu": False, "omdb": True, "imdb": False}
		self.movie_search_order = {"tmdb": True, "imdb": False, "anime": False, "kitsu": False, "tvdb": True, "omdb": True}
		self.language = "en-US"
		self.all_keys = [
						"countries", "releaseDate", "media_type", "genres", "vote_average",
						"vote_count", "cover_url", "backdrop_url", "titlelogo_url", "provider_ids"
						]  # with exception of 'Title' and 'Description', as these receive special treatment
		self.all_prov_ids = ["imdb", "tmdb", "tvdb", "tvmaze", "anime", "anilist", "kitsu"]
		self.providers_dict = {"tmdb": provider_tmdb, "tvdb": provider_tvdb, "tvmaze": provider_tvmaze, "anime": provider_anime, "kitsu": provider_kitsu, "imdb": provider_imdb, "omdb": provider_omdb}
		self.artwork_provider = provider_fanart
		self.ready_providers = set()
		self.start_errors = []
		self.last_search_errors = []

	def start(self, language, api_keys, series_search_order, movie_search_order):
		self.series_search_order = series_search_order
		self.movie_search_order = movie_search_order
		self.language = language.replace("_", "-")
		self.ready_providers = set()
		self.start_errors = []
		self.last_search_errors = []
		for pvr_name in series_search_order | movie_search_order:  # combine and remove duplicates
			provider, api_key = self.providers_dict.get(pvr_name), api_keys.get(pvr_name)
			enabled = bool(series_search_order.get(pvr_name) or movie_search_order.get(pvr_name))
			if provider and enabled:
				if api_key or not getattr(provider, "requires_api_key", True):
					try:
						provider_error = provider.start(api_key or "", self.language)  # initiate all active provider parser
					except Exception as err:
						provider_error = str(err)
					if provider_error:
						self.start_errors.append("%s: %s" % (pvr_name, provider_error))
						write_log(f"{MODULE_NAME} ERROR in module 'E2MDBProviders:start': {provider_error}")
					else:
						self.ready_providers.add(pvr_name)
				else:
					error = f"missing API-Key for provider '{pvr_name}'"
					self.start_errors.append(error)
					write_log(f"{MODULE_NAME} ERROR in module 'E2MDBProviders:start': {error}")
		if api_keys.get("fanart_active"):
			# FanArt.tv is used as artwork fallback only. E2MDB needs one personal FanArt.tv API key.
			fanart_key = api_keys.get("fanart", "")
			if fanart_key:
				fanart_err = self.artwork_provider.start(fanart_key, self.language)
				if fanart_err:
					self.start_errors.append(str(fanart_err))
					write_log(f"{MODULE_NAME} ERROR in module 'E2MDBProviders:start': {fanart_err}")
			else:
				error = "missing personal API-Key for provider 'fanart'"
				self.start_errors.append(error)
				write_log(f"{MODULE_NAME} ERROR in module 'E2MDBProviders:start': {error}")
		else:
			self.artwork_provider.stop()
		return "; ".join(self.start_errors)

	def get_movie_details(self, pvr_name, movieId):
		err_msg, movie_dict = "", {}
		provider = self.get_desired_provider(pvr_name)
		if provider:
			err_msg, movie_dict = provider.get_movie_details(movieId)
			if err_msg:
				write_log(err_msg)
		return err_msg, movie_dict

	def get_series_details_index(self, pvr_name, series_id):
		err_msg, series_dict, episode_index = "", {}, {}
		provider = self.get_desired_provider(pvr_name)
		if provider:
			err_msg, series_dict, episode_index = provider.get_series_details_index(series_id)
		return err_msg, series_dict, episode_index

	def find_season_episode(self, pvr_name, episode_index, episode_name, plain_season_episode=""):
		season_episode = ()
		for name, active in self.series_search_order.items():
			if name == pvr_name and active:
				provider = self.providers_dict.get(pvr_name)
				season_episode = provider.find_season_episode(episode_index, episode_name, plain_season_episode)  # result e.g. ('1-2', '283766', 'Die Warnung')
				break
		return season_episode

	def get_season_details(self, pvr_name, series_dict, season_no):  # 'series_id' and 'season_no' is only required by TMDB, they don't accept 'season_id'
		err_msg, season_dict = "", {}
		provider = self.get_desired_provider(pvr_name)
		if provider:
			err_msg, season_dict = provider.get_season_details(series_dict, season_no)
			if err_msg:
				write_log(err_msg)
		return err_msg, season_dict

	def get_episode_details(self, pvr_name, series_id, episode_id, season_no, episode_no):
		err_msg, episode_dict = "", {}
		provider = self.get_desired_provider(pvr_name)
		if provider:
			err_msg, episode_dict = provider.get_episode_details(series_id, episode_id, season_no, episode_no)
			if err_msg:
				write_log(err_msg)
		return err_msg, episode_dict

	def get_asset_details(self, pvr_name, asset_id, category, season_no="", episode_no=""):  # get asset infos acc. provider, Id and category
		# TVDB and OMDB uses ids for "series", "season", "episode", "movie", although ODB does not support either 'series' or 'episodes'
		# TMDB uses ids for movies only, for "series", "season", "episode" TMDB uses series_id+season_no+episode_no only
		err_msg, asset_dict = "", {}
		provider = self.get_desired_provider(pvr_name)
		if provider:
			err_msg, asset_dict = provider.get_asset_details(category, asset_id, season_no=season_no, episode_no=episode_no)
			if err_msg:
				write_log(err_msg)
		return err_msg, asset_dict

	def get_fanart_artwork(self, final_dict):
		"""Return FanArt artwork matching the already selected media item."""
		if not self.artwork_provider.is_active() or not final_dict:
			return "", {}
		provider_ids = dict(final_dict.get("provider_ids", {}) or {})
		media_type = final_dict.get("media_type", "")
		if media_type == "series" and final_dict.get("series_id") and not provider_ids.get("tvdb") and final_dict.get("provider") == "tvdb":
			provider_ids["tvdb"] = final_dict.get("series_id")
		season_no = final_dict.get("season_no", "")
		err_msg, artwork_dict = self.artwork_provider.get_e2mdb_artwork(provider_ids, media_type, season_no)
		if err_msg and "No FanArt artwork found" not in str(err_msg):
			write_log(f"{MODULE_NAME} FanArt artwork fill skipped: {err_msg}")
		return err_msg, artwork_dict

	def get_desired_provider(self, pvr_name):
		search_order = self.series_search_order or self.movie_search_order or {}
		for name, active in search_order.items():
			if name == pvr_name and active:
				return self.providers_dict.get(pvr_name)
		return self.providers_dict.get(pvr_name) if pvr_name in self.providers_dict else None

	def get_active_provider_order(self, source_order, special_first=False, manga_only=False):
		"""Return an ordered provider map without forcing TMDB ahead of the configured order."""
		ordered = {}
		special_providers = ("anime", "kitsu")
		if special_first:
			for name in special_providers:
				active = bool(self.series_search_order.get(name) or self.movie_search_order.get(name))
				if active:
					ordered[name] = True
		if manga_only:
			return {name: bool(active and name in self.ready_providers) for name, active in ordered.items()}
		for name, active in (source_order or {}).items():
			if name in special_providers:
				if not special_first and active:
					ordered[name] = bool(active)
				continue
			ordered[name] = bool(active)
		return {name: bool(active and name in self.ready_providers) for name, active in ordered.items()}

	def get_provider_media_types(self, pvr_name, estimated_type):
		"""Map the requested media family to provider search modes.

		Series and movie scans are intentionally strict here: a confirmed series no
		longer searches movie endpoints, and a confirmed movie no longer searches
		series endpoints. Mixed searches still use both families.
		"""
		is_special_provider = pvr_name in ("anime", "kitsu")
		match estimated_type:
			case "anime":
				return ["anime"] if is_special_provider else (["series", "movie"] if pvr_name != "tmdb" else ["multi"])
			case "anime_series":
				return ["series"]
			case "anime_movie":
				return ["movie"]
			case "manga" | "manga_series" | "manga_movie":
				return ["manga"] if is_special_provider else []
			case "multi":
				return ["multi"] if pvr_name == "tmdb" else ["series", "movie"]
			case "series":
				return ["series"]
			case "movie":
				return ["movie"]
			case _:
				return ["multi"] if pvr_name == "tmdb" else ["series", "movie"]

	def gather_providers_info(self, title, estimated_type, year):
		norm_dicts = []
		self.last_search_errors = []
		estimated_type = str(estimated_type or "multi")
		anime_or_manga = estimated_type in ("anime", "manga", "anime_series", "anime_movie", "manga_series", "manga_movie")
		manga_only = estimated_type in ("manga", "manga_series", "manga_movie")
		if estimated_type in ("movie", "anime_movie", "manga_movie"):
			base_order = self.movie_search_order.copy()
		elif estimated_type == "multi":
			base_order = self.series_search_order.copy()
		else:
			base_order = self.series_search_order.copy()
		search_order_dict = self.get_active_provider_order(base_order, special_first=anime_or_manga, manga_only=manga_only)
		write_log(f"{MODULE_NAME} Gathering data for title '{title}' as '{estimated_type}' using providers: {', '.join([name for name, active in search_order_dict.items() if active]) or 'none'}")
		for pvr_name, active in search_order_dict.items():  # go through all active providers
			if not active:
				continue
			provider = self.providers_dict.get(pvr_name)
			media_types = self.get_provider_media_types(pvr_name, estimated_type)
			for media_type in media_types:
				if provider:
					try:
						err_msg, pvr_dicts = provider.get_result_dicts(title, media_type=media_type, year=year if year else None)
					except Exception as err:
						err_msg, pvr_dicts = str(err), {}
					if err_msg:
						self.last_search_errors.append("%s: %s" % (pvr_name, err_msg))
						write_log(err_msg)
						continue
					write_log(f"{MODULE_NAME} - '{pvr_name}' search result as '{media_type}': {'found infos' if pvr_dicts else 'found nothing'}")
					if pvr_dicts:
						for item in pvr_dicts:
							if isinstance(item, dict):
								item["_provider_priority"] = list(search_order_dict.keys()).index(pvr_name)
						norm_dicts += pvr_dicts
		return norm_dicts


providers = E2MDBProviders()


def main(argv):  # shell interface
	title, language, media_type, year, api_keys = "the+blacklist", "en-US", "", "", {}
	helpstring = "E2MDBProviders v0.1: try 'python E2MDBProviders.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:a:h", ["query=", "language=", "media_type=", "api_keys=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip().strip()
		if not opts or opt == "-h":
			write_log("Usage 'E2MDBProviders v0.1': python E2MDBProviders.py [option...] <data>\n"
			"Example: python E2MDBProviders.py -q the+blacklist -l de-DE -m series -a \"{'tmdb': 'APIkey', 'tvdb': 'APIkey', 'omdb': 'APIkey', 'imdb': ''}\"\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language formatted like 'en-US'\n"
			"-m, --media_type <options>\tset media type 'multi', 'movie', 'series', 'anime' or 'manga' (default 'multi')\n"
			"-a, --api_keys <api_keys>\tyour personal API-Keys e.g. \"{'tmdb': '123', 'tvdb': '456', 'omdb': '789'}\"")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--media_type"):
			media_type = arg
		elif opt in ("-a", "--api_keys"):
			api_keys = loads(arg.replace("'", "\""))
		if not media_type:
			found = search(r"\(\d{4}\)", title)  # search for e.g. '(1997)'
			if found:
				found = found.group(0)
				title = title.replace(found, "")[::-1].replace(found, "").replace("+", " ", 1)[::-1].strip()  # replace one '+' from right side
				media_type, year = "movie", found.replace("(", "").replace(")", "").strip()
			else:
				media_type = "multi"  # set fallback
	if title and api_keys:
		series_search_order = {"tvdb": True, "tmdb": True, "tvmaze": True, "anime": True, "kitsu": True, "omdb": True, "imdb": True}
		movie_search_order = {"tmdb": True, "imdb": True, "anime": True, "kitsu": True, "tvdb": True, "omdb": True}
		if not language:
			language = "en-US"
			write_log("ERROR getting data: 'Language' is missing, using 'en_US' instead.")
		providers.start(language, api_keys, series_search_order, movie_search_order)
		norm_dicts = providers.gather_providers_info(title, media_type, year)
		if norm_dicts:
			file_name = "e2MDB_norm_dicts.json"
			with open(file_name, "w") as file:
				dump(norm_dicts, file)
			write_log(f"All results normalized JSON file '{file_name}' was successfully created.")
	else:
		write_log("ERROR getting data: 'Title' or the dict 'api_keys' is missing.")


if __name__ == "__main__":
	main(argv[1:])
