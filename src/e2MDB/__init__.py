from datetime import datetime
from os import listdir, makedirs, remove
from zipfile import ZIP_DEFLATED, ZipFile
from gettext import bindtextdomain, dgettext, gettext
from os.path import dirname, join, isfile, getsize, basename
from secrets import choice
from sys import modules
from enigma import getDesktop
from Components.config import config, ConfigInteger, ConfigSelection, ConfigSubsection, ConfigText, ConfigYesNo, NoSave
from Components.Language import language
from Components.International import international
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from .E2MDBPriority import PRIORITY_CHANNEL_SELECTION, PRIORITY_INFOBAR_NOW, PRIORITY_PREFILL, PRIORITY_PREFILL_IDLE, PRIORITY_PREFILL_STANDBY

__version__ = "1.0"
PluginLanguageDomain = "e2MDB"
PluginLanguageDir = "Extensions/e2MDB/locale"


class E2MDBGlobals:
	RELEASE = f"v{__version__}"
	MODULE_NAME = f"[{__name__.split(".")[-1]}]"
	MOVIE_LIST_SREF_ROOT = "2:0:1:0:0:0:0:0:0:0:"
	RESOLUTION = "FHD" if getDesktop(0).size().width() > 1300 else "HD"
	PLUGINDIR = dirname(modules[__name__].__file__)  # e.g. /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/
	ICONDIR = join(PLUGINDIR, f"pics/{RESOLUTION}/icons/")
	CACHEDIRS = ["data", "index", "series", "seasons", "backdrop", "cover", "titlelogo", "image", "preview", "fanart", "fernsehserien", "wikimedia", "wikipedia", "results"]
	TEMPDIR = "/var/run/e2mdb"
	REPORTDIR = "/home/root/logs/"
	# possible separators 'title|episodename' of foreign recordings (e.g. '.mp4'), the order is essential!
	FOREIGN_SEPAS = (("_", ""), (": ", ": "), (" – ", ""), (" - ", ""), ("! ", "! "))  # (separator, replacement)
	# possible separators 'title|episodename' of foreign recordings (e.g. '.mp4'), the order is essential!
	EPGTYPE_SEPAS = (("_", ""), (": ", ": "), (" – ", ""), (" - ", ""), ("! ", "! "), ("|", "|"))  # (separator, replacement)
	EXCLUDED_DIRS = {"trash", ".trash", "scan", ".scan", "trashcan", ".trashcan"}
	VIDEO_EXTS = (".ts", ".mkv", ".avi", ".mp4", ".m4v", ".mpg", ".mpeg", ".mov", ".wmv", ".flv", ".stream", ".iso")
	IMAGE_EXTS = ("jpg", "jpeg", "png", "gif")
	IMAGE_RESOLUTIONS = {"backdrop": (1280, 720), "cover": (350, 525), "titlelogo": (200, 50)}  # values valid for HD
	USERAGENT = choice([
			"Mozilla/5.0 (Linux; Android 14; SM-A536B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.231 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14; SM-S918W Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.119 Mobile Safari/537.36/122.0.6261.119",
			"Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/127.0.6533.103 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile DuckDuckGo/5 Safari/537.36",
			"Mozilla/5.0 (Linux; Android 14; G9FPL) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.48 Mobile Safari/537.36",
			"Mozilla/5.0 (Linux; arm_64; Android 14; Pixel Fold) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.232 YaBrowser/23.11.0.232.00 SA/3 Mobile Safari/537.36"
			"Mozilla/5.0 (Linux; Android 14; SM-F731N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.119 Mobile Safari/537.36 OPR/81.1.4292.78446"
			])
	DEFAULT_RECORDING_PATH = "/media/hdd/movie"


e2mdbglobals = E2MDBGlobals


def locale_init():
	bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguageDir))


def _(txt):
	if translated := dgettext(PluginLanguageDomain, txt):
		return translated
	else:
		# print(f"[{PluginLanguageDomain}] fallback to default translation for {txt}")
		return gettext(txt)


locale_init()
language.addCallback(locale_init)

config.plugins.e2mdb = ConfigSubsection()

langs = [
	"af", "sq", "am", "ar", "hy", "az", "eu", "be", "bn", "bs", "bg", "ca", "zh", "co", "hr", "cs", "da",
	"nl", "en", "eo", "fr", "fi", "fy", "gl", "ka", "de", "el", "ht", "ha", "hu", "is", "ig", "ga", "it",
	"ja", "jv", "kn", "kk", "km", "rw", "ko", "ku", "ky", "lo", "la", "lv", "lt", "lb", "mk", "mg", "ms",
	"mt", "mi", "mr", "mn", "no", "ny", "or", "ps", "fa", "pl", "pt", "ro", "ru", "sm", "gd", "sr", "st",
	"sn", "sk", "sl", "so", "es", "su", "sw", "sv", "tl", "tg", "te", "th", "tr", "tk", "uk", "ur", "ug",
	"uz", "cy", "xh", "yi", "yo", "zu", "et"
	]
langs = [(x, international.LANGUAGE_DATA[x][1]) for x in langs]
langs.sort(key=lambda x: x[1])

default = config.misc.locale.value.split("_")[0]

if default not in [x[0] for x in langs]:
	default = "en"

config.plugins.e2mdb.lang = ConfigSelection(default=default, choices=langs)

E2MDB_SERVICE_LIST_EVENTVIEW_KEY = "e2mdb"
E2MDB_SERVICE_LIST_EVENTVIEW_LABEL = _("e2MDB EventView")
E2MDB_SERVICE_LIST_EPG_KEY = "e2mdb_epg"
E2MDB_SERVICE_LIST_EPG_LABEL = _("e2MDB Single EPG")


def _e2mdb_get_config_choices(config_selection):
	choices = getattr(config_selection, "choices", [])
	try:
		return list(choices)
	except Exception:
		return []


def _e2mdb_choice_key(choice):
	if isinstance(choice, (list, tuple)) and choice:
		return choice[0]
	return choice


def register_e2mdb_servicelist_infokey():
	try:
		usage_config = getattr(config, "usage", None)
		info_key_config = getattr(usage_config, "servicelist_infokey", None)
		if info_key_config is None:
			return False

		# config.usage.servicelist_infokey is loaded before optional plugin
		# choices are registered. If the saved value is "e2mdb" or
		# "e2mdb_epg", ConfigSelection falls back during load because the value
		# is not in the initial core choice list yet. Preserve the raw saved
		# value here and restore it after extending the choices.
		saved_value = getattr(info_key_config, "saved_value", None)
		current_value = getattr(info_key_config, "value", None)
		default_value = getattr(info_key_config, "default", "event")

		choices = _e2mdb_get_config_choices(info_key_config)
		keys = [_e2mdb_choice_key(choice) for choice in choices]
		changed = False
		for choice_key, choice_label in ((E2MDB_SERVICE_LIST_EVENTVIEW_KEY, E2MDB_SERVICE_LIST_EVENTVIEW_LABEL), (E2MDB_SERVICE_LIST_EPG_KEY, E2MDB_SERVICE_LIST_EPG_LABEL)):
			if choice_key not in keys:
				choices.append((choice_key, choice_label))
				keys.append(choice_key)
				changed = True
		if changed:
			try:
				info_key_config.setChoices(choices, default=default_value)
			except Exception:
				info_key_config.choices = choices

		if saved_value in (E2MDB_SERVICE_LIST_EVENTVIEW_KEY, E2MDB_SERVICE_LIST_EPG_KEY):
			try:
				info_key_config.value = saved_value
			except Exception:
				pass
		elif current_value in (E2MDB_SERVICE_LIST_EVENTVIEW_KEY, E2MDB_SERVICE_LIST_EPG_KEY):
			try:
				info_key_config.value = current_value
			except Exception:
				pass
		return True
	except Exception:
		return False


register_e2mdb_servicelist_infokey()
config.plugins.e2mdb.tmdbactive = ConfigYesNo(default=True)
config.plugins.e2mdb.tmdbapikey = ConfigText()
config.plugins.e2mdb.tvdbactive = ConfigYesNo(default=True)
config.plugins.e2mdb.tvdbapikey = ConfigText()
config.plugins.e2mdb.omdbactive = ConfigYesNo(default=False)
config.plugins.e2mdb.omdbapikey = ConfigText()
config.plugins.e2mdb.imdbactive = ConfigYesNo(default=False)
config.plugins.e2mdb.tvmazeactive = ConfigYesNo(default=False)
config.plugins.e2mdb.tvspielfilmactive = ConfigYesNo(default=True)
config.plugins.e2mdb.fernsehserienactive = ConfigYesNo(default=True)
config.plugins.e2mdb.wikimediaactive = ConfigYesNo(default=False)
config.plugins.e2mdb.animeactive = ConfigYesNo(default=False)
config.plugins.e2mdb.kitsuactive = ConfigYesNo(default=False)
config.plugins.e2mdb.fanartactive = ConfigYesNo(default=False)
config.plugins.e2mdb.fanartapikey = ConfigText()
config.plugins.e2mdb.fanartmode = ConfigSelection(default="missing", choices=[("missing", _("Fill missing artwork only")), ("prefer", _("Prefer FanArt artwork"))])
config.plugins.e2mdb.cachePath = ConfigText(default=join("/media/hdd/"))
config.plugins.e2mdb.webPort = ConfigInteger(default=6066, limits=(1, 65535))
config.plugins.e2mdb.enableDatabase = ConfigYesNo(default=True)
config.plugins.e2mdb.showInMainMenu = ConfigYesNo(default=False)
config.plugins.e2mdb.scannerRescanExisting = ConfigYesNo(default=False)
config.plugins.e2mdb.epgMetaEnabled = ConfigYesNo(default=True)
config.plugins.e2mdb.epgEventViewUseE2MDB = ConfigYesNo(default=True)
config.plugins.e2mdb.mediaEventViewUseE2MDB = ConfigYesNo(default=True)
config.plugins.e2mdb.epgChannelSelectionEnabled = ConfigYesNo(default=True)
config.plugins.e2mdb.epgInfoBarEnabled = ConfigYesNo(default=True)
config.plugins.e2mdb.epgServiceListPreviewMode = ConfigSelection(default="backdrop_preview", choices=[("backdrop_preview", _("Backdrop, fallback preview/still")), ("preview", _("Preview/still, fallback backdrop")), ("backdrop", _("Backdrop only"))])
config.plugins.e2mdb.epgRetentionDays = ConfigInteger(default=3, limits=(1, 30))
config.plugins.e2mdb.epgNoMatchRetentionHours = ConfigInteger(default=1, limits=(1, 72))
config.plugins.e2mdb.epgCleanupSqliteVacuum = ConfigYesNo(default=True)
config.plugins.e2mdb.epgCleanupSqliteReindex = ConfigYesNo(default=False)
config.plugins.e2mdb.epgPrefillEnabled = ConfigYesNo(default=True)
config.plugins.e2mdb.epgPrefillMode = ConfigSelection(default="night", choices=[("off", _("Off")), ("standby", _("Standby only")), ("night", _("Night window")), ("idle", _("Idle time"))])
config.plugins.e2mdb.epgPrefillStartHour = ConfigInteger(default=4, limits=(0, 23))
config.plugins.e2mdb.epgPrefillHorizonDays = ConfigInteger(default=2, limits=(1, 7))
config.plugins.e2mdb.epgPrefillMaxEvents = ConfigInteger(default=1500, limits=(10, 5000))
config.plugins.e2mdb.epgPrefillMaxEventsPerService = ConfigInteger(default=120, limits=(1, 500))
config.plugins.e2mdb.epgUseZapHistory = ConfigYesNo(default=True)
config.plugins.e2mdb.epgZapHistoryTopN = ConfigInteger(default=25, limits=(1, 50))
config.plugins.e2mdb.translateTitleSearch = ConfigYesNo(default=False)
config.plugins.e2mdb.translateTitleSearchLanguage = ConfigSelection(default=default, choices=langs)
config.plugins.e2mdb.providerEnglishTextFallback = ConfigYesNo(default=True)
config.plugins.e2mdb.translateMetadataFallback = ConfigYesNo(default=False)
config.plugins.e2mdb.debugLog = ConfigSelection(default=1, choices=[(0, _("Off")), (1, _("On")), (2, _("Verbose"))])
config.plugins.e2mdb.logTarget = ConfigSelection(default="file", choices=[("file", _("e2MDB.log")), ("debuglog", _("Enigma2 debug log")), ("both", _("Both"))])
config.plugins.e2mdb.logRotateSizeMb = ConfigInteger(default=5, limits=(1, 100))


def get_api_key(provider=None):
	provider_dict = {
					"tmdb": config.plugins.e2mdb.tmdbapikey.value,
					"tvdb": config.plugins.e2mdb.tvdbapikey.value,
					"omdb": config.plugins.e2mdb.omdbapikey.value,
					"imdb": "",
					"fanart": config.plugins.e2mdb.fanartapikey.value
					}
	return provider_dict.get(provider) if provider else None


def _get_e2mdb_log_path():
	return join(e2mdbglobals.REPORTDIR, "e2MDB.log")


def rotate_e2mdb_log(force=False):
	"""Rotate e2MDB.log into a compressed archive and keep the newest five archives."""
	log_path = _get_e2mdb_log_path()
	try:
		if not isfile(log_path):
			return False
		size_config = getattr(config.plugins.e2mdb, "logRotateSizeMb", None)
		max_size_mb = int(getattr(size_config, "value", 5) or 5)
		max_size = max(1, max_size_mb) * 1024 * 1024
		if not force and getsize(log_path) < max_size:
			return False
		makedirs(e2mdbglobals.REPORTDIR, exist_ok=True)
		timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
		zip_path = join(e2mdbglobals.REPORTDIR, f"e2MDB-{timestamp}.log.zip")
		with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
			archive.write(log_path, basename(log_path))
		remove(log_path)
		archives = []
		for name in listdir(e2mdbglobals.REPORTDIR):
			if name.startswith("e2MDB-") and name.endswith(".log.zip"):
				archives.append(join(e2mdbglobals.REPORTDIR, name))
		archives.sort(reverse=True)
		for old_path in archives[5:]:
			try:
				remove(old_path)
			except OSError:
				pass
		return True
	except Exception:
		return False


def _normalized_log_mode(value=None):
	"""Return the effective e2MDB log mode: off, on or verbose."""
	try:
		if value is None:
			value = config.plugins.e2mdb.debugLog.value
	except Exception:
		value = 1
	text = str(value).strip().lower()
	if text in ("0", "off", "aus", "false", "no", "none"):
		return "off"
	if text in ("2", "verbose", "debug", "all", "e2mdb.log"):
		return "verbose"
	return "on"


def e2mdb_log_is_verbose():
	"""Return True when full diagnostic logging is enabled."""
	return _normalized_log_mode() == "verbose"


def _normalized_log_target(value=None):
	"""Return the configured e2MDB log target: file, debuglog or both."""
	try:
		if value is None:
			value = config.plugins.e2mdb.logTarget.value
	except Exception:
		value = "file"
	text = str(value).strip().lower()
	if text in ("debug", "debuglog", "e2", "enigma2", "print", "stdout"):
		return "debuglog"
	if text in ("both", "all", "file+debuglog", "debuglog+file"):
		return "both"
	return "file"


def _has_meaningful_assignment(text, key):
	try:
		needle = f"{key}="
		start = text.find(needle)
		if start < 0:
			return False
		value = text[start + len(needle):].strip()
		if not value:
			return False
		if value[0] in ("'", '\"'):
			quote = value[0]
			end = value.find(quote, 1)
			value = value[1:end if end >= 0 else len(value)]
		else:
			value = value.split()[0]
		value = value.strip().strip(",;")
		if "=" in value and not value.startswith(("http://", "https://")):
			return False
		return bool(value and value.lower() not in ("none", "null", "false", "0", "ok", "matched", "done"))
	except Exception:
		return False


def _is_expected_non_error_log_message(text):
	"""Return True for expected misses/status messages which are verbose-only."""
	if not text:
		return False
	if "adhoc finish" in text:
		return not _has_meaningful_assignment(text, "error") and " failed" not in text and "refresh failed" not in text
	verbose_only_markers = (
		"url_miss",
		"detail failed",
		"get_html",
		"image_miss",
		"tvspielfilm miss",
		"fernsehserien miss",
		"wikimedia miss",
		"picture could not be saved: 404",
		"picture could not be saved: 410",
		"client error: not found",
		"client error: gone",
		"connecttimeout",
		"readtimeout",
		"max retries exceeded",
	)
	return any(marker in text for marker in verbose_only_markers)


def _is_error_log_message(log_text1, log_text2=""):
	"""Best-effort classification for the normal log mode."""
	text = f"{log_text1} {log_text2}".lower()
	if _is_expected_non_error_log_message(text):
		return False
	error_markers = (
		" error", "error ", "error:", "error'", 'error"',
		" failed", "failed ", "failed:", "failed=", "failure",
		" exception", "exception ", "exception:", "traceback", "stacktrace",
		" fatal", "fatal ", "critical", "crash", "crashed"
	)
	if "error=" in text and _has_meaningful_assignment(text, "error"):
		return True
	return any(marker in text for marker in error_markers) or text.startswith(("error", "failed", "exception", "traceback", "stacktrace", "fatal", "critical"))


def _write_e2mdb_log_file(line):
	try:
		makedirs(e2mdbglobals.REPORTDIR, exist_ok=True)
		rotate_e2mdb_log(force=False)
		with open(_get_e2mdb_log_path(), "a") as file:
			file.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:13]} {line}\n")
	except Exception:
		pass


def write_log(log_text1, log_text2="", level=None):
	mode = _normalized_log_mode()
	if mode == "off":
		return
	if mode != "verbose":
		level_text = str(level or "").strip().lower()
		if level_text:
			if level_text not in ("error", "exception", "critical", "fatal"):
				return
		elif not _is_error_log_message(log_text1, log_text2):
			return
	line = f"{log_text1} {log_text2}".rstrip()
	target = _normalized_log_target()
	if target in ("debuglog", "both"):
		try:
			print(line)
		except Exception:
			pass
	if target in ("file", "both"):
		_write_e2mdb_log_file(line)
