import gettext

from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS

__version__ = "1.0"

PluginLanguageDomain = "e2MDB"
PluginLanguagePath = "Extensions/e2MDB/locale"


def localeInit():
	gettext.bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


def _(txt):
	if gettext.dgettext(PluginLanguageDomain, txt):
		return gettext.dgettext(PluginLanguageDomain, txt)
	else:
		print(f"[{PluginLanguageDomain}] fallback to default translation for {txt}")
		return gettext.gettext(txt)


language.addCallback(localeInit)
