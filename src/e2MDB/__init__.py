from os.path import dirname, join
from sys import modules
from gettext import bindtextdomain, dgettext, gettext
from Components.config import ConfigSubsection, config, ConfigText, ConfigYesNo
from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS

__version__ = "1.0"

PluginLanguageDomain = "e2MDB"
PluginLanguagePath = "Extensions/e2MDB/locale"


def localeInit():
	bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	if translated := dgettext(PluginLanguageDomain, txt):
		return translated
	else:
		# print(f"[{PluginLanguageDomain}] fallback to default translation for {txt}")
		return gettext(txt)


PLUGINDIR = dirname(modules[__name__].__file__)


language.addCallback(localeInit)

config.plugins.e2mdb = ConfigSubsection()
config.plugins.e2mdb.tmdbapikey = ConfigText()
config.plugins.e2mdb.omdbapikey = ConfigText()
config.plugins.e2mdb.tvdbapikey = ConfigText()
config.plugins.e2mdb.cachePath = ConfigText(default=join("/media/hdd/"))
config.plugins.e2mdb.databasePath = ConfigText(default=join("/media/hdd/"))
config.plugins.e2mdb.enableDatabase = ConfigYesNo(default=False)


def getApiKey(provider=None):
	providerDict = {
					"tmdb": config.plugins.e2mdb.tmdbapikey.value,
					"omdb": config.plugins.e2mdb.omdbapikey.value,
					"tvdb": config.plugins.e2mdb.tvdbapikey.value
					}
	return providerDict.get(provider) if provider else None
