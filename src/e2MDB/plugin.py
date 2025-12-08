########################################################################################################
# e2MDB by Mr.Servo @OpenATV and jbleyel @OpenATV (c) 2025 - skin & design by stein17 @OpenATV         #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from json import dump, load
from glob import glob
from os.path import exists, join, normpath, split, splitext, isfile
from os import stat, makedirs, remove
from PIL import Image
from requests import get, exceptions
from secrets import choice
from struct import unpack
from time import localtime, strftime
from twisted.internet.reactor import callInThread

# ENIGMA IMPORTS

from enigma import eListboxPythonMultiContent, eServiceCenter, eServiceReference, eLabel, eListbox, eSize, eTimer, getDesktop, gFont, iServiceInformation, RT_HALIGN_CENTER, RT_VALIGN_CENTER, RT_BLEND, BT_SCALE, BT_KEEP_ASPECT_RATIO

from Components.ActionMap import HelpableActionMap
from Components.config import config, ConfigYesNo, ConfigSubsection, ConfigText
from Components.GUIComponent import GUIComponent
from Components.Label import Label
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from Components.Pixmap import Pixmap
from Components.PluginComponent import plugins
from Components.ProgressBar import ProgressBar
from Components.ScrollLabel import ScrollLabel
from Components.Sources.Event import Event
from Components.Sources.ServiceEvent import ServiceEvent
from Components.Sources.StaticText import StaticText
from Components.UsageConfig import preferredTimerPath
from Plugins.Plugin import PluginDescriptor
from RecordTimer import RecordTimerEntry, parseEvent
from Screens.ChoiceBox import ChoiceBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.TimerEntry import TimerEntry
from ServiceReference import ServiceReference
from skin import parseColor, parseFont


from Tools.BoundFunction import boundFunction
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import resolveFilename, SCOPE_GUISKIN

from .e2MDBProviders import e2mdbproviders
from .e2MDBDatabase import mediadb

from . import PLUGINDIR, _


class e2MDBglobals:
	MODULE_NAME = __name__.split(".")[-2]
	MOVIE_LIST_SREF_ROOT = "2:0:1:0:0:0:0:0:0:0:"
	RESOLUTION = "FHD" if getDesktop(0).size().width() > 1300 else "HD"
	USERAGENT = choice([
			"Mozilla/5.0 (Linux; Android 14; SM-A536B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.231 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14; SM-S918W Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.119 Mobile Safari/537.36/122.0.6261.119",
			"Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.103 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile DuckDuckGo/5 Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14; G9FPL) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.48 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; arm_64; Android 14; Pixel Fold) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.232 YaBrowser/23.11.0.232.00 SA/3 Mobile Safari/537.36"
			"Mozilla/5.0 (Linux; Android 14; SM-F731N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.119 Mobile Safari/537.36 OPR/81.1.4292.78446"
			])


e2mdbglobals = e2MDBglobals()


class e2MDBhelper:
	def getCachePath(self):
		return f"{config.plugins.e2mdb.cachePath.value}tmp/e2MDB/" if config.plugins.e2mdb.cachePath.value == "/" else f"{config.plugins.e2mdb.cachePath.value}e2MDB/"

	def getMoviePath(self):  # TODO: stimmt das so?
		return f"{config.plugins.e2mdb.cachePath.value}movie/"

	def getDataBaseFile(self):
		path = join(config.plugins.e2mdb.databasePath.value, "e2MDB")
		if not exists(path):
			makedirs(path)
		path = join(path, "e2MDB.db")
		mediadb.setPath(path)
		if not exists(path):
			mediadb.createTable()
		return path

	def calcMovieLen(self, fname):
		if exists(fname):
			try:
				with open(fname, "rb") as f:
					packed = f.read()
				while len(packed) > 0:
					packedCue = packed[:12]
					packed = packed[12:]
					cue = unpack(">QI", packedCue)
					if cue[1] == 5:
						movie_len = cue[0] / 90000
						return movie_len
			except Exception as err:
				print(f"[{e2mdbglobals.MODULE_NAME}] ERROR failure at getting movie length from cut list: {err}!")
		return -1

	def createCachePaths(self):
		try:
			cachePath = self.getCachePath()
			for path in [cachePath, f"{cachePath}series/", f"{cachePath}events/"]:
				if not isfile(path):
					makedirs(path, exist_ok=True)
		except OSError as errMsg:
			print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBhelper:createCachePaths': {errMsg}!")
			return errMsg
		return ""

	def cleanupCache(self):  # delete older asset overviews, detailed assets and images
		return
# now = datetime.today()
# latest = now - timedelta(days=config.plugins.e2mdb.keepcache.value)
# ldate = latest.replace(hour=0, minute=0, second=0, microsecond=0)
# for filename in glob(join(f"{self.getCachePath()}series/", "*.json")):
# if datetime.strptime(filename.split("/")[-1][6:16], "%Y-%m-%d") < ldate:  # keepcache or older?
# remove(filename)

	def getAPIDict(self, url, headers=None, params=None):
		errMsg, jsondict = "", {}
		try:
			response = get(url, params=params, headers=headers, timeout=(3.05, 6))
			response.raise_for_status()
			if response.ok:
				errMsg, jsondict = "", response.json()
			else:
				errMsg, jsondict = f"API server access ERROR, response code: {response.raise_for_status()}", {}
			del response
			return errMsg, jsondict
		except exceptions.RequestException as errMsg:
			print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBhelper:getAPIdata': {errMsg}")
			return errMsg, jsondict

	def scanSingleTitle(self, serviceref, info, progressCallback=None):
		def dataError(error):
			print(f"[{e2mdbglobals.MODULE_NAME}] ERROR: {error}")

		title = info.getName(serviceref)
		serviceList = []
		downloadList = []
		if not title.startswith("."):
			event = info.getEvent(serviceref)
			extended_description = event and event.getExtendedDescription() or ""
			short_description = event and event.getShortDescription() or ""
			desc = info.getInfoString(serviceref, iServiceInformation.sDescription)
			print("#####serviceref.getPath():", serviceref.getPath())
			serviceList.append((serviceref, title, serviceref.getPath(), desc, short_description, extended_description))

		for index, (serviceref, title, path, desc, short_desc, ext_desc) in enumerate(serviceList):
			print(f"[{e2mdbglobals.MODULE_NAME}] Service: {title}, Path: {path}, Description: {desc}, Short Description: {short_desc}, Extended Description: {ext_desc}")
			pathWithoutExtension = splitext(path)[0]
			jsonFile = f"{pathWithoutExtension}.json"
			if isfile(jsonFile):
				continue

			coverPath = f"{pathWithoutExtension}.jpg"
			# coverPath = f"{pathWithoutExtension}.cover.jpg"
			backdropPath = f"{pathWithoutExtension}.backdrop.jpg"
			titleLogoPath = f"{pathWithoutExtension}.logo.jpg"
			print("#####title:", title)
			print("#####descs:", desc, short_desc, ext_desc)
			estimatedType, foundStr = e2mdbproviders.guessCategory([title, desc, short_desc, ext_desc])
			print("#####estimated Type:", estimatedType if estimatedType else "not possible", foundStr)
			errMsg, normDicts, finalDict = e2mdbproviders.getInfo(title, mediaType=estimatedType, year="")  # TODO: Das Jahr muß noch rein
			print("#####finalMediaType:", finalDict.get("mediaType", ""))
			try:
				with open(jsonFile, "w") as file:
					dump(finalDict, file)
			except OSError as osError:
				print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Final result data could not be saved: {osError}")
			coverUrl = finalDict.get("coverUrl", "")
			backdropUrl = finalDict.get("backdropUrl", "")
			titleLogoUrl = finalDict.get("titleLogoUrl", "")
			if coverUrl and not isfile(coverPath):
				downloadList.append((coverUrl, coverPath))
			if backdropUrl and not isfile(backdropPath):
				downloadList.append((backdropUrl, backdropPath))
			if titleLogoUrl and not isfile(titleLogoPath):
				downloadList.append((titleLogoUrl, titleLogoPath))
			print(f"[{e2mdbglobals.MODULE_NAME}] Result for '{title}': {errMsg}, Final Dict: {finalDict}, Result Dicts: {normDicts}")
			if finalDict.get("mediaType", "") == "series":  # in case title is declared as series, try to find all seasons/episodes
				finalProvider = finalDict.get("source", "")
				seriesId = finalDict.get("providerIds", {}).get(finalProvider, "")
				if finalProvider and seriesId:
					seriesFile = join(f"{self.getCachePath()}series/{finalProvider}_{seriesId}.idx")
					if isfile(seriesFile):
						errMsg, seriesIndex = e2mdbproviders.readSeriesIndex(finalProvider, seriesFile)
						if errMsg:
							print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Series data could not be loaded: {errMsg}")
					else:
# if progressCallback and callable(progressCallback):
# progressCallback(f"{_('Seriesinfo:')} '{title}'")
						errMsg, seriesIndex = e2mdbproviders.getSeriesIndex(finalProvider, seriesId)
						if errMsg:
							print(f"[{e2mdbglobals.MODULE_NAME}] No series info found for '{title}': {errMsg}")
						else:
							print("#####seriesIndex :", seriesIndex)
							print("type(seriesIndex):", type(seriesIndex))
							errMsg = e2mdbproviders.writeSeriesIndex(finalProvider, seriesFile, seriesIndex)
							if errMsg:
								print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Series data could not be saved: {errMsg}")
							else:
								print(f"[{e2mdbglobals.MODULE_NAME}] Series index for '{title}' was successfully stored in '{seriesFile}'.")
# if progressCallback and callable(progressCallback):
# progressCallback(detailInfo)

		for url, fileName in downloadList:
			infoText = f"[{e2mdbglobals.MODULE_NAME}] Downloading {url} to {fileName}"
			print(infoText)
			callInThread(self.imageDownload, url, fileName, fail=dataError)  # download + store image

	def imageDownload(self, url, imgFile, callback=None, fail=None):
		if not isfile(imgFile):
			try:
				headers = {"User-Agent": e2mdbglobals.USERAGENT}
				response = get(url, headers=headers, timeout=(3.05, 6))
				response.raise_for_status()
				try:
					with open(imgFile, "wb") as file:
						file.write(response.content)
				except OSError as osError:
					print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'TVscreenHelper:imageDownload': {imgFile} - picture could not be saved: {osError}")
					if fail:
						fail(osError)
				if callback:
					callback(imgFile)
			except exceptions.RequestException as rqError:
				print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'TVscreenHelper:imageDownload': {url} - picture could not be downloaded: {rqError}")
				if fail:
					fail(rqError)


class StubInfo:
	def __init__(self):  # NOSONAR
		pass

	def getName(self, serviceref):
		return split(serviceref.getPath())[1]

	def getLength(self, serviceref):
		return -1

	def getEvent(self, serviceref, *args):
		return None

	def isPlayable(self):
		return True

	def getInfo(self, serviceref, w):
		try:
			if w == iServiceInformation.sTimeCreate:
				return stat(serviceref.getPath()).st_birthtime
			if w == iServiceInformation.sFileSize:
				return stat(serviceref.getPath()).st_size
			if w == iServiceInformation.sDescription:
				return serviceref.getPath()
		except Exception:  # nosec # noqa: E722
			pass
		return 0

	def getInfoString(self, serviceref, w):
		return ""


justStubInfo = StubInfo()


class e2MDBSetup(Setup, e2MDBhelper):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="e2MDB", plugin="Extensions/e2MDB")
		self.SCANACTIVE = False
		self.SCANSTOPPED = False
		self.e2MDBinfobox = session.instantiateDialog(e2MDBinfoBox)
		self.e2MDBscanbox = session.instantiateDialog(e2MDBscanBox)
		self["key_yellow"] = StaticText(_("Start Scanning"))
		self["key_blue"] = StaticText(_("Remove JPG & JSON"))  # TODO: set to "" after tests
		description = _("Pluto TV Actions")
		self["addAction"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.keyYellow, _("Start Scanning")),
			"blue": (self.keyBlue, _("Removing Data"))  # TODO: remove after tests
		}, prio=0, description=description)
		self.onLayoutFinish.append(self.layoutFinished)
		e2mdbproviders.start(config.misc.locale.value)  # start all providers with default language
		if self.createCachePaths():
			self.exit()
		self.cleanupCache()

	def keySave(self):
		if config.plugins.e2mdb.enableDatabase.value:
			self.getDataBaseFile()
		Setup.keySave(self)

	def layoutFinished(self):
		self.e2MDBscanbox.setHeadline(_("Scanning 'movie' folder"))
		self.e2MDBscanbox.setKeyYellow(_("Abort"))
		self.e2MDBscanbox.setKeyBlue(_("Show/hide"))

	def keyBlue(self):
		if self.SCANACTIVE:
			if self.e2MDBscanbox.getIsVisible():
				self.e2MDBscanbox.hideDialog()
			else:
				self.e2MDBscanbox.showDialog()
		else:  # TODO: remove after tests
			for file in glob(f"{self.getMoviePath()}*.jpg"):
				remove(file)
			for file in glob(f"{self.getMoviePath()}*.json"):
				remove(file)
			self.e2MDBinfobox.showDialog(_("JPG and JSON data have been successfully removed from movie folder."))

	def keyYellow(self):
		if self.SCANACTIVE:
			self.SCANSTOPPED = True
		else:
			self.SCANSTOPPED = False
			callInThread(self.titleScanner)

	def titleScanner(self):
		def dataError(error):
			print(f"[{e2mdbglobals.MODULE_NAME}] ERROR: {error}")

		useMediaDB = False
		if config.plugins.e2mdb.enableDatabase.value:
			self.getDataBaseFile()
			useMediaDB = True

		self.SCANACTIVE = True
		self.e2MDBscanbox.showDialog()
		servicehandler = eServiceCenter.getInstance()
		directorycount = 0
		root = eServiceReference(f"{e2mdbglobals.MOVIE_LIST_SREF_ROOT}{self.getMoviePath()}")
		reflist = root and servicehandler.list(root)
		serviceList = []  # TODO: does this necessarily have to be 'serviceList' or can it also be called 'serviceList'
		downloadList = []
		if reflist is None:
			print(f"[{e2mdbglobals.MODULE_NAME}] Listing of movies failed")
			return
		rootpath = normpath(root.getPath())
		print(f"[{e2mdbglobals.MODULE_NAME}] Scanning directory: {rootpath}")
		while True:
			serviceref = reflist.getNext()
			if self.SCANSTOPPED or not serviceref.valid():
				break
			info = servicehandler.info(serviceref)
			if info is None:
				info = justStubInfo
	# begin = info.getInfo(serviceref, iServiceInformation.sTimeCreate)
			if serviceref.flags & eServiceReference.mustDescent:
	# dirname = info.getName(serviceref)
	# if not dirname.endswith('.AppleDouble/') and not dirname.endswith('.AppleDesktop/') and not dirname.endswith('.AppleDB/') and not dirname.endswith('Network Trash Folder/') and not dirname.endswith('Temporary Items/'):
	# self.list.append((serviceref, info, begin, -1))
	# directorycount += 1
				continue
			title = info.getName(serviceref)
			if title.startswith("."):
				continue
			event = info.getEvent(serviceref)
			extended_description = event and event.getExtendedDescription() or ""
			short_description = event and event.getShortDescription() or ""
			desc = info.getInfoString(serviceref, iServiceInformation.sDescription)
			begin = info.getInfo(serviceref, iServiceInformation.sTimeCreate)
			tags = info.getInfoString(serviceref, iServiceInformation.sTags)
			size = self.getFileSize(serviceref.getPath())
			duration = info.getLength(serviceref)
			if duration < 0:
				duration = self.calcMovieLen(f"{serviceref.getPath()}.cuts")
			print("#####serviceref.getPath():", serviceref.getPath())
			serviceList.append((serviceref, title, serviceref.getPath(), desc, short_description, extended_description, begin, tags, size, duration))
		lenList = len(serviceList)
		self.e2MDBscanbox.setPrgsRange((0, lenList))
		for index, (serviceref, title, path, desc, short_desc, ext_desc, begin, tags, size, duration) in enumerate(serviceList):
			if self.SCANSTOPPED:
				break
			if useMediaDB:
				fpath, fname = split(path)
				record = {
					"path": fpath,
					"fname": fname,
					"ref": serviceref.toString(),
					"title": title,
					"shortDesc": short_desc,
					"extDesc": ext_desc,
					"tags": tags,
					"duration": duration,
					"begin": begin,
					"fsize": size
				}
				mediadb.upsert(record)
			detailInfo = f"{_('Detailinfo:')} '{title}'"
			self.e2MDBscanbox.setPrgsValue(index)
			self.e2MDBscanbox.setPrgsHeader(detailInfo)
			self.e2MDBscanbox.setPrgsText(f"{index + 1}/{lenList}")
			print(f"[{e2mdbglobals.MODULE_NAME}] Service: {title}, Path: {path}, Description: {desc}, Short Description: {short_desc}, Extended Description: {ext_desc}")
			pathWithoutExtension = splitext(path)[0]
			jsonFile = f"{pathWithoutExtension}.json"
			if isfile(jsonFile):
				continue

			coverPath = f"{pathWithoutExtension}.jpg"
			# coverPath = f"{pathWithoutExtension}.cover.jpg"
			backdropPath = f"{pathWithoutExtension}.backdrop.jpg"
			titleLogoPath = f"{pathWithoutExtension}.logo.jpg"
			print("#####title:", title)
			print("#####descs:", desc, short_desc, ext_desc)
			estimatedType, foundStr = e2mdbproviders.guessCategory([title, desc, short_desc, ext_desc])
			print("#####estimated Type:", estimatedType if estimatedType else "not possible", foundStr)
			errMsg, normDicts, finalDict = e2mdbproviders.getInfo(title, mediaType=estimatedType, year="")  # TODO: Das Jahr muß noch rein
			print("#####finalMediaType:", finalDict.get("mediaType", ""))
			try:
				with open(jsonFile, "w") as file:
					dump(finalDict, file)
			except OSError as osError:
				print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Final result data could not be saved: {osError}")
			coverUrl = finalDict.get("coverUrl", "")
			backdropUrl = finalDict.get("backdropUrl", "")
			titleLogoUrl = finalDict.get("titleLogoUrl", "")
			if coverUrl and not isfile(coverPath):
				downloadList.append((coverUrl, coverPath))
			if backdropUrl and not isfile(backdropPath):
				downloadList.append((backdropUrl, backdropPath))
			if titleLogoUrl and not isfile(titleLogoPath):
				downloadList.append((titleLogoUrl, titleLogoPath))
			print(f"[{e2mdbglobals.MODULE_NAME}] Result for '{title}': {errMsg}, Final Dict: {finalDict}, Result Dicts: {normDicts}")
			if finalDict.get("mediaType", "") == "series":  # in case title is declared as series, try to find all seasons/episodes
				finalProvider = finalDict.get("source", "")
				seriesId = finalDict.get("providerIds", {}).get(finalProvider, "")
				if finalProvider and seriesId:
					seriesFile = join(f"{self.getCachePath()}series/{finalProvider}_{seriesId}.idx")
					if isfile(seriesFile):
						errMsg, seriesIndex = e2mdbproviders.readSeriesIndex(finalProvider, seriesFile)
						if errMsg:
							print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Series data could not be loaded: {errMsg}")
					else:
						self.e2MDBscanbox.setPrgsHeader(f"{_('Seriesinfo:')} '{title}'")
						errMsg, seriesIndex = e2mdbproviders.getSeriesIndex(finalProvider, seriesId)
						if errMsg:
							print(f"[{e2mdbglobals.MODULE_NAME}] No series info found for '{title}': {errMsg}")
						else:
							print("#####seriesIndex :", seriesIndex)
							print("type(seriesIndex):", type(seriesIndex))
							errMsg = e2mdbproviders.writeSeriesIndex(finalProvider, seriesFile, seriesIndex)
							if errMsg:
								print(f"[{e2mdbglobals.MODULE_NAME}] ERROR in class 'e2MDBSetup:titleScanner': Series data could not be saved: {errMsg}")
							else:
								print(f"[{e2mdbglobals.MODULE_NAME}] Series index for '{title}' was successfully stored in '{seriesFile}'.")
						self.e2MDBscanbox.setPrgsHeader(detailInfo)
		for url, fileName in downloadList:
			infoText = f"[{e2mdbglobals.MODULE_NAME}] Downloading {url} to {fileName}"
			print(infoText)
			callInThread(self.imageDownload, url, fileName, fail=dataError)  # download + store image
		self.e2MDBscanbox.hideDialog()
		self.SCANACTIVE = False

	def exit(self):
		self.session.deleteDialog(self.e2MDBinfobox)
		self.session.deleteDialog(self.e2MDBscanbox)


class e2MDBinfoBox(Screen):
	skin = """
	<screen name="e2MDBinfoBox" position="390,432" size="500,110" flags="wfNoBorder" resolution="1280,720" title="e2MDB Infobox">
		<eLabel position="0,0" size="500,110" backgroundColor="#00203060" zPosition="-1" />
		<eLabel position="2,2" size="496,106" zPosition="-1" />
		<widget source="info" render="Label" position="5,5" size="490,100" font="Regular;24" halign="center" valign="center" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self["info"] = StaticText()
		self.isVisible = False
		self.tvinfoboxTimer = eTimer()
		self.tvinfoboxTimer.callback.append(self.hideDialog)

	def showDialog(self, info, timeout=2500):
		self["info"].setText(info)
		self.isVisible = True
		self.show()
		self.tvinfoboxTimer.start(timeout, True)

	def hideDialog(self):
		self.tvinfoboxTimer.stop()
		self.isVisible = False
		self.hide()

	def getIsVisible(self):
		return self.isVisible


class e2MDBscanBox(Screen):
	skin = """
	<screen name="e2MDBscanBox" position="820,250" size="410,142" flags="wfNoBorder" resolution="1280,720" title="e2MDB Scanning progress">
		<eLabel name="e2MDB_bg" position="2,2" size="406,32" backgroundColor="black,#203060,horizontal" zPosition="-1" />
		<eLabel name="e2MDB_line" position="2,34" size="406,2" backgroundColor="#27153c,#101093,black,horizontal" zPosition="10" />
		<eLabel position="0,0" size="410,142" backgroundColor="#203060" zPosition="-3" />
		<eLabel position="2,2" size="406,138" backgroundColor="#10060613" zPosition="-2" />
		<widget source="headline" render="Label" position="10,2" size="400,32" font="Regular;24" transparent="1" halign="left" valign="center"/>
		<widget source="progressHdr" render="Label" position="10,38" size="390,28" font="Regular;18" wrap="ellipsis" transparent="1" valign="bottom" />
		<widget name="progressBar" position="80,68" size="320,20" foregroundColor="#203060" zPosition="1" backgroundColor="#505050" />
		<widget source="progressTxt" render="Label" position="10,70" size="68,16" font="Regular;14" foregroundColor="yellow" backgroundColor="#16000000" transparent="0" halign="center" valign="top" zPosition="2" />
		<eLabel position="8,68" size="72,20" zPosition="-1" backgroundColor="#324b96" />
		<widget source="key_yellow" render="Label" position="36,108" size="120,24" font="Regular;18" transparent="1" halign="left" valign="center"/>
		<widget source="key_blue" render="Label" position="176,108" size="160,24" font="Regular;18" transparent="1" halign="left" valign="center"/>
		<eLabel name="button_yellow" position="20,106" size="6,30" backgroundColor="#7a6213,#e6c619,vertical" zPosition="1" />
		<eLabel name="button_blue" position="160,106" size="6,30" backgroundColor="#101093,#4040ff,vertical" zPosition="1" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self["headline"] = StaticText()
		self["progressHdr"] = StaticText()
		self["progressBar"] = ProgressBar()
		self["progressTxt"] = StaticText()
		self["key_yellow"] = StaticText()
		self["key_blue"] = StaticText()
		self.isVisible = False
		self.wasVisible = False

	def showDialog(self):
		self.wasVisible = False
		self.isVisible = True
		self.show()

	def hideDialog(self):
		self.wasVisible = self.isVisible
		self.isVisible = False
		self.hide()

	def getWasVisible(self):
		return self.wasVisible

	def getIsVisible(self):
		return self.isVisible

	def setPrgsRange(self, range):
		self["progressBar"].setRange(range)

	def setPrgsValue(self, value):
		self["progressBar"].setValue(value)

	def setHeadline(self, text):
		self["headline"].setText(text)

	def setPrgsText(self, text):
		self["progressTxt"].setText(text)

	def setPrgsHeader(self, text):
		self["progressHdr"].setText(text)

	def setKeyYellow(self, text):
		self["key_yellow"].setText(text)

	def setKeyBlue(self, text):
		self["key_blue"].setText(text)


class InfoLine(GUIComponent):
	def __init__(self, screen):
		GUIComponent.__init__(self)
		self.screen = screen
		self.screen.onShow.append(self.onContainerShown)
		self.data = []
		self.font = gFont("Regular", 18)
		self.fontAdditional = gFont("Regular", 18)
		self.foreColorAdditional = 0xffffff
		# self.b_back = LoadPixmap(f"{PLUGINDIR}/images/b_back.png")
		self.star24 = LoadPixmap(f"{PLUGINDIR}/images/star.png")
		self.rt_gt_60 = LoadPixmap(f"{PLUGINDIR}/images/rt60.png")
		self.rt_lt_60 = LoadPixmap(f"{PLUGINDIR}/images/rt59.png")
		self.l = eListboxPythonMultiContent()  # noqa: E741
		self.l.setBuildFunc(self.buildEntry)
		self.spacing = 28
		self.l.setItemHeight(35)
		self.l.setItemWidth(35)

	GUI_WIDGET = eListbox

	def postWidgetCreate(self, instance):
		instance.setSelectionEnable(False)
		instance.setContent(self.l)
		instance.allowNativeKeys(False)

	def onContainerShown(self):
		self.l.setItemHeight(self.instance.size().height())
		self.l.setItemWidth(self.instance.size().width())

	def applySkin(self, desktop, parent):
		attribs = []
		for (attrib, value) in self.skinAttributes[:]:
			if attrib == "font":
				self.font = parseFont(value, parent.scale)
			elif attrib == "fontAdditional":
				self.fontAdditional = parseFont(value, parent.scale)
			elif attrib == "foregroundColor":
				self.foreColor = parseColor(value).argb()
			elif attrib == "foregroundColorAdditional":
				self.foreColorAdditional = parseColor(value).argb()
			elif attrib == "spacing":
				self.spacing = int(value)
			else:
				attribs.append((attrib, value))
		self.skinAttributes = attribs
		self.l.setFont(0, self.font)
		self.l.setFont(1, self.fontAdditional)
		self.instance.setOrientation(eListbox.orHorizontal)
		self.l.setOrientation(eListbox.orHorizontal)
		return GUIComponent.applySkin(self, desktop, parent)

	def updateInfo(self, item):
		l_list = []
		l_list.append((item,))
		self.l.setList(l_list)

	def _calcTextWidth(self, text, font=None, size=None):
		size = eLabel.calculateTextSize(font, text, size)
		res_width = size.width()
		res_height = size.height()
		return res_width, res_height

	def getDesktopWith(self):
		return getDesktop(0).size().width()

	def getSize(self):
		s = self.instance.size()
		return s.width(), s.height()

	def constructLabelBox(self, res, text, height, xPos, yPos, spacing=None, borderColor=0x757472, backColor=0x55111111, textColor=0xffffff):
		if not spacing:
			spacing = self.spacing

		textWidth, textHeight = self._calcTextWidth(text, font=self.fontAdditional, size=eSize(self.getDesktopWith() // 3, 0))
		rec_height = textHeight + 10

		res.append(MultiContentEntryText(
			pos=(xPos + 2, yPos + (height - rec_height) // 2 + 1), size=(textWidth + 26, rec_height - 4),
			font=1, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER,
			text=text,
			cornerRadius=6,
			border_color=borderColor, border_width=2,
			backcolor=backColor, backcolor_sel=backColor,
			color=textColor, color_sel=textColor))
		xPos += spacing + textWidth + 30
		return xPos

	def buildEntry(self, item):
		xPos = 0
		yPos = 0
		height = self.instance.size().height()
		res = [None]

		dates = item.get("Year")
		user_rating = int(item.get("CommunityRating", "0"))  # IMDB
		critics_rating = int(item.get("CriticRating", "0"))  # Rotten
		mpaa = item.get("OfficialRating", None)  # FSK
		runtime = item.get("Runtime")
		genres = item.get("Genres")

		if user_rating:
			pixd_size = self.star24.size()
			pixd_width = pixd_size.width()
			pixd_height = pixd_size.height()
			res.append(MultiContentEntryPixmapAlphaBlend(
				pos=(xPos, yPos - 2 + (height - pixd_height) // 2),
				size=(pixd_width, height),
				png=self.star24,
				backcolor=None, backcolor_sel=None,
				flags=BT_SCALE | BT_KEEP_ASPECT_RATIO))
			xPos += 7 + pixd_width

			user_rating_str = f" {user_rating:.1f}"

			textWidth = self._calcTextWidth(user_rating_str, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]

			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(textWidth, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=user_rating_str,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + textWidth

		if critics_rating:
			rt_icon = self.rt_gt_60
			if critics_rating < 60:
				rt_icon = self.rt_lt_60
			pixd_size = rt_icon.size()
			pixd_width = pixd_size.width()
			pixd_height = pixd_size.height()
			res.append(MultiContentEntryPixmapAlphaBlend(
				pos=(xPos, yPos - 2 + (height - pixd_height) // 2),
				size=(pixd_width, height),
				png=rt_icon,
				backcolor=None, backcolor_sel=None,
				flags=BT_SCALE | BT_KEEP_ASPECT_RATIO))
			xPos += 7 + pixd_width

			critics_rating_str = f" {critics_rating}%"

			textWidth = self._calcTextWidth(critics_rating_str, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]

			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(textWidth, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=critics_rating_str,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + textWidth

		if dates:
			textWidth = self._calcTextWidth(dates, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]

			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(textWidth, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=dates,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + textWidth

		if runtime:
			textWidth = self._calcTextWidth(runtime, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]

			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(textWidth, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=runtime,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + textWidth

		if genres:
			textWidth = self._calcTextWidth(genres, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]

			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(textWidth, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=genres,
				textBColor=0x000000, textBWidth=1,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + textWidth

		if mpaa:
			xPos = self.constructLabelBox(res, mpaa, height, xPos, yPos, None)

		return res


class e2MDBEventViewSimple(Screen):

	skin = """
		<screen name="EventViewSimple" position="0,0" size="1280,720" resolution="1280,720" title="EventviewSimple" flags="wfNoBorder" backgroundColor="#0000000">
			<widget name="backdrop" position="0,0" size="e,e" alphatest="blend" zPosition="-10" scaleFlags="moveRightTop"/>
			<widget name="backdrop_mask" position="0,0" size="e,e" alphatest="blend" zPosition="-9" scaleFlags="moveRightTop"/>
			<widget name="title_logo" position="40,40" size="600,60" alphatest="blend"/>
			<widget name="title" position="40,30" size="600,60" alphatest="blend" font="Regular;50" transparent="1" noWrap="1"/>
			<widget name="infoline" position="40,100" size="600,40" font="Regular;24" fontAdditional="Regular;14" transparent="1"/>

			<widget name="epg_description" position="50,150" size="400,520" font="epg_info;22" scrollbarMode="showOnDemand" foregroundColor="layer-a-foreground" transparent="1" />
			<widget name="channel" position="832,218" size="370,70" font="epg_event;26" halign="center" valign="bottom" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" transparent="1" />
			<eLabel text="Playback Time:" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" noWrap="1" font="screen_info;24" halign="right" position="812,295" size="200,30" transparent="1" />
			<!--
			<widget source="session.CurrentService" render="Label" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" font="screen_info;24" halign="right" position="1012,295" size="80,30" transparent="1">
				<convert type="MetrixHDServiceTime">StartTime</convert>
			</widget>
			<eLabel backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" font="screen_info;24" halign="center" position="1090,295" size="30,30" text="-" transparent="1" />
			<widget source="session.CurrentService" render="Label" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" font="screen_info;24" halign="left" position="1118,295" size="80,30" transparent="1">
				<convert type="MetrixHDServiceTime">EndTime</convert>
			</widget>
			<widget source="Service" render="Picon" position="907,80" size="220,132" zPosition="5" transparent="1" alphatest="blend">
				<convert type="MovieInfo">RecordServiceRef</convert>
			</widget>
			<eLabel position="859,330" size="315,1" backgroundColor="layer-b-accent1" />
			<widget source="session.CurrentService" render="Progress" position="859,328" size="315,5" foregroundColor="layer-b-progress" transparent="1" zPosition="1">
				<convert type="ServicePosition">Position</convert>
			</widget>
			<widget name="datetime" position="882,350" size="270,40" font="screen_info;24" halign="center" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" transparent="1" />
			<widget name="duration" position="882,390" size="270,40" font="screen_info;24" halign="center" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" transparent="1" />
			<widget source="Service" render="Label" position="882,430" size="270,40" font="screen_info;24" halign="center" backgroundColor="layer-b-background" foregroundColor="layer-b-foreground" transparent="1">
				<convert type="MovieInfo">FileSize</convert>
			</widget>
			<ePixmap alphatest="blend" pixmap="icons/ico_dolby_off.png" position="942,490" size="34,23" zPosition="1"/>
			<widget alphatest="blend" pixmap="icons/ico_dolby_on.png" position="942,490" render="Pixmap" size="34,23" source="session.CurrentService" zPosition="2">
				<convert type="ServiceInfo">IsMultichannel</convert>
				<convert type="ConditionalShowHide"/>
			</widget>
			<widget alphatest="blend" pixmaps="icons/ico_hd_off.png,icons/ico_hd_on.png,icons/ico_uhd_on.png,icons/ico_hd_hdr_on.png,icons/ico_hdr_on.png,icons/ico_hdr10_on.png,icons/ico_hlg_on.png" position="992,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
				<convert type="MetrixHDServiceInfo2">VideoInfo</convert>
			</widget>
			<ePixmap alphatest="blend" pixmap="icons/ico_format_off.png" position="1059,490" size="43,23" zPosition="1"/>
			<widget alphatest="blend" pixmap="icons/ico_format_on.png" position="1059,490" render="Pixmap" size="43,23" source="session.CurrentService" zPosition="2">
				<convert type="ServiceInfo">IsWidescreen</convert>
				<convert type="ConditionalShowHide"/>
			</widget>
			<panel name="template1_2layer" />
			<panel name="ime-buttons_template1" />
			<eLabel text="Event View" position="5,555" size="1280,180" font="global_large_screen;90" noWrap="0" backgroundColor="text-background" transparent="1" foregroundColor="background-text" valign="bottom" zPosition="-50" />
			-->
		</screen>
	"""

	ADD_TIMER = 0
	REMOVE_TIMER = 1
	NO_ACTION = 2

	def __init__(self, session, event, serviceRef, jsonPath, coverPath, titleLogoPath, backDropPath):
		Screen.__init__(self, session, enableHelp=True)
		self.keyGreenAction = self.NO_ACTION
		self.event = event
		self.serviceRef = serviceRef
		self.isRecording = (not serviceRef.ref.flags & eServiceReference.isGroup) and serviceRef.ref.getPath() and "%3a//" not in serviceRef.ref.toString()
		self.setTitle(_("Event View"))
		self.images = (coverPath, titleLogoPath, backDropPath)
		if isfile(jsonPath):
			with open(jsonPath, "r") as file:
				self.jsonData = load(file)
		else:
			self.jsonData = {}

		self["title_logo"] = Pixmap()
		self["title"] = Label()
		self["backdrop"] = Pixmap()
		self["backdrop_mask"] = Pixmap()
		self["infoline"] = InfoLine(self)
		self["Service"] = ServiceEvent()
		self["Event"] = Event()
		self["epg_description"] = ScrollLabel()
		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))
		self["key_red"] = StaticText("")
		self["key_blue"] = StaticText("")
		self["summary_description"] = StaticText()
		self["datetime"] = Label()
		self["channel"] = Label()
		self["duration"] = Label()
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "EventViewActions", "ColorActions"], {
			"cancel": (self.close, _("Close screen")),
			"ok": (self.close, _("Close screen")),
			# "contextMenu": (self.doContext, _("Open context menu")),
			# "info": (self.close, _("Close screen")),
			"pageUp": (self.pageUp, _("Show previous page")),
			"pageDown": (self.pageDown, _("Show next page")),
			"blue": (self.keyBlue, _("Gater Data"))
		}, prio=0, description=_("Event View Actions"))

		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self.setService(self.serviceRef)
		hasEvent = self.setEvent(self.event)
		if self.jsonData:
			title = self.jsonData.get("title", {}).get("text")
			self["title"].setText(title)
			description = self.jsonData.get("description", {}).get("text")
			genres = self.jsonData.get("genres")
# if genres:
# description = f"{description}\nGenres: {genres}"
			countries = self.jsonData.get("countries")
			if countries:
				description = f"{description}\nCountries: {countries}"
			self["epg_description"].setText(description)

			item = {
				"Year": "2025",
				"OfficialRating": "FSK16",
				"Runtime": "1:12",
				"Genres": genres
			}
			self["infoline"].updateInfo(item)


# if isfile(self.images[0]):
# self["cover"].setPixmap(LoadPixmap(self.images[0]))
		if isfile(self.images[1]):
			self["title_logo"].setPixmap(LoadPixmap(self.images[1]))
			self["title"].setText("")
		if isfile(self.images[2]):
			if True:
				maskAlpha = Image.open(join(PLUGINDIR, "/images/mask_l.png")).convert("RGBA").split()[3]
				if maskAlpha.mode != "L":
					maskAlpha = maskAlpha.convert("L")
				im = Image.open(self.images[2]).convert("RGBA")
				im_width, im_height = im.size
				required_height = im_width // 1.77
				if im_height > required_height:
					im = im.crop((0, 0, im_width, required_height))
				if maskAlpha.size != im.size:
					maskAlpha = maskAlpha.resize(im.size, Image.BOX)
				im.putalpha(maskAlpha)
				im.save("/tmp/backdrop.png", compress_type=3)
				self["backdrop"].setPixmap(LoadPixmap("/tmp/backdrop.png"))
			else:
				self["backdrop"].setPixmap(LoadPixmap(self.images[2]))
				self["backdrop_mask"].setPixmap(LoadPixmap(f"{PLUGINDIR}/images/mask_l_inverted.png"))

	def keyBlue(self):
		pass  # TODO Hier kann man für einenn einzelnen Event die Daten holen falls nicht vorhanden oder für Refresh.

	def pageUp(self):
		self["epg_description"].pageUp()

	def pageDown(self):
		self["epg_description"].pageDown()

	def getCurrentService(self):
		return self.serviceRef

	currentService = property(getCurrentService)  # currentService property to support 3rd party plugins

	def setService(self, service):
		self.serviceRef = service
		self["Service"].newService(service.ref)
		serviceName = service.getServiceName()
		self["channel"].setText(f"{serviceName if serviceName else _("Unknown Service")} - {_("Recording")} if self.isRecording else ""}")

	def setEvent(self, event):
		if event is None or not hasattr(event, "getEventName"):
			return False
		self["Event"].newEvent(event)
		self.event = event
		text = event.getEventName()
		self["title"].setText(text)
		short = event.getShortDescription()
		extended = event.getExtendedDescription()
		if short == text:
			short = ""
		if short and extended and extended.replace("\n", "") == short.replace("\n", ""):
			pass  # extended = extended
		elif short and extended:
			extended = f"{short}\n{extended}"
		elif short:
			extended = short
		if text and extended:
			text += "\n\n"
		text += extended
		self["epg_description"].setText(text)
		self["summary_description"].setText(extended)
		beginTime = event.getBeginTime()
		if not beginTime:
			return
		begin = localtime(beginTime)
		end = localtime(beginTime + event.getDuration())
# self["datetime"].setText("%s - %s" % (strftime("%s, %s" % (config.usage.date.short.value, config.usage.time.short.value), begin), strftime(config.usage.time.short.value, end)))  # TODO: remove after tests
		self["datetime"].setText(f"{strftime("{config.usage.date.short.value}, {config.usage.time.short.value}", begin)} - {strftime(config.usage.time.short.value, end)}")
		self["duration"].setText(_("%d min") % (event.getDuration() / 60))
# if self.keyGreenAction != self.NO_ACTION:
# self.setTimerState()

		return True

	def editTimer(self, timer):
		self.session.open(TimerEntry, timer)

	def timerAdd(self):
		if self.isRecording:
			return
		event = self.event
		serviceref = self.serviceRef
		if event is None:
			return
		eventid = event.getEventId()
		refstr = ":".join(serviceref.ref.toString().split(":")[:11])
		for timer in self.session.nav.RecordTimer.timer_list:
			if timer.eit == eventid and ":".join(timer.service_ref.ref.toString().split(":")[:11]) == refstr:
				# Disable dialog box -> Workaround for non closed dialog when press key GREEN for Delete Timer.  (Crash when again GREEN, BLUE or OK key was pressed.)
				self.editTimer(timer)
				break
		else:
			newEntry = RecordTimerEntry(self.serviceRef, checkOldTimers=True, dirname=preferredTimerPath(), *parseEvent(self.event))
			self.session.openWithCallback(self.finishedAdd, TimerEntry, newEntry)

	def finishedAdd(self, answer):
		print("[EventView] Finished add.")
		if isinstance(answer, bool) and answer:  # Special case for close recursive
			self.close(True)
			return
		if answer[0]:
			entry = answer[1]
			simulTimerList = self.session.nav.RecordTimer.record(entry)
			if simulTimerList is not None:
				for x in simulTimerList:
					if x.setAutoincreaseEnd(entry):
						self.session.nav.RecordTimer.timeChanged(x)
				simulTimerList = self.session.nav.RecordTimer.record(entry)
				if simulTimerList is not None:
					if not entry.repeated and not config.recording.margin_before.value and not config.recording.margin_after.value and len(simulTimerList) > 1:
						change_time = False
						conflict_begin = simulTimerList[1].begin
						conflict_end = simulTimerList[1].end
						if conflict_begin == entry.end:
							entry.end -= 30
							change_time = True
						elif entry.begin == conflict_end:
							entry.begin += 30
							change_time = True
						if change_time:
							simulTimerList = self.session.nav.RecordTimer.record(entry)
					if simulTimerList is not None:
						try:
							from Screens.TimerEdit import TimerSanityConflict
						except Exception:  # maybe already been imported from another module
							pass
						self.session.openWithCallback(self.finishSanityCorrection, TimerSanityConflict, simulTimerList)
			self["key_green"].setText(_("Change Timer"))
			self.keyGreenAction = self.REMOVE_TIMER
		else:
			self["key_green"].setText(_("Add Timer"))
			self.keyGreenAction = self.ADD_TIMER
			print("[EventView] Timer edit aborted.")

	def finishSanityCorrection(self, answer):
		self.finishedAdd(answer)

	def setTimerState(self):
		isRecordEvent = self.doesTimerExist()
		if isRecordEvent and self.keyGreenAction != self.REMOVE_TIMER:
			self["key_green"].setText(_("Change Timer"))
			self.keyGreenAction = self.REMOVE_TIMER
		elif not isRecordEvent and self.keyGreenAction != self.ADD_TIMER:
			self["key_green"].setText(_("Add Timer"))
			self.keyGreenAction = self.ADD_TIMER

	def doesTimerExist(self):
		eventId = self.event.getEventId()
		# begin = self.event.getBeginTime()
		# end = begin + self.event.getDuration()
		refStr = ":".join(self.serviceRef.ref.toString().split(":")[:11])
		isRecordEvent = False
		for timer in self.session.nav.RecordTimer.timer_list:
			neededRef = ":".join(timer.service_ref.ref.toString().split(":")[:11]) == refStr
			# if neededRef and (timer.eit == eventId and (begin < timer.begin <= end or timer.begin <= begin <= timer.end) or timer.repeated and self.session.nav.RecordTimer.isInRepeatTimer(timer, self.event)):
			if neededRef and timer.eit == eventId:
				isRecordEvent = True
				break
		return isRecordEvent

	def doContext(self):
		if self.event:
			menu = []
			for p in plugins.getPlugins(PluginDescriptor.WHERE_EVENTINFO):
				# Only list service or event specific eventinfo plugins here, no servelist plugins.
				if "servicelist" not in p.__call__.__code__.co_varnames:
					menu.append((p.name, boundFunction(self.runPlugin, p)))
			if menu:
				def boxAction(choice):
					if choice:
						choice[1]()

				text = f"{_("Select action")}: {self.event.getEventName()}"
				self.session.openWithCallback(boxAction, ChoiceBox, title=text, list=menu, windowTitle=_("Event View Context Menu"), skin_name="EventViewContextMenuChoiceBox")

	def runPlugin(self, plugin):
		plugin(session=self.session, service=self.serviceRef, event=self.event, eventName=self.event.getEventName())


oldeshowEventInformation = None


def e2MDBshowEventInformation(self):
	path = self.getCurrent().getPath()
	pathWithoutExtension = splitext(path)[0]
	jsonPath = f"{pathWithoutExtension}.json"
	if isfile(jsonPath):
		evt = self["list"].getCurrentEvent()
		coverPath = f"{pathWithoutExtension}.jpg"
		# coverPath = f"{pathWithoutExtension}.cover.jpg"
		backdropPath = f"{pathWithoutExtension}.backdrop.jpg"
		titleLogoPath = f"{pathWithoutExtension}.logo.png"
		self.session.open(e2MDBEventViewSimple, evt, ServiceReference(self.getCurrent()), jsonPath, coverPath, titleLogoPath, backdropPath)
	else:
		oldeshowEventInformation(self)


def setup(session, **kwargs):
	session.open(e2MDBSetup)


class e2MDBBackroundRefresh(e2MDBhelper):
	def __init__(self):
		pass


e2mdbackroundrefresh = e2MDBBackroundRefresh()


def e2MDBServiceEventRefreshData(self):
	service = self.source.service
	info = self.source.info
	event = self.source.event
	if info and service:
		e2mdbackroundrefresh.scanSingleTitle(service, info, None)


def autostart(reason, session):
	global oldeshowEventInformation
	from Screens.MovieSelection import MovieSelection
	oldeshowEventInformation = MovieSelection.showEventInformation
	MovieSelection.showEventInformation = e2MDBshowEventInformation
	# ServiceEvent.refreshData = e2MDBServiceEventRefreshData # TODO Enable for background data refresh.


def menu(menuid, **kwargs):
	if menuid == "mainmenu":  # Starting from main menu.
		return [(_("e2MDB"), setup, "e2mdb", 1)]
	return []


def Plugins(**kwargs):
	return [
		PluginDescriptor(name=_("e2MDB"), description=_("e2MDB"), where=[PluginDescriptor.WHERE_PLUGINMENU], icon="plugin.png", fnc=setup),
		PluginDescriptor(name=_("e2MDB"), description=_("e2MDB"), where=[PluginDescriptor.WHERE_MENU], icon="plugin.png", fnc=menu),
		PluginDescriptor(name=_("e2MDB"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
	]
