from os.path import dirname
from sys import modules
from gettext import bindtextdomain, dgettext, gettext
from Components.config import ConfigSubsection, config, ConfigText
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

config.plugins.e2MDB = ConfigSubsection()
config.plugins.e2MDB.tmdbapikey = ConfigText()
config.plugins.e2MDB.omdbapikey = ConfigText()
config.plugins.e2MDB.tvdbapikey = ConfigText()


def getApiKey(provider=None):
	providerDict = {
					"tmdb": config.plugins.e2MDB.tmdbapikey.value,
					"omdb": config.plugins.e2MDB.omdbapikey.value,
					"tvdb": config.plugins.e2MDB.tvdbapikey.value
					}
	return providerDict.get(provider) if provider else None
