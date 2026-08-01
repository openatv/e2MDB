########################################################################################################
# e2MDB by Mr.Servo @OpenATV and jbleyel @OpenATV (c) 2026 - skin & design by stein17 @OpenATV         #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from hashlib import md5
from os import makedirs
from os.path import isfile, isdir, join
from time import localtime, strftime
from PIL import Image
from twisted.internet.reactor import callInThread

# ENIGMA IMPORTS
from enigma import eLabel, eServiceReference, eListboxPythonMultiContent, eListbox, eSize, gFont, RT_HALIGN_CENTER, RT_VALIGN_CENTER, RT_BLEND, BT_SCALE, BT_KEEP_ASPECT_RATIO
from Components.ActionMap import ActionMap, HelpableActionMap
from Components.config import config
from Components.GUIComponent import GUIComponent
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Components.Sources.List import List
from Components.Sources.Event import Event
from Components.Sources.ServiceEvent import ServiceEvent
from Components.Sources.StaticText import StaticText
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from Components.UsageConfig import preferredTimerPath
from Components.PluginComponent import plugins
from Plugins.Plugin import PluginDescriptor
from RecordTimer import RecordTimerEntry, parseEvent
from skin import parseColor, parseFont
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.TimerEntry import TimerEntry
from Tools.BoundFunction import boundFunction
from Tools.LoadPixmap import LoadPixmap

# PLUGIN IMPORTS
from . import e2mdbglobals, write_log, _
from .E2MDBHelper import E2MDBHelper
from .E2MDBDatabase import resultsdb
from .E2MDBSkin import build_eventview_final_dict_from_db


class E2MDBEventViewSimple(Screen, E2MDBHelper):
	skin = """
	<screen name="E2MDBMediaEventView" position="0,0" size="1280,720" resolution="1280,720" title="EventviewSimple" flags="wfNoBorder" backgroundColor="#0000000">
		<widget name="backdrop" position="160,0" size="e,e" alphatest="blend" zPosition="-10" scaleFlags="centerScaled" cornerRadius="40" />
		<widget name="titlelogo" position="40,20" size="960,60" alphatest="blend" scaleFlags="leftTop" />
		<widget source="title" render="Label" position="40,20" size="960,60" font="Regular;46" backgroundColor="black" foregroundColor="#efefef" transparent="1" noWrap="1" textBorderColor="black" textBorderWidth="2" />
		<widget source="subtitle" render="Label" position="40,80" size="960,40" font="Regular;32" backgroundColor="black" foregroundColor="#efefef" transparent="1" noWrap="1" textBorderColor="black" textBorderWidth="2" />
		<widget name="image" position="950,60" size="300,200" alphatest="blend" scaleFlags="leftTop" cornerRadius="16"/>
		<widget name="cover" position="950,400" size="300,300" alphatest="blend" scaleFlags="rightTop" cornerRadius="16" />
		<widget name="infoline" position="40,140" size="960,40" font="Regular;24" fontAdditional="Regular;14" transparent="1" borderWidth="2" borderColor="black" />
		<widget name="description" position="50,190" size="720,504" font="Regular;22" transparent="1" backgroundColor="black" foregroundColor="#efefef" textBorderColor="black" textBorderWidth="2" scrollbarMode="showNever" />
	</screen>
	"""

	ADD_TIMER = 0
	REMOVE_TIMER = 1
	NO_ACTION = 2

	def __init__(self, session, event, serviceRef, org_path, json_path):
		Screen.__init__(self, session, enableHelp=True)
		self.keyGreenAction = self.NO_ACTION
		self.event = event
		self.serviceRef = serviceRef
		self.org_path = org_path
		if event and hasattr(event, "getEventName"):
			self.org_title = event.getEventName()
		self.json_path = json_path
		self.isRecording = (not serviceRef.ref.flags & eServiceReference.isGroup) and serviceRef.ref.getPath() and "%3a//" not in serviceRef.ref.toString()
		self.setTitle(_("Event View"))
		self["Event"] = Event()
		for widget in ["title", "subtitle", "datetime", "channel", "runtime"]:  # staticText widgets used by the skin
			self[widget] = StaticText()
		for widget in ("cover", "backdrop", "titlelogo", "image"):  # pixmap widgets used by the skin
			self[widget] = Pixmap()
		self.skin, self.skinName = self.skin, "E2MDBMediaEventView"
		self["description"] = ScrollLabel()
		service_source = ServiceEvent()
		self["service"] = service_source
		self["Service"] = service_source
		self["infoline"] = InfoLine(self)
		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))
		self["key_red"] = StaticText()
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "EventViewActions", "ColorActions"], {
			"cancel": (self.close, _("Close screen")),
			"ok": (self.close, _("Close screen")),
			# "contextMenu": (self.doContext, _("Open context menu")),
			# "info": (self.close, _("Close screen")),
			"pageUp": (self.pageUp, _("Show previous page")),
			"pageDown": (self.pageDown, _("Show next page")),
		}, prio=0, description=_("Event View Actions"))
		self.onLayoutFinish.append(self.layoutFinished)

	def pageUp(self):
		try:
			self["description"].pageUp()
		except Exception as err_msg:
			write_log(f"[E2MDBEventViewSimple] pageUp failed: {err_msg}")

	def pageDown(self):
		try:
			self["description"].pageDown()
		except Exception as err_msg:
			write_log(f"[E2MDBEventViewSimple] pageDown failed: {err_msg}")

	def _service_source_ref(self, service):
		try:
			ref = getattr(service, "ref", None)
			if ref is not None:
				return ref
		except Exception:
			pass
		return service

	def setService(self, service):
		self.serviceRef = service
		service_ref = self._service_source_ref(service)
		try:
			self["service"].newService(service_ref, self.event)
		except Exception as err_msg:
			write_log(f"[E2MDBEventViewSimple] setService failed: {err_msg}")

	def setEvent(self, event):
		self.event = event
		try:
			self["Event"].newEvent(event)
		except Exception as err_msg:
			write_log(f"[E2MDBEventViewSimple] setEvent source update failed: {err_msg}")
		try:
			self["service"].newService(self._service_source_ref(self.serviceRef), event)
		except Exception:
			pass


	def _service_ref_string(self):
		try:
			ref = getattr(self.serviceRef, "ref", None)
			if ref is not None and hasattr(ref, "toString"):
				return ref.toString()
		except Exception:
			pass
		try:
			if hasattr(self.serviceRef, "toString"):
				return self.serviceRef.toString()
		except Exception:
			pass
		return str(self.serviceRef or "")

	def _load_final_dict_from_db(self):
		# First try exact EPG/Live data, then fall back to final media metadata
		# for recordings/movies that are opened through EventViewSimple.
		row = {}
		if self.event:
			try:
				event_id = self.event.getEventId() if hasattr(self.event, "getEventId") else 0
			except Exception:
				event_id = 0
			try:
				begin_time = self.event.getBeginTime() if hasattr(self.event, "getBeginTime") else 0
			except Exception:
				begin_time = 0
			try:
				title = self.event.getEventName() if hasattr(self.event, "getEventName") else ""
			except Exception:
				title = ""
			row = resultsdb.get_epg_event_for_service(self._service_ref_string(), event_id=event_id, begin_time=begin_time, title=title)
			if row:
				write_log("[E2MDBEventViewSimple] DB display metadata source=epg")
				return build_eventview_final_dict_from_db(event_row=row)
		try:
			media_hash = self.get_reduced_org_hash(self.org_path)
			row = resultsdb.get_media_metadata(media_hash)
			if not row and hasattr(resultsdb, "get_media_metadata_by_path"):
				row = resultsdb.get_media_metadata_by_path(self.org_path)
			if row and (row.get("metadata_title") or row.get("metadata_overview") or row.get("metadata_cover_path") or row.get("metadata_backdrop_path") or row.get("metadata_image_path") or row.get("artwork_poster_path") or row.get("artwork_backdrop_path") or row.get("artwork_episode_path")):
				write_log(f"[E2MDBEventViewSimple] DB display metadata source=media path={self.org_path} hash={media_hash}")
				return build_eventview_final_dict_from_db(event_row=row)
		except Exception as err:
			write_log(f"[E2MDBEventViewSimple] DB media metadata lookup failed: {err}")
		return {}

	def layoutFinished(self):
		def get_picture_path(pic_type):
			pic_path = final_dict.get(f"{pic_type}_path", "")
			if pic_path:
				pic_path = self.get_full_org_path(pic_path)
			return pic_path
		self.setService(self.serviceRef)
		self.setEvent(self.event)  # TODO: can response 'hasEvent' be deleted in function?
		final_dict = self._load_final_dict_from_db()
		if not final_dict:
			write_log("[E2MDBEventViewSimple] DB display metadata not found; JSON is not used for EventView display")
			return

		if final_dict:
			media_type = _(final_dict.get("media_type", ""))
			runtime = final_dict.get("runtime", "")
			runtime = f"{runtime} {_('min')}" if runtime else ""
			age_rating = final_dict.get("age_rating", "")
			vote_average = final_dict.get("vote_average", "")
			provider = final_dict.get("provider", "")
			crew_dict = {}
			white_list = [("director", _("Director")), ("writer", _("Writer")), ("novel", _("Novel")), ("music", _("Music"))]
			job_filter = [job[0] for job in white_list]
			for member in final_dict.get("crew", []):
				job = member.get("job", "")
				if job.lower() in job_filter:  # filter jobs of interest only
					persons = crew_dict.get(job, [])
					persons.append(member.get("name", ""))  # collect all names for each qualified job
					crew_dict[job] = persons
			crew_short, crew_long = "", ""
			for job, names in crew_dict.items():
				crew_short += f"{job}: {', '.join(names)}\n"
				crew_long += f"{job}:\t{', '.join(names)}\n"
			cast_long, cast_list = "", []
			for index, member in enumerate(final_dict.get("cast", [])):
				if not index:  # if very first member
					cast_long += f"{_('Actors')}:\n"
				cast_long += f"{member.get('name', {_('unkown')})} {_('as')} '{member.get('character', {_('unkown')})}'\n"
				cast_list.append(f"{member.get('name', {_('unkown')})}")
			cast_short = f"*{_('Actors')}: "
			cast_short += ", ".join(cast_list)
			# feeds widgets used by the skin
			self["title"].setText(final_dict.get("title", ""))
			self["subtitle"].setText(final_dict.get("episode_name", "") or final_dict.get("tagline", ""))
			self["runtime"].setText(runtime)
			desc_short = final_dict.get("overview", "")
			desc_long = f"{desc_short}\n\n{crew_long}\n{cast_long}"
			self["description"].setText(desc_long)
			item_dict = {}  # data for infoline
			self.set_dict_key(item_dict, "media_type", media_type)
			self.set_dict_key(item_dict, "countries", final_dict.get("countries", ""))
			self.set_dict_key(item_dict, "released", final_dict.get("released", "")[:4])
			self.set_dict_key(item_dict, "genres", final_dict.get("genres", ""))
			season_no, episode_no = final_dict.get("season_no", ""), final_dict.get("episode_no", "")
			desc_list = []
			if season_no and episode_no:
				desc_list.append(f"{_('Season')} {season_no} / {_('Episode')} {episode_no}")
			self.set_dict_key(item_dict, "season_epsiode", ", ".join(desc_list))
			self.set_dict_key(item_dict, "runtime", runtime)
			self.set_dict_key(item_dict, "age_rating", age_rating)
			self.set_dict_key(item_dict, "vote_average", vote_average)
			self.set_dict_key(item_dict, "provider", provider)
			self["infoline"].updateInfo(item_dict)
			backdrop_path = get_picture_path("backdrop")
			if backdrop_path and isfile(backdrop_path):
				try:
					mask_alpha = Image.open(join(e2mdbglobals.PLUGINDIR, "images", "mask_l.png")).convert("RGBA").split()[3]
					if mask_alpha.mode != "L":
						mask_alpha = mask_alpha.convert("L")
					img = Image.open(backdrop_path).convert("RGBA")
					im_width, im_height = img.size
					required_height = im_width // 1.77
					if im_height > required_height:
						img = img.crop((0, 0, im_width, required_height))
					if mask_alpha.size != img.size:
						mask_alpha = mask_alpha.resize(img.size, Image.BOX)
					img.putalpha(mask_alpha)
					img.save("/tmp/backdrop.png", compress_type=3)
					self["backdrop"].instance.setPixmapFromFile("/tmp/backdrop.png")
				except Exception as err_msg:
					write_log(f"[E2MDBEventViewSimple] ERROR in module 'layoutFinished': {err_msg}")
			else:  # use default backdrop
				self["backdrop"].instance.setPixmapFromFile(f"{e2mdbglobals.PLUGINDIR}/images/backdrop.png")
			cover_path = get_picture_path("cover")
			if cover_path and isfile(cover_path):
				self["cover"].instance.setPixmapFromFile(cover_path)
			titlelogo_path = get_picture_path("titlelogo")
			if titlelogo_path and isfile(titlelogo_path):
				self["titlelogo"].instance.setPixmapFromFile(titlelogo_path)
				self["title"].setText("")
			image_path = get_picture_path("image")
			if image_path and isfile(image_path):
				self["image"].instance.setPixmapFromFile(image_path)



class E2MDBEventSelection(E2MDBHelper, Screen):
	skin = """
	<screen name="E2MDBEventSelection" position="10,10" size="1260,700" flags="wfNoBorder" resolution="1280,720" backgroundColor="#16000000" title="e2MDB Event Selection">
		<widget source="searchtitle" render="Label" position="6,4" size="980,36" font="Regular;24" textBorderColor="#00505050" textBorderWidth="1" foregroundColor="#00ffff00" backgroundColor="#16000000" valign="center" zPosition="12" transparent="1" />
		<widget source="short_desc" render="Label" position="6,40" size="980,20" font="Regular;18" textBorderColor="#00505050" textBorderWidth="1" foregroundColor="#00ffff00" backgroundColor="#16000000" valign="center" zPosition="12" transparent="1" />
		<widget source="global.CurrentTime" render="Label" position="1110,0" size="140,60" font="Regular;46" noWrap="1" halign="center" valign="bottom" foregroundColor="white" backgroundColor="#16000000" zPosition="12" transparent="1">
			<convert type="ClockToText">Default</convert>
		</widget>
		<widget source="global.CurrentTime" render="Label" position="1000,2" size="100,26" font="Regular;16" noWrap="1" halign="right" valign="bottom" foregroundColor="white" backgroundColor="#16000000" zPosition="12" transparent="1">
			<convert type="ClockToText">Format:%A</convert>
		</widget>
		<widget source="global.CurrentTime" render="Label" position="1000,26" size="100,26" font="Regular;16" noWrap="1" halign="right" valign="bottom" foregroundColor="white" backgroundColor="#16000000" zPosition="12" transparent="1">
			<convert type="ClockToText">Format:%e. %B</convert>
		</widget>
		<widget source="menuList" render="Listbox" position="4,70" size="1252,576" enableWrapAround="1" foregroundColorSelected="white" backgroundColor="#16000000" transparent="1" scrollbarMode="showOnDemand">
			<convert type="TemplatedMultiContent">{"template": [
				MultiContentEntryText(pos=(6,2), size=(814,28), font=0, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=0),  # title
				MultiContentEntryText(pos=(824,0), size=(44,16), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=1),  # countries
				MultiContentEntryText(pos=(874,0), size=(64,16), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=2),  # mediaType
				MultiContentEntryText(pos=(934,0), size=(104,16), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=3),  # genres
				MultiContentEntryText(pos=(1044,0), size=(24,16), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=4),  # vote_average
				MultiContentEntryText(pos=(1084,0), size=(34,16), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=5),  # provider
				MultiContentEntryText(pos=(6,28), size=(1158,64), font=1, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_WRAP, color=0x00ffff, text=6),  # overview
				MultiContentEntryPixmapAlphaBlend(pos=(1164,2), size=(62,92), flags=BT_HALIGN_CENTER|BT_VALIGN_CENTER|BT_SCALE|BT_KEEP_ASPECT_RATIO, png=7)  # cover
				],
				"fonts": [gFont("Regular",20),gFont("Regular",18),gFont("Regular",16)],
				"itemHeight":96
				}
			</convert>
		</widget>
		<widget source="key_red" render="Label" position="20,666" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,664" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,666" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,666" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,664" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,666" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,666" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,664" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,666" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel text="MENU" position="742,666" size="76,26" zPosition="1" font="Regular; 16" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="menu_bg" position="740,664" size="80,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="menu_bg_center" position="742,666" size="76,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="4,64" size="1252,1" backgroundColor="grey" />
		<eLabel name="line" position="4,654" size="1252,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session, results_dict, org_path):
		self.session = session
		self.org_path = org_path
		Screen.__init__(self, session)
		self.todo_covers = []
		self["searchtitle"] = StaticText()
		self["short_desc"] = StaticText()
		self["menuList"] = List()
		self["key_red"] = StaticText()
		self["key_green"] = StaticText("Select")
		self["key_yellow"] = StaticText()
		self["actions"] = ActionMap(["OkCancelActions", "ButtonSetupActions"], {
			"ok": self.keyOk,
#			"red": self.keyRed,
			"green": self.keyGreen,
#			"yellow": self.openEPGSearch,
#			"blue": self.zapToCurrent,
#			"channeldown": self.prevDay,
#			"channelup": self.nextDay,
#			"previous": self.prevweek,
#			"next": self.nextweek,
#			"info": self.keyInfo,
			"cancel": self.keyExit
		}, -1)
		self.results = results_dict.get("results", [])
		self.search_data = results_dict.get("search_data", {})
		self.onLayoutFinish.append(self.refresh_menulist)

	def refresh_menulist(self):
#		self["menuList"].onSelectionChanged.append(self.showCurrentAsset)  # TODO: wird wahrscheinlich nicht gebraucht
		self["searchtitle"].setText(self.search_data.get("search_title", ""))
		self["short_desc"].setText(self.search_data.get("short_desc", ""))

		skin_list, self.todo_covers = [], []
		for result in self.results:
			title = result.get("title", "")
			if not title:
				continue
			season_no = result.get("season_no", "")
			season_no = int(season_no) if season_no.isdigit() else ""
			episode_no = result.get("episode_no", "")
			episode_no = int(episode_no) if episode_no.isdigit() else ""
			if season_no and episode_no:
				title += f" | S{(season_no):02d}E{episode_no:02d}"
			episode_name = result.get("episode_name", "")
			if episode_name:
				title += f" | {episode_name}"
			released = result.get("released", "")
			if released:
				title += f" | ({released})"
			countries = result.get("countries", "")
			media_type = result.get("media_type", "")
			genres = result.get("genres", "")
			vote_average = result.get("vote_average", "")
			provider = result.get("provider", "")
			overview = result.get("overview", "")
			cover_url = result.get("cover_url", "")
			extension = cover_url[cover_url.rfind(".") + 1:]  # 'jpg' or 'png'
			tmp_path = join(e2mdbglobals.TEMPDIR, "covers")
			cover_path = join(tmp_path, f"{md5(cover_url.encode()).hexdigest()}.{extension}")
			coverpix = None
			if not isdir(tmp_path):
				makedirs(tmp_path)
			if isfile(cover_path):
				coverpix = LoadPixmap(cached=True, path=cover_path)
			else:
				if cover_url and (cover_path not in self.todo_covers):
					self.todo_covers.append(cover_path)
					callInThread(self.image_download, cover_url, cover_path, callback=self.image_downloadCb, fail=lambda error: write_log(f"{self.MODULE_NAME} ERROR in module 'refresh_menulist': {error}"))  # download + store image
			skin_list.append((title, countries, media_type, genres, vote_average, provider, overview, coverpix))
		self["menuList"].updateList(skin_list)

	def image_downloadCb(self, cover_path):
		if cover_path in self.todo_covers:
			self.todo_covers.remove(cover_path)
		self.refresh_menulist()

	def keyGreen(self):
		curr_index = min(self["menuList"].getCurrentIndex(), len(self.results) - 1)
		self.close(self.results[curr_index])

	def keyOk(self):
		pass

	def keyExit(self):
		self.close()


class InfoLine(GUIComponent):
	def __init__(self, screen):
		GUIComponent.__init__(self)
		self.screen = screen
		self.screen.onShow.append(self.onContainerShown)
		self.data = []
		self.font = gFont("Regular", 18)
		self.fontAdditional = gFont("Regular", 18)
		self.foreColorAdditional = 0xffffff
		# self.b_back = LoadPixmap(f"{e2mdbglobals.PLUGINDIR}/images/b_back.png")
		self.star24 = LoadPixmap(f"{e2mdbglobals.PLUGINDIR}/images/star.png")
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
		from enigma import getDesktop
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
			pos=(xPos + 2, yPos + (height - rec_height) // 2 + 1),
			size=(textWidth + 26, rec_height - 4),
			font=1,
			flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER,
			text=text,
			cornerRadius=6,
			border_color=borderColor,
			border_width=2,
			backcolor=backColor,
			backcolor_sel=backColor,
			color=textColor,
			color_sel=textColor
			))
		return textWidth + 30

	def buildEntry(self, item_dict):
		def buildMultiContentEntryText(text, color=0xffffff, color_sel=0xffffff):
			text_width = self._calcTextWidth(text, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]
			res.append(MultiContentEntryText(
				pos=(xPos, yPos),
				size=(text_width, height),
				font=0,
				flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=text,
				color=color,
				color_sel=color_sel
				))
			return text_width

		xPos, yPos = 0, 0
		height = self.instance.size().height()
		res = [None]
		countries = item_dict.get("countries")
		released = item_dict.get("released")
		media_type = item_dict.get("media_type")
		genres = item_dict.get("genres")
		season_episode = item_dict.get("season_epsiode")
		runtime = item_dict.get("runtime")
		age_rating = item_dict.get("age_rating", "")
		provider = item_dict.get("provider", "")
		vote_average = float(item_dict.get("vote_average", "0.0"))  # IMDB-Rating
		if vote_average:
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
			user_rating_str = f" {vote_average:.1f}"
			text_width = self._calcTextWidth(user_rating_str, font=self.font, size=eSize(self.getDesktopWith() // 3, 0))[0]
			res.append(MultiContentEntryText(
				pos=(xPos, yPos), size=(text_width, height),
				font=0, flags=RT_HALIGN_CENTER | RT_BLEND | RT_VALIGN_CENTER,
				text=user_rating_str,
				color=0xffffff, color_sel=0xffffff))
			xPos += self.spacing + text_width
		if countries:
			xPos += self.spacing + buildMultiContentEntryText(countries)
		if released:
			xPos += self.spacing + buildMultiContentEntryText(released)
		if genres:
			xPos += self.spacing + buildMultiContentEntryText(genres)
		if season_episode:
			xPos += self.spacing + buildMultiContentEntryText(season_episode)
		if runtime:
			xPos += self.spacing + buildMultiContentEntryText(runtime)
		if age_rating:
			xPos += self.spacing + self.constructLabelBox(res, age_rating, height, xPos, yPos, None)
		if media_type:
			xPos += self.spacing + self.constructLabelBox(res, media_type, height, xPos, yPos, None)
		if provider:
			xPos += self.spacing + self.constructLabelBox(res, provider, height, xPos, yPos, None)
		return res
