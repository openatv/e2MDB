########################################################################################################
# TMDBparser by Mr.Servo @OpenATV (c) 2025                                                             #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

from json import dump
from os import remove
from os.path import isfile
from getopt import getopt, GetoptError
from requests import get, exceptions
from sys import exit, argv

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class Provider_tmdb:
	def __init__(self):
		# HINT: API V4 requires a monthly changing bearer token that cannot be generated automatically using apikey
		self.baseUrl = "https://api.themoviedb.org/3"  # using API V3
		self.imgUrl = "https://image.tmdb.org/t/p/original"  # reduced size 500 'https://image.tmdb.org/t/p/w500'
		self.mediaTypes = ["multi", "movie", "series"]  # exclude from search: 'collection', 'company', 'keyword', 'person'
		self.apiKey = bytes.fromhex("64343265366238323061313534316363363963653738393637316665626133393"[:-1]).decode()
		self.language = ""

	def getName(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def isActive(self):
		return True

	def start(self, language="en_US", apiKey=None):
		self.apiKey = apiKey or self.apiKey
		self.language = language
		allGenres = {}
		allGenres["movie"] = self.getGenreList("movie")
		allGenres["series"] = self.getGenreList("series")
		self.allGenres = allGenres
		return ""

	def getImagesDict(self, tmdbId):
		url = f"https://api.themoviedb.org/3/movie/{tmdbId}/images"
		params = {
					"api_key": self.apiKey,
					"include_image_language": "en-US,null",  # additional languages
					"language": self.language,  # acc. ISO 3166-1 alpha-2
				}
		errMsg, imagesDict = self.getApiDict(url, params=params)
		if imagesDict:
			for imageType in ["backdrops", "logos", "posters"]:
				for imageDict in imagesDict.get(imageType, []):
					filePath = imageDict.get("file_path", "")
					if filePath:
						imageDict["url"] = f"{provider_tmdb.imgUrl}{filePath}"
						imageDict.pop("file_path")
		return errMsg, imagesDict

	def getInfo(self, title, mediaType="multi", year=None):
		if mediaType not in self.mediaTypes:  # exclude from results: 'collection', 'company', 'keyword', 'person'
			return f"ERROR in module 'getInfo': unknown search_mode '{mediaType}'. Supported is '{', '.join(self.mediaTypes)}'", {}
		url = f"{self.baseUrl}/search/{mediaType.replace("series", "tv")}"  # e.g. 'movie' or 'series', TMDB uses 'tv' instead of 'series'
		params = {
					"query": title,
					"primary_release_year": year,
					"api_key": self.apiKey,
					"include_adult": True,
					"language": self.language,  # acc. ISO 3166-1 alpha-2
					"page": 1,
					"append_to_response": "videos,images",
					"accept": "application/json"
				}
		errMsg, tmdbDicts = self.getApiDict(url, params=params)
		newDicts, newList = {}, []
		if not errMsg:
			for result in tmdbDicts.get("results", []):   # fill up search parameter 'media_type' in case it is missing
				if not result.get("media_type", "").replace("tv", "series"):  # e.g. 'movie' or 'series', TMDB uses 'tv' instead of 'series'
					result.update({"media_type": mediaType})
				newList.append(result)
		newDicts["results"] = newList
		return errMsg, newDicts

	def createNormalized(self, tmdbDicts, entriesmax=0):
		def setNormKey(key, value):
			if value:
				normDict[key] = value

		normDicts, normList = {}, []
		results = tmdbDicts.get("results", [])[:entriesmax] if entriesmax else tmdbDicts.get("results", [])
		if results:
			for result in results:  # There are other series with similar titles, but they are being limited here by [:maxentries]
				try:
					mediaType = result.get("media_type", "")
					normDict = {}
					titleDict = {}
					title = result.get("title", "") or result.get("name", "")  # 'multi' & 'movie' uses 'title', 'tv' uses 'name'
					if title:
						language = self.language
					else:
						title = result.get("original_title", "") or result.get("original_name", "")  # 'multi' & 'movie' uses 'title', 'tv' uses 'name'
						language = result.get("original_language", "")
						if not language:
							language = "en-US"  # fallback
					titleDict["language"] = language
					titleDict["text"] = title  # e.g. 'Titanic'
					setNormKey("title", titleDict)
					countries = "/".join(result.get("origin_country", []) or [result.get("original_language", "")])
					setNormKey("countries", [country.upper() for country in countries.split(", ")][0])
					setNormKey("released", result.get("first_air_date", 0))  # e.g. '1970-11-29'
					setNormKey("mediaType", mediaType.replace("tv", "series"))  # TMDB uses 'tv' instead of 'series'
					genres = []
					for genreId in result.get("genre_ids", []):  # [28, 18]
						for genre in self.allGenres.get(mediaType, []):  # {'movie': [(28, 'Action'), (12, 'Abenteuer'), (16, 'Animation'), (18, 'Drama'),...}
							if genreId == genre[0]:
								genres.append(genre[1])
					setNormKey("genres", ", ".join(genres if genres else []))
					description = {}
					description["language"] = self.language
					overview = result.get("overview", "")  # longtext
					if overview:
						description["text"] = overview
						normDict["description"] = description
					voteAverage = round(result.get("vote_average", 0), 1)  # e.g. '7.9'
					setNormKey("voteAverage", str(voteAverage) if voteAverage else "")
					setNormKey("voteCount", str(result.get("vote_count", 0)))  # e.g. '26151'
					poster = result.get("poster_path", "")  # e.g. '/MlnPG3oxhfmuiDwcoeElQWui9m.jpg'
					setNormKey("coverUrl", f"{self.imgUrl}{poster}" if poster else "")
					backdrop = result.get("backdrop_path", "")  # e.g. '/sCzcYW9h55WcesOqA12cgEr9Exw.jpg'
					setNormKey("backdropUrl", f"{self.imgUrl}{backdrop}" if backdrop else "")
					tmdbId = str(result.get("id", 0))  # e.g. '597'
					errMsg, imagesDict = self.getImagesDict(tmdbId)
					if not errMsg:
						logoUrl, fallback = "", ""
						for logoDict in imagesDict.get("logos", []):
							if not fallback:
								fallback = logoDict.get("url", "")
							if logoDict.get("iso_639_1", "") == self.language[:2]:
								logoUrl = logoDict.get("url", "")
								break
						setNormKey("logoUrl", logoUrl if logoUrl else fallback)
					providerIds = {}
					providerIds["tmdb"] = tmdbId
					setNormKey("providerIds", providerIds)
					normList.append(normDict)
				except Exception as errMsg:
					print(f"{MODULE_NAME}ERROR in module 'createNormalized': {errMsg}'")
			normDicts["tmdb"] = normList
		return normDicts

	def getGenreList(self, mediaType):
		if mediaType not in self.mediaTypes:  # exclude 'people', 'all'
			print(f"{MODULE_NAME}ERROR in module 'getGenreList': unknown mediaType '{mediaType}'. Supported is '{', '.join(self.mediaTypes)}'")
			return []
		url = f"{self.baseUrl}/genre/{mediaType.replace("series", "tv")}/list"  # TMDB uses 'tv' instead of 'series'
		params = {
				"language": self.language,
				"api_key": self.apiKey
				}
		errMsg, genreDict = self.getApiDict(url, params=params)
		genreList = [(entry.get("id", 0), entry.get("name", "")) for entry in genreDict.get("genres", [])]
		if errMsg:
			print(f"{MODULE_NAME}ERROR in module 'getGenreList': {errMsg}")
		return genreList

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
		url = f"{self.baseUrl}/tv/{seriesId}"
		params = {"language": self.language, "api_key": self.apiKey}
		errMsg, seasonDict = self.getApiDict(url, params=params)  # get all seasons
		if not errMsg:
			seriesIndex = f"{str({'source': 'tmdb', 'seriesId': str(seasonDict.get('id', '')), 'seriesName': seasonDict.get('name', '')})}\n"
			for season in seasonDict.get("seasons", []):
				seasonNumber = season.get("season_number", "")
				if seasonNumber:  # seasonNumber '0' only contains accompanying information for the series
					url = f"{self.baseUrl}/tv/{seriesId}/season/{seasonNumber}"  # get all episodes
					errMsg, episodesDict = self.getApiDict(url, params=params)
					if not errMsg:
						for episode in episodesDict.get("episodes", []):
							seriesIndex += f"{seasonNumber}-{episode.get('episode_number', '')}\t{episode.get("id", '')}\t{episode.get("name", '')}\n"
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
		return seasonEpisode  # e.g. ['1-2', '283766', 'Die Warnung']

	def getEpisodeDetails(self, seriesId=None, seasonEpisode=[]):  # TMDB needs seriesId, seasonNo and episodeNo
		errMsg, episodeDict = "", {}
		if seriesId and seasonEpisode and "-" in seasonEpisode[0]:
			seasonNo, episodeNo = seasonEpisode[0].split("-")
			if seriesId and seasonNo and episodeNo:
				url = f"{self.baseUrl}/tv/{seriesId}/season/{seasonNo}/episode/{episodeNo}"
				params = {"language": self.language, "api_key": self.apiKey}
				errMsg, tmdbDict = self.getApiDict(url, params=params)
				if errMsg:
					print(f"{MODULE_NAME}ERROR in module 'getEpisodeDetails': {errMsg}")
				return errMsg, self.createNormEpisodeDict(tmdbDict)
		else:
			errMsg, episodeDict = f"{MODULE_NAME}ERROR in module 'TMDB.getEpisodeDetails': missing parameters 'seriesId' and/or 'seasonEpisode.", {}
		return errMsg, episodeDict

	def createNormEpisodeDict(self, episodeDict):  # creates episode details in a normalized form
		def setNormKey(key, value):
			if value:
				normDict[key] = value

		normDict = {}
		if episodeDict:
			setNormKey("source", "tmdb")
			setNormKey("episodeId", episodeDict.get("id", ""))
			setNormKey("name", episodeDict.get("name", ""))
			setNormKey("overview", episodeDict.get("overview", ""))  # longtext
			setNormKey("seasonNumber", episodeDict.get("season_number", ""))
			setNormKey("episodeNumber", episodeDict.get("episode_number", ""))
			setNormKey("released", episodeDict.get("air_date", ""))
			image = episodeDict.get("still_path", "")
			setNormKey("image", f"{self.imgUrl}{image}" if image else "")  # e.g. '/eZgBiSDTc25mEjMoyRKZTa2ggbm.jpg'
			setNormKey("crew", episodeDict.get("crew", ""))  # is TMDB original dict
			setNormKey("guestStars", episodeDict.get("guest_stars", ""))  # is TMDB original dict
		return normDict

	def getApiDict(self, url, params=None, timeout=(3.05, 6)):
		headers = {"accept": "application/json"}
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			errMsg, tmdbDicts = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			return errMsg, tmdbDicts
		except exceptions.RequestException as errMsg:
			return errMsg, {}


provider_tmdb = Provider_tmdb()


def main(argv):  # shell interface
	normFile, tmdbFile, seriesFile, imagesFile, title, language, mediaType, seriesId = "", "", "", "", "Titanic", "en-US", "", ""
	normDict, tmdbDicts = {}, {}
	entriesmax = 0
	helpstring = "TMDBparser v0.1: try 'python TMDBparser.py -h' for more information"
	try:
		opts, args = getopt(argv, "o:n:s:i:q:l:e:m:h", ["original=", "normalized=", "seriesindex", "images=", "query=", "language=", "entriesmax=", "mediatype"])
	except GetoptError as error:
		print(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip().strip()
		if not opts or opt == "-h":
			print("Usage 'TMDBparser v0.1': python TMDBparser.py [option...] <data>\n"
			"Example: python TMDBparser.py -q Titanic -o original.json -n normalized.json\n"
			"-q, --query <options>\t\tget result list from TMDB search'\n"
			"-l, --language <options>\tset language formatted like 'en-US'\n"
			"-e, --entriesmax <options>\tset maximum number of entries (defaut is 0=all)\n"
			"-m, --mediatype <options>\tset media type 'multi', 'movie' or 'series' (default 'multi')\n"
			"-o, --original <filename>\tfile output of original, formatted in JSON\n"
			"-n, --normalized <filename>\tfile output of normalized, formatted in JSON\n"
			"-s, --seriesindex <filename>\tfile output of all seasons and episodes of a series, formatted in JSON\n"
			"-i, --images <filename>\t\tfile output of all images and logos, formatted in JSON (details see code)\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-o", "--original"):
			tmdbFile = arg
		elif opt in ("-n", "--normalized"):
			normFile = arg
		elif opt in ("-s", "--seriesindex"):
			seriesFile = arg
		elif opt in ("-i", "--images"):
			imagesFile = arg
		elif opt in ("-l", "--language"):
			language = arg
		elif opt in ("-e", "--entriesmax"):
			entriesmax = int(arg) if arg.isdigit() else 0
		elif opt in ("-m", "--mediatype"):
			mediaType = arg
	if title and language:
		if not mediaType:
			mediaType = "multi"  # set fallback
		print(f"Search for '{title.replace("+", " ")}', mediaType: '{mediaType}'")
		provider_tmdb.start(language)
		errMsg, tmdbDicts = provider_tmdb.getInfo(title, mediaType=mediaType, year=None)
		if errMsg:
			print("ERROR getting data:", errMsg)
			exit(2)
		if tmdbDicts:
			if tmdbFile:
				with open(tmdbFile, "w") as file:
					dump(tmdbDicts, file)
				print(f"Original JSON file '{tmdbFile}' was successfully created.")
			normDict = provider_tmdb.createNormalized(tmdbDicts, entriesmax=entriesmax)
		if normDict and normFile:
			with open(normFile, "w") as file:
				dump(normDict, file)
			print(f"Normalized JSON file '{normFile}' was successfully created.")
		if seriesFile and tmdbDicts:
			result = tmdbDicts.get("results", [])[:1]
			if result:
				result = result[0]  # get first result only
				seriesId = str(result.get("id", 0))  # e.g. '1368'
				mediaType = result.get("media_type", "").replace("tv", "series")  # e.g. 'movie' or 'series', TMDB uses 'tv' instead of 'series'
				if seriesId and mediaType == "series":
					if isfile(seriesFile):
						errMsg, seriesIndex = provider_tmdb.readSeriesIndex(seriesFile)
						if errMsg:
							remove(seriesFile)
						else:
							print(f"Series index file '{seriesFile}' was successfully loaded from cache.")
					else:
						print("Download series info index...")
						errMsg, seriesIndex = provider_tmdb.getSeriesIndex(seriesId)
						if errMsg:
							print(f"Error creating series index file '{seriesFile}': {errMsg}")
						elif seriesIndex:
							errMsg = provider_tmdb.writeSeriesIndex(seriesFile, seriesIndex)
							if errMsg:
								print(f"Error writing series index file '{seriesFile}': {errMsg}")
							else:
								print(f"Series index file '{seriesFile}' was successfully created.")
					print(provider_tmdb.findSeasonEpisode(seriesIndex, "Emily hat Geldprobleme"))  # special episode search for series

			"""
			errMsg, detailDict = provider_tmdb.getEpisodeDetails(seriesId="1912244", seasonEpisode="19-80")
			if detailDict:
				with open("detailsTMDB.json", "w") as file:
					dump(detailDict, file)
			"""
		if imagesFile:
			errMsg, imagesDict = provider_tmdb.getImagesDict("597")
			if errMsg:
				print(f"Error creating images file '{seriesFile}': {errMsg}")
			elif imagesDict:
				with open(imagesFile, "w") as file:
					dump(imagesDict, file)
				print(f"Images JSON file '{imagesFile}' was successfully created.")
	else:
		errMsg = "'Title' or 'language' is missing"
		print("ERROR getting data:", errMsg)


if __name__ == "__main__":
	main(argv[1:])
