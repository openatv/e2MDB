########################################################################################################
# OMDBparser by Mr.Servo @OpenATV (c) 2025                                                             #
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

MODULE_NAME = f"[{__name__.split(".")[-1]}] ".replace("[__main__] ", "")


class Provider_omdb:
	def __init__(self):
		self.baseUrl = "http://www.omdbapi.com/"
		self.mediaTypes = ["movie", "series", "episode"]  # exclude from search: {nothing}
		self.apiKey = bytes.fromhex("39383734653564F"[:-1]).decode()

	def getName(self):
		return self.__class__.__name__.split("_")[-1].lower()

	def isActive(self):
		return True

	def start(self, language="", apikey=None):  # OMDB doesn't support language requests
		self.apiKey = apikey or self.apiKey
		return ""

	def getInfo(self, title, mediaType="series", year=None):  # OMDB only returns a single result and does not have neither localization support nor its own episodesId
		if mediaType not in self.mediaTypes:
			return f"{MODULE_NAME}ERROR in module 'getInfo': unknown search_mode '{mediaType}'. Supported is '{', '.join(self.mediaTypes)}'", {}
		url = self.baseUrl
		# param 's' (search) returns a result list with useless tiny results, 't' (title) returns only one, but a complete result
		params = {"t": title, "type": mediaType, "y": year, "plot": "full", "apikey": self.apiKey}
		return self.getApiDict(url, params=params)

	def createNormalized(self, result, includeLogos=True, entriesmax=0):  # omdbDict contains only a single result, therefore 'entriesmax' is not used here, 'includeLogos' for compatibility reasons
		def setNormKey(key, value):
			if value and value != "N/A":
				normDict[key] = value
		normDicts, normList = {}, []
		if result and result.get("Response", "False") == "True":
			try:
				normDict = {}
				titleDict = {}
				titleDict["text"] = result.get("Title", "")  # e.g. 'Titanic'
				setNormKey("title", titleDict)
				setNormKey("countries", result.get("Country", ""))  # e.g. 'United States'
				relList = result.get("Released", "").upper().split(" ")  # e.g. '04 Oct 1997'
				if relList and len(relList) > 2:  # necessary workaround due to fixed localisation of Enigma2 (e.g. to 'de_DE')
					month = {"JAN": 1, " FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}.get(relList[1], 0)
					setNormKey("released", datetime.now().replace(year=int(relList[2]), month=month, day=int(relList[0]), hour=0, minute=0, second=0, microsecond=0, tzinfo=None))
				setNormKey("mediaType", result.get("Type", ""))  # e.g. 'movie'
				description = {}
				plot = result.get("Plot", "")  # longtext
				if plot and plot != "N/A":
					description["text"] = plot
					setNormKey("description", description)
				setNormKey("genres", result.get("Genre", ""))  # e.g. 'Drama, Romance'
				setNormKey("voteAverage", result.get("imdbRating", "").replace(",", ""))  # e.g. '7.9'
				setNormKey("vote_count", result.get("imdbVotes", "").replace(",", ""))  # e.g. '26151'
				setNormKey("coverUrl", result.get("Poster", ""))
				# e.g. https://m.media-amazon.com/images/M/MV5BYzYyN2FiZmUtYWYzMy00MzViLWJkZTMtOGY1ZjgzNWMwN2YxXkEyXkFqcGc@._V1_SX300.jpg
				providerIds = {}
				imdbId = result.get("imdbID", "")  # STR, e.g. '231'
				if imdbId and imdbId != "N/A":
					providerIds["imdb"] = imdbId
				setNormKey("providerIds", providerIds)
				normList.append(normDict)
				normDicts["omdb"] = normList
			except Exception as errMsg:
				print(f"{MODULE_NAME}ERROR in module 'createNormalized': {errMsg}'")
		return normDicts

	def readSeriesIndex(self, seriesFile):  # OMDB do not support this function at all
		return "not supported by provider 'OMDB'", ""

	def writeSeriesIndex(self, seriesFile, seriesIndex):  # OMDB do not support this function at all
		return "not supported by provider 'OMDB'"

	def getSeriesIndex(self, seriesId):  # OMDB do not support this function at all
		return "not supported by provider 'OMDB'", ""

	def findSeasonEpisode(self, seriesIndex="", episodeDescs=[]):  # OMDB do not support this function at all
		return "not supported by provider 'OMDB'", []

	def getEpisodeDetails(self, seriesId=None, seasonEpisode=[]):  # OMDB  do not support this function at all, use getInfo instead
		return "not supported by provider 'OMDB'", {}

	def getApiDict(self, url, params=None, timeout=(3.05, 6)):
		headers = {"accept": "application/json"}
		try:
			response = get(url, params=params, headers=headers, timeout=timeout)
			errMsg, omdbDict = ("", response.json()) if response.ok else (f"API server access ERROR, response code: {response.raise_for_status()}", {})
			return errMsg, omdbDict
		except exceptions.RequestException as errMsg:
			return errMsg, {}


provider_omdb = Provider_omdb()


def main(argv):  # shell interface
	normFile, omdbFile, title, language, mediaType = "", "", "", "en-US", ""
	normDict, omdbDict = {}, {}
	entriesmax = 0
	helpstring = "OMDBparser v0.1: try 'python OMDBparser.py -h' for more information"
	try:
		opts, args = getopt(argv, "o:n:q:e:m:h", ["original=", "normalized=", "query=", "entriesmax=", "mediatype"])
	except GetoptError as error:
		print(f"{MODULE_NAME}ERROR in module 'main': {error}\n{helpstring}")
		exit(2)
	for opt, arg in opts:
		opt = opt.lower().strip()
		arg = arg.strip()
		if not opts or opt == "-h":
			print("Usage 'OMDBparser v0.1': python OMDBparser.py [option...] <data>\n"
			"Example: python OMDBparser.py -q Titanic -o original.json -n normalized.json\n"
			"-q, --query <options>\t\tget result list from OMDB search'\n"
			"-e, --entriesmax <options>\tset maximum number of entries (defaut is 0=all)\n"
			"-m, --mediatype <options>\tset media type 'movie' or 'series' (default 'series')\n"
			"-o, --original <filename>\tfile output of original formatted in JSON\n"
			"-n, --normalized <filename>\tnormalized file output formatted in JSON\n")
			exit()
		elif opt in ("-q", "--query"):
			title = arg.replace("+", " ").strip()
		elif opt in ("-o", "--original"):
			omdbFile = arg
		elif opt in ("-n", "--normalized"):
			normFile = arg
		elif opt in ("-e", "--entriesmax"):
			entriesmax = int(arg) if arg.isdigit() else 0
		elif opt in ("-m", "--mediatype"):
			mediaType = arg
	if title and language:
		if not mediaType:
			mediaType = "series"  # set fallback
		print(f"Search for '{title}', mediaType: '{mediaType}'")
		provider_omdb.start(language)
		errMsg, omdbDict = provider_omdb.getInfo(title, mediaType=mediaType, year=None)
		if errMsg:
			print("ERROR getting data:", errMsg)
			exit(2)
	print(omdbDict.get("Response", "***"))
	if omdbDict:
		if omdbDict.get("Response", "False") == "True":
			print("YIEPPEEEE")
		normDict = provider_omdb.createNormalized(omdbDict, entriesmax=entriesmax)
		if omdbFile:
			with open(omdbFile, "w") as file:
				dump(omdbDict, file)
			print(f"Original JSON file '{omdbFile}' was successfully created.")
	if normDict and normFile:
		with open(normFile, "w") as file:
			dump(normDict, file)
		print(f"Normalized JSON file '{normFile}' was successfully created.")


if __name__ == "__main__":
	main(argv[1:])
