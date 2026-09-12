########################################################################################################
# IMDB provider for E2MDB                                                                              #
# IMDb anonymous GraphQL integration, adapted from the Enigma2 IMDb plugin API logic.                  #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from datetime import datetime
from getopt import getopt, GetoptError
from html import unescape
from json import dumps, dump
from re import sub
from requests import post, exceptions
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


class ProviderIMDB:
	def __init__(self):
		self.base_url = "https://caching.graphql.imdb.com/"
		self.media_types = ["movie", "series", "episode"]
		self.language = "en"
		self.locale = "en-US"
		self.country = "US"
		self.api_key = ""
		self.last_update = None
		self.requires_api_key = False
		# Keep lightweight search results as a safe fallback when IMDb rejects
		# a later detail GraphQL request. IMDb's anonymous endpoint is brittle and
		# can return HTTP 400 for single detail fields while the search payload still
		# contains usable title, plot and poster data.
		self._search_result_cache = {}

	def get_name(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def is_active(self):
		return True

	def start(self, api_key="", language="en-US"):
		self.api_key = api_key or ""
		self.locale = self._normalize_locale(language)
		parts = self.locale.split("-", 1)
		self.language = parts[0].lower()
		self.country = parts[1].upper() if len(parts) > 1 else "US"
		self.last_update = datetime.now().isoformat()
		return ""

	def get_result_dicts(self, title, media_type="series", year=None):
		norm_dicts = []
		if media_type not in self.media_types:
			return f"{MODULE_NAME}ERROR in module 'get_result_dicts': unknown search_mode '{media_type}'. Supported is '{', '.join(self.media_types)}'", {}
		query = self.search_query_graphql(title, media_type)
		err_msg, imdb_dict = self.get_api_dicts(query)
		if err_msg:
			write_log(f"{MODULE_NAME}ERROR in module 'get_result_dicts': {err_msg}")
		else:
			edges = self._get(imdb_dict, ("data", "mainSearch", "edges"), [])
			norm_dicts = self.create_norm_result_dicts(edges, media_type, year=year)
		return err_msg, norm_dicts

	def create_norm_result_dicts(self, result_edges, media_type, year=None, entriesmax=0):
		norm_dicts = []
		results = result_edges[:entriesmax] if entriesmax else result_edges
		for edge in results:
			try:
				result = self._get(edge, ("node", "entity"), {})
				if not result:
					continue
				imdb_id = self._get(result, "id")
				if not imdb_id:
					continue
				result_media_type = self._media_type_from_title(result)
				if media_type != result_media_type:
					continue
				release_year = self._get(result, ("releaseYear", "year"))
				if year and release_year and str(release_year) != str(year):
					continue
				norm_dict = {}
				self.set_dict_key(norm_dict, Fields.PROVIDER, "imdb")
				self.set_dict_key(norm_dict, Fields.TITLE, self._get(result, ("titleText", "text")) or self._get(result, ("originalTitleText", "text")))
				self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, result_media_type)
				self.set_dict_key(norm_dict, Fields.RELEASED, str(release_year) if release_year else "")
				self.set_dict_key(norm_dict, Fields.OVERVIEW, self._get(result, ("plot", "plotText", "plainText")))
				self.set_dict_key(norm_dict, Fields.COVER_URL, self._get(result, ("primaryImage", "url")))
				self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"imdb": imdb_id})
				self._cache_search_result(imdb_id, norm_dict)
				norm_dicts.append(norm_dict)
			except Exception as err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'create_norm_result_dicts': {err_msg}'")
		return norm_dicts

	def get_movie_details(self, movieId):
		err_msg, movie_details = "", {}
		if self._valid_imdb_id(movieId):
			err_msg, title_dict = self.get_title_dict(movieId)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_movie_details': {err_msg}")
				movie_details = self._cached_result_details(movieId, expected_media_type="movie")
				if movie_details:
					write_log(f"{MODULE_NAME}Using cached search result fallback for movie details '{movieId}'.")
					return "", movie_details
			else:
				movie_details = self.create_norm_title_dict(title_dict, expected_media_type="movie")
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'IMDB.get_movie_details': missing or invalid parameter 'movieId' (must be IMDb ID like 'tt0111161')."
		return err_msg, movie_details

	def get_series_details_index(self, series_id):
		err_msg, series_details, episode_index = "", {}, {}
		episode_index = {"provider": "imdb", "episodes": {}, "note": "IMDb anonymous GraphQL access is used without HTML parsing; episode listing is not requested."}
		if self._valid_imdb_id(series_id):
			err_msg, title_dict = self.get_title_dict(series_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_series_details_index': {err_msg}")
				series_details = self._cached_result_details(series_id, expected_media_type="series")
				if series_details:
					write_log(f"{MODULE_NAME}Using cached search result fallback for series details '{series_id}'.")
					return "", series_details, episode_index
				return err_msg, {}, {}
			series_details = self.create_norm_title_dict(title_dict, expected_media_type="series")
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'IMDB.get_series_details_index': missing or invalid parameter 'series_id' (must be IMDb ID like 'tt0944947')."
		return err_msg, series_details, episode_index

	def get_season_details(self, series_dict, season_no):
		return "", {}

	def get_episode_details(self, series_id="", episode_id="", season_no="", episode_no=""):
		err_msg, episode_details = "", {}
		if self._valid_imdb_id(episode_id):
			err_msg, title_dict = self.get_title_dict(episode_id)
			if err_msg:
				write_log(f"{MODULE_NAME}ERROR in module 'get_episode_details': {err_msg}")
				episode_details = self._cached_result_details(episode_id, expected_media_type="episode")
				if episode_details:
					write_log(f"{MODULE_NAME}Using cached search result fallback for episode details '{episode_id}'.")
					err_msg = ""
			else:
				episode_details = self.create_norm_title_dict(title_dict, expected_media_type="episode")
			self.set_dict_key(episode_details, Fields.SERIES_ID, series_id)
			self.set_dict_key(episode_details, Fields.SEASON_NO, str(season_no) if season_no else "")
			self.set_dict_key(episode_details, Fields.EPISODE_NO, str(episode_no) if episode_no else "")
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'IMDB.get_episode_details': missing or invalid parameter 'episode_id' (must be IMDb ID like 'tt0944947')."
		return err_msg, episode_details

	def get_asset_details(self, category, asset_id, season_no="", episode_no=""):
		err_msg, asset_details = "", {}
		if category == "movie":
			err_msg, asset_details = self.get_movie_details(asset_id)
		elif category == "series":
			err_msg, asset_details, _episode_index = self.get_series_details_index(asset_id)
		elif category == "episode":
			err_msg, asset_details = self.get_episode_details("", asset_id, season_no, episode_no)
		else:
			err_msg = f"{MODULE_NAME}ERROR in module 'get_asset_details': unsupported category '{category}'."
		return err_msg, asset_details

	def find_season_episode(self, episode_index, episode_name="", plain_season_episode=""):
		return ()

	def get_title_dict(self, title_id):
		query = self.storyline_query_graphql(title_id)
		err_msg, imdb_dict = self.get_api_dicts(query)
		if err_msg:
			write_log(f"{MODULE_NAME}Detail query failed for '{title_id}', retrying with minimal title query: {err_msg}")
			minimal_query = self.minimal_title_query_graphql(title_id)
			minimal_err, imdb_dict = self.get_api_dicts(minimal_query)
			if minimal_err:
				return f"{err_msg} | minimal retry: {minimal_err}", {}
		title_dict = self._get(imdb_dict, ("data", "title"), {})
		if not title_dict:
			return "IMDb title details unavailable", {}
		return "", title_dict

	def create_norm_title_dict(self, title_dict, expected_media_type=""):
		norm_dict = {}
		if not title_dict:
			return norm_dict
		media_type = self._media_type_from_title(title_dict)
		if expected_media_type == "movie" and media_type != "movie":
			media_type = "movie"
		elif expected_media_type == "series" and media_type != "series":
			media_type = "series"
		elif expected_media_type == "episode" and media_type != "episode":
			media_type = "episode"
		imdb_id = self._get(title_dict, "id")
		self.set_dict_key(norm_dict, Fields.PROVIDER, "imdb")
		self.set_dict_key(norm_dict, Fields.TITLE, self._get(title_dict, ("titleText", "text")) or self._get(title_dict, ("originalTitleText", "text")))
		self.set_dict_key(norm_dict, Fields.MEDIA_TYPE, media_type)
		if media_type == "series":
			self.set_dict_key(norm_dict, Fields.SERIES_ID, imdb_id)
		elif media_type == "episode":
			self.set_dict_key(norm_dict, Fields.EPISODE_ID, imdb_id)
		self.set_dict_key(norm_dict, Fields.RELEASED, self._release_date(title_dict))
		self.set_dict_key(norm_dict, Fields.AGE_RATING, self._get(title_dict, ("certificate", "rating")))
		self.set_dict_key(norm_dict, Fields.COUNTRIES, "/".join([self._get(c, "text") for c in self._get(title_dict, ("countriesOfOrigin", "countries"), []) if self._get(c, "text")]))
		genres = [self._get(genre, "text") for genre in self._get(title_dict, ("genres", "genres"), []) if self._get(genre, "text")]
		self.set_dict_key(norm_dict, Fields.GENRES, ", ".join(genres))
		self.set_dict_key(norm_dict, Fields.OVERVIEW, self._overview(title_dict))
		self.set_dict_key(norm_dict, Fields.RUNTIME, self._runtime_minutes(title_dict))
		self.set_dict_key(norm_dict, Fields.VOTE_AVERAGE, self._rating(title_dict))
		self.set_dict_key(norm_dict, Fields.VOTE_COUNT, str(self._get(title_dict, ("ratingsSummary", "voteCount"))) if self._get(title_dict, ("ratingsSummary", "voteCount")) else "")
		cover_url = self._get(title_dict, ("primaryImage", "url"))
		self.set_dict_key(norm_dict, Fields.COVER_URL, cover_url)
		self.set_dict_key(norm_dict, Fields.COVER_SRC, media_type)
		self.set_dict_key(norm_dict, Fields.LAST_UPDATED, self.last_update)
		self.set_dict_key(norm_dict, Fields.PROVIDER_IDS, {"imdb": imdb_id})
		crew_list, cast_list = self.get_characters(title_dict)
		self.set_dict_key(norm_dict, Fields.CREW, crew_list)
		self.set_dict_key(norm_dict, Fields.CAST, cast_list)
		if media_type == "series":
			self.set_dict_key(norm_dict, Fields.SEASONS, [])
		return norm_dict

	def get_characters(self, title_dict):
		crew_list, cast_list = [], []
		for group in self._get(title_dict, "principalCredits", []):
			for credit in self._get(group, "credits", []):
				staff_dict = {}
				job = self._get(credit, ("category", "text"))
				name = self._get(credit, ("name", "nameText", "text"))
				profile_id = self._get(credit, ("name", "id"))
				self.set_dict_key(staff_dict, Fields.JOB, job)
				self.set_dict_key(staff_dict, Fields.NAME, name)
				self.set_dict_key(staff_dict, Fields.PROFILE_ID, profile_id)
				if not staff_dict:
					continue
				if job and job.lower() in ("actor", "actress", "star", "stars"):
					cast_list.append(staff_dict)
				else:
					crew_list.append(staff_dict)
		return crew_list, cast_list

	def search_query_graphql(self, search_term, media_type="movie"):
		search_term = dumps(search_term)
		# Use the same broad title type set as the standalone IMDb plugin and
		# filter locally afterwards. This avoids IMDb GraphQL 400 responses when
		# a narrower enum set changes or behaves inconsistently.
		title_types = "[MOVIE, TV, TV_EPISODE]"
		return """
query Search {
  mainSearch(
    first: 25
    options: {
      searchTerm: %s
      type: TITLE
      includeAdult: true
      isExactMatch: false
      titleSearchOptions: {
        type: %s
      }
    }
  ) {
    edges {
      node {
        entity {
          ... on Title {
            id
            titleText { text }
            originalTitleText { text }
            titleType { text }
            releaseYear { year endYear }
            primaryImage { url width height }
            series {
              series {
                id
                titleText { text }
                releaseYear { year }
              }
            }
            plot { plotText { plainText } }
          }
        }
      }
    }
  }
}
""" % (search_term, title_types)

	def storyline_query_graphql(self, title_id):
		title_id = dumps(title_id)
		return """
query TitleStoryline {
  title(id: %s) {
    id
    titleText { text }
    originalTitleText { text }
    titleType { text }
    releaseYear { year endYear }
    releaseDate { day month year country { text } }
    ratingsSummary { aggregateRating voteCount }
    primaryImage { url width height }
    plot { plotText { plainText } }
    genres { genres { id text } }
    countriesOfOrigin { countries { id text } }
    spokenLanguages { spokenLanguages { id text } }
    runtime { seconds }
    certificate { rating ratingReason ratingsBody { id } }
    principalCredits {
      credits(limit: 20) {
        category { text }
        name { id nameText { text } }
      }
    }
    summaries: plots(first: 1, filter: {type: SUMMARY}) {
      edges { node { author plotText { plaidHtml } } }
    }
    outlines: plots(first: 1, filter: {type: OUTLINE}) {
      edges { node { plotText { plaidHtml } } }
    }
    synopses: plots(first: 1, filter: {type: SYNOPSIS}) {
      edges { node { plotText { plaidHtml } } }
    }
    taglines(first: 1) { edges { node { text } } total }
  }
}
""" % title_id

	def minimal_title_query_graphql(self, title_id):
		# Deliberately small fallback. IMDb occasionally rejects optional detail
		# fields on caching.graphql.imdb.com with HTTP 400, while this stable core
		# set remains enough for e2MDB metadata and artwork.
		title_id = dumps(title_id)
		return """
query TitleStorylineMinimal {
  title(id: %s) {
    id
    titleText { text }
    originalTitleText { text }
    titleType { text }
    releaseYear { year endYear }
    releaseDate { day month year }
    ratingsSummary { aggregateRating voteCount }
    primaryImage { url width height }
    plot { plotText { plainText } }
    genres { genres { text } }
    runtime { seconds }
  }
}
""" % title_id

	def get_api_dicts(self, query, timeout=(3.05, 8)):
		headers = self._headers()
		response = None
		try:
			response = post(self.base_url, data=dumps({"query": query}), headers=headers, timeout=timeout)
			try:
				response.raise_for_status()
			except exceptions.HTTPError as err_msg:
				body = ""
				try:
					body = (response.text or "").replace("\n", " ").strip()[:500]
				except Exception:
					body = ""
				return f"{err_msg} | body: {body}" if body else err_msg, {}
			api_dict = response.json() if response.ok else {}
			if api_dict.get("errors"):
				return self._graphql_error(api_dict), {}
			return "", api_dict
		except exceptions.RequestException as err_msg:
			return err_msg, {}
		except ValueError as err_msg:
			return f"Invalid IMDb JSON response: {err_msg}", {}
		finally:
			try:
				if response is not None:
					response.close()
			except Exception:
				pass

	def _cache_search_result(self, imdb_id, norm_dict):
		if not imdb_id or not norm_dict:
			return
		try:
			self._search_result_cache[imdb_id] = norm_dict.copy()
		except Exception:
			pass

	def _cached_result_details(self, imdb_id, expected_media_type=""):
		base = self._search_result_cache.get(imdb_id, {}) if hasattr(self, "_search_result_cache") else {}
		if not base:
			return {}
		details = base.copy()
		for internal_key in ("_search_title", "_search_year", "_expected_media_type", "_strict_media_type", "_provider_priority"):
			details.pop(internal_key, None)
		self.set_dict_key(details, Fields.PROVIDER, "imdb")
		if expected_media_type:
			details[Fields.MEDIA_TYPE] = expected_media_type
		provider_ids = details.get(Fields.PROVIDER_IDS, {}) or {}
		if not isinstance(provider_ids, dict):
			provider_ids = {}
		provider_ids["imdb"] = imdb_id
		details[Fields.PROVIDER_IDS] = provider_ids
		if expected_media_type == "series":
			self.set_dict_key(details, Fields.SERIES_ID, imdb_id)
		elif expected_media_type == "episode":
			self.set_dict_key(details, Fields.EPISODE_ID, imdb_id)
		self.set_dict_key(details, Fields.COVER_SRC, expected_media_type or details.get(Fields.MEDIA_TYPE, ""))
		self.set_dict_key(details, Fields.LAST_UPDATED, self.last_update)
		return details

	def _headers(self):
		# Keep the anonymous IMDb GraphQL request close to the standalone IMDb plugin.
		# Extra web-client headers and locale values such as "de-DE" have caused 400
		# responses on caching.graphql.imdb.com with some schema revisions.
		return {
			"content-type": "application/json",
			"user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
			"X-Imdb-User-Language": self.language,
			"X-Imdb-User-Country": self.country,
		}

	def _normalize_locale(self, language):
		locale = (language or "en-US").replace("_", "-").strip()
		if not locale:
			return "en-US"
		parts = [part for part in locale.split("-") if part]
		lang = parts[0].lower()
		if len(parts) > 1:
			return f"{lang}-{parts[1].upper()}"
		default_locales = {
			"af": "af-ZA", "am": "am-ET", "ar": "ar-SA", "az": "az-AZ", "be": "be-BY",
			"bg": "bg-BG", "bn": "bn-BD", "bs": "bs-BA", "ca": "ca-ES", "co": "co-FR",
			"cs": "cs-CZ", "cy": "cy-GB", "da": "da-DK", "de": "de-DE", "el": "el-GR",
			"en": "en-US", "eo": "eo-001", "es": "es-ES", "et": "et-EE", "eu": "eu-ES",
			"fa": "fa-IR", "fi": "fi-FI", "fr": "fr-FR", "fy": "fy-NL", "ga": "ga-IE",
			"gd": "gd-GB", "gl": "gl-ES", "ha": "ha-NG", "ht": "ht-HT", "hu": "hu-HU",
			"hy": "hy-AM", "ig": "ig-NG", "is": "is-IS", "it": "it-IT", "ja": "ja-JP",
			"jv": "jv-ID", "ka": "ka-GE", "kk": "kk-KZ", "km": "km-KH", "kn": "kn-IN",
			"ko": "ko-KR", "ku": "ku-TR", "ky": "ky-KG", "la": "la-VA", "lb": "lb-LU",
			"lo": "lo-LA", "lt": "lt-LT", "lv": "lv-LV", "mg": "mg-MG", "mi": "mi-NZ",
			"mk": "mk-MK", "mn": "mn-MN", "mr": "mr-IN", "ms": "ms-MY", "mt": "mt-MT",
			"nl": "nl-NL", "no": "nb-NO", "ny": "ny-MW", "or": "or-IN", "pl": "pl-PL",
			"ps": "ps-AF", "pt": "pt-PT", "ro": "ro-RO", "ru": "ru-RU", "rw": "rw-RW",
			"sk": "sk-SK", "sl": "sl-SI", "sm": "sm-WS", "sn": "sn-ZW", "so": "so-SO",
			"sq": "sq-AL", "sr": "sr-RS", "st": "st-ZA", "su": "su-ID", "sv": "sv-SE",
			"sw": "sw-KE", "ta": "ta-IN", "te": "te-IN", "tg": "tg-TJ", "th": "th-TH",
			"tk": "tk-TM", "tl": "tl-PH", "tr": "tr-TR", "ug": "ug-CN", "uk": "uk-UA",
			"ur": "ur-PK", "uz": "uz-UZ", "xh": "xh-ZA", "yi": "yi-001", "yo": "yo-NG",
			"zh": "zh-CN", "zu": "zu-ZA",
		}
		return default_locales.get(lang, "en-US")

	def _graphql_error(self, api_dict):
		errors = api_dict.get("errors", [])
		messages = []
		for error in errors:
			message = error.get("message", "") if isinstance(error, dict) else str(error)
			if message:
				messages.append(message)
		return "; ".join(messages) if messages else "IMDb GraphQL request failed"

	def _media_type_from_title(self, title_dict):
		# The standalone IMDb plugin only requests titleType.text. Keep id optional
		# so provider parsing remains tolerant of IMDb payload changes.
		title_type_id = (self._get(title_dict, ("titleType", "id")) or "").lower()
		title_type_text = (self._get(title_dict, ("titleType", "text")) or "").lower()
		combined = f"{title_type_id} {title_type_text}"
		if "episode" in combined or "folge" in combined:
			return "episode"
		if "tv" in combined or "series" in combined or "serie" in combined or "mini" in combined:
			return "series"
		return "movie"

	def _release_date(self, title_dict):
		release_date = self._get(title_dict, "releaseDate", {})
		year = self._get(release_date, "year") or self._get(title_dict, ("releaseYear", "year"))
		month = self._get(release_date, "month")
		day = self._get(release_date, "day")
		if year and month and day:
			return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
		if year and month:
			return f"{int(year):04d}-{int(month):02d}"
		return str(year) if year else ""

	def _overview(self, title_dict):
		for path in (("plot", "plotText", "plainText"), ("outlines", "edges", "node", "plotText", "plaidHtml"), ("summaries", "edges", "node", "plotText", "plaidHtml"), ("synopses", "edges", "node", "plotText", "plaidHtml")):
			text = self._get(title_dict, path)
			if text:
				return self.html_to_text(text)
		return ""

	def _runtime_minutes(self, title_dict):
		seconds = self._get(title_dict, ("runtime", "seconds"), 0)
		try:
			seconds = int(seconds)
		except Exception:
			seconds = 0
		return str(seconds // 60) if seconds else ""

	def _rating(self, title_dict):
		rating = self._get(title_dict, ("ratingsSummary", "aggregateRating"))
		try:
			return str(round(float(rating), 1)) if rating else ""
		except Exception:
			return str(rating) if rating else ""

	def _valid_imdb_id(self, imdb_id):
		return bool(imdb_id and isinstance(imdb_id, str) and imdb_id.startswith("tt") and imdb_id[2:].isdigit())

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

	def set_dict_key(self, dictionary, key, value):
		if value and value != "N/A":
			dictionary[key] = value


provider_imdb = ProviderIMDB()


def main(argv):
	title, language, media_type, title_id = "the+blacklist", "en-US", "series", ""
	helpstring = "IMDB v0.1: try 'python IMDB.py -h' for more information"
	try:
		opts, args = getopt(argv, "q:l:m:i:h", ["query=", "language=", "mediatype=", "id=", "help"])
	except GetoptError as error:
		write_log(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			write_log("Usage 'IMDB v0.1': python IMDB.py [option...] <data>\n"
			"Example: python IMDB.py -q the+blacklist -l de-DE -m series\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language formatted like 'en-US'\n"
			"-m, --mediatype <options>\tset media type 'movie', 'series' or 'episode'\n"
			"-i, --id <options>\t\tget title details for an IMDb ID")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			media_type = arg
		elif opt in ("-i", "--id"):
			title_id = arg
	provider_imdb.start("", language)
	if title_id:
		err_msg, details = provider_imdb.get_movie_details(title_id) if media_type == "movie" else provider_imdb.get_series_details_index(title_id)[:2]
		if err_msg:
			write_log(err_msg)
		else:
			with open("imdb_details.json", "w") as file:
				dump(details, file)
			write_log("IMDb details JSON file 'imdb_details.json' was successfully created.")
	else:
		err_msg, norm_dicts = provider_imdb.get_result_dicts(title, media_type=media_type)
		if err_msg:
			write_log(err_msg)
		else:
			with open("imdb_dicts.json", "w") as file:
				dump(norm_dicts, file)
			write_log("IMDb normalized JSON file 'imdb_dicts.json' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
