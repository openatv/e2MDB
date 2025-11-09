########################################################################################################
# e2MDBproviders by Mr.Servo @OpenATV (c) 2025                                                         #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
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
from re import search
from sys import exit, argv
try:
	from .parser.TMDBparser import provider_tmdb
	from .parser.TVDBparser import provider_tvdb
	from .parser.OMDBparser import provider_omdb
	from . import getApiKey
except ImportError:
	from parser.TMDBparser import provider_tmdb
	from parser.TVDBparser import provider_tvdb
	from parser.OMDBparser import provider_omdb

	def getApiKey(provider=None):
		return None  # fallback for standalone usage without e2MDB plugin


MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class e2MDBproviders:
	def __init__(self):
		self.seriesSearchOrder = [(provider_tmdb, True), (provider_tvdb, True), (provider_omdb, True)]  # (provider, active), will be defined later by the user in setup
		self.movieSearchOrder = [(provider_tmdb, True), (provider_tvdb, True), (provider_omdb, True)]  # (provider, active), will be defined later by the user in setup
		self.allKeys = [
						"countries", "releaseDate", "mediaType", "genres", "voteAverage",
						"voteCount", "coverUrl", "backdropUrl", "logoUrl", "providerIds"
						]  # with exception of 'Title' and 'Description', as these receive special treatment
		self.allProvIds = ["imdb", "tmdb", "tvdb"]

	def start(self, language):
		self.language = language.replace("_", "-")
		for provider in dict.fromkeys(self.seriesSearchOrder + self.movieSearchOrder):  # initiate all active provider parser
			if provider[1]:  # provider is active?
				provider[0].start(self.language, getApiKey(provider[0].getName()))

	def getInfo(self, title, mediaType="multi", year="", descriptions=[], callback=None, errback=None):
		if not title:
			errMsg = f"{MODULE_NAME}ERROR in module 'getInfo': title is missing."
			return errMsg, {}, {}
		if not mediaType or mediaType == "multi":
			estimatedType, foundStr = self.guessCategory([title] + descriptions)
			mediaType = estimatedType if estimatedType else "multi"  # 'movie', 'series' or 'multi'
			year = foundStr if foundStr and foundStr.isdigit() else ""
		yearStr = f"' with year '{year}'" if year else ""
		print(f"{MODULE_NAME}Gathering data for title '{title}'{yearStr} as media type '{mediaType}'...")
		errMsg, normDicts = self.gatherProvidersInfo(title, mediaType=mediaType, year=year)
		if errMsg:
			if errback:
				errback(errMsg, {}, {})
			return errMsg, {}, {}
		if not normDicts and mediaType != "multi":  # fallback when no result
			mediaType = "series" if mediaType == "movie" else "movie"  # switch mediaTypes 'movie' and 'series' and try again
			errMsg, normDicts = self.gatherProvidersInfo(title, mediaType=mediaType, year=year)
			if errMsg:
				if errback:
					errback(errMsg, {}, {})
				return errMsg, {}, {}
		errMsg, finalDict = self.assembleFinalResult(normDicts, title, descriptions=descriptions)
		if errMsg:
			if errback:
				errback(errMsg, {}, {})
			return errMsg, {}, {}
		if callback:
			callback(errMsg, normDicts, finalDict)
		return errMsg, normDicts, finalDict

	def readSeriesIndex(self, providerName, seriesFile):
		errMsg, seriesIndex = "", ""
		for provider in self.seriesSearchOrder:
			if provider[1] and providerName == provider[0].getName():  # provider is active and equal name?
				errMsg, seriesIndex = provider[0].readSeriesIndex(seriesFile)
		return errMsg, seriesIndex

	def writeSeriesIndex(self, providerName, seriesFile, seriesIndex):
		errMsg = ""
		for provider in self.seriesSearchOrder:
			if provider[1] and providerName == provider[0].getName():  # provider is active and equal name?
				errMsg = provider[0].writeSeriesIndex(seriesFile, seriesIndex)
		return errMsg

	def getSeriesIndex(self, providerName, seriesId):
		errMsg, seriesIndex = "", ""
		for provider in self.seriesSearchOrder:
			if provider[1] and providerName == provider[0].getName():  # provider is active and equal name?
				errMsg, seriesIndex = provider[0].getSeriesIndex(seriesId)
		return errMsg, seriesIndex

	def findSeasonEpisode(self, providerName, seriesIndex, comparison):
		seasonEpisode = ["", "", ""]
		for provider in self.seriesSearchOrder:
			if provider[1] and providerName == provider[0].getName():  # provider is active and equal name?
				seasonEpisode = provider[0].findSeasonEpisode(seriesIndex, comparison)
		return seasonEpisode

	def guessCategory(self, sources):
		movieKeys = ["film", "movie", "фильм", "кино", "ταινία", "película", "cinéma", "cine", "cinema", "filma"]
		seriesKeys = [
					"serial", "series", "serie", "serien", "série", "séries", "serious", "folge", "episodio", "episode",
					"épisode", "l'épisode", "ep.", "animation", "staffel", "soap", "doku", "tv", "talk", "show", "news",
					"factual", "entertainment", "telenovela", "dokumentation", "dokutainment", "documentary", "informercial",
					"information", "sitcom", "reality", "program", "magazine", "mittagsmagazin", "т/с", "м/с", "сезон", "с-н",
					"эпизод", "сериал", "серия", "actualité", "discussion", "interview", "débat", "émission", "divertissement",
					"jeu", "magasine", "information", "météo", "journal", "sport", "culture", "infos", "feuilleton",
					"téléréalité", "société", "clips", "concert", "santé", "éducation", "variété"
					]
		result = "", ""
		for source in sources:
			if source:
				# search for season/episode tags
				seasonEpisode = ""
				for regex in [r"S\d+E\d+", r"S\d+\/E\d+", r"S\d+\|E\d+", r"\(\d+\/\d+\)", r"\(\d+\|\d+\)"]:  # search for e.g. 'S02E05', 'S02/E05', 'S02|E05', (02/05), (02|05)
					found = search(regex, source)
					if found:
						seasonEpisode = found.group(0).replace("/", "").replace("|", "").replace("(", "").replace(")", "").strip()
						break
				if seasonEpisode:
					result = "series", seasonEpisode
					break
				# search for year tags
				yearReleased = ""
				for regex in [r"\(\d{4}\)", r" \d{4}"]:  # search for e.g. '(1997)', ' 1997'
					found = search(regex, source)
					if found:
						yearReleased = found.group(0).strip()
						break
				if yearReleased:
					result = "movie", yearReleased
					break
				# search for series keywords
				seriesFound = ""
				lowerSource = source.lower()
				for tag in seriesKeys:
					if tag in lowerSource:
						seriesFound = tag
						break
				if seriesFound:
					result = "series", ""
					break
				# search for movie keywords
				movieFound = ""
				for tag in movieKeys:
					if tag in lowerSource:
						movieFound = tag
						break
				if movieFound:
					result = "movie", ""
					break
		return result

	def gatherProvidersInfo(self, title, mediaType="", year=None):
		errMsg, normDicts = "", {}
		providers = self.movieSearchOrder[:] if mediaType == "movie" else self.seriesSearchOrder[:]
		if mediaType == "multi":
			if (provider_tmdb, True) in providers:
				providers.insert(0, providers.pop(providers.index((provider_tmdb, True))))  # make TMDB the first entry
			else:
				mediaType = "series"  # fallback to 'series'
		elif not mediaType:
			mediaType = "series"  # fallback to 'series'
		for index, provider in enumerate(providers):
			if provider[1]:  # provider is active?
				providerName = provider[0].getName()
				if index:  # further calls of remaining providers
					if mediaType == "multi":  # 'multi' is only known in TMDB
						mediaType = "series"  # fallback to 'series'
						print(f"{MODULE_NAME}MediaType 'multi' is not supported in {providerName}-search. Continue with '{mediaType}'...")
				if year == "":
					year = None
				errMsg, providerDict = provider[0].getInfo(title, mediaType=mediaType, year=year)
				normDict = provider[0].createNormalized(providerDict)
				foundInfo = "found infos" if normDict.get(providerName) else "found nothing"
				print(f"{MODULE_NAME}Searching for title '{title}' in {providerName}...{foundInfo}")
				if not index:  # very first call of provider (is forced TMDB in case of 'multi')
					mediaType = normDict.get("mediatype", "") or mediaType
					if not mediaType:
						mediaType = "series"  # fallback to 'series'
						print(f"{MODULE_NAME}MediaType was missing in {providerName}-search. Continue with '{mediaType}'...")
				if errMsg:
					print(f"{MODULE_NAME}ERROR in module 'gatherProvidersInfo': {errMsg}")
					return errMsg, {}
				if normDict:
					normDicts.update(normDict)
					if normDict.get(providerName, []):  # disable this two lines in order to actvate full search over all providers
						break  # premature termination on first result
		return errMsg, normDicts

	def assembleFinalResult(self, normDicts, title, descriptions=[]):
		errMsg, finalDict = "", {}
		missingKeys, missingIds = self.allKeys[:], self.allProvIds[:]
		abort = False
		for provider in dict.fromkeys(self.seriesSearchOrder + self.movieSearchOrder):  # use all active provider parser
			if abort:
				break
			if provider[1]:  # provider is active?
				providerName = provider[0].getName()
				for providerEntry in normDicts.get(providerName, []):
					if abort:
						break
					newTitleDict = providerEntry.get("title", {})
					newTitleText = newTitleDict.get("text", "")
					compareTitle = title.replace("–", "").replace("-", "").lower()
					compareNewTitle = newTitleText.replace("–", "").replace("-", "").lower()
					if compareTitle in compareNewTitle and abs(len(newTitleText) - len(title)) < 8:  # entry is a qualified source
						titleDict = finalDict.get("title")
						if titleDict:
							if titleDict.get("language")[:2] != self.language[:2] and newTitleDict.get("language", "")[:2] == self.language[:2]:
								finalDict["title"] = newTitleDict
						else:
							finalDict["title"] = newTitleDict
						newDescDict = providerEntry.get("description", {})
						newDescText = newDescDict.get("text", "")
						if len(newDescText) > 49:  # ignore short descriptions e.g. 'deutscher Spielfilm'
							finalDescDict = finalDict.get("description", {})  # for future diff-comparison
							if finalDescDict:
								if newDescDict.get("language", "")[:2] == self.language[:2] and len(newDescText) > len(finalDescDict.get("text", "")):
									finalDict["description"] = newDescDict
							else:
								finalDict["description"] = newDescDict
						for missingKey in missingKeys[:]:  # fill-up finalDict
							item = providerEntry.get(missingKey, "")
							if item:
								finalDict[missingKey] = item
								missingKeys.remove(missingKey)
						for missingId in missingIds[:]:
							item = providerEntry.get("providerIds", {}).get(missingId, "")
							if item:
								if not finalDict.get("providerIds"):
									finalDict["providerIds"] = {}
								finalDict["providerIds"][missingId] = item
								missingIds.remove(missingId)
						if not missingKeys and not missingIds:
							abort = True  # premature termination when normDicts is complete
							break
						abort = True  # premature termination when normDicts is complete
						if finalDict:
							finalDict["source"] = providerName
							break
		return errMsg, finalDict


e2mdbproviders = e2MDBproviders()


#class e2MDBProvider():
#	def __init__(self):
#		pass
#
#	def getInfo(self, title, year=None, description=None, season=None, episode=None):
#		raise NotImplementedError("This method should be overridden by subclasses")


def main(argv):  # shell interface
	normFile, finalFile, seriesFile, title, language, mediaType, year = "", "", "", "", "", "", ""
	finalDict = {}
	helpstring = "providers v0.1: try 'python providers.py -h' for more information"
	try:
		opts, args = getopt(argv, "n:f:s:q:l:m:h", ["normalized=", "finalresult=", "seriesinfo=", "query=", "language=", "mediatype="])
	except GetoptError as error:
		print(f"Error: {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip().strip()
		if not opts or opt == "-h":
			print("Usage 'providers v0.1': python providers.py [option...] <data>\n"
			"Example: python providers.py -q Titanic -n normalized.json\n"
			"-q, --query <options>\t\tget result list\n"
			"-l, --language <options>\tset language formatted like 'en-US'\n"
			"-m, --mediatype <options>\tset media type 'multi', 'movie' or 'series' (default 'multi')\n"
			"-n, --normalized <filename>\tfile output of single normalized result, formatted in JSON\n"
			"-f, --finalresult <filename>\tfile output of normalized single final result, formatted in JSON\n"
			"-s, --seriesinfo <filename>\tfile output of all seasons and episodes of a series, formatted in JSON\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-n", "--normalized"):
			normFile = arg
		elif opt in ("-f", "--finalresult"):
			finalFile = arg
		elif opt in ("-s", "--seriesinfo"):
			seriesFile = arg
		elif opt in ("-l", "--language"):
			language = arg.replace("_", "-")
		elif opt in ("-m", "--mediatype"):
			mediaType = arg
		if not mediaType:
			found = search(r"\(\d{4}\)", title)  # search for e.g. '(1997)'
			if found:
				found = found.group(0)
				title = title.replace(found, "")[::-1].replace(found, "").replace("+", " ", 1)[::-1].strip()  # replace one '+' from right side
				mediaType, year = "movie", found.replace("(", "").replace(")", "").strip()
			else:
				mediaType = "multi"  # set fallback
	if title and language:
		e2mdbproviders.start(language)
		errMsg, normDicts, finalDict = e2mdbproviders.getInfo(title, mediaType=mediaType, year=year)
		if errMsg:
			exit(2)
		if normDicts and normFile:
			with open(normFile, "w") as file:
				dump(normDicts, file)
			print(f"All results normalized JSON file '{normFile}' was successfully created.")
		if finalDict and finalFile:
			with open(finalFile, "w") as file:
				dump(finalDict, file)
			print(f"All results original JSON file '{finalFile}' was successfully created.")
		if finalDict and seriesFile:
			finalProvider = finalDict.get("source", "")
			if finalProvider:
				seriesId = str(finalDict.get("providerIds", {}).get(finalProvider, 0))  # e.g. '597'
				mediaType = finalDict.get("mediaType", "")  # e.g. 'movie' or 'series'
				if seriesId and mediaType == "series":  # special episode search for series
					if isfile(seriesFile):
						errMsg, seriesIndex = e2mdbproviders.readSeriesIndex(finalProvider, seriesFile)
						if errMsg:
							remove(seriesFile)
						else:
							print(f"Series index file '{seriesFile}' was successfully loaded from cache.")
					else:
						print("Download series info index...")
						errMsg, seriesIndex = e2mdbproviders.getSeriesIndex(finalProvider, seriesId)
						if errMsg:
							print(f"Error creating series info: {errMsg}")
						elif seriesIndex and len(seriesIndex) > 1:
							errMsg = e2mdbproviders.writeSeriesIndex(finalProvider, seriesFile, seriesIndex)
							if errMsg:
								print(f"Series info index file '{seriesFile}' was successfully created.")

							print(f"Series info index file '{seriesFile}' was successfully created.")
	else:
		errMsg = "'Title' or 'language' is missing"
		print("ERROR getting data:", errMsg)


if __name__ == "__main__":
	main(argv[1:])
