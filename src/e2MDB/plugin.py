########################################################################################################
# e2MDB by Mr.Servo @OpenATV and jbleyel @OpenATV (c) 2026 - skin & design by stein17 @OpenATV         #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from dataclasses import dataclass
from datetime import datetime
from time import time
from json import load, dump
from os import makedirs, remove, walk
from os.path import join, isfile, isdir, abspath, basename, dirname, exists
from twisted.internet import reactor
from twisted.internet.reactor import callInThread

# ENIGMA IMPORTS
from enigma import eTimer, eServiceCenter, eServiceReference, eEPGCache
from Components.ActionMap import ActionMap, HelpableActionMap
from Components.config import config, ConfigSelection, ConfigYesNo, configfile, setOnSaveCallback
from Components.ProgressBar import ProgressBar
from Components.SelectionList import SelectionList
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Scheduler import addFunctionTimer
from Screens.ChoiceBox import ChoiceBox
from Screens.EventView import EventViewSimple, EventViewEPGSelect
from Screens.LocationBox import LocationBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from ServiceReference import ServiceReference

# PLUGIN IMPORTS
from . import PluginLanguageDomain, __version__, e2mdbglobals, write_log, rotate_e2mdb_log, register_e2mdb_servicelist_infokey, E2MDB_SERVICE_LIST_EVENTVIEW_KEY, E2MDB_SERVICE_LIST_EPG_KEY, _
from .E2MDBDatabase import resultsdb
from .E2MDBHelper import E2MDBHelper
from .E2MDBEventViewSimple import E2MDBEventViewSimple
from .E2MDBEPGBridge import install_epg_selection_hooks
from .E2MDBChannelSelectionBridge import install_channel_selection_hooks
from .E2MDBInfoBarBridge import install_infobar_hooks
from .E2MDBComponentMeta import install_component_meta_hooks
from .E2MDBPrefillManager import run_prefill_background, request_prefill_background, prefill_background_running
from .E2MDBCleanupManager import start_cleanup_manager
from .E2MDBSchedulerTasks import start_scan_task, stop_scan_task, start_cleanup_task, stop_cleanup_task, start_sqlite_maintenance_task, stop_sqlite_maintenance_task
from .E2MDBPrefillConfig import E2MDBPrefillServices
from .E2MDBIgnoreConfig import E2MDBIgnorePatterns
from .E2MDBBackendConfig import init_backend_config, ensure_backend_dirs, PATHS_FILE, RUNTIME_DIR
from .E2MDBBackendClient import backend_request, run_backend_live_cleanup, start_backend_scan_and_enrich
from .E2MDBBackendNotify import start_backend_notify_listener
from .E2MDBServiceListIntegration import install_service_list_event_pixmap_provider


BACKEND_PHASE_MSGIDS = {
	"queued": "Queued",
	"running": "Running",
	"done": "Done",
	"validate_paths": "Validating media scan paths",
	"collect": "Collecting media files",
	"recording_scan": "Media scan",
	"recording_scan_done": "Media scan finished",
	"db_import": "Importing scan data",
	"provider_prepare": "Preparing provider search",
	"provider_lookup": "Searching internet metadata",
	"provider_done": "Provider search finished",
	"live_queue_prepare": "Preparing Live/EPG queue",
	"live_provider_lookup": "Processing Live/EPG metadata",
	"cleanup_prepare": "Preparing Live/EPG cleanup",
	"sqlite_maintenance": "Running SQLite maintenance",
	"cache_cleanup": "Cleaning cache",
	"success": "Finished",
	"error": "Error",
	"aborted": "Aborted",
}

BACKEND_JOB_TYPE_MSGIDS = {
	"scan_and_enrich": "Media refresh",
	"recording_scan": "Media scan",
	"metadata_enrich": "Metadata download",
	"live_epg_worker": "Live/EPG metadata worker",
	"live_epg_cleanup": "Live/EPG cleanup",
	"sqlite_maintenance": "SQLite maintenance",
	"cache_cleanup": "Cache cleanup",
}

BACKEND_MESSAGE_MSGIDS = {
	"Validating media scan paths": "Validating media scan paths",
	"No valid recording/media scan paths found": "No valid recording/media scan paths found",
	"Collecting media files": "Collecting media files",
	"No media files found in configured scan paths": "No media files found in configured scan paths",
	"Scanning media files": "Scanning media files",
	"Scanning TS recordings": "Scanning TS recordings",
	"Skipping unchanged media files": "Skipping unchanged media files",
	"Scanning TS recordings with E2MDBScanner Python META/EIT/CUTS parser": "Scanning TS recordings",
	"Scanning media files with E2MDBScanner path mode and filename parser": "Scanning media files",
	"Importing scan data": "Importing scan data",
	"Preparing provider search": "Preparing provider search",
	"No recordings need provider enrichment": "No recordings need provider enrichment",
	"Searching internet metadata": "Searching internet metadata",
	"Preparing Live/EPG queue": "Preparing Live/EPG queue",
	"Preparing Live/EPG queue worker": "Preparing Live/EPG queue worker",
	"Searching Live/EPG metadata": "Searching Live/EPG metadata",
	"Processing Live/EPG metadata": "Processing Live/EPG metadata",
	"Live/EPG worker aborted": "Live/EPG worker aborted",
	"Preparing Live/EPG cleanup": "Preparing Live/EPG cleanup",
	"Running SQLite maintenance": "Running SQLite maintenance",
	"Backend job finished.": "Backend job finished.",
	"Aborted": "Aborted",
	"success": "Finished",
	"error": "Error",
}


def _backend_progress_translation_catalog():
	# TRANSLATORS: Backend progress/status labels shown in the e2MDB scanner screen.
	_("Queued")
	_("Running")
	_("Done")
	_("Finished")
	_("Aborted")
	_("Media refresh")
	_("Media scan")
	_("Metadata download")
	_("Live/EPG metadata worker")
	_("Live/EPG cleanup")
	_("SQLite maintenance")
	_("Cache cleanup")
	_("Validating media scan paths")
	_("Collecting media files")
	_("Scanning media files")
	_("Scanning TS recordings")
	_("Skipping unchanged media files")
	_("Media scan finished")
	_("Importing scan data")
	_("Preparing provider search")
	_("Searching internet metadata")
	_("Provider search finished")
	_("Preparing Live/EPG queue")
	_("Preparing Live/EPG queue worker")
	_("Searching Live/EPG metadata")
	_("Processing Live/EPG metadata")
	_("Preparing Live/EPG cleanup")
	_("Running SQLite maintenance")
	_("Cleaning cache")
	_("No valid recording/media scan paths found")
	_("No media files found in configured scan paths")
	_("No recordings need provider enrichment")
	_("Live/EPG worker aborted")
	_("Media path scan completed:")
	_("Provider enrichment completed:")
	_("Backend is not available:")
	_("Backend job could not be started:")


def _init_backend_config():
	try:
		init_backend_config(reason="setup-save")
		try:
			backend_request("settings_reload")
		except Exception as reload_err:
			write_log("[e2MDB][BACKEND-CONFIG]", f"setup-save backend reload skipped error={reload_err}")
	except Exception as err:
		write_log("[e2MDB][BACKEND-CONFIG]", f"setup-save export failed error={err}")


setOnSaveCallback("e2MDB", _init_backend_config)


class E2MDBMain(E2MDBHelper, Screen):
	MODULE_NAME = "[E2MDBMain]"
	skin = """
	<screen name="E2MDBMain" position="center,center" size="900,680" resolution="1280,720" title="e2MDB - Scanner" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="860,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget name="path_list" position="20,60" size="860,420" foregroundColor="#ffffff" backgroundColor="black" scrollbarMode="showNever" transparent="1" />
		<widget source="progheader" render="Label" position="20,500" size="860,26" font="Regular;20" foregroundColor="green" backgroundColor="black" transparent="1" valign="bottom" textBorderColor="black" textBorderWidth="2" />
		<widget name="progbar" position="20,532" size="860,16" foregroundColor="blue" borderColor="grey" borderWidth="2" backgroundColor="black" cornerRadius="8" />
		<widget source="progsubline" render="Label" position="20,554" size="860,26" font="Regular;20" foregroundColor="yellow" backgroundColor="black" transparent="1" textBorderColor="black" textBorderWidth="2" />
		<widget source="progstatus" render="Label" position="20,600" size="860,26" font="Regular;20" foregroundColor="white" backgroundColor="black" transparent="1" textBorderColor="black" textBorderWidth="2" />
		<widget source="key_red" render="Label" position="20,646" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,644" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,646" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,646" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,644" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,646" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,646" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,644" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,646" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,646" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,644" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,646" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel text="MENU" position="752,646" size="56,26" zPosition="1" font="Regular; 16" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="menu_bg" position="750,644" size="60,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="menu_bg_center" position="752,646" size="56,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20, 50" size="860,1" backgroundColor="grey" />
		<eLabel name="line" position="20,634" size="860,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.language = config.plugins.e2mdb.lang.value
		self.session = session
		title = f"e2MDB - Scanner {e2mdbglobals.RELEASE}"
		self.setTitle(title)
		self.selectAll = True
		self.e2mdb_infobox = session.instantiateDialog(E2MDBInfoBox)
		self.selection_list = SelectionList()
		self["path_list"] = self.selection_list
		self["key_red"] = StaticText(_("Deselect all"))
		self["key_green"] = StaticText(_("Paths"))
		self["key_yellow"] = StaticText(_("Clean Cache"))
		self["key_blue"] = StaticText(_("Start scan"))
		self["progheader"] = StaticText()
		self["progbar"] = ProgressBar()
		self["progbar"].hide()
		self["progsubline"] = StaticText()
		self["progstatus"] = StaticText()
		self.backend_job_active = False
		self.backend_last_job_state = ""
		self.backend_last_message = ""
		self.backend_poll_timer = eTimer()
		try:
			self.backend_poll_timer.callback.append(self.poll_backend_status)
		except Exception:
			self.backend_poll_timer_conn = self.backend_poll_timer.timeout.connect(self.poll_backend_status)
		self.gui_bridge_last_command = ""
		self.gui_bridge_previous_service = None
		self.gui_bridge_timer = eTimer()
		try:
			self.gui_bridge_timer.callback.append(self.poll_gui_bridge_command)
		except Exception:
			self.gui_bridge_timer_conn = self.gui_bridge_timer.timeout.connect(self.poll_gui_bridge_command)
		self.onClose.append(self.stop_backend_poll_timer)
		self["actions"] = ActionMap(["OkCancelActions", "ButtonSetupActions", "MenuActions"], {
			"cancel": self.key_exit,
			"red": self.selection_list.toggleAllSelection,
			"green": self.key_green,
			"yellow": self.key_yellow,
			"blue": self.key_blue,
			"ok": self.selection_list.toggleSelection,
			"menu": self.key_menu
		}, -1)
		self.load_paths()
		self.update_buttons()
		self.poll_backend_status()
		self.backend_poll_timer.start(1000, False)
		self.gui_bridge_timer.start(250, False)

	def load_paths(self):
		paths = E2MDBPaths.load()  # load paths from JSON config file
		self.selection_list.list = []
		idx = 0
		for pathObj in paths:
			path = pathObj.path
			mode = pathObj.mode
			recursive = pathObj.recursive
			if mode:
				mode_str = E2MDBPathSetup.mode_label(mode)
				recursive_str = _("Recursive") if recursive else _("Non-recursive")
				self.selection_list.addSelection(f"{path} / ({mode_str}, {recursive_str})", pathObj, idx, True)
			idx += 1

	def update_buttons(self):
		if self.backend_job_active:
			self["key_blue"].setText(_("Stop scan"))
		else:
			self["key_blue"].setText(_("Start scan"))

	def check_settings(self):
		err_msg = self.create_cache_paths()
		if err_msg:
			self.e2mdb_infobox.showDialog(_(f"The cache paths could not be created: {err_msg}"))
			return False
		else:
			self.remove_log_file()
			serious_err = self.init_providers()
			if serious_err:
				self.session.open(MessageBox, f"{_('Error')}: '{serious_err}'\n{_('Please add all missing personal provider API-Key(s)s in e2MDB settings or deactivate providers.')}", type=MessageBox.TYPE_ERROR, timeout=10, close_on_any_key=True)
				return False
		return True

	def show_last_scan_results(self):
		self.session.open(E2MDBScanResults)

	def getselected_paths(self):
		return [path_obj for label, path_obj, index in self.selection_list.getSelectionsList()]

	def key_exit(self):
		self.close()

	def key_menu(self):
		self.session.open(E2MDBSetup)

	def key_yellow(self):
		if self.backend_job_active:
			return
		choices = [
			(_("All cache (without database)"), "all_cache"),
			(_("Series cache"), "series_cache"),
			(_("Movie cache"), "movie_cache"),
			(_("Live/EPG cache"), "epg_cache"),
			(_("Covers/artwork only"), "artwork_cache"),
			(_("Database only"), "database_only"),
			(_("All cache + database"), "all_with_db"),
		]
		self.session.openWithCallback(self._cache_cleanup_selected, ChoiceBox, title=_("What should be deleted?"), list=choices)

	def _cache_cleanup_selected(self, choice):
		if not choice:
			return
		label, action = choice
		confirm_text = _("Delete '%s'?\n\nThis cannot be undone.") % label
		self.session.openWithCallback(lambda answer: self._cache_cleanup_confirmed(answer, action, label), MessageBox, confirm_text, type=MessageBox.TYPE_YESNO, default=False)

	def _cache_cleanup_confirmed(self, answer, action, label):
		if not answer:
			return
		self.e2mdb_infobox.showDialog(_("Backend cleanup started. Please wait!"), timeout=3)
		callInThread(self._run_backend_cache_cleanup_thread, action, label)

	def _run_backend_cache_cleanup_thread(self, action, label):
		result = None
		error = ""
		try:
			result = backend_request("cache_cleanup_run", timeout=180.0, action=action, dry_run=False)
		except Exception as err:
			error = str(err)
		try:
			reactor.callFromThread(self._backend_cache_cleanup_finished, action, label, result, error)
		except Exception:
			self._backend_cache_cleanup_finished(action, label, result, error)

	def _backend_cache_cleanup_finished(self, action, label, result, error=""):
		if error:
			self.e2mdb_infobox.showDialog(_("ERROR trying to remove pictures and data from cache.: %s") % error, timeout=10)
			return
		result = result if isinstance(result, dict) else {}
		if not result.get("success"):
			error_message = result.get("error") or "unknown backend error"
			self.e2mdb_infobox.showDialog(_("ERROR trying to remove pictures and data from cache.: %s") % error_message, timeout=10)
			return
		stats = result.get("stats") if isinstance(result.get("stats"), dict) else result
		self.e2mdb_infobox.showDialog(_("Cleanup finished: %s\nDeleted files: %d\nDeleted folders: %d") % (label, int(stats.get("files", 0) or 0), int(stats.get("folders", 0) or 0)), timeout=10)
		try:
			self.create_cache_paths()
		except Exception:
			pass

	def key_green(self):
		self.session.openWithCallback(lambda result=None: self.load_paths(), E2MDBPathSetup)

	def key_blue(self):
		if self.backend_job_active:
			self.e2mdb_infobox.showDialog(_("Backend job will be stopped. Please wait!"))
			try:
				backend_request("stop_job", source="enigma-gui")
			except Exception as err:
				write_log(f"{self.MODULE_NAME} Backend stop failed: {err}")
			self.update_buttons()
			return

		# Keep the v16 behaviour: the selected paths already define what has to be
		# scanned. Blue therefore starts the full backend refresh directly without an
		# additional job selection dialog.
		self._backend_job_selected((_("Scan selected media paths + provider metadata"), "scan_enrich"))

	def _backend_job_selected(self, choice):
		if not choice:
			return
		label, action = choice
		selected_paths = self.getselected_paths()
		if not selected_paths:
			self.e2mdb_infobox.showDialog(_("No media path selected."), timeout=5)
			return
		err_msg = self.create_cache_paths()
		if err_msg:
			self.e2mdb_infobox.showDialog(_(f"The cache paths could not be created: {err_msg}"))
			return
		self.remove_log_file()
		self.e2mdb_infobox.showDialog(_("Backend job will be started. Please wait!"))
		try:
			rescan_existing = bool(config.plugins.e2mdb.scannerRescanExisting.value)
			response = start_backend_scan_and_enrich(source="enigma-gui", limit=0, paths=selected_paths, only_missing=not rescan_existing, rescan_existing=rescan_existing)
		except Exception as err:
			self.e2mdb_infobox.showDialog(_(f"Backend is not available: {err}"), timeout=10)
			write_log(f"{self.MODULE_NAME} Backend job start failed: {err}")
			return
		if not response.get("success"):
			self.e2mdb_infobox.showDialog(_(f"Backend job could not be started: {response.get('error', 'unknown error')}"), timeout=10)
			return
		self.backend_job_active = True
		self.update_buttons()
		self.poll_backend_status()

	def stop_backend_poll_timer(self):
		try:
			self.backend_poll_timer.stop()
		except Exception:
			pass
		try:
			self.gui_bridge_timer.stop()
		except Exception:
			pass

	def _gui_command_file(self):
		return join(RUNTIME_DIR, "gui_command.json")

	def poll_gui_bridge_command(self):
		command_path = self._gui_command_file()
		try:
			if not isfile(command_path):
				return
			with open(command_path, "r", encoding="utf-8") as handle:
				command = load(handle)
		except Exception as err:
			write_log(f"{self.MODULE_NAME} GUI bridge command read failed: {err}")
			return
		command_id = str(command.get("id") or "")
		if command_id and command_id == self.gui_bridge_last_command:
			return
		self.gui_bridge_last_command = command_id
		action = str(command.get("action") or "")
		try:
			if action == "play":
				path = str(command.get("file_path") or "")
				if path and isfile(path):
					try:
						current_ref = self.session.nav.getCurrentlyPlayingServiceReference()
					except Exception:
						current_ref = None
					# Store the currently running live service/movie before starting web playback.
					# Stop can then restore it instead of leaving a black screen.
					if current_ref is not None:
						self.gui_bridge_previous_service = current_ref
					ref = eServiceReference(4097, 0, path)
					self.session.nav.playService(ref)
					write_log(f"{self.MODULE_NAME} GUI bridge play path='{path}'")
			elif action == "stop":
				if self.gui_bridge_previous_service is not None:
					self.session.nav.playService(self.gui_bridge_previous_service)
					self.gui_bridge_previous_service = None
					write_log(f"{self.MODULE_NAME} GUI bridge restored previous service")
				else:
					self.session.nav.stopService()
					write_log(f"{self.MODULE_NAME} GUI bridge stop without previous service")
		except Exception as err:
			write_log(f"{self.MODULE_NAME} GUI bridge action failed: {err}")
		try:
			remove(command_path)
		except Exception:
			pass

	def _translate_backend_status(self, value, mapping=None):
		value = str(value or "").strip()
		if not value:
			return ""
		msgid = (mapping or {}).get(value) or value
		return _(msgid)

	def _translate_backend_message(self, value):
		value = str(value or "").strip()
		if not value:
			return ""
		msgid = BACKEND_MESSAGE_MSGIDS.get(value)
		if msgid:
			return _(msgid)
		if value.startswith("Media path scan completed:"):
			return value.replace("Media path scan completed:", _("Media path scan completed:"), 1)
		if value.startswith("Provider enrichment completed:"):
			return value.replace("Provider enrichment completed:", _("Provider enrichment completed:"), 1)
		if value.startswith("Backend is not available:"):
			return value.replace("Backend is not available:", _("Backend is not available:"), 1)
		if value.startswith("Backend job could not be started:"):
			return value.replace("Backend job could not be started:", _("Backend job could not be started:"), 1)
		return value

	def poll_backend_status(self):
		try:
			response = backend_request("status", timeout=0.5)
		except Exception as err:
			self.backend_job_active = False
			self.backend_last_job_state = ""
			self.backend_last_message = str(err)
			self.display_progress(header=_("Backend not running"), progress=-1, sub_line="", status=str(err), show=False)
			self.update_buttons()
			return
		status = response.get("status") if response.get("success") else {}
		if not isinstance(status, dict):
			status = {}
		job = status.get("job") or {}
		if not isinstance(job, dict):
			job = {}
		state = str(job.get("state") or "")
		phase = str(job.get("phase") or "")
		message = str(job.get("message") or "")
		display_message = self._translate_backend_message(message)
		active = state in ("queued", "running")
		self.backend_job_active = active
		percent = int(job.get("percent") or 0) if active else -1
		title = str(job.get("title") or "")
		if not title:
			title = self._translate_backend_status(job.get("type") or "", BACKEND_JOB_TYPE_MSGIDS)
		current = int(job.get("current") or 0)
		total = int(job.get("total") or 0)
		if active:
			display_phase = self._translate_backend_status(phase or state, BACKEND_PHASE_MSGIDS)
			part_current = int(job.get("part_current") or 0)
			part_total = int(job.get("part_total") or 0)
			phase_percent = int(job.get("phase_percent") or 0)
			if part_total > 1 and part_current:
				header = _("Backend job: %s  Part %s/%s") % (display_phase, part_current, part_total)
			else:
				header = _("Backend job: %s") % display_phase
			line = title or str(job.get("path") or "")
			if total:
				if part_total > 1 and part_current:
					stat = _("%s / %s  %s%%  total %s%%  %s") % (current, total, phase_percent, percent, display_message)
				else:
					stat = _("%s / %s  %s%%  %s") % (current, total, percent, display_message)
			else:
				stat = _("%s%%  %s") % (percent, display_message)
			self.display_progress(header=header, range=(0, 100), progress=percent, sub_line=line, status=stat, show=True)
		else:
			if self.backend_last_job_state in ("queued", "running") and state in ("success", "error", "aborted"):
				self.e2mdb_infobox.showDialog(display_message or _("Backend job finished."), timeout=8)
			self.display_progress(header="", progress=-1, sub_line="", status=display_message if state else "", show=False)
		self.backend_last_job_state = state
		self.backend_last_message = message
		self.update_buttons()

	def finish_title_scanner(self, answer):
		self.display_progress(header="", progress=-1, sub_line="", status="", show=False)
		msg_text = _("Scan was canceled by user.") if answer else _("Scan successfully finished.")
		self.update_buttons()
		self.e2mdb_infobox.showDialog(msg_text)

	def display_progress(self, header=None, range=None, progress=None, sub_line=None, status=None, show=None):
		if header is not None:
			self["progheader"].setText(header)
		if range is not None:
			self["progbar"].setRange(range)
		if progress is not None:
			self["progbar"].setValue(progress)
		if sub_line is not None:
			self["progsubline"].setText(sub_line)
		if status is not None:
			self["progstatus"].setText(status)
		if show is True:
			self["progbar"].show()
		elif show is False:
			self["progbar"].hide()

	def create_cache_paths(self):
		try:
			cache_path = self.get_cache_dir()
			if not isdir(cache_path):
				makedirs(cache_path)
			for sub_path in e2mdbglobals.CACHEDIRS:
				path_name = join(cache_path, sub_path)
				if not isdir(path_name):
					makedirs(path_name)
			resultsdb.set_path(cache_path)
			if not isdir(e2mdbglobals.TEMPDIR):
				makedirs(e2mdbglobals.TEMPDIR)
		except OSError as err_msg:
			write_log(f"{self.MODULE_NAME} ERROR in module 'create_cache_paths': {err_msg}!")
			return err_msg
		return ""

	def remove_log_file(self):
		# Keep the active e2MDB.log unless the configured rotation limit is reached.
		# Older logs are compressed by rotate_e2mdb_log() and limited to five archives.
		rotate_e2mdb_log(force=False)


class E2MDBScanResults(E2MDBHelper, Screen):
	skin = """
	<screen name="E2MDBScanResults" position="40,40" size="1200,640" backgroundColor="#16000000" flags="wfNoBorder" resolution="1280,720" title="e2MDB Scan Results">
		<widget source="results" render="Listbox" position="4,4" size="1192,598" itemCornerRadiusSelected="4" enableWrapAround="1" foregroundColorSelected="white" backgroundColor="#16000000" transparent="1" scrollbarMode="showOnDemand">
			<convert type="TemplatedMultiContent">
				{"template": [
					MultiContentEntryRectangle(pos=(4,44), size=(1170,2), borderWidth=2, borderColor=0x393D47),  # line separator
					MultiContentEntryText(pos=(4,0), size=(1170,36), font=0, flags=RT_HALIGN_LEFT|RT_VALIGN_BOTTOM, color=0xFDFf00, color_sel=0xFDFf00, text=0),  # headline
					MultiContentEntryText(pos=(4,0), size=(1170,26), font=1, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP, text=1),  # title | short_desc
					MultiContentEntryText(pos=(4,24), size=(1170,20), font=2, flags=RT_HALIGN_LEFT|RT_VALIGN_TOP|RT_ELLIPSIS, text=2)  # path
					],
					"fonts": [gFont("Regular",28),gFont("Regular",20), gFont("Regular",16)],
					"itemHeight":46
				}
			</convert>
		</widget>
		<widget source="status" render="Label" position="4,610" size="1184,20" font="Regular;18" textBorderColor="#00505050" textBorderWidth="1" foregroundColor="#ffff00" halign="center" valign="center" transparent="1" />
		<eLabel text="&lt;" position="1060,6" size="30,40" halign="center" valign="center" font="Regular;42" zPosition="10" transparent="1" backgroundColor="black" foregroundColor="#ffff00" borderWidth="2" borderColor="black" />
		<eLabel text="&gt;" position="1120,6" size="30,40" halign="center" valign="center" font="Regular;42" zPosition="10" transparent="1" backgroundColor="black" foregroundColor="#ffff00" borderWidth="2" borderColor="black" />
	</screen>
	"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["results"] = List()
		self["status"] = StaticText()
		self['actions'] = ActionMap(["OkCancelActions", "DirectionActions"], {
			"ok": self.close,
			"cancel": self.close,
			"up": self.keyChannelDown,
			"down": self.keyChannelDown,
			"chplus": self.keyChannelUp,
			"chminus": self.keyChannelDown
			}, -1)
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self["results"].selectionEnabled(0)
		self.update_skin_list()

	def update_skin_list(self):
		def sec2min(duration):  # converts seconds in minutes (e.g. '6045 seconds' in '100:45 minutes')
			try:
				if isinstance(duration, str):
					duration = duration.strip()
				duration = float(duration) if duration else 0.0
			except (TypeError, ValueError):
				duration = 0.0
			m, s = divmod(int(round(duration)), 60)
			return f"{m:02d}:{s:02d}"

		skin_list = []
		failure_dict = self.read_scan_dicts("failed")
		failure_list = failure_dict.get("results", [])
		failure_count = len(failure_list)
		skin_list.append((_(f"Records not found: ({failure_count})"), "", ""))
		skin_list += self.build_result_list(failure_list)
		success_dict = self.read_scan_dicts("succeeded")
		success_list = success_dict.get("results", [])
		success_count = len(success_list)
		skin_list.append((_(f"Successfully found records: ({success_count})"), "", ""))
		skin_list += self.build_result_list(success_list)
		self["results"].updateList(skin_list)
		scan_dict = failure_dict or success_dict
		start_time, duration = scan_dict.get("start_scan", ""), scan_dict.get("duration_sec", "")
		try:
			if isinstance(duration, str):
				duration = duration.strip()
			duration = float(duration) if duration else 0.0
		except (TypeError, ValueError):
			duration = 0.0
		try:
			start_time = datetime.fromisoformat(start_time).strftime("%c") if start_time else _("{not yet}")
		except Exception:
			start_time = start_time or _("{not yet}")
		total_count = success_count + failure_count
		if total_count:
			status_text = f"{_('Total')}: {total_count}"
			status_text += f" | {_('Succesful')}: {success_count} ({round(success_count / total_count * 100, 1):n} %)"
			status_text += f" | {_('Failed')}: {failure_count} ({round(failure_count / total_count * 100, 1):n} %)"
			status_text += f" | {_('Last scan')}: {start_time}"
			status_text += f" | {_('Duration')}: {sec2min(duration)} min"
			status_text += f" (Ø {round(duration / total_count, 1):n} s {_('per record')})"
		else:
			status_text = _("Nothing found!")
		self["status"].setText(f"{status_text}")

	def read_scan_dicts(self, file_name):
		scan_dict, file_base = {}, f"{self.get_cache_dir()}/scan_{file_name}.json"
		try:
			if isfile(file_base):
				with open(file_base) as file:
					scan_dict = load(file)
			else:
				write_log(f"{self.MODULE_NAME} ERROR in module 'show_last_scan_results': File not found '{file_base}'")
		except Exception as err_msg:
			write_log(f"{self.MODULE_NAME} ERROR in module 'show_last_scan_results': {err_msg}!")
		return scan_dict

	def build_result_list(self, scan_list):
		curr_list = []
		for curr_dict in scan_list:
			title = curr_dict.get("title", "").strip()
			short_desc = curr_dict.get("short_desc", "").strip()
			short_desc = f" | {short_desc}" if short_desc else ""
			long_title = f"{title}{short_desc}"
			media_path = curr_dict.get("media_path", "")
			curr_list.append(("", long_title, media_path))  # (headline, long_title,path)
		return curr_list

	def keyChannelUp(self):
		self["results"].pageUp()

	def keyChannelDown(self):
		self["results"].pageDown()


@dataclass
class E2MDBPathItem:
	path: str = ""
	mode: int = 0
	recursive: bool = False


class E2MDBPaths:
	CONFIG_FILE = PATHS_FILE

	@classmethod
	def load(cls) -> list[E2MDBPathItem]:
		"""Load paths from the clean-start backend JSON directory."""
		paths = []
		try:
			ensure_backend_dirs()
			if isfile(cls.CONFIG_FILE):
				with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
					data = load(f)
					if isinstance(data, dict):
						data = data.get("paths", [])
					paths = [E2MDBPathItem(**item) for item in data if isinstance(item, dict)]
		except Exception as e:
			write_log(f"[E2MDBPaths] ERROR loading {cls.CONFIG_FILE}: {e}")
		return paths

	@classmethod
	def save(cls, paths: list[E2MDBPathItem]):
		"""Save paths to the clean-start backend JSON directory."""
		try:
			ensure_backend_dirs()
			with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
				dump([path.__dict__ for path in paths], f, indent=2, sort_keys=True)
				f.write("\n")
		except Exception as e:
			write_log(f"[E2MDBPaths] ERROR saving {cls.CONFIG_FILE}: {e}")


class E2MDBPathSetup(Setup):
	MODULE_NAME = "[E2MDBPathSetup]"
	PATH_CHOICES = [
		(0, _("Exclude")),
		(3, _("Movie/Series")),
		(1, _("Movie")),
		(2, _("Series")),
		(4, _("Anime Series")),
		(6, _("Anime Movie")),
		(5, _("Manga Series")),
		(7, _("Manga Movie"))
	]

	@staticmethod
	def mode_label(mode):
		return {
			3: _("Movie/Series"),
			1: _("Movie"),
			2: _("Series"),
			4: _("Anime Series"),
			6: _("Anime Movie"),
			5: _("Manga Series"),
			7: _("Manga Movie"),
		}.get(mode, _("Unknown"))

	def __init__(self, session):
		self.paths = E2MDBPaths.load()  # ensure config is loaded
		Setup.__init__(self, session=session, setup="E2MDBPathSetup")
		self["key_yellow"] = StaticText(_("Add"))
		self["key_blue"] = StaticText(_("Remove"))
		self["add_remove_actions"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.key_add_path, _("Add path")),
			"blue": (self.key_remove_path, _("Remove path"))
		}, prio=0)

	def createSetup(self):  # NOSONAR silence S2638
		self.path_items = []
		for pathObj in self.paths:
			path = pathObj.path
			mode = pathObj.mode
			self.path_items.append((path,))
			self.path_items.append((
				(_("Mode"), 1),
				ConfigSelection(default=mode, choices=self.PATH_CHOICES),
				_("Define if the path contains movies, series or both. This is used to optimize the scan process."),
				pathObj,
				0
			))
			print(f"[E2MDBPathSetup] Added config entries for path: {path} with mode: {mode}", type(mode))
			if mode:  # only show recursive option if path is not excluded
				self.path_items.append((
					(_("Recursive"), 1),
					ConfigYesNo(default=pathObj.recursive == 1), _("Include subdirectories"),
					pathObj,
					1
				))

		Setup.createSetup(self, appendItems=self.path_items)

	def changedEntry(self):
		current_index = -1
		current = self["config"].getCurrent()
		if current and len(current) == 5:  # check if current entry is a path config entry
			current_index = self["config"].getCurrentIndex()
			pathObj = current[3]
			config_item_index = current[4]
			if config_item_index == 0:  # mode config item
				pathObj.mode = current[1].value
			if config_item_index == 1:  # recursive config item
				pathObj.recursive = 1 if current[1].value else 0
			self.paths = [pathObj if p.path == pathObj.path else p for p in self.paths]  # update pathObj in paths list
		Setup.changedEntry(self)
		if current_index != -1:
			self["config"].setCurrentIndex(current_index)

	def key_add_path(self):
		def on_path_selected(path):
			if path and isdir(path):
				# Normalize path
				path = abspath(path)
				for pathObj in self.paths:
					if pathObj.path == path:
						return  # path already exists, do nothing
				self.paths.append(E2MDBPathItem(path=path, mode=3, recursive=1))  # default to Movie/Series
				self.createSetup()  # trigger save and refresh
				for pos, data in enumerate(self["config"].list):
					if len(data) == 5 and data[3].path == path:
						self["config"].setCurrentIndex(pos)
						break

		self.session.openWithCallback(on_path_selected, LocationBox, _("Select path for media"), currDir="/media/hdd/movie/")

	def key_remove_path(self):
		current = self["config"].getCurrent()
		if current and len(current) == 5:  # check if current entry is a path config entry
			pathObj = current[3]
			self.paths = [p for p in self.paths if p.path != pathObj.path]
			self.createSetup()  # trigger save and refresh

	def keySave(self):
		E2MDBPaths.save(self.paths)
		self.close()


class E2MDBPatternListSelection(Screen):
	"""Edit JSON-backed Live/EPG ignore pattern lists."""

	MODULE_NAME = "[E2MDBPatternListSelection]"
	skin = """
	<screen name="E2MDBPatternListSelection" position="center,center" size="920,600" resolution="1280,720" title="e2MDB - Ignore patterns" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="summary" render="Label" position="20,52" size="880,24" font="Regular;18" foregroundColor="#d0d0d0" backgroundColor="black" transparent="1" />
		<widget name="pattern_list" position="20,86" size="880,450" foregroundColor="#ffffff" backgroundColor="black" scrollbarMode="showOnDemand" transparent="1" />
		<widget source="key_red" render="Label" position="20,566" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,564" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,566" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,566" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,564" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,566" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,566" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,564" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,566" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,566" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,564" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,566" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="740,566" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="738,564" size="170,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="740,566" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,80" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,554" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session, title, list_key, default_patterns="", source_type=None):
		Screen.__init__(self, session)
		self.title = title
		self.list_key = list_key
		self.default_patterns = default_patterns
		self.source_type = source_type or list_key
		self.patterns = E2MDBIgnorePatterns.parse(list_key)
		self.selection_list = SelectionList()
		self["pattern_list"] = self.selection_list
		self.setTitle(title)
		self["summary"] = StaticText()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText(_("Delete"))
		self["key_blue"] = StaticText(_("Add"))
		self["key_ok"] = StaticText(_("OK = Edit"))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
			"ok": self.key_edit,
			"cancel": self.key_cancel,
			"red": self.key_cancel,
			"green": self.key_save,
			"yellow": self.key_delete,
			"blue": self.key_add,
		}, -1)
		self.build_list()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _extract_pattern_from_selection(self, selection):
		if isinstance(selection, dict):
			return selection.get("pattern", "")
		if isinstance(selection, (list, tuple)):
			for element in selection:
				if isinstance(element, dict) and "pattern" in element:
					return element.get("pattern", "")
		return ""

	def _current_index(self):
		try:
			current = self.selection_list.getCurrent()
		except Exception:
			current = None
		if isinstance(current, (list, tuple)):
			for element in current:
				if isinstance(element, dict) and "index" in element:
					try:
						return int(element.get("index") or 0)
					except Exception:
						return -1
			pattern = self._extract_pattern_from_selection(current)
			if pattern in self.patterns:
				return self.patterns.index(pattern)
			if len(current) > 2:
				try:
					return int(current[2])
				except Exception:
					pass
		try:
			return int(self.selection_list.getCurrentIndex())
		except Exception:
			pass
		try:
			return int(self.selection_list.instance.getCurrentIndex())
		except Exception:
			return -1

	def _save_patterns(self, reason="setup", close=False):
		try:
			self.patterns = E2MDBIgnorePatterns.save(self.list_key, self.patterns, reason=reason)
			self.log(f"SAVE title='{self.title}' patterns={len(self.patterns)} reason={reason}")
			if close:
				self.close(True)
			else:
				self.build_list(self._current_index())
			return True
		except Exception as err:
			self.log(f"SAVE failed title='{self.title}' error={err}")
			try:
				self.session.open(MessageBox, _("Could not save ignore list:\n%s") % err, type=MessageBox.TYPE_ERROR, timeout=8)
			except Exception:
				pass
			return False

	def build_list(self, current_index=None):
		self.selection_list.list = []
		for idx, pattern in enumerate(self.patterns):
			self.selection_list.addSelection(pattern, {"index": idx, "pattern": pattern}, idx, False)
		if not self.patterns:
			self.selection_list.addSelection(_("No patterns configured"), {"index": -1, "pattern": ""}, 0, False)
		try:
			self.selection_list.updateList()
			if current_index is not None and current_index >= 0:
				self.selection_list.moveToIndex(min(current_index, max(len(self.patterns) - 1, 0)))
		except Exception:
			pass
		self["summary"].setText(_("Patterns: %d   Stored in %s") % (len(self.patterns), E2MDBIgnorePatterns.get_storage_path(self.list_key)))

	def _open_keyboard(self, title, text, callback):
		try:
			from Screens.VirtualKeyBoard import VirtualKeyBoard
			self.session.openWithCallback(callback, VirtualKeyBoard, title=title, text=text)
		except Exception as err:
			self.log(f"VirtualKeyBoard failed error={err}")

	def key_add(self):
		choices = [(_("Add manually"), "manual")]
		if self.source_type == E2MDBIgnorePatterns.EPG_TITLE:
			choices.append((_("Add from current EPG titles"), "source"))
		elif self.source_type == E2MDBIgnorePatterns.SERVICE_NAME:
			choices.append((_("Add from channel list"), "source"))
		elif self.source_type == E2MDBIgnorePatterns.FOLDER_NAME:
			choices.append((_("Add from media folders"), "source"))
		self.session.openWithCallback(self._add_choice_selected, ChoiceBox, title=_("Add ignore pattern"), list=choices)

	def _add_choice_selected(self, selection):
		if not selection:
			return
		label, key = selection
		if key == "source":
			if self.source_type == E2MDBIgnorePatterns.EPG_TITLE:
				title = _("Select EPG titles to ignore")
			elif self.source_type == E2MDBIgnorePatterns.SERVICE_NAME:
				title = _("Select service names to ignore")
			else:
				title = _("Select folder names to ignore")
			self.session.openWithCallback(self._source_patterns_selected, E2MDBPatternSourceSelection, title, self.source_type, self.patterns)
			return

		def done(value):
			value = (value or "").strip()
			if value and value not in self.patterns:
				self.patterns.append(value)
				self._save_patterns(reason="manual-add")
			else:
				self.build_list(self._current_index())
		self._open_keyboard(_("Add pattern"), "", done)

	def _source_patterns_selected(self, patterns):
		added = 0
		for pattern in patterns or []:
			pattern = (pattern or "").strip()
			if pattern and pattern not in self.patterns:
				self.patterns.append(pattern)
				added += 1
		if added:
			self._save_patterns(reason="source-add")
		else:
			self.build_list(None)

	def key_edit(self):
		idx = self._current_index()
		if idx < 0 or idx >= len(self.patterns):
			return
		old = self.patterns[idx]

		def done(value):
			value = (value or "").strip()
			if not value:
				del self.patterns[idx]
				self._save_patterns(reason="edit-delete")
			elif value not in self.patterns or value == old:
				self.patterns[idx] = value
				self._save_patterns(reason="edit")
			else:
				self.build_list(idx)
		self._open_keyboard(_("Edit pattern"), old, done)

	def key_delete(self):
		idx = self._current_index()
		if 0 <= idx < len(self.patterns):
			del self.patterns[idx]
			self._save_patterns(reason="delete")

	def key_save(self):
		self._save_patterns(reason="setup", close=True)

	def key_cancel(self):
		self.close(False)


class E2MDBPatternSourceSelection(Screen):
	"""Select ignore patterns from channel names or current EPG titles."""

	MODULE_NAME = "[E2MDBPatternSourceSelection]"
	TV_BOUQUET_ROOT = '1:7:1:0:0:0:0:0:0:0:(type == 1) FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
	MAX_EPG_EVENTS_PER_SERVICE = 3
	MAX_SOURCE_ITEMS = 700

	skin = """
	<screen name="E2MDBPatternSourceSelection" position="center,center" size="920,650" resolution="1280,720" title="e2MDB - Select ignore patterns" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="summary" render="Label" position="20,52" size="880,28" font="Regular;18" foregroundColor="#d0d0d0" backgroundColor="black" transparent="1" />
		<widget name="source_list" position="20,88" size="880,500" foregroundColor="#ffffff" backgroundColor="black" scrollbarMode="showOnDemand" transparent="1" />
		<widget source="key_red" render="Label" position="20,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,614" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,614" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,614" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,614" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="740,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="738,614" size="170,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="740,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,82" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,604" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session, title, source_type, existing_patterns=None):
		Screen.__init__(self, session)
		self.title = title
		self.source_type = source_type
		self.existing_patterns = set(existing_patterns or [])
		self.entries = []
		self.selection_list = SelectionList()
		self["source_list"] = self.selection_list
		self.setTitle(title)
		self["summary"] = StaticText()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Add selected"))
		self["key_yellow"] = StaticText(_("Unmark all"))
		self["key_blue"] = StaticText(_("Mark all"))
		self["key_ok"] = StaticText(_("OK = Mark"))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
			"ok": self.key_ok,
			"cancel": self.key_cancel,
			"red": self.key_cancel,
			"green": self.key_save,
			"yellow": self.key_unmark_all,
			"blue": self.key_mark_all,
		}, -1)
		self.load_entries()
		self.build_list()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _service_name(self, service_ref, fallback=""):
		try:
			return ServiceReference(service_ref).getServiceName() or fallback or service_ref
		except Exception:
			return fallback or service_ref

	def _collect_services(self):
		services = []
		seen = set()
		try:
			service_handler = eServiceCenter.getInstance()
			root = eServiceReference(self.TV_BOUQUET_ROOT)
			bouquets = service_handler.list(root)
			if bouquets is None:
				return services
			while True:
				bouquet = bouquets.getNext()
				if not bouquet or not bouquet.valid():
					break
				if bouquet.flags & eServiceReference.isMarker:
					continue
				if bouquet.flags & eServiceReference.isDirectory:
					items = service_handler.list(bouquet)
					if items is None:
						continue
					while True:
						service = items.getNext()
						if not service or not service.valid():
							break
						if service.flags & (eServiceReference.isMarker | eServiceReference.isDirectory):
							continue
						service_ref = service.toString()
						if not service_ref or service_ref.startswith("-1:") or service_ref in seen:
							continue
						seen.add(service_ref)
						services.append((service_ref, self._service_name(service_ref)))
				else:
					service_ref = bouquet.toString()
					if service_ref and not service_ref.startswith("-1:") and service_ref not in seen:
						seen.add(service_ref)
						services.append((service_ref, self._service_name(service_ref)))
		except Exception as err:
			self.log(f"SERVICE SOURCE failed error={err}")
		return services

	def _collect_service_name_entries(self):
		entries = []
		seen_names = set()
		for service_ref, service_name in self._collect_services():
			name = (service_name or service_ref or "").strip()
			key = name.lower()
			if name and key not in seen_names:
				seen_names.add(key)
				entries.append({"label": name, "pattern": name})
			if len(entries) >= self.MAX_SOURCE_ITEMS:
				break
		return entries

	def _collect_epg_title_entries(self):
		entries = []
		seen_titles = set()
		try:
			epg = eEPGCache.getInstance()
		except Exception:
			epg = None
		if epg is None:
			return entries

		now = int(time())
		for service_ref, service_name in self._collect_services():
			try:
				ref = eServiceReference(service_ref)
				lookup_time = -1
				for _idx in range(self.MAX_EPG_EVENTS_PER_SERVICE):
					event = epg.lookupEventTime(ref, lookup_time)
					if not event:
						break
					title = (event.getEventName() or "").strip()
					if title:
						key = title.lower()
						if key not in seen_titles:
							seen_titles.add(key)
							entries.append({"label": f"{title}  —  {service_name or service_ref}", "pattern": title})
							if len(entries) >= self.MAX_SOURCE_ITEMS:
								return entries
					try:
						begin = int(event.getBeginTime() or now)
						duration = max(60, int(event.getDuration() or 60))
						lookup_time = max(now, begin + duration) + 1
					except Exception:
						break
			except Exception:
				continue
		return entries

	def _collect_folder_name_entries(self):
		entries = []
		seen_names = set()
		try:
			paths = E2MDBPaths.load()
		except Exception:
			paths = []
		for path_obj in paths:
			root = getattr(path_obj, "path", "") or ""
			recursive = bool(getattr(path_obj, "recursive", 1))
			if not root or not isdir(root):
				continue
			try:
				for current_root, dirs, files in walk(root):
					dirs[:] = [folder for folder in dirs if folder and not folder.startswith(".")]
					for folder in dirs:
						name = (folder or "").strip()
						key = name.lower()
						if name and key not in seen_names:
							seen_names.add(key)
							entries.append({"label": f"{name}  —  {current_root}", "pattern": name})
							if len(entries) >= self.MAX_SOURCE_ITEMS:
								return entries
					if not recursive:
						break
			except Exception as err:
				self.log(f"FOLDER SOURCE failed root='{root}' error={err}")
		return entries

	def load_entries(self):
		if self.source_type == E2MDBIgnorePatterns.SERVICE_NAME:
			self.entries = self._collect_service_name_entries()
		elif self.source_type == E2MDBIgnorePatterns.FOLDER_NAME:
			self.entries = self._collect_folder_name_entries()
		else:
			self.entries = self._collect_epg_title_entries()
		self.log(f"LOAD source_type={self.source_type} entries={len(self.entries)}")

	def build_list(self):
		self.selection_list.list = []
		for idx, entry in enumerate(self.entries):
			pattern = entry.get("pattern") or ""
			label = entry.get("label") or pattern
			self.selection_list.addSelection(label, {"pattern": pattern}, idx, pattern in self.existing_patterns)
		if not self.entries:
			self.selection_list.addSelection(_("No selectable entries found"), {"pattern": ""}, 0, False)
		try:
			self.selection_list.updateList()
		except Exception:
			pass
		self.update_summary()

	def update_summary(self):
		selected = len(self._selected_patterns())
		if self.source_type == E2MDBIgnorePatterns.SERVICE_NAME:
			self["summary"].setText(_("Channel names: %d   Selected: %d") % (len(self.entries), selected))
		elif self.source_type == E2MDBIgnorePatterns.FOLDER_NAME:
			self["summary"].setText(_("Folder names: %d   Selected: %d") % (len(self.entries), selected))
		else:
			self["summary"].setText(_("EPG titles: %d   Selected: %d") % (len(self.entries), selected))

	def _selected_patterns(self):
		selected = []

		def add_pattern(pattern):
			pattern = (pattern or "").strip()
			if pattern and pattern not in selected:
				selected.append(pattern)
		try:
			for selection in self.selection_list.getSelectionsList():
				if isinstance(selection, dict):
					add_pattern(selection.get("pattern"))
				elif isinstance(selection, (list, tuple)):
					for element in selection:
						if isinstance(element, dict) and "pattern" in element:
							add_pattern(element.get("pattern"))
							break
		except Exception:
			pass
		if not selected:
			try:
				for selection in getattr(self.selection_list, "list", []):
					if isinstance(selection, (list, tuple)) and len(selection) > 3 and selection[3]:
						for element in selection:
							if isinstance(element, dict) and "pattern" in element:
								add_pattern(element.get("pattern"))
								break
			except Exception:
				pass
		return selected

	def key_ok(self):
		try:
			self.selection_list.toggleSelection()
		except Exception:
			pass
		self.update_summary()

	def key_mark_all(self):
		self.existing_patterns = set()
		for entry in self.entries:
			pattern = entry.get("pattern") or ""
			if pattern:
				self.existing_patterns.add(pattern)
		self.build_list()

	def key_unmark_all(self):
		self.existing_patterns = set()
		self.build_list()

	def key_save(self):
		self.close(self._selected_patterns())

	def key_cancel(self):
		self.close([])


class E2MDBPrefillServiceSelection(Screen):
	"""Two-level bouquet/channel selection screen for manual Live/EPG prefill services."""

	MODULE_NAME = "[E2MDBPrefillServiceSelection]"
	skin = """
	<screen name="E2MDBPrefillServiceSelection" position="center,center" size="920,650" resolution="1280,720" title="e2MDB - Manual prefill services" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="level" render="Label" position="20,48" size="880,28" font="Regular;20" halign="center" foregroundColor="#ffd24a" backgroundColor="black" transparent="1" />
		<widget source="summary" render="Label" position="20,76" size="880,24" font="Regular;18" foregroundColor="#d0d0d0" backgroundColor="black" transparent="1" />
		<widget name="service_list" position="20,110" size="880,476" foregroundColor="#ffffff" backgroundColor="black" scrollbarMode="showOnDemand" transparent="1" />
		<widget source="key_red" render="Label" position="20,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,614" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,614" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,614" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,614" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="740,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="738,614" size="170,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="740,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,102" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,604" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	TV_BOUQUET_ROOT = '1:7:1:0:0:0:0:0:0:0:(type == 1) FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
	LEVEL_BOUQUETS = "bouquets"
	LEVEL_SERVICES = "services"

	def __init__(self, session):
		Screen.__init__(self, session)
		self.selected_services = set(E2MDBPrefillServices.parse())
		self.bouquets = []
		self.current_bouquet_index = 0
		self.level = self.LEVEL_BOUQUETS
		self.selection_list = SelectionList()
		self["service_list"] = self.selection_list
		self.setTitle(_("Manual Live/EPG prefill services"))
		self["level"] = StaticText()
		self["summary"] = StaticText()
		self["key_red"] = StaticText()
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText()
		self["key_blue"] = StaticText()
		self["key_ok"] = StaticText()
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
			"ok": self.key_ok,
			"cancel": self.key_cancel,
			"red": self.key_red,
			"green": self.key_save,
			"yellow": self.key_yellow,
			"blue": self.key_blue,
			"left": self.key_left,
			"right": self.key_right,
		}, -1)
		self.load_bouquets()
		self.build_bouquet_list()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _service_name(self, service_ref, fallback=""):
		try:
			return ServiceReference(service_ref).getServiceName() or fallback or service_ref
		except Exception:
			return fallback or service_ref

	def _get_bouquet_name(self, bouquet_ref):
		try:
			return ServiceReference(bouquet_ref).getServiceName() or ""
		except Exception:
			return ""

	def _append_configured_fallback_bouquet(self, known_services):
		missing = []
		for service_ref in sorted(self.selected_services):
			if service_ref and service_ref not in known_services:
				missing.append({
					"service_ref": service_ref,
					"service_name": self._service_name(service_ref),
					"number": "",
				})
		if missing:
			self.bouquets.append({
				"name": _("Configured services"),
				"service_ref": "",
				"services": missing,
			})

	def _collect_bouquet_services(self, bouquet_ref):
		services = []
		seen_in_bouquet = set()
		try:
			service_handler = eServiceCenter.getInstance()
			items = service_handler.list(bouquet_ref)
			if items is None:
				return services
			while True:
				service = items.getNext()
				if not service or not service.valid():
					break
				if service.flags & (eServiceReference.isMarker | eServiceReference.isDirectory):
					continue
				service_ref = service.toString()
				if not service_ref or service_ref.startswith("-1:") or service_ref in seen_in_bouquet:
					continue
				seen_in_bouquet.add(service_ref)
				try:
					number = service.getChannelNum()
				except Exception:
					number = ""
				services.append({
					"service_ref": service_ref,
					"service_name": self._service_name(service_ref),
					"number": number or "",
				})
		except Exception as err:
			self.log(f"BOUQUET failed ref='{bouquet_ref.toString() if hasattr(bouquet_ref, 'toString') else bouquet_ref}' error={err}")
		return services

	def load_bouquets(self):
		self.bouquets = []
		known_services = set()
		try:
			service_handler = eServiceCenter.getInstance()
			root = eServiceReference(self.TV_BOUQUET_ROOT)
			bouquets = service_handler.list(root)
			if bouquets is not None:
				while True:
					bouquet = bouquets.getNext()
					if not bouquet or not bouquet.valid():
						break
					if bouquet.flags & eServiceReference.isMarker:
						continue
					bouquet_name = self._get_bouquet_name(bouquet) or bouquet.toString()
					if bouquet.flags & eServiceReference.isDirectory:
						services = self._collect_bouquet_services(bouquet)
					else:
						service_ref = bouquet.toString()
						services = [{
							"service_ref": service_ref,
							"service_name": self._service_name(service_ref),
							"number": "",
						}] if service_ref and not service_ref.startswith("-1:") else []
					if services:
						for item in services:
							known_services.add(item.get("service_ref") or "")
						self.bouquets.append({
							"name": bouquet_name,
							"service_ref": bouquet.toString(),
							"services": services,
						})
		except Exception as err:
			self.log(f"LOAD failed error={err}")
		self._append_configured_fallback_bouquet(known_services)
		if not self.bouquets:
			self.bouquets.append({"name": _("No TV bouquets found"), "service_ref": "", "services": []})
		self.current_bouquet_index = min(max(self.current_bouquet_index, 0), max(len(self.bouquets) - 1, 0))
		self.log(f"LOAD bouquets={len(self.bouquets)} services={sum(len(b.get('services') or []) for b in self.bouquets)} selected={len(self.selected_services)}")

	def _current_bouquet(self):
		if self.bouquets and 0 <= self.current_bouquet_index < len(self.bouquets):
			return self.bouquets[self.current_bouquet_index]
		return {"name": "", "services": []}

	def _service_refs_for_bouquet(self, bouquet):
		refs = []
		for item in bouquet.get("services") or []:
			service_ref = item.get("service_ref") or ""
			if service_ref and service_ref not in refs:
				refs.append(service_ref)
		return refs

	def _bouquet_selection_state(self, bouquet):
		refs = self._service_refs_for_bouquet(bouquet)
		if not refs:
			return "empty", 0, 0
		selected = len([ref for ref in refs if ref in self.selected_services])
		if selected == 0:
			return "none", selected, len(refs)
		if selected == len(refs):
			return "all", selected, len(refs)
		return "partial", selected, len(refs)

	def _status_prefix(self, state):
		if state == "all":
			return "[x]"
		if state == "partial":
			return "[-]"
		if state == "empty":
			return "[ ]"
		return "[ ]"

	def _current_selection_item(self):
		try:
			current = self.selection_list.getCurrent()
			if current and isinstance(current, list):
				current = current[0]
				if current and isinstance(current, tuple) and len(current) > 1:
					current = current[1]
					return current if isinstance(current, dict) else None
		except Exception:
			current = None
		# SelectionList usually returns [(display, value, index, selected), ...] or a similar tuple.
		return None

	def build_bouquet_list(self):
		self.level = self.LEVEL_BOUQUETS
		self.selection_list.list = []
		for idx, bouquet in enumerate(self.bouquets):
			state, selected, total = self._bouquet_selection_state(bouquet)
			label = f"{self._status_prefix(state)} {bouquet.get("name") or ""}  ({selected}/{total})"
			self.selection_list.addSelection(label, {"type": "bouquet", "index": idx}, idx, state == "all")
		try:
			self.selection_list.updateList()
		except Exception:
			pass
		self.update_summary()

	def build_service_list(self):
		self.level = self.LEVEL_SERVICES
		bouquet = self._current_bouquet()
		services = bouquet.get("services") or []
		self.selection_list.list = []
		for idx, item in enumerate(services):
			service_ref = item.get("service_ref") or ""
			service_name = item.get("service_name") or service_ref
			number = item.get("number") or ""
			label = "{}{}".format((f"{number}  ") if number else "", service_name)
			self.selection_list.addSelection(label, {"type": "service", "service_ref": service_ref}, idx, service_ref in self.selected_services)
		try:
			self.selection_list.updateList()
		except Exception:
			pass
		self.update_summary()

	def _selected_from_list(self):
		selected = []
		try:
			for label, item, index in self.selection_list.getSelectionsList():
				service_ref = item.get("service_ref") if isinstance(item, dict) else ""
				if service_ref and service_ref not in selected:
					selected.append(service_ref)
		except Exception:
			selected = []
		return selected

	def _sync_current_bouquet_selection(self):
		if self.level != self.LEVEL_SERVICES:
			return
		bouquet = self._current_bouquet()
		current_refs = set(item.get("service_ref") for item in (bouquet.get("services") or []) if item.get("service_ref"))
		selected_now = set(self._selected_from_list())
		self.selected_services.difference_update(current_refs)
		self.selected_services.update(selected_now)

	def _set_current_bouquet_selected(self, selected=True):
		bouquet = self._current_bouquet()
		refs = self._service_refs_for_bouquet(bouquet)
		if selected:
			self.selected_services.update(refs)
		else:
			self.selected_services.difference_update(refs)
		return len(refs)

	def _toggle_bouquet(self, bouquet_index=None):
		if bouquet_index is None:
			bouquet_index = self.current_bouquet_index
		if not self.bouquets or not (0 <= bouquet_index < len(self.bouquets)):
			return
		self.current_bouquet_index = bouquet_index
		bouquet = self._current_bouquet()
		state, selected, total = self._bouquet_selection_state(bouquet)
		# Toggle partial and none to all; all to none.
		self._set_current_bouquet_selected(selected=(state != "all"))

	def update_summary(self):
		if self.level == self.LEVEL_BOUQUETS:
			selected_bouquets = 0
			partial_bouquets = 0
			for bouquet in self.bouquets:
				state, selected, total = self._bouquet_selection_state(bouquet)
				if state == "all":
					selected_bouquets += 1
				elif state == "partial":
					partial_bouquets += 1
			self["level"].setText(_("Bouquets"))
			self["summary"].setText(_("Bouquets: %d   Full: %d   Partial: %d   Total selected services: %d") % (len(self.bouquets), selected_bouquets, partial_bouquets, len(self.selected_services)))
			self["key_red"].setText(_("Close"))
			self["key_yellow"].setText(_("Unmark bouquet"))
			self["key_blue"].setText(_("Mark bouquet"))
			self["key_ok"].setText(_("OK = Open"))
		else:
			bouquet = self._current_bouquet()
			services = bouquet.get("services") or []
			selected_in_bouquet = len([item for item in services if item.get("service_ref") in self.selected_services])
			self["level"].setText(_("Bouquet %d/%d: %s") % (self.current_bouquet_index + 1, len(self.bouquets), bouquet.get("name") or ""))
			self["summary"].setText(_("Selected in bouquet: %d / %d   Total selected services: %d") % (selected_in_bouquet, len(services), len(self.selected_services)))
			self["key_red"].setText(_("Back"))
			self["key_yellow"].setText(_("Unmark all"))
			self["key_blue"].setText(_("Mark all"))
			self["key_ok"].setText(_("OK = Mark"))

	def key_ok(self):
		if self.level == self.LEVEL_BOUQUETS:
			item = self._current_selection_item()
			if item and item.get("type") == "bouquet":
				self.current_bouquet_index = int(item.get("index") or 0)
			self.build_service_list()
		else:
			self.selection_list.toggleSelection()
			self._sync_current_bouquet_selection()
			self.update_summary()

	def key_blue(self):
		if self.level == self.LEVEL_BOUQUETS:
			item = self._current_selection_item()
			if item and item.get("type") == "bouquet":
				self.current_bouquet_index = int(item.get("index") or 0)
			self._set_current_bouquet_selected(True)
			index = self.selection_list.getCurrentIndex()
			self.build_bouquet_list()
			self.selection_list.setCurrentIndex(index)
		else:
			self._set_current_bouquet_selected(True)
			self.build_service_list()

	def key_yellow(self):
		if self.level == self.LEVEL_BOUQUETS:
			item = self._current_selection_item()
			if item and item.get("type") == "bouquet":
				self.current_bouquet_index = int(item.get("index") or 0)
			self._set_current_bouquet_selected(False)
			index = self.selection_list.getCurrentIndex()
			self.build_bouquet_list()
			self.selection_list.setCurrentIndex(index)
		else:
			self._set_current_bouquet_selected(False)
			self.build_service_list()

	def key_red(self):
		if self.level == self.LEVEL_SERVICES:
			self._sync_current_bouquet_selection()
			self.build_bouquet_list()
		else:
			self.key_cancel()

	def key_left(self):
		if self.level == self.LEVEL_SERVICES:
			self.key_red()

	def key_right(self):
		if self.level == self.LEVEL_BOUQUETS:
			self.key_ok()

	def key_save(self):
		self._sync_current_bouquet_selection()
		services = E2MDBPrefillServices.save(list(self.selected_services))
		self.log(f"SAVE selected={len(services)}")
		self.close(True)

	def key_cancel(self):
		self.close(False)


class E2MDBPrefillStatusScreen(Screen):
	MODULE_NAME = "[E2MDBPrefillStatus]"
	skin = """
	<screen name="E2MDBPrefillStatusScreen" position="center,center" size="920,650" resolution="1280,720" title="e2MDB - Live/EPG Prefill status" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,14" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="#00101824" transparent="1" />
		<widget source="info" render="Label" position="20,60" size="880,520" font="Regular;20" foregroundColor="#ffffff" backgroundColor="#00101824" transparent="1" />
		<widget source="key_red" render="Label" position="20,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,614" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,614" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,614" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,614" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="740,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="738,614" size="170,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="740,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,50" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,604" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Live/EPG Prefill status"))
		self["info"] = StaticText("")
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Refresh"))
		self["key_yellow"] = StaticText(_("Reset No-EPG"))
		self["key_blue"] = StaticText(_("Clear queue"))
		self["actions"] = ActionMap(["ColorActions", "OkCancelActions"], {
			"red": self.close,
			"green": self.refresh,
			"yellow": self.reset_no_epg_state,
			"blue": self.clear_prefill_queue,
			"cancel": self.close,
			"ok": self.refresh,
		}, -1)
		self.refresh()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			timestamp = int(timestamp or 0)
			if timestamp <= 0:
				return "-"
			return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
		except Exception:
			return str(timestamp or "-")

	def _connect(self):
		try:
			return resultsdb._connect()
		except Exception:
			return None

	def _cleanup_state(self, key, default=""):
		try:
			return resultsdb.get_cleanup_state(key, default)
		except Exception:
			return default

	def _prefill_services_count(self):
		try:
			return len(E2MDBPrefillServices.parse())
		except Exception:
			return 0

	def _prefill_state_summary(self):
		path = "/etc/enigma2/e2mdb/prefill_state.json"
		summary = {"path": path, "tracked": 0, "blocked": 0, "last_no_epg": 0, "last_has_events": 0}
		try:
			if not isfile(path):
				return summary
			with open(path, "r", encoding="utf-8") as handle:
				data = load(handle) or {}
			services = data.get("services") or {}
			now = int(datetime.now().timestamp())
			summary["tracked"] = len(services)
			for state in services.values():
				try:
					if int(state.get("no_epg_until") or 0) > now:
						summary["blocked"] += 1
				except Exception:
					pass
				try:
					summary["last_no_epg"] = max(summary["last_no_epg"], int(state.get("last_no_epg") or 0))
				except Exception:
					pass
				try:
					summary["last_has_events"] = max(summary["last_has_events"], int(state.get("last_has_events") or 0))
				except Exception:
					pass
		except Exception as err:
			summary["error"] = str(err)
		return summary

	def _queue_group_rows(self):
		rows = []
		conn = self._connect()
		if not conn:
			return rows
		try:
			with conn:
				cur = conn.execute("""
					SELECT state, reason, priority, COUNT(*) AS count
					FROM e2mdb_fetch_queue
					WHERE reason LIKE 'prefill%'
					GROUP BY state, reason, priority
					ORDER BY priority DESC, state, reason
				""")
				rows = cur.fetchall()
		except Exception as err:
			self.log(f"QUEUE stats failed error={err}")
		return rows

	def _recent_queue_rows(self):
		rows = []
		conn = self._connect()
		if not conn:
			return rows
		try:
			with conn:
				cur = conn.execute("""
					SELECT q.state, q.priority, q.reason, q.title, COALESCE(e.service_name, '') AS service_name, e.status AS event_status, q.begin_time, q.attempts
					FROM e2mdb_fetch_queue q
					LEFT JOIN e2mdb_epg_events e ON e.source_key = q.source_key
					WHERE q.reason LIKE 'prefill%'
					ORDER BY q.updated_at DESC
					LIMIT 10
				""")
				rows = cur.fetchall()
		except Exception as err:
			self.log(f"RECENT queue failed error={err}")
		return rows

	def _recent_event_rows(self):
		rows = []
		conn = self._connect()
		if not conn:
			return rows
		try:
			with conn:
				cur = conn.execute("""
					SELECT service_name, title, status, begin_time, updated_at
					FROM e2mdb_epg_events
					ORDER BY updated_at DESC
					LIMIT 8
				""")
				rows = cur.fetchall()
		except Exception as err:
			self.log(f"RECENT events failed error={err}")
		return rows

	def _build_info_text(self):
		lines = []
		selected_count = self._prefill_services_count()
		last_prefill = self._cleanup_state("last_epg_prefill", "0")
		state = self._prefill_state_summary()
		lines.append(_("Manual selected services: %d") % selected_count)
		lines.append(_("Last prefill run: %s") % self._format_time(last_prefill))
		lines.append(_("Prefill state file: %s") % state.get("path", ""))
		lines.append(_("No-EPG tracked: %d   blocked now: %d") % (state.get("tracked", 0), state.get("blocked", 0)))
		lines.append(_("Last no-EPG: %s   Last service with events: %s") % (self._format_time(state.get("last_no_epg", 0)), self._format_time(state.get("last_has_events", 0))))
		if state.get("error"):
			lines.append(_("Prefill state error: %s") % state.get("error"))
		lines.append("")
		lines.append(_("Prefill queue summary:"))
		queue_rows = self._queue_group_rows()
		if queue_rows:
			for state_name, reason, priority, count in queue_rows:
				lines.append(f"  {state_name or "":-12s} prio={priority or 0:-3s} {reason or "":-24s} {count or 0}")
		else:
			lines.append("  " + _("No prefill queue entries."))
		lines.append("")
		lines.append(_("Recent prefill queue entries:"))
		recent = self._recent_queue_rows()
		if recent:
			for state_name, priority, reason, title, service_name, event_status, begin_time, attempts in recent:
				lines.append(f"  {state_name or ''}/{event_status or ''} {self._format_time(begin_time)} {service_name or ''} - {title or ''}")
		else:
			lines.append("  " + _("No recent prefill queue entries."))
		lines.append("")
		lines.append(_("Recent Live/EPG events:"))
		for service_name, title, status, begin_time, updated_at in self._recent_event_rows():
			lines.append(f"  {self._format_time(begin_time)} {service_name or ''} - {title or ''} ({status or ''})")
		return "\n".join(lines)

	def refresh(self):
		try:
			self["info"].setText(self._build_info_text())
		except Exception as err:
			self["info"].setText(_("Failed to read prefill status: %s") % err)
			self.log(f"REFRESH failed error={err}")

	def reset_no_epg_state(self):
		path = "/etc/enigma2/e2mdb/prefill_state.json"
		try:
			if isfile(path):
				remove(path)
			try:
				from .E2MDBPrefillManager import get_prefill_service_state
				get_prefill_service_state().data = None
			except Exception:
				pass
			self.log(f"RESET no-epg-state file='{path}'")
		except Exception as err:
			self.log(f"RESET no-epg-state failed error={err}")
		self.refresh()

	def clear_prefill_queue(self):
		deleted = 0
		conn = self._connect()
		if conn:
			try:
				with conn:
					cur = conn.execute("DELETE FROM e2mdb_fetch_queue WHERE reason LIKE 'prefill%'")
					deleted = cur.rowcount
				self.log(f"CLEAR prefill-queue deleted={deleted}")
			except Exception as err:
				self.log(f"CLEAR prefill-queue failed error={err}")
		self.refresh()


class E2MDBWorkerQueueStatusScreen(Screen):
	MODULE_NAME = "[E2MDBWorkerQueueStatus]"
	skin = """
	<screen name="E2MDBWorkerQueueStatusScreen" position="center,center" size="920,650" resolution="1280,720" title="e2MDB - Live/EPG Worker queue" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="info" render="Label" position="20,60" size="880,520" font="Regular;20" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="key_red" render="Label" position="20,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,614" size="170,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="200,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="198,614" size="170,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="200,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_yellow" render="Label" position="380,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="yellow_bg" position="378,614" size="170,30" backgroundColor="yellow" cornerRadius="4" zPosition="-2" />
		<eLabel name="yellow_bg_center" position="380,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="560,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="558,614" size="170,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="560,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="740,616" size="166,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="738,614" size="170,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="740,616" size="166,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,50" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,604" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Live/EPG Worker queue"))
		self["info"] = StaticText("")
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Refresh"))
		self["key_yellow"] = StaticText(_("Retry no match"))
		self["key_blue"] = StaticText(_("Clear failed"))
		self["key_ok"] = StaticText(_("Clear prefill"))
		self.last_action = ""
		self["actions"] = ActionMap(["ColorActions", "OkCancelActions"], {
			"red": self.close,
			"green": self.refresh,
			"yellow": self.retry_no_match,
			"blue": self.clear_failed,
			"cancel": self.close,
			"ok": self.clear_prefill,
		}, -1)
		self.refresh()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			timestamp = int(timestamp or 0)
			if timestamp <= 0:
				return "-"
			return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
		except Exception:
			return str(timestamp or "-")

	def _connect(self):
		try:
			return resultsdb._connect()
		except Exception:
			return None

	def _fetchall(self, query, args=()):
		conn = self._connect()
		if not conn:
			return []
		try:
			with conn:
				return conn.execute(query, args).fetchall()
		except Exception as err:
			self.log(f"QUERY failed error={err}")
			return []

	def _build_info_text(self):
		lines = []
		lines.append(_("Queue state summary:"))
		rows = self._fetchall("""
			SELECT state, reason, priority, COUNT(*) AS count
			FROM e2mdb_fetch_queue
			GROUP BY state, reason, priority
			ORDER BY priority DESC, state, reason
		""")
		if rows:
			for state, reason, priority, count in rows:
				lines.append(f"  {state or "":-14s} prio={priority or 0:-3s} {reason or "":-28s} {count or 0}")
		else:
			lines.append("  " + _("No queue entries."))
		lines.append("")
		lines.append(_("Pending worker queue:"))
		pending = self._fetchall("""
			SELECT q.state, q.priority, q.reason, q.title, COALESCE(e.service_name, '') AS service_name, e.status AS event_status, q.begin_time, q.attempts
			FROM e2mdb_fetch_queue q
			LEFT JOIN e2mdb_epg_events e ON e.source_key = q.source_key
			WHERE q.state='pending'
			ORDER BY q.priority DESC, q.begin_time ASC
			LIMIT 18
		""")
		if pending:
			for state, priority, reason, title, service_name, event_status, begin_time, attempts in pending:
				lines.append(f"  p{priority or 0:-3s} {service_name or "":-18s} {self._format_time(begin_time)} - {title or ""}")
		else:
			lines.append("  " + _("No pending queue entries."))
		lines.append("")
		lines.append(_("Recently updated queue entries:"))
		recent = self._fetchall("""
			SELECT q.state, q.priority, q.reason, q.title, COALESCE(e.service_name, '') AS service_name, e.status AS event_status, q.begin_time, q.updated_at
			FROM e2mdb_fetch_queue q
			LEFT JOIN e2mdb_epg_events e ON e.source_key = q.source_key
			ORDER BY q.updated_at DESC
			LIMIT 10
		""")
		if recent:
			for state, priority, reason, title, service_name, event_status, begin_time, updated_at in recent:
				lines.append(f"  {state or "":-10s}/{event_status or "":-10s} {self._format_time(updated_at)} {service_name or ""} - {title or ""}")
		else:
			lines.append("  " + _("No recent queue entries."))
		if self.last_action:
			lines.append("")
			lines.append(self.last_action)
		return "\n".join(lines)

	def refresh(self):
		try:
			self.last_action = _("Last action: refreshed at %s") % self._format_time(int(time()))
			self["info"].setText(self._build_info_text())
			self.log("REFRESH done")
		except Exception as err:
			self["info"].setText(_("Failed to read worker queue: %s") % err)
			self.log(f"REFRESH failed error={err}")

	def _clear_queue(self, mode, label=""):
		try:
			result = backend_request("live_queue_clear", mode=mode) or {}
			removed = int(result.get("removed") or 0)
			if result.get("success"):
				self.last_action = _("Last action: %s removed %d queue entries.") % (label or mode, removed)
			else:
				self.last_action = _("Last action failed: %s") % str(result.get("error") or "unknown error")
			self.log(f"CLEAR mode={mode} result={result}")
		except Exception as err:
			self.last_action = _("Last action failed: %s") % str(err)
			self.log(f"CLEAR mode={mode} failed error={err}")
		try:
			self["info"].setText(self._build_info_text())
		except Exception as err:
			self["info"].setText(_("Failed to read worker queue: %s") % err)

	def clear_finished(self):
		self._clear_queue("finished", label=_("finished"))

	def retry_no_match(self):
		try:
			result = backend_request("live_queue_retry_no_match", active_only=True, priority=90) or {}
			requeued = int(result.get("requeued") or 0)
			if result.get("success"):
				if requeued:
					wake = backend_request(
						"live_worker_start",
						source="enigma-manual-no-match-retry",
						limit=max(1, min(100, requeued)),
					) or {}
					wake_state = _("worker requested") if wake.get("success") else _("worker request failed")
					self.last_action = _("Last action: requeued %d active no-match entries, %s.") % (requeued, wake_state)
				else:
					self.last_action = _("Last action: no active no-match entries found.")
			else:
				self.last_action = _("Last action failed: %s") % str(result.get("error") or "unknown error")
			self.log(f"RETRY no-match result={result}")
		except Exception as err:
			self.last_action = _("Last action failed: %s") % str(err)
			self.log(f"RETRY no-match failed error={err}")
		try:
			self["info"].setText(self._build_info_text())
		except Exception as err:
			self["info"].setText(_("Failed to read worker queue: %s") % err)

	def clear_failed(self):
		self._clear_queue("failed", label=_("failed/error"))

	def clear_prefill(self):
		self._clear_queue("prefill", label=_("prefill"))


class E2MDBCleanupStatusScreen(Screen):
	MODULE_NAME = "[E2MDBCleanupStatus]"
	skin = """
	<screen name="E2MDBCleanupStatusScreen" position="center,center" size="920,650" resolution="1280,720" title="e2MDB - DB status and maintenance" backgroundColor="#20000000" flags="wfNoBorder">
		<widget source="Title" render="Label" position="20,10" size="880,34" font="Regular;26" halign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="info" render="Label" position="20,60" size="880,520" font="Regular;20" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<widget source="key_red" render="Label" position="20,616" size="206,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="red_bg" position="18,614" size="210,30" backgroundColor="red" cornerRadius="4" zPosition="-2" />
		<eLabel name="red_bg_center" position="20,616" size="206,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_green" render="Label" position="246,616" size="206,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="green_bg" position="244,614" size="210,30" backgroundColor="green" cornerRadius="4" zPosition="-2" />
		<eLabel name="green_bg_center" position="246,616" size="206,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_blue" render="Label" position="472,616" size="206,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="blue_bg" position="470,614" size="210,30" backgroundColor="blue" cornerRadius="4" zPosition="-2" />
		<eLabel name="blue_bg_center" position="472,616" size="206,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<widget source="key_ok" render="Label" position="698,616" size="206,26" zPosition="1" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="black" transparent="1" />
		<eLabel name="ok_bg" position="696,614" size="210,30" backgroundColor="#666666" cornerRadius="4" zPosition="-2" />
		<eLabel name="ok_bg_center" position="698,616" size="206,26" backgroundColor="black" cornerRadius="4" zPosition="-1" />
		<eLabel name="line" position="20,50" size="880,1" backgroundColor="grey" />
		<eLabel name="line" position="20,604" size="880,1" backgroundColor="grey" />
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("DB status and maintenance"))
		self["info"] = StaticText("")
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Refresh"))
		self["key_blue"] = StaticText(_("Run cleanup"))
		self["key_ok"] = StaticText(_("DB maintenance"))
		self.last_result = None
		self["actions"] = ActionMap(["ColorActions", "OkCancelActions"], {
			"red": self.close,
			"green": self.refresh,
			"blue": self.run_cleanup,
			"cancel": self.close,
			"ok": self.run_db_cleanup,
		}, -1)
		self.refresh()

	def log(self, message):
		try:
			write_log(self.MODULE_NAME, message)
		except Exception:
			print(self.MODULE_NAME, message)

	def _format_time(self, timestamp):
		try:
			timestamp = int(timestamp or 0)
			if timestamp <= 0:
				return "-"
			return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
		except Exception:
			return str(timestamp or "-")

	def _cleanup_state(self, key, default=""):
		try:
			if not hasattr(self, "_last_cleanup_diag") or not isinstance(self._last_cleanup_diag, dict):
				self._last_cleanup_diag = backend_request("cleanup_status")
			return self._last_cleanup_diag.get(key, default)
		except Exception:
			return default

	def _safe_int(self, value, default=0):
		try:
			return int(value or 0)
		except Exception:
			return default

	def _format_size(self, value):
		try:
			value = float(value or 0)
		except Exception:
			value = 0.0
		units = ("B", "KB", "MB", "GB", "TB")
		index = 0
		while value >= 1024.0 and index < len(units) - 1:
			value /= 1024.0
			index += 1
		if index == 0:
			return f"{int(value)} {units[index]}"
		return f"{value:.1f} {units[index]}"

	def _quick_database_status(self):
		try:
			status = backend_request("database_status", timeout=2.0) or {}
			if isinstance(status, dict):
				return status
			return {"success": False, "error": "invalid response"}
		except Exception as err:
			return {"success": False, "error": str(err)}

	def _format_count(self, value):
		try:
			value = int(value)
			if value < 0:
				return "-"
			return str(value)
		except Exception:
			return "-"

	def _format_decimal(self, value, default="-"):
		try:
			return f"{float(value):.1f}"
		except Exception:
			return default

	def _format_cpu_percent(self, system):
		system = system if isinstance(system, dict) else {}
		value = system.get("cpu_percent")
		if value is None:
			value = system.get("load_percent")
		try:
			return f"{float(value):.1f}%"
		except Exception:
			return "-"

	def _build_info_text(self):
		diag = backend_request("cleanup_status")
		self._last_cleanup_diag = diag
		db_status = self._quick_database_status()
		inventory = db_status.get("inventory") if isinstance(db_status.get("inventory"), dict) else {}
		last_cleanup = diag.get("last_cleanup", 0)
		queue_states = diag.get("queue_states") or {}
		lines = []
		db_state = db_status.get("exists") and _("available") or _("not available")
		lines.append(_("Database: %s  Size: %s  Free inside DB: %s") % (db_state, self._format_size(db_status.get("total_size_bytes", db_status.get("size_bytes", 0))), self._format_size(db_status.get("freelist_bytes", 0))))
		system = db_status.get("system") if isinstance(db_status.get("system"), dict) else {}
		if system:
			lines.append(_("CPU load: %s  System load: %s / %d cores") % (self._format_cpu_percent(system), self._format_decimal(system.get("load1")), max(1, self._safe_int(system.get("cores"), 1))))
		if db_status.get("busy"):
			lines.append(_("Database is currently busy; refresh again for detailed counters."))
		elif db_status.get("success"):
			lines.append(_("Imported files: %s  Media entries: %s  Browser-ready: %s") % (self._format_count(inventory.get("recordings_total")), self._format_count(inventory.get("media_total")), self._format_count(inventory.get("browser_ready"))))
			lines.append(_("File split: TS recordings %s  media files %s") % (self._format_count(inventory.get("ts_recordings")), self._format_count(inventory.get("media_files"))))
			lines.append(_("Media types: movies %s  series %s  episodes %s  unknown %s") % (self._format_count(inventory.get("movies")), self._format_count(inventory.get("series")), self._format_count(inventory.get("local_episodes")), self._format_count(inventory.get("unknown"))))
			lines.append(_("Provider: done %s  pending %s  missing %s  errors %s") % (self._format_count(inventory.get("provider_done")), self._format_count(inventory.get("provider_pending")), self._format_count(inventory.get("provider_missing")), self._format_count(inventory.get("provider_errors"))))
			lines.append(_("Artwork: with artwork %s  missing artwork %s") % (self._format_count(inventory.get("media_with_artwork")), self._format_count(inventory.get("missing_artwork"))))
			lines.append(_("Live/EPG: active %s  expired %s  queue %s") % (self._format_count(inventory.get("live_epg_active")), self._format_count(inventory.get("live_epg_expired")), self._format_count(inventory.get("queue_total"))))
		else:
			lines.append(_("DB status could not be read: %s") % str(db_status.get("error") or "unknown error"))
		lines.append("")
		lines.append(_("Maintenance: enabled %s  VACUUM %s  REINDEX %s") % (diag.get("sqlite_maintenance_enabled") and _("Yes") or _("No"), diag.get("sqlite_vacuum_enabled") and _("Yes") or _("No"), diag.get("sqlite_reindex_enabled") and _("Yes") or _("No")))
		lines.append(_("Last cleanup: %s") % self._format_time(last_cleanup))
		lines.append(_("Last SQLite maintenance: %s") % self._format_time(diag.get("last_sqlite_maintenance", 0)))
		lines.append(_("Cleanup candidates: expired Live/EPG %s  queue %s  primary cache %s") % (self._format_count(diag.get("expired_events")), self._format_count(diag.get("queue_cleanup_candidates")), self._format_count(diag.get("cache_candidates"))))
		lines.append(_("Prefill state: tracked %s  blocked now %s") % (self._format_count(diag.get("prefill_state_tracked")), self._format_count(diag.get("prefill_state_blocked"))))
		state_parts = []
		if queue_states:
			for state_name in sorted(queue_states.keys()):
				state_parts.append(f"{state_name or "-"} {queue_states.get(state_name) or 0}")
		lines.append(_("Queue states: %s") % (", ".join(state_parts[:6]) if state_parts else _("No queue entries.")))
		lines.append("")
		if self.last_result:
			result = self.last_result
			lines.append(_("Last manual action result:"))
			lines.append(f"  result={result.get("result")} reason={result.get("reason")}")
			lines.append(f"  events={result.get("events", 0)} queue={result.get("queue", 0)} prefill_state_removed={result.get("prefill_state_removed", 0)}")
			lines.append(f"  cache_candidates={result.get("cache_candidates", 0)} cache_deleted={result.get("cache_deleted", 0)} cache_kept={result.get("cache_kept", 0)} errors={result.get("cache_errors", 0)}")
			if result.get("sqlite_maintenance"):
				lines.append(f"  sqlite_saved={self._format_size(result.get("sqlite_size_saved", 0))}")
			elif result.get("size_saved") is not None:
				lines.append(f"  sqlite_saved={self._format_size(result.get("size_saved", 0))}")
		else:
			try:
				stats = self._cleanup_state("last_epg_cleanup_stats", "")
				if stats:
					lines.append(_("Last cleanup stats:"))
					lines.append("  " + stats[:220])
			except Exception:
				pass
		return "\n".join(lines)

	def refresh(self):
		try:
			self["info"].setText(self._build_info_text())
		except Exception as err:
			self["info"].setText(_("Failed to read DB status: %s") % err)
			self.log(f"REFRESH failed error={err}")

	def run_cleanup(self):
		try:
			self.last_result = run_backend_live_cleanup(reason="setup-manual", dry_run=False)
			self.log(f"RUN backend cleanup result={self.last_result.get('result')} events={self.last_result.get('events', 0)} queue={self.last_result.get('queue', 0)} cache_deleted={self.last_result.get('cache_deleted', 0)}")
		except Exception as err:
			self.last_result = {"result": "failed", "reason": "setup-manual", "error": str(err)}
			self.log(f"RUN backend cleanup failed error={err}")
		self.refresh()

	def run_db_cleanup(self):
		try:
			diag = backend_request("cleanup_status")
			self.last_result = backend_request("database_maintenance", vacuum=bool(diag.get("sqlite_vacuum_enabled", True)), analyze=True, reindex=bool(diag.get("sqlite_reindex_enabled", False)))
			self.log(f"RUN backend sqlite-maintenance result={self.last_result.get('result')} saved={self.last_result.get('size_saved', 0)}")
		except Exception as err:
			self.last_result = {"result": "failed", "reason": "setup-sqlite-maintenance", "error": str(err)}
			self.log(f"RUN backend sqlite-maintenance failed error={err}")
		self.refresh()


class E2MDBSetup(Setup, E2MDBHelper):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="e2MDB", plugin="Extensions/e2MDB", PluginLanguageDomain=PluginLanguageDomain)
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText(_("Prefill channels"))
		self["key_blue"] = StaticText(_("More..."))
		# Keep the normal Setup green/save behavior.  Live/EPG tools are opened
		# via the menu key only, while yellow/blue keep the e2MDB shortcuts.
		self["e2mdb_prefill_actions"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.key_prefill_services, _("Select manual Live/EPG prefill channels")),
			"blue": (self.key_tools, _("More...")),
		}, prio=-100)

	def keySave(self):
		try:
			Setup.keySave(self)
		except Exception:
			try:
				configfile.save()
			except Exception:
				pass
		try:
			init_backend_config(reason="setup-save")
			try:
				backend_request("settings_reload")
			except Exception as reload_err:
				write_log("[e2MDB][BACKEND-CONFIG]", f"setup-save backend reload skipped error={reload_err}")
		except Exception as err:
			write_log("[e2MDB][BACKEND-CONFIG]", f"setup-save export failed error={err}")

	def key_tools(self):
		choices = [
			(_("Live/EPG worker queue"), "worker-queue"),
			(_("Retry missing media metadata/artwork"), "media-retry-missing"),
			(_("DB status and maintenance"), "cleanup-status"),
			(_("Run Live/EPG prefill now"), "prefill-now"),
			(_("Prefill status / diagnostics"), "prefill-status"),
			(_("Ignored EPG title patterns"), "epg-title"),
			(_("Ignored service name patterns"), "service-name"),
			(_("Ignored folder name patterns"), "folder-name"),
		]
		self.session.openWithCallback(self._ignore_list_selected, ChoiceBox, title=_("e2MDB tools"), list=choices)

	def _open_ignore_pattern_list(self, key):
		if key == "epg-title":
			self.session.openWithCallback(lambda result=None: self.createSetup(), E2MDBPatternListSelection, _("Ignored EPG title patterns"), E2MDBIgnorePatterns.EPG_TITLE, source_type=E2MDBIgnorePatterns.EPG_TITLE)
		elif key == "service-name":
			self.session.openWithCallback(lambda result=None: self.createSetup(), E2MDBPatternListSelection, _("Ignored service name patterns"), E2MDBIgnorePatterns.SERVICE_NAME, source_type=E2MDBIgnorePatterns.SERVICE_NAME)
		elif key == "folder-name":
			self.session.openWithCallback(lambda result=None: self.createSetup(), E2MDBPatternListSelection, _("Ignored folder name patterns"), E2MDBIgnorePatterns.FOLDER_NAME, source_type=E2MDBIgnorePatterns.FOLDER_NAME)

	def _ignore_list_selected(self, selection):
		if not selection:
			return
		label, key = selection
		if key == "worker-queue":
			self.session.open(E2MDBWorkerQueueStatusScreen)
		elif key == "media-retry-missing":
			self._run_media_retry_missing()
		elif key == "cleanup-status":
			self.session.open(E2MDBCleanupStatusScreen)
		elif key == "prefill-status":
			self.session.open(E2MDBPrefillStatusScreen)
		elif key == "prefill-now":
			self._run_prefill_now()
		elif key in ("epg-title", "service-name", "folder-name"):
			self._open_ignore_pattern_list(key)

	def _run_media_retry_missing(self):
		try:
			init_backend_config(reason="manual-media-retry")
			reload_result = backend_request("settings_reload") or {}
			if not reload_result.get("success"):
				raise RuntimeError(reload_result.get("error") or "settings reload failed")
			response = backend_request(
				"start_job",
				job="metadata_enrich",
				source="enigma-manual-media-retry",
				options={
					"limit": 0,
					"only_missing": True,
					"rescan_existing": False,
					"retry_no_match": True,
					"retry_missing_artwork": True,
				},
			) or {}
			if not response.get("success"):
				raise RuntimeError(response.get("error") or "backend job could not be started")
			self.session.open(
				MessageBox,
				_("Retry of missing media metadata/artwork started."),
				type=MessageBox.TYPE_INFO,
				timeout=6,
				close_on_any_key=True,
			)
			write_log("[e2MDB][SETUP]", "MEDIA retry-missing started")
		except Exception as err:
			self.session.open(
				MessageBox,
				_("Could not start missing media metadata/artwork retry:\n%s") % err,
				type=MessageBox.TYPE_ERROR,
				timeout=10,
				close_on_any_key=True,
			)
			write_log("[e2MDB][SETUP]", f"MEDIA retry-missing failed error={err}")

	def key_prefill_services(self):
		self.session.openWithCallback(lambda result=None: self._refresh_setup_safe(), E2MDBPrefillServiceSelection)

	def _refresh_setup_safe(self):
		try:
			self.createSetup()
		except Exception:
			pass

	def _set_prefill_button_status(self, text):
		try:
			self["key_blue"].setText(text)
		except Exception:
			pass

	def _run_prefill_now(self):
		# The setup key handler must not touch EPGCache or start prefill work directly.
		# It only writes a lightweight request file. The PrefillManager polling timer
		# will pick it up from the Enigma2 main loop a few seconds later.
		if prefill_background_running():
			write_log("[e2MDB][PREFILL][SETUP]", "REQUEST skipped reason=busy")
			self._set_prefill_button_status(_("Prefill busy"))
			return
		if request_prefill_background(reason="setup-manual", force=True):
			write_log("[e2MDB][PREFILL][SETUP]", "REQUEST written reason=setup-manual")
			self._set_prefill_button_status(_("Prefill requested"))
		else:
			write_log("[e2MDB][PREFILL][SETUP]", "REQUEST failed")
			self._set_prefill_button_status(_("Prefill request failed"))


class E2MDBInfoBox(Screen):
	skin = """
	<screen name="E2MDBInfoBox" position="390,432" size="500,110" flags="wfNoBorder" resolution="1280,720" title="e2MDB Infobox">
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


def E2MDBshowEventInformation(self):
	if not _useE2MDBMediaEventView():
		old_show_event_information(self)
		return
	e2mdbhelper = E2MDBHelper()
	current = self.getCurrent()
	org_path = current.getPath()
	json_path = e2mdbhelper.get_primary_datapath(org_path)
	event = self["list"].getCurrentEvent()
	db_row = {}
	media_row = {}
	try:
		service_ref = current.toString() if hasattr(current, "toString") else str(current or "")
		event_id = event.getEventId() if event and hasattr(event, "getEventId") else 0
		begin_time = event.getBeginTime() if event and hasattr(event, "getBeginTime") else 0
		title = event.getEventName() if event and hasattr(event, "getEventName") else ""
		db_row = resultsdb.get_epg_event_for_service(service_ref, event_id=event_id, begin_time=begin_time, title=title)
	except Exception:
		db_row = {}
	try:
		media_hash = e2mdbhelper.get_reduced_org_hash(org_path)
		media_row = resultsdb.get_media_metadata(media_hash)
	except Exception:
		media_row = {}
	media_has_metadata = False
	try:
		media_has_metadata = bool(media_row and (media_row.get("metadata_title") or media_row.get("metadata_overview") or media_row.get("metadata_cover_path") or media_row.get("metadata_backdrop_path") or media_row.get("metadata_image_path")))
	except Exception:
		media_has_metadata = False
	epg_has_metadata = _epgRowHasE2MDBMetadata(db_row)
	if epg_has_metadata or media_has_metadata:
		self.session.open(E2MDBEventViewSimple, event, ServiceReference(current), org_path, json_path)
	else:
		old_show_event_information(self)


# The old in-process Enigma2 background scanner has been removed.
# Clean-start builds forward all scan/enrich work to e2mdbd.


def start_task(callback, entry=None, **kwargs):
	return start_scan_task(callback, entry, **kwargs)


def stop_task(**kwargs):
	return stop_scan_task(**kwargs)


class E2MDBPrefillSchedulerTask:
	"""Scheduler wrapper for OpenATV Live/EPG prefill runs.

	The OpenATV timer must stay running until the prefill really finished. If a
	prefill is already active when the timer starts, this wrapper retries inside
	the timer window instead of reporting immediate success.
	"""

	MODULE_NAME = "[e2MDB][PREFILL][TASK]"
	RETRY_INTERVAL_MS = 60000

	def __init__(self):
		self.callback = None
		self.entry = None
		self.running = False
		self.cancel_requested = False
		self.retry_timer = eTimer()
		self.retry_timer.callback.append(self._try_start_prefill)

	def _log_timer(self, code, message):
		entry = self.entry
		try:
			if entry and hasattr(entry, "log"):
				entry.log(code, message)
		except Exception:
			pass

	def _deadline(self):
		try:
			return int(getattr(self.entry, "end", 0) or 0)
		except Exception:
			return 0

	def start(self, callback, entry=None, **kwargs):
		if not callback or not callable(callback):
			return False
		if self.running:
			write_log(self.MODULE_NAME, "START refused reason=task-wrapper-busy", level="error")
			return False
		self.callback = callback
		self.entry = entry
		self.running = True
		self.cancel_requested = False
		self._log_timer(10, "e2MDB Live/EPG Prefill timer started.")
		write_log(self.MODULE_NAME, "START timer reason=scheduler-task force=True")
		self._try_start_prefill()
		return True

	def stop(self, **kwargs):
		write_log(self.MODULE_NAME, f"STOP requested running={self.running}")
		self.cancel_requested = True
		try:
			self.retry_timer.stop()
		except Exception:
			pass
		if self.running and not prefill_background_running():
			self._finish(success=False)

	def _schedule_retry(self, reason):
		deadline = self._deadline()
		now = int(time())
		if deadline > 0 and now < deadline and not self.cancel_requested:
			remaining_ms = max(1000, min(self.RETRY_INTERVAL_MS, (deadline - now) * 1000))
			self._log_timer(20, f"e2MDB Live/EPG Prefill {reason}; retrying within timer window.")
			write_log(self.MODULE_NAME, f"RETRY reason={reason} until={deadline}")
			try:
				self.retry_timer.start(int(remaining_ms), True)
			except Exception:
				self._finish(success=False)
			return True
		self._log_timer(30, f"e2MDB Live/EPG Prefill could not start before timer window ended: {reason}.")
		write_log(self.MODULE_NAME, f"FAILED retry-window-ended reason={reason}", level="error")
		self._finish(success=False)
		return False

	def _try_start_prefill(self):
		if not self.running:
			return
		if self.cancel_requested:
			self._finish(success=False)
			return
		if prefill_background_running():
			self._schedule_retry("busy")
			return
		self._log_timer(10, "e2MDB Live/EPG Prefill started.")
		write_log(self.MODULE_NAME, "START background reason=scheduler-task force=True")
		started = run_prefill_background(reason="scheduler-task", force=True, callback=self._background_done)
		if not started:
			self._schedule_retry("busy")

	def _finish(self, success=True):
		try:
			self.retry_timer.stop()
		except Exception:
			pass
		callback = self.callback
		self.callback = None
		self.entry = None
		self.running = False
		self.cancel_requested = False
		if callback and callable(callback):
			try:
				# OpenATV Scheduler.functionTimerCallback expects True for success and False for failure.
				callback(bool(success))
			except Exception as err:
				write_log(self.MODULE_NAME, f"CALLBACK failed error={err}", level="error")

	def _background_done(self, result, error=None):
		if error:
			write_log(self.MODULE_NAME, f"FAILED error={error}", level="error")
			self._log_timer(30, f"e2MDB Live/EPG Prefill failed: {error}")
			self._finish(success=False)
			return
		result = result or {}
		message = "result={} services={} inserted={} queued={} skipped={} provider_skipped={} no_epg={} no_epg_skipped={} ignored_services={}".format(
			result.get("result", "unknown"),
			result.get("services", 0),
			result.get("inserted", 0),
			result.get("queued", 0),
			result.get("skipped", 0),
			result.get("provider_skipped", 0),
			result.get("no_epg_services", 0),
			result.get("no_epg_skipped", 0),
			result.get("ignored_services", 0),
		)
		write_log(self.MODULE_NAME, "DONE " + message)
		self._log_timer(10, "e2MDB Live/EPG Prefill finished: " + message)
		if self.cancel_requested:
			self._finish(success=False)
			return
		self._finish(success=result.get("result") in ("ok", "no-services"))


e2mdb_prefill_scheduler_task = E2MDBPrefillSchedulerTask()


def start_prefill_task(callback, entry, **kwargs):
	return e2mdb_prefill_scheduler_task.start(callback, entry, **kwargs)


def stop_prefill_task(**kwargs):
	e2mdb_prefill_scheduler_task.stop(**kwargs)


def _getServicelistInfoKeyValue(default="event"):
	try:
		info_key_config = getattr(getattr(config, "usage", None), "servicelist_infokey", None)
		return getattr(info_key_config, "value", default) if info_key_config is not None else default
	except Exception:
		return default


def _useE2MDBEPGEventView():
	try:
		return bool(config.plugins.e2mdb.epgEventViewUseE2MDB.value)
	except Exception:
		return True


def _useE2MDBMediaEventView():
	try:
		return bool(config.plugins.e2mdb.mediaEventViewUseE2MDB.value)
	except Exception:
		return True


def _epgRowHasE2MDBMetadata(row):
	if not row:
		return False
	metadata_keys = (
		"metadata_title", "metadata_subtitle", "metadata_overview", "metadata_genres",
		"metadata_provider", "metadata_provider_ids", "metadata_media_type", "metadata_year",
		"metadata_runtime", "metadata_rating", "metadata_vote_count", "metadata_cover_path",
		"metadata_backdrop_path", "metadata_logo_path", "metadata_image_path", "metadata_released",
		"metadata_countries", "metadata_age_rating", "metadata_cast", "metadata_crew",
		"metadata_season_no", "metadata_episode_no"
	)
	try:
		return any(bool(row.get(key)) for key in metadata_keys)
	except Exception:
		return False


def _getE2MDBEPGEventRow(ref, event):
	try:
		from .E2MDBLiveEPG import E2MDBLiveEPG
		adapter = E2MDBLiveEPG()
		service = ServiceReference(ref)
		try:
			service_name = service.getServiceName() or ""
		except Exception:
			service_name = ""
		candidate = adapter.event_to_candidate(service, event, service_name=service_name, source_type=adapter.SOURCE_EPG)
		row = resultsdb.get_epg_event_readonly(candidate.source_key)
		return candidate, row
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR reading e2MDB EPG metadata: {err}")
		return None, {}


def shouldUseE2MDBEPGEventView(event=None, serviceRef=None):
	"""Return True when the global EventView hook should open the e2MDB EPG EventView."""
	if not _useE2MDBEPGEventView():
		return False
	if event is None or serviceRef is None:
		return False
	try:
		ref = getattr(serviceRef, "ref", serviceRef)
	except Exception:
		ref = serviceRef
	_candidate, event_row = _getE2MDBEPGEventRow(ref, event)
	return _epgRowHasE2MDBMetadata(event_row)


def _getChannelSelectionEventList(channel_selection):
	try:
		ref = channel_selection.getCurrentSelection()
	except Exception:
		ref = None
	if not ref:
		return None, []
	epglist = []
	try:
		epg = eEPGCache.getInstance()
		ptr = ref and ref.valid() and epg.lookupEventTime(ref, -1)
		if ptr:
			epglist.append(ptr)
			ptr = epg.lookupEventTime(ref, ptr.getBeginTime(), +1)
			if ptr:
				epglist.append(ptr)
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR reading service-list EPG event: {err}")
	return ref, epglist


def _openE2MDBEventViewFromChannelSelection(channel_selection):
	if not _useE2MDBEPGEventView():
		return False
	ref, epglist = _getChannelSelectionEventList(channel_selection)
	if not ref or not epglist:
		return False
	candidate, event_row = _getE2MDBEPGEventRow(ref, epglist[0])
	if not _epgRowHasE2MDBMetadata(event_row):
		return False
	try:
		from .E2MDBEventViewEPG import E2MDBEventViewEPGSelect
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR loading e2MDB EventView screen: {err}")
		return False
	try:
		channel_selection.epglist = epglist
	except Exception:
		pass
	try:
		channel_selection.session.openWithCallback(
			lambda *args, **kwargs: None,
			E2MDBEventViewEPGSelect,
			epglist[0],
			ServiceReference(ref),
			channel_selection.eventViewCallback,
			None,
			None,
			channel_selection.eventViewSimilarCallback,
			None
		)
		return True
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR opening e2MDB EventView: {err}")
		return False


def _openSingleEPGWithE2MDBMetaFromChannelSelection(channel_selection):
	"""Open the normal OpenATV Single EPG.

	e2MDB metadata is attached by the generic EPGSelection hook to the standard
	Event/Service sources, so no dedicated e2MDB EPG screen or EPG skin alias
	is required. Skinners can extend the regular EPGSelection/GraphicalEPG/etc.
	skins with condition="config.plugins.e2mdb.epgMetaEnabled.value".
	"""
	try:
		ref = channel_selection.getCurrentSelection()
	except Exception:
		ref = None
	if not ref:
		return False
	try:
		from Screens.EpgSelection import EPGSelection
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR importing standard EPGSelection: {err}")
		return False
	try:
		channel_selection.savedService = ref
	except Exception:
		pass
	try:
		channel_selection.session.openWithCallback(channel_selection.SingleServiceEPGClosed, EPGSelection, ref, serviceChangeCB=channel_selection.changeServiceCB, EPGtype="single")
		return True
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR opening standard Single EPG with e2MDB metadata hook: {err}")
		return False


def registerInfoKeyScreenHandlers():
	try:
		from Screens.ChannelSelection import registerServicelistInfoKeyHandler
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR service-list info-key registry unavailable: {err}")
		return False
	ok = True
	try:
		ok = registerServicelistInfoKeyHandler(E2MDB_SERVICE_LIST_EVENTVIEW_KEY, _openE2MDBEventViewFromChannelSelection) and ok
		ok = registerServicelistInfoKeyHandler(E2MDB_SERVICE_LIST_EPG_KEY, _openSingleEPGWithE2MDBMetaFromChannelSelection) and ok
	except Exception as err:
		write_log(f"[e2MDB][INFOKEY] ERROR registering service-list info-key handlers: {err}")
		return False
	return ok


def _getOptionalEventViewSimple(event=None, serviceRef=None):
	if not shouldUseE2MDBEPGEventView(event, serviceRef):
		return EventViewSimple
	try:
		from .E2MDBEventViewEPG import E2MDBEventViewEPG
		return E2MDBEventViewEPG
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] ERROR loading e2MDB simple EventView: {err}")
		return EventViewSimple


def _getOptionalEventViewEPGSelect(event=None, serviceRef=None):
	if not shouldUseE2MDBEPGEventView(event, serviceRef):
		return EventViewEPGSelect
	try:
		from .E2MDBEventViewEPG import E2MDBEventViewEPGSelect
		return E2MDBEventViewEPGSelect
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] ERROR loading e2MDB EventViewEPGSelect: {err}")
		return EventViewEPGSelect


def _showEventViewCallback(closeCallback, session, simple, event, serviceRef, callback=None, singleEPGCB=None, multiEPGCB=None, similarEPGCB=None, skinName=None):
	if not closeCallback:
		closeCallback = lambda *args, **kwargs: None
	if simple:
		screenClass = _getOptionalEventViewSimple(event, serviceRef)
		return session.openWithCallback(closeCallback, screenClass, event, serviceRef, callback, similarEPGCB=similarEPGCB, skin=skinName or "EventViewSimple")
	screenClass = _getOptionalEventViewEPGSelect(event, serviceRef)
	return session.openWithCallback(closeCallback, screenClass, event, serviceRef, callback, singleEPGCB=singleEPGCB, multiEPGCB=multiEPGCB, similarEPGCB=similarEPGCB, skinName=skinName)


def _getEventViewInstance(session, event, serviceRef, skinName=None):
	if skinName == "InfoBarEventView":
		return session.instantiateDialog(EventViewSimple, event, serviceRef, skin=skinName)
	screenClass = _getOptionalEventViewSimple(event, serviceRef)
	return session.instantiateDialog(screenClass, event, serviceRef, skin=skinName or "EventViewSimple")


def installEventViewHooks():
	try:
		import Screens.EventView
		Screens.EventView.showEventViewCallback = _showEventViewCallback
		Screens.EventView.getEventViewInstance = _getEventViewInstance
	except Exception as err:
		write_log(f"[e2MDB][EVENTVIEW] ERROR patching Screens.EventView: {err}")
		return False
	# Several core screens import the EventView helpers directly at module load time.
	# Patch those module-level references too, otherwise they keep calling the original functions.
	for module_name in ("Screens.ChannelSelection", "Screens.EpgSelection", "Screens.InfoBarGenerics"):
		try:
			module = __import__(module_name, fromlist=["dummy"])
			if hasattr(module, "showEventViewCallback"):
				module.showEventViewCallback = _showEventViewCallback
			if hasattr(module, "getEventViewInstance"):
				module.getEventViewInstance = _getEventViewInstance
		except Exception as err:
			write_log(f"[e2MDB][EVENTVIEW] ERROR patching {module_name}: {err}")
	return True


# Persistent GUI bridge for backend web commands.
# This bridge runs from sessionstart, so web MediaBrowser Play/Stop also works
# when the e2MDB scanner screen is not open.
class E2MDBGuiCommandBridge:
	MODULE_NAME = "[E2MDBGuiCommandBridge]"

	def __init__(self, session):
		self.session = session
		self.last_command = ""
		self.previous_service = None
		self.timer = eTimer()
		try:
			self.timer.callback.append(self.poll)
		except Exception:
			self.timer_conn = self.timer.timeout.connect(self.poll)

	def start(self):
		try:
			self.timer.start(250, False)
			write_log(f"{self.MODULE_NAME} started")
		except Exception as err:
			write_log(f"{self.MODULE_NAME} start failed: {err}")

	def command_file(self):
		return join(RUNTIME_DIR, "gui_command.json")

	def _remove_command_file(self, path):
		try:
			if isfile(path):
				remove(path)
		except Exception as err:
			write_log(f"{self.MODULE_NAME} command cleanup failed: {err}")

	def poll(self):
		command_path = self.command_file()
		try:
			if not isfile(command_path):
				return
			with open(command_path, "r", encoding="utf-8") as handle:
				command = load(handle)
		except Exception as err:
			write_log(f"{self.MODULE_NAME} command read failed: {err}")
			self._remove_command_file(command_path)
			return

		command_id = str(command.get("id") or "")
		if command_id and command_id == self.last_command:
			self._remove_command_file(command_path)
			return
		self.last_command = command_id
		action = str(command.get("action") or "")
		try:
			if action == "play":
				path = str(command.get("file_path") or "")
				if not path or not isfile(path):
					write_log(f"{self.MODULE_NAME} play ignored, file missing: '{path}'")
					return
				try:
					current_ref = self.session.nav.getCurrentlyPlayingServiceReference()
				except Exception:
					current_ref = None
				if current_ref is not None:
					self.previous_service = current_ref
				ref = eServiceReference(4097, 0, path)
				try:
					ref.setName(str(command.get("title") or basename(path)))
				except Exception:
					pass
				self.session.nav.playService(ref)
				write_log(f"{self.MODULE_NAME} play path='{path}'")
			elif action == "stop":
				if self.previous_service is not None:
					self.session.nav.playService(self.previous_service)
					self.previous_service = None
					write_log(f"{self.MODULE_NAME} restored previous service")
				else:
					self.session.nav.stopService()
					write_log(f"{self.MODULE_NAME} stop without previous service")
			else:
				write_log(f"{self.MODULE_NAME} unknown command action='{action}'")
		except Exception as err:
			write_log(f"{self.MODULE_NAME} action failed: {err}")
		finally:
			self._remove_command_file(command_path)


def _get_e2mdb_web_port():
	try:
		port = int(config.plugins.e2mdb.webPort.value)
	except Exception:
		port = 6066
	return port if 1 <= port <= 65535 else 6066


e2mdb_gui_command_bridge = None
e2mdb_openwebif_link_registered = False


class E2MDBOpenWebifRedirectResource(object):
	# OpenWebif requires a real Twisted resource. Registering a tuple with
	# child=None makes OpenWebif fail while building its root tree.
	isLeaf = True

	def __new__(cls):
		from twisted.web.resource import Resource

		class RedirectResource(Resource):
			isLeaf = True

			def render_GET(self, request):
				return self._redirect(request)

			def render_POST(self, request):
				return self._redirect(request)

			def _redirect(self, request):
				from twisted.web.util import redirectTo
				host = request.getHeader("host") or "localhost"
				if host.startswith("[") and "]" in host:
					host_name = host.split("]", 1)[0] + "]"
				else:
					host_name = host.split(":", 1)[0]
				target = f"http://{host_name}:{_get_e2mdb_web_port()}/"
				return redirectTo(target.encode("utf-8"), request)

		return RedirectResource()


def setup_web():
	global e2mdb_openwebif_link_registered
	if e2mdb_openwebif_link_registered:
		return
	try:
		from Tools.Directories import resolveFilename, SCOPE_PLUGINS
		if exists(resolveFilename(SCOPE_PLUGINS, "Extensions/OpenWebif/pluginshook.src")):
			try:
				from Plugins.Extensions.WebInterface.WebChilds.Toplevel import addExternalChild
				addExternalChild(("e2mdb", E2MDBOpenWebifRedirectResource(), "e2MDB", __version__, True, ""))
				e2mdb_openwebif_link_registered = True
				write_log("[e2MDB] OpenWebif backend link registered successfully")
			except Exception as ex:
				write_log(f"[e2MDB] exception registering OpenWebif backend link: {ex}")
		else:
			write_log("[e2MDB] No known webinterface available")
	except Exception as e:
		write_log(f"[e2MDB] Error in setup_web: {e}")


def start_gui_command_bridge(session):
	global e2mdb_gui_command_bridge
	if session is None:
		return
	try:
		if e2mdb_gui_command_bridge is None:
			e2mdb_gui_command_bridge = E2MDBGuiCommandBridge(session)
			e2mdb_gui_command_bridge.start()
	except Exception as err:
		write_log(f"[E2MDBGuiCommandBridge] init failed: {err}")


def sessionstart(reason, **kwargs):
	global old_show_event_information
	if reason == 0 and 'session' in kwargs:
		from Screens.MovieSelection import MovieSelection
		old_show_event_information = MovieSelection.showEventInformation
		MovieSelection.showEventInformation = E2MDBshowEventInformation
		# ServiceEvent.refreshData = E2MDBserviceEventRefreshData # TODO Enable for background data refresh.
		try:
			init_backend_config(reason="sessionstart")
		except Exception as e:
			print(f"[e2MDB] ERROR initiating backend config: {e}")

		try:
			start_gui_command_bridge(kwargs.get('session'))
		except Exception as e:
			print(f"[e2MDB] ERROR starting GUI command bridge: {e}")

		try:
			setup_web()
		except Exception as e:
			print(f"[e2MDB] ERROR initiating WebComponent: {e}")

		component_meta_ready = install_component_meta_hooks()
		try:
			start_backend_notify_listener()
		except Exception as e:
			print(f"[e2MDB] ERROR starting backend notify listener: {e}")

		install_service_list_event_pixmap_provider()
		install_epg_selection_hooks()
		register_e2mdb_servicelist_infokey()
		# Service-list info-key integration is now controlled by config.usage.servicelist_infokey
		# through the generic ChannelSelection handler registry.
		install_channel_selection_hooks()
		if component_meta_ready:
			write_log("[e2MDB][INFOBAR]", "SKIP old hook reason=component-meta-active")
		else:
			install_infobar_hooks()
		start_cleanup_manager(kwargs.get('session'))

		registerInfoKeyScreenHandlers()
		installEventViewHooks()

	if reason == 0:
		addFunctionTimer(_("e2MDB Refresh"), _("Scan e2MDB media folders"), start_task, stop_task, True)
		addFunctionTimer(_("e2MDB Live/EPG Prefill"), _("Prefill selected/preferred Live/EPG metadata"), start_prefill_task, stop_prefill_task, True)
		addFunctionTimer(_("e2MDB Live/EPG Cleanup"), _("Remove expired Live/EPG metadata and queue entries"), start_cleanup_task, stop_cleanup_task, True)
		addFunctionTimer(_("e2MDB SQLite Maintenance"), _("Optimize e2MDB database"), start_sqlite_maintenance_task, stop_sqlite_maintenance_task, True)


def main(session, **kwargs):
	session.open(E2MDBMain)


def menu(menuid, **kwargs):
	if menuid == "mainmenu" and bool(config.plugins.e2mdb.showInMainMenu.value):
		return [(_("e2MDB"), main, "e2mdb", 1)]
	return []


def Plugins(**kwargs):
	return [
		PluginDescriptor(name=_("e2MDB"), description=_("e2MDB"), where=[PluginDescriptor.WHERE_PLUGINMENU], icon="plugin.png", fnc=main),
		PluginDescriptor(name=_("e2MDB"), description=_("e2MDB"), where=[PluginDescriptor.WHERE_MENU], icon="plugin.png", fnc=menu),
		PluginDescriptor(name=_("e2MDB"), where=PluginDescriptor.WHERE_SESSIONSTART, needsRestart=True, fnc=sessionstart),
	]
