########################################################################################################
# e2MDB Live/EPG EventView screen                                                                      #
# -----------------------------------------------------------------------------------------------------#
# Optional replacement for OpenATV EventViewSimple/EventViewEPGSelect. It keeps the OpenATV EventView   #
# behaviour and adds e2MDB Live/EPG skin sources only when selected through the e2MDB EventView mode.   #
########################################################################################################

# ENIGMA IMPORTS
from Components.config import NoSave, ConfigYesNo
from Components.Sources.StaticText import StaticText
from Screens.EventView import EventViewEPGSelect, EventViewSimple

# PLUGIN IMPORTS
from . import write_log, _
from .E2MDBEventViewBridge import E2MDBEventViewBridge
from .E2MDBSkin import ensure_epg_skin_sources


def _select_e2mdb_eventview_skin(screen):
	screen.skin = E2MDBEventViewEPG.skin
	screen.skinName = "E2MDBEventView"


def _attach_e2mdb_eventview(screen):
	try:
		screen._e2mdb_eventview_bridge = E2MDBEventViewBridge(screen)
		if hasattr(screen, "onClose"):
			screen.onClose.append(screen._e2mdb_eventview_bridge.close)
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] EPG screen bridge attach failed: {err}")


def _update_e2mdb_eventview(screen, reason="eventview"):
	try:
		bridge = getattr(screen, "_e2mdb_eventview_bridge", None)
		if bridge:
			bridge.update(reason=reason)
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] EPG screen update failed reason={reason} error={err}")


def _event_description_without_title(event):
	if event is None or not hasattr(event, "getEventName"):
		return ""
	try:
		name = event.getEventName() or ""
		short = event.getShortDescription() or ""
		extended = event.getExtendedDescription() or ""
	except Exception:
		return ""
	if short == name:
		short = ""
	if short and extended and extended.replace("\n", "") == short.replace("\n", ""):
		return extended
	if short and extended:
		return "%s\n%s" % (short, extended)
	return short or extended or name


def _source_text(screen, source_name):
	try:
		source = screen[source_name]
	except Exception:
		return ""
	try:
		return source.getText() or ""
	except Exception:
		try:
			return source.text or ""
		except Exception:
			return ""

def _ensure_neutral_button_sources(screen):
	for widget in ("key_red", "key_green", "key_yellow", "key_blue"):
		try:
			screen[widget]
		except Exception:
			screen[widget] = StaticText("")


class E2MDBEventViewEPG(EventViewSimple):
	"""Skinned e2MDB EventView for simple live/EPG events.

	The constructor intentionally matches Screens.EventView.EventViewSimple so the
	OpenATV EventView dispatcher can switch between the standard and e2MDB screen
	without changing the caller.
	"""

	skin = """
	<screen name="E2MDBEventView" position="0,0" size="1280,720" resolution="1280,720" title="Eventview" flags="wfNoBorder" backgroundColor="#000000">
		<eLabel name="right_panel" position="805,0" size="475,652" backgroundColor="#000000" zPosition="-30" />
		<eLabel name="bottom_panel" position="0,652" size="1280,68" backgroundColor="#000000" zPosition="-25" />
		<eLabel name="split_line" position="805,0" size="1,652" backgroundColor="#303030" zPosition="-5" />

		<widget source="e2mdb_backdrop" render="Pixmap" position="40,235" size="765,401" alphatest="blend" zPosition="-10" scaleFlags="fill" />
		<widget source="e2mdb_backdrop_gradient" render="Rectangle" backgroundColor="black,transparent,vertical,1" position="40,0" size="765,636" zPosition="-9">
			<convert type="ConditionalShowHide" />
		</widget>

		<widget source="e2mdb_title" render="Label" position="70,48" size="700,44" font="Regular;32" noWrap="1" backgroundColor="black" foregroundColor="#efefef" transparent="1" textBorderColor="black" textBorderWidth="2" />
		<widget source="e2mdb_subtitle" render="Label" position="70,96" size="700,36" font="Regular;24" noWrap="1" backgroundColor="black" foregroundColor="#efefef" transparent="1" textBorderColor="black" textBorderWidth="2" />
		<widget source="e2mdb_infoline" render="Label" position="70,138" size="700,32" font="Regular;20" noWrap="1" backgroundColor="black" foregroundColor="#dfdfdf" transparent="1" textBorderColor="black" textBorderWidth="2" />
		<widget name="epg_description" position="70,195" size="700,260" font="Regular;22" transparent="1" backgroundColor="black" foregroundColor="#efefef" textBorderColor="black" textBorderWidth="2" scrollbarMode="showNever" />

		<widget source="e2mdb_cover" render="Pixmap" position="677,462" size="128,190" alphatest="blend" zPosition="35" scaleFlags="fill" />

		<widget source="global.CurrentTime" render="Label" position="1120,18" size="140,54" font="Regular;44" noWrap="1" halign="right" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1">
			<convert type="ClockToText">Default</convert>
		</widget>
		<widget source="global.CurrentTime" render="Label" position="1000,20" size="110,24" font="Regular;18" noWrap="1" halign="right" valign="bottom" foregroundColor="#dfdfdf" backgroundColor="black" transparent="1">
			<convert type="ClockToText">Format:%A</convert>
		</widget>
		<widget source="global.CurrentTime" render="Label" position="1000,46" size="110,24" font="Regular;18" noWrap="1" halign="right" valign="bottom" foregroundColor="#dfdfdf" backgroundColor="black" transparent="1">
			<convert type="ClockToText">Format:%e. %B</convert>
		</widget>

		<widget source="e2mdb_imageOrPicon" render="Pixmap" position="887,80" size="220,132" alphatest="blend" zPosition="6" scaleFlags="fill" />
		<widget name="channel" position="832,212" size="370,70" font="Regular;28" halign="center" valign="bottom" backgroundColor="black" foregroundColor="#efefef" transparent="1" />
		<eLabel position="859,310" size="315,1" backgroundColor="#80808080" />
		<widget source="Service" render="Progress" position="859,308" size="315,5" foregroundColor="#efefef" backgroundColor="#202020" transparent="1" zPosition="1">
			<convert type="EventTime">Progress</convert>
		</widget>
		<widget name="datetime" position="882,337" size="270,40" font="Regular;24" halign="center" valign="center" backgroundColor="black" foregroundColor="#efefef" transparent="1" />
		<eLabel text="&lt;" position="825,330" size="36,48" zPosition="10" font="Regular;44" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />
		<eLabel text="&gt;" position="1174,330" size="36,48" zPosition="10" font="Regular;44" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />
		<widget name="duration" position="882,392" size="270,40" font="Regular;24" halign="center" valign="center" backgroundColor="black" foregroundColor="#efefef" transparent="1" />

		<ePixmap alphatest="blend" pixmap="icons/subtitle_off.png" position="829,490" size="31,23" />
		<widget alphatest="blend" pixmap="icons/subtitle_on.png" position="829,490" render="Pixmap" size="31,23" source="session.CurrentService" zPosition="1">
			<convert type="ServiceInfo">SubservicesAvailable</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<ePixmap alphatest="blend" pixmap="icons/ico_hbbtv_off.png" position="874,490" size="64,24" zPosition="1" />
		<widget alphatest="blend" pixmap="icons/ico_hbbtv_on.png" position="874,490" render="Pixmap" size="64,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">HasHBBTV</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<ePixmap alphatest="blend" pixmap="icons/ico_txt_off.png" position="953,490" size="30,23" zPosition="1" />
		<widget alphatest="blend" pixmap="icons/ico_txt_on.png" position="953,490" render="Pixmap" size="30,23" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">HasTelext</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<ePixmap alphatest="blend" pixmap="icons/ico_dolby_off.png" position="997,490" size="34,23" zPosition="1" />
		<widget alphatest="blend" pixmap="icons/ico_dolby_on.png" position="997,490" render="Pixmap" size="34,23" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsMultichannel</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hd_off.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsSD</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hd_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsHD</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_uhd_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">Is4K</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hd_hdr_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsHDHDR</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hdr_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsHDR</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hdr10_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsHDR10</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<widget alphatest="blend" pixmap="icons/ico_hlg_on.png" position="1047,490" render="Pixmap" size="49,24" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsHLG</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<ePixmap alphatest="blend" pixmap="icons/ico_format_off.png" position="1108,490" size="43,23" zPosition="1" />
		<widget alphatest="blend" pixmap="icons/ico_format_on.png" position="1108,490" render="Pixmap" size="43,23" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsWidescreen</convert>
			<convert type="ConditionalShowHide" />
		</widget>
		<ePixmap alphatest="blend" pixmap="icons/ico_crypt_off.png" position="1167,490" size="37,23" zPosition="1" />
		<widget alphatest="blend" pixmap="icons/ico_crypt_on.png" position="1167,490" render="Pixmap" size="37,23" source="session.CurrentService" zPosition="2">
			<convert type="ServiceInfo">IsCrypted</convert>
			<convert type="ConditionalShowHide" />
		</widget>

		<eLabel name="red_key_bg" position="20,666" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_key_inner" position="22,668" size="166,26" backgroundColor="#000000" cornerRadius="4" zPosition="-1" />
		<widget source="key_red" render="Label" position="22,668" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />
		<eLabel name="green_key_bg" position="200,666" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_key_inner" position="202,668" size="166,26" backgroundColor="#000000" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="202,668" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_key_bg" position="380,666" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_key_inner" position="382,668" size="166,26" backgroundColor="#000000" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="382,668" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />
		<eLabel name="blue_key_bg" position="560,666" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_key_inner" position="562,668" size="166,26" backgroundColor="#000000" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="562,668" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="black" transparent="1" />

		<eLabel name="info_key_bg" position="926,662" size="82,42" backgroundColor="#000000" cornerRadius="2" borderWidth="2" borderColor="#efefef" zPosition="-1" />
		<eLabel text="INFO" position="926,662" size="82,42" zPosition="1" font="Regular;22" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="#000000" />
		<eLabel name="menu_key_bg" position="1020,662" size="92,42" backgroundColor="#000000" cornerRadius="2" borderWidth="2" borderColor="#efefef" zPosition="-1" />
		<eLabel text="MENU" position="1020,662" size="92,42" zPosition="1" font="Regular;22" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="#000000" />
		<eLabel name="exit_key_bg" position="1124,662" size="92,42" backgroundColor="#000000" cornerRadius="2" borderWidth="2" borderColor="#efefef" zPosition="-1" />
		<eLabel text="EXIT" position="1124,662" size="92,42" zPosition="1" font="Regular;22" halign="center" valign="center" foregroundColor="#efefef" backgroundColor="#000000" />
	</screen>
	"""

	def __init__(self, session, event, serviceRef, callback=None, similarEPGCB=None, singleEPGCB=None, multiEPGCB=None, skin="E2MDBEventView"):
		EventViewSimple.__init__(self, session, event, serviceRef, callback=callback, similarEPGCB=similarEPGCB, singleEPGCB=singleEPGCB, multiEPGCB=multiEPGCB, skin=skin)
		self.backdrop = NoSave(ConfigYesNo(default=False))
		# TODO: if backdrop -> self.backdrop.value = True.

		ensure_epg_skin_sources(self)
		_ensure_neutral_button_sources(self)
		_select_e2mdb_eventview_skin(self)
		_attach_e2mdb_eventview(self)
		try:
			self["key_blue"].setText(_("e2MDB"))
		except Exception:
			pass

	def setEvent(self, event):
		EventViewSimple.setEvent(self, event)
		self._set_compact_description(event)
		self.updateE2MDB("setEvent")

	def setService(self, service):
		EventViewSimple.setService(self, service)
		self.updateE2MDB("setService")

	def _set_compact_description(self, event):
		description = _event_description_without_title(event)
		if not description:
			return
		try:
			self["epg_description"].setText(description)
		except Exception:
			pass
		for source in ("FullDescription", "summary_description"):
			try:
				self[source].setText(description)
			except Exception:
				pass

	def updateE2MDBDescription(self):
		overview = _source_text(self, "e2mdb_overview")
		if overview:
			try:
				self["epg_description"].setText(overview)
			except Exception:
				pass
			for source in ("FullDescription", "summary_description"):
				try:
					self[source].setText(overview)
				except Exception:
					pass

	def updateE2MDB(self, reason="eventview"):
		_update_e2mdb_eventview(self, reason=reason)


class E2MDBEventViewEPGSelect(EventViewEPGSelect):
	"""Skinned e2MDB EventView for the ChannelSelection/EPG info path.

	This keeps the EventViewEPGSelect behaviour such as timer handling and
	single/multi EPG callbacks, but renders the e2MDB skin sources when enabled.
	"""

	skin = E2MDBEventViewEPG.skin

	def __init__(self, session, event, serviceRef, callback=None, singleEPGCB=None, multiEPGCB=None, similarEPGCB=None, skinName=None):
		EventViewEPGSelect.__init__(self, session, event, serviceRef, callback=callback, singleEPGCB=singleEPGCB, multiEPGCB=multiEPGCB, similarEPGCB=similarEPGCB, skinName=skinName)
		ensure_epg_skin_sources(self)
		_ensure_neutral_button_sources(self)
		_select_e2mdb_eventview_skin(self)
		_attach_e2mdb_eventview(self)

	def setEvent(self, event):
		EventViewEPGSelect.setEvent(self, event)
		self._set_compact_description(event)
		self.updateE2MDB("setEvent")

	def setService(self, service):
		EventViewEPGSelect.setService(self, service)
		self.updateE2MDB("setService")

	def _set_compact_description(self, event):
		description = _event_description_without_title(event)
		if not description:
			return
		try:
			self["epg_description"].setText(description)
		except Exception:
			pass
		for source in ("FullDescription", "summary_description"):
			try:
				self[source].setText(description)
			except Exception:
				pass

	def updateE2MDBDescription(self):
		overview = _source_text(self, "e2mdb_overview")
		if overview:
			try:
				self["epg_description"].setText(overview)
			except Exception:
				pass
			for source in ("FullDescription", "summary_description"):
				try:
					self[source].setText(overview)
				except Exception:
					pass

	def updateE2MDB(self, reason="eventview"):
		_update_e2mdb_eventview(self, reason=reason)
