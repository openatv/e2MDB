########################################################################################################
# TVDBparser by Mr.Servo @OpenATV (c) 2025                                                             #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from json import dump
from getopt import getopt, GetoptError
from os import remove
from os.path import isfile
from requests import get, post, exceptions
from sys import exit, argv

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class Provider_tvdb:
	def __init__(self):
		self.baseUrl = "https://api4.thetvdb.com/v4"
		self.mediaTypes = ["movie", "series"]  # # exclude from search: 'person', 'company'
		self.apiKey = bytes.fromhex("66616633353133312D613531632D343636632D626264612D343566623665393135366535A"[:-1]).decode()
		self.langCode, self.token = "", ""

	def getName(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def isActive(self):
		return True

	def start(self, language="en-US", apikey=None):
		self.apiKey = apikey or self.apiKey
		self.language = language
		langMap = {
			"aa-ER": "aar", "af-NA": "afr", "af-ZA": "afr", "am-ET": "amh", "ar-EG": "ara", "ar-DZ": "ara", "ar-BH": "ara",
			"ar-DJ": "ara", "ar-ER": "ara", "ar-IQ": "ara", "ar-IL": "ara", "ar-YE": "ara", "ar-JO": "ara", "ar-QA": "ara",
			"ar-KM": "ara", "ar-KW": "ara", "ar-LB": "ara", "ar-LY": "ara", "ar-MA": "ara", "ar-MR": "ara", "ar-OM": "ara",
			"ar-PS": "ara", "ar-SA": "ara", "ar-SO": "ara", "ar-SD": "ara", "ar-SY": "ara", "ar-TD": "ara", "ar-TN": "ara",
			"ar-AE": "ara", "ay-BO": "aym", "az-AZ": "aze", "be-BY": "bel", "bn-BD": "ben", "bi-VU": "bis", "bs-BA": "bos",
			"bs-ME": "bos", "bg-BG": "bul", "byn-ER": "byn", "ca-AD": "cat", "cs-CZ": "ces", "ch-GU": "cha", "ch-MP": "cha",
			"da-DK": "dan", "de-BE": "deu", "de-DE": "deu", "de-LI": "deu", "de-LU": "deu", "de-AT": "deu", "de-CH": "deu",
			"de-VA": "deu", "dv-MV": "div", "dz-BT": "dzo", "el-GR": "ell", "el-CY": "ell", "en-AS": "eng", "en-AI": "eng",
			"en-AQ": "eng", "en-AG": "eng", "en-AU": "eng", "en-BS": "eng", "en-BB": "eng", "en-BZ": "eng", "en-BM": "eng",
			"en-BW": "eng", "en-IO": "eng", "en-CK": "eng", "en-CW": "eng", "en-DM": "eng", "en-ER": "eng", "en-SZ": "eng",
			"en-FK": "eng", "en-FJ": "eng", "en-FM": "eng", "en-GM": "eng", "en-GH": "eng", "en-GI": "eng", "en-GD": "eng",
			"en-GU": "eng", "en-GG": "eng", "en-GY": "eng", "en-HM": "eng", "en-HK": "eng", "en-IN": "eng", "en-IM": "eng",
			"en-IE": "eng", "en-JM": "eng", "en-JE": "eng", "en-VG": "eng", "en-VI": "eng", "en-KY": "eng", "en-CM": "eng",
			"en-CA": "eng", "en-KE": "eng", "en-KI": "eng", "en-UM": "eng", "en-CC": "eng", "en-LS": "eng", "en-LR": "eng",
			"en-MW": "eng", "en-MT": "eng", "en-MH": "eng", "en-MU": "eng", "en-MS": "eng", "en-NA": "eng", "en-NR": "eng",
			"en-NZ": "eng", "en-NG": "eng", "en-NU": "eng", "en-MP": "eng", "en-NF": "eng", "en-PK": "eng", "en-PW": "eng",
			"en-PG": "eng", "en-PH": "eng", "en-PN": "eng", "en-PR": "eng", "en-RW": "eng", "en-MF": "eng", "en-SB": "eng",
			"en-ZM": "eng", "en-WS": "eng", "en-SC": "eng", "en-SL": "eng", "en-ZW": "eng", "en-SG": "eng", "en-SX": "eng",
			"en-SH": "eng", "en-KN": "eng", "en-LC": "eng", "en-VC": "eng", "en-ZA": "eng", "en-SD": "eng", "en-GS": "eng",
			"en-SS": "eng", "en-TZ": "eng", "en-TK": "eng", "en-TO": "eng", "en-TT": "eng", "en-TC": "eng", "en-TV": "eng",
			"en-UG": "eng", "en-VU": "eng", "en-US": "eng", "en-GB": "eng", "en-CX": "eng", "et-EE": "est", "fan-GQ": "fan",
			"fo-FO": "fao", "fa-IR": "fas", "fj-FJ": "fij", "fi-FI": "fin", "fr-GQ": "fra", "fr-BE": "fra", "fr-BJ": "fra",
			"fr-BF": "fra", "fr-BI": "fra", "fr-CD": "fra", "fr-DJ": "fra", "fr-CI": "fra", "fr-FR": "fra", "fr-GF": "fra",
			"fr-PF": "fra", "fr-TF": "fra", "fr-MC": "fra", "fr-GA": "fra", "fr-GP": "fra", "fr-GG": "fra", "fr-GN": "fra",
			"fr-HT": "fra", "fr-JE": "fra", "fr-CM": "fra", "fr-CA": "fra", "fr-KM": "fra", "fr-LB": "fra", "fr-LU": "fra",
			"fr-MG": "fra", "fr-ML": "fra", "fr-MQ": "fra", "fr-YT": "fra", "fr-NC": "fra", "fr-NE": "fra", "fr-CG": "fra",
			"fr-RE": "fra", "fr-RW": "fra", "fr-MF": "fra", "fr-BL": "fra", "fr-CH": "fra", "fr-SN": "fra", "fr-SC": "fra",
			"fr-PM": "fra", "fr-TG": "fra", "fr-TD": "fra", "fr-VU": "fra", "fr-VA": "fra", "fr-WF": "fra", "fr-CF": "fra",
			"ff-BF": "ful", "ff-GN": "ful", "ga-IE": "gle", "gv-IM": "glv", "gn-AR": "grn", "gn-PY": "grn", "ht-HT": "hat",
			"he-IL": "heb", "hif-FJ": "hif", "hi-IN": "hin", "hr-BA": "hrv", "hr-HR": "hrv", "hr-ME": "hrv", "hu-HU": "hun",
			"hy-AM": "hye", "hy-CY": "hye", "id-ID": "ind", "is-IS": "isl", "it-IT": "ita", "it-SM": "ita", "it-CH": "ita",
			"it-VA": "ita", "ja-JP": "jpn", "kl-GL": "kal", "ka-GE": "kat", "kk-KZ": "kaz", "km-KH": "khm", "rw-RW": "kin",
			"ky-KG": "kir", "kg-CD": "kon", "ko-KP": "kor", "ko-KR": "kor", "kun-ER": "kun", "ku-IQ": "kur", "lo-LA": "lao",
			"la-VA": "lat", "lv-LV": "lav", "ln-CD": "lin", "ln-CG": "lin", "lt-LT": "lit", "lb-LU": "ltz", "lu-CD": "lub",
			"mh-MH": "mah", "mk-MK": "mkd", "mg-MG": "mlg", "mt-MT": "mlt", "mn-MN": "mon", "mi-NZ": "mri", "ms-BN": "msa",
			"ms-SG": "msa", "my-MM": "mya", "na-NR": "nau", "nr-ZA": "nbl", "nd-ZW": "nde", "ne-NP": "nep", "nl-AW": "nld",
			"nl-BE": "nld", "nl-CW": "nld", "nl-BQ": "nld", "nl-NL": "nld", "nl-MF": "nld", "nl-SX": "nld", "nl-SR": "nld",
			"nn-BV": "nno", "nn-NO": "nno", "nb-BV": "nob", "nb-NO": "nob", "no-BV": "nor", "no-NO": "nor", "no-SJ": "nor",
			"nrb-ER": "nrb", "ny-MW": "nya", "pa-AW": "pan", "pa-CW": "pan", "pl-PL": "pol", "pt-AO": "por", "pt-GQ": "por",
			"pt-BR": "por", "pt-GW": "por", "pt-CV": "por", "pt-MO": "por", "pt-MZ": "por", "pt-TL": "por", "pt-PT": "por",
			"pt-ST": "por", "ps-AF": "pus", "qu-BO": "que", "rar-CK": "rar", "rm-CH": "roh", "ro-MD": "ron", "ro-RO": "ron",
			"rtm-FJ": "rtm", "rn-BI": "run", "ru-AQ": "rus", "ru-BY": "rus", "ru-KZ": "rus", "ru-KG": "rus", "ru-RU": "rus",
			"ru-TJ": "rus", "ru-TM": "rus", "ru-UZ": "rus", "sg-CF": "sag", "si-LK": "sin", "sk-SK": "slk", "sk-CZ": "slk",
			"sl-SI": "slv", "sm-AS": "smo", "sm-WS": "smo", "sn-ZW": "sna", "so-SO": "som", "st-LS": "sot", "st-ZA": "sot",
			"es-GQ": "spa", "es-AR": "spa", "es-BZ": "spa", "es-BO": "spa", "es-CL": "spa", "es-CR": "spa", "es-DO": "spa",
			"es-EC": "spa", "es-SV": "spa", "es-GU": "spa", "es-GT": "spa", "es-HN": "spa", "es-CO": "spa", "es-CU": "spa",
			"es-MX": "spa", "es-NI": "spa", "es-PA": "spa", "es-PY": "spa", "es-PE": "spa", "es-PR": "spa", "es-ES": "spa",
			"es-UY": "spa", "es-VE": "spa", "es-EH": "spa", "sq-AL": "sqi", "sq-XK": "sqi", "sq-ME": "sqi", "sr-BA": "srp",
			"sr-XK": "srp", "sr-ME": "srp", "sr-RS": "srp", "ss-SZ": "ssw", "ss-ZA": "ssw", "ssy-ER": "ssy", "sw-CD": "swa",
			"sw-KE": "swa", "sw-TZ": "swa", "sw-UG": "swa", "sv-AX": "swe", "sv-FI": "swe", "sv-SE": "swe", "ta-SG": "tam",
			"ta-LK": "tam", "tg-TJ": "tgk", "th-TH": "tha", "tig-ER": "tig", "ti-ER": "tir", "to-TO": "ton", "tn-BW": "tsn",
			"tn-ZA": "tsn", "ts-ZA": "tso", "tk-AF": "tuk", "tk-TM": "tuk", "tr-TR": "tur", "tr-CY": "tur", "uk-UA": "ukr",
			"ur-PK": "urd", "uz-AF": "uzb", "uz-UZ": "uzb", "ve-ZA": "ven", "vi-VN": "vie", "xh-ZA": "xho", "zh-CN": "zho",
			"zh-HK": "zho", "zh-MO": "zho", "zh-SG": "zho", "zh-TW": "zho", "ms-MY": "msa", "zu-ZA": "zul"
		}  # 'localeCode' to 'ISO 639-2', source: 'https://simplelocalize.io/data/locales/', special TVDB-deal: "zh-TW" is not "zho"

		if not self.token:
			errMsg, self.token = self.getToken()
			if errMsg:
				return errMsg
		langCode = langMap.get(language, "")  # e.g. 'deu' in case of 'de-DE'
		errMsg, languages = self.getLanguages()
		if not errMsg:
			codes = [code.get("id", "") for code in languages if langCode == code.get("id", "")]
			if codes:
				self.langCode = codes[0]
			else:
				self.langCode = "eng"
				print(f"{MODULE_NAME}INFO in module 'start': language '{language}' is not supported. Continue with English language...")
		else:
			self.langCode = "eng"
			print(f"{MODULE_NAME}INFO in module 'start': Language table could not be downloaded, continue with English language....")
		return errMsg

	def getInfo(self, title, mediaType="series", year=None):
		if mediaType not in self.mediaTypes:
			return f"ERROR in module 'getInfo': unknown search_mode '{mediaType}'. Supported is '{', '.join(self.mediaTypes)}'", {}
		url = f"{self.baseUrl}/search"
		params = {
			"query": title,
			"type": mediaType,
			"year": year,
			"language": self.langCode,
			"limit": 10,
			"page": 0
		}
		return self.getApiDict(url, params=params)

	def createNormalized(self, tvdbDicts, includeLogos=True, entriesmax=0):  # 'includeLogos' for compatibility reasons
		def setNormKey(key, value):
			if value:
				normDict[key] = value

		normDict, normList = {}, []
		results = tvdbDicts.get("data", [])[:entriesmax] if entriesmax else tvdbDicts.get("data", [])
		if results:
			for result in results:  # There are other series with similar titles, but they are being stalled here by [:entriesmax]
				try:
					normDict = {}
					language = self.language  # e.g. 'de-DE'
					translations = result.get("translations", {})
					title = translations.get(self.langCode, "")
					if not title:  # fallback to English translation
						language = "en-US"
						title = translations.get("eng", "")
						if not title:  # fallback to last chance
							title = result.get("name", "")
					if title:
						titleDict = {}
						titleDict["language"] = language
						titleDict["text"] = title  # e.g. 'Titanic'
						setNormKey("title", titleDict)
					setNormKey("countries", "/".join([x[:2].upper() for x in result.get("country", "").split(", ")]))
					setNormKey("released", result.get("first_air_time", ""))  # e.g. '1970-11-29'
					setNormKey("mediaType", result.get("primary_type", "") or result.get("type", ""))  # STR, e.g. 'movie'
					overviews = result.get("overviews", {})
					overview, language = overviews.get(self.langCode, ""), language
					if not overview:  # fallback to English translation
						overview, language = overviews.get("eng", ""), "en-US"
						if not overview:  # fallback to last chance
							overview = result.get("overview", "")
					if overview:
						descDict = {}
						descDict["language"] = language
						descDict["text"] = result.get("overviews", {}).get(self.langCode, "") or overview
						setNormKey("description", descDict)
					posterUrl = result.get("image_url", "")  # e.g. 'https://artworks.thetvdb.com/banners/v4/movie/231/posters/642d748b22859.jpg'
					if "/missing/" not in posterUrl:  # ignore stupid image for missing movie / tv
						setNormKey("coverUrl", posterUrl)
					providerIds = {}
					providerIds["tvdb"] = result.get("tvdb_id", 0)  # e.g. '231'
					for remoteIds in result.get("remote_ids", []):
						sourceName = remoteIds.get("sourceName", "").replace("TheMovieDB.com", "tmdb").lower()
						if sourceName in ["imdb", "tmdb"]:
							remoteId = remoteIds.get("id", "")
							if remoteId:
								providerIds[sourceName] = remoteIds.get("id", "")
					normDict["providerIds"] = providerIds
					normList.append(normDict)
				except Exception as errMsg:
					print(f"{MODULE_NAME}ERROR in module 'createNormalized': {errMsg}'")
			normDict["tvdb"] = normList
		return normDict

	def getToken(self):
		errMsg, authDict = "", {}
		url = f"{self.baseUrl}/login"
		headers = {"accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
		json = {"apiKey": self.apiKey, "pin": ""}
		try:
			response = post(url, json=json, headers=headers, timeout=(3.05, 6))
			response.raise_for_status()
			errMsg, authDict = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			del response
			if errMsg:
				return errMsg, {}
		except exceptions.RequestException as errMsg:
			print(f"{MODULE_NAME}ERROR in module 'getToken': {errMsg}")
			return errMsg, {}
		return ("", authDict.get("data", {}).get("token", "")) if authDict.get("status", "") == "success" else ("{unknown error}", "")

	def getLanguages(self):
		url = f"{self.baseUrl}/languages"
		errMsg, languageDict = self.getApiDict(url)
		if errMsg:
			print(f"{MODULE_NAME}ERROR in module 'getLanguages': {errMsg}")
		return errMsg, languageDict.get("data", [])

	def readSeriesIndex(self, seriesFile):
		try:
			with open(seriesFile, "r") as file:
				seriesIndex = file.read()
		except OSError as errMsg:
			return errMsg, ""
		return "", seriesIndex

	def writeSeriesIndex(self, seriesFile, seriesIndex):
		if seriesIndex:
			try:
				with open(seriesFile, "w") as file:
					file.write(seriesIndex)
			except OSError as errMsg:
				return errMsg
		return ""

	def getSeriesIndex(self, seriesId):  # create 'seriesIndex' containing 'season-episode', 'episodeID and 'episodeName'
		errMsg, seriesIndex = "", ""
		url = f"{self.baseUrl}/series/{seriesId}/episodes/default/{self.langCode}"
		params = {"page": 0}
		errMsg, episodesDict = self.getApiDict(url, params=params)  # get first page of all seasons
		if not errMsg:
			data = episodesDict.get("data", {})
			seriesIndex = f"{str({'source': 'tvdb', 'seriesId': str(data.get('id', '')), 'seriesName': data.get('name', '')})}\n"
			while not errMsg:
				url = episodesDict.get("links", {}).get("next", "")  # get url for next page
				data = episodesDict.get("data", {})
				for episode in data.get("episodes", []):
					seasonNumber = episode.get("seasonNumber", "")
					if seasonNumber:  # seasonNumber '0' only contains accompanying information for the series
						name = episode.get("name", "").split(" - ")
						name = name[2] if len(name) > 2 else name[0]  # might be 'Odenthal - 15 - Mordfieber', so reduce to 'Mordfieber'
						seriesIndex += f"{seasonNumber}-{episode.get('number', '')}\t{episode.get("id", '')}\t{name}\n"
				if url:
					errMsg, episodesDict = self.getApiDict(url, params=params)  # get first page of all seasons
				else:
					break
		return errMsg, seriesIndex

	def findSeasonEpisode(self, seriesIndex="", episodeDescs=[]):
		seasonEpisode, hitIndex = [], -1
		if seriesIndex:
			seriesIndex = "\n".join(seriesIndex.split("\n")[1:])  # remove first line
			for desc in episodeDescs:
				if desc:
					hitIndex = seriesIndex.lower().find(desc.lower())
					if hitIndex != -1:
						break
		if hitIndex != -1:
			partialStr = seriesIndex[seriesIndex[:hitIndex].rfind("\n") + 1:]  # cut off entries before hitIndex excluding preceding LF
			seasonEpisode = partialStr[:partialStr.find("\n")].split("\t")  # cut off entries inclusive following LF and create list
		return seasonEpisode

	def getEpisodeDetails(self, seriesId=None, seasonEpisode=[]):  # TVDB only need episodeId
		errMsg, episodeDict = "", {}
		if seasonEpisode and len(seasonEpisode) > 1:
			episodeId = seasonEpisode[1]
			if episodeId:
				url = f"{self.baseUrl}/episodes/{episodeId}/translations/{self.langCode}"
				params = {"page": 0}
				errMsg, tvdbDict = self.getApiDict(url, params=params)
				episodeDict = self.createNormEpisodeDict(tvdbDict, episodeId)
				if not errMsg:
					with open("tvdbDetails.json", "w") as file:
						dump(tvdbDict, file)
		else:
			errMsg, tvdbDict = f"{MODULE_NAME}ERROR in module 'TVDB.getEpisodeDetails': missing parameter 'episodeId'.", {}
		return errMsg, episodeDict

	def createNormEpisodeDict(self, episodeDict, episodeId=""):
		def setNormKey(key, value):
			if value:
				normDict[key] = value

		normDict = {}
		if episodeDict:
			setNormKey("source", "tvdb")
			setNormKey("episodeId", episodeId)
			data = episodeDict.get("data", {})
			name = data.get("name", "").split(" - ")
			setNormKey("name", name[2] if len(name) > 2 else name[0])  # might be 'Odenthal - 15 - Mordfieber', so reduce to 'Mordfieber'
			setNormKey("overview", data.get("overview", ""))  # longtext
		return normDict

	def getApiDict(self, url, params=None, timeout=(3.05, 6)):
		headers = {"accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			errMsg, tvdbDicts = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			return errMsg, tvdbDicts
		except exceptions.RequestException as errMsg:
			return errMsg, {}


provider_tvdb = Provider_tvdb()


def main(argv):  # shell interface
	normFile, tvdbFile, seriesFile, title, language, mediaType, seriesId = "", "", "", "", "en-US", "", ""
	normDict, tvdbDicts = {}, {}
	entriesmax = 0
	helpstring = "TVDBparser v0.1: try 'python TVDBparser.py -h' for more information"
	try:
		opts, args = getopt(argv, "o:n:s:q:l:e:m:h", ["original=", "normalized=", "seriesindex", "query=", "language=", "entriesmax=", "mediatype"])
	except GetoptError as error:
		print(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			print("Usage 'TVDBparser v0.1': python TVDBparser.py [option...] <data>\n"
			"Example: python TVDBparser.py -q Titanic -o original.json -n normalized.json\n"
			"-q, --query <options>\tget result list from TVDB search'\n"
			"-l, --language <options>\tset language formatted like 'en-US'\n"
			"-e, --entriesmax <options>\tset maximum number of entries (defaut is 0=all)\n"
			"-m, --mediatype <options>\tset media type 'movie' or 'series' (default 'series')\n"
			"-o, --original <filename>\tfile output of original formatted in JSON\n"
			"-n, --normalized <filename>\tnormalized file output formatted in JSON\n",
			"-s, --seriesindex <filename>\tfile output of all seasons and episodes of a series, formatted in JSON\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-o", "--original"):
			tvdbFile = arg
		elif opt in ("-n", "--normalized"):
			normFile = arg
		elif opt in ("-s", "--seriesindex"):
			seriesFile = arg
		elif opt in ("-l", "--language"):
			language = arg
		elif opt in ("-e", "--entriesmax"):
			entriesmax = int(arg) if arg.isdigit() else 0
		elif opt in ("-m", "--mediatype"):
			mediaType = arg
	if title and language:
		if not mediaType:
			mediaType = "series"  # set fallback
		print(f"Search for '{title.replace("+", " ")}', mediaType: '{mediaType}'")
		provider_tvdb.start(language)
		errMsg, tvdbDicts = provider_tvdb.getInfo(title, mediaType=mediaType, year=None)
		if errMsg:
			print("ERROR getting data:", errMsg)
			exit(2)
		if tvdbDicts:
			if tvdbFile:
				with open(tvdbFile, "w") as file:
					dump(tvdbDicts, file)
				print(f"Original JSON file '{tvdbFile}' was successfully created.")
			normDict = provider_tvdb.createNormalized(tvdbDicts, entriesmax=entriesmax)
		if normDict and normFile:
			with open(normFile, "w") as file:
				dump(normDict, file)
			print(f"Normalized JSON file '{normFile}' was successfully created.")
		if seriesFile and tvdbDicts:
			result = tvdbDicts.get("data", [])[:1]
			if result:
				result = result[0]  # get first result only
				seriesId = result.get("id", "").replace("series-", "")  # e.g. '597' after removing prefix 'series-'
				mediaType = result.get("primary_type", "")  # e.g. 'movie' or 'series'
				if seriesId and mediaType == "series":
					if isfile(seriesFile):
						errMsg, seriesIndex = provider_tvdb.readSeriesIndex(seriesFile)
						if errMsg:
							remove(seriesFile)
						else:
							print(f"Series index file '{seriesFile}' was successfully loaded from cache.")
					else:
						print("Download series info index...")
						errMsg, seriesIndex = provider_tvdb.getSeriesIndex(seriesId)
						if errMsg:
							print(f"Error creating seriesindex: {errMsg}")
						elif seriesIndex:
							errMsg = provider_tvdb.writeSeriesIndex(seriesFile, seriesIndex)
							if errMsg:
								print(f"Error writing series index file '{seriesFile}': {errMsg}")
							else:
								print(f"Series index file '{seriesFile}' was successfully created.")
					print(provider_tvdb.findSeasonEpisode(seriesIndex, "Emily hat Geldprobleme"))  # special episode search for series
			"""
				errMsg, episodeDict = provider_tvdb.getEpisodeDetails(episodeId="10298220")
				if episodeDict:
					with open("detailsTVDB.json", "w") as file:
						dump(episodeDict, file)
			"""
	else:
		errMsg = "'Title' or 'language' is missing"
		print("ERROR getting data:", errMsg)


if __name__ == "__main__":
	main(argv[1:])
