

from enigma import eDVBDB, eEPGCache, ePicLoad, eServiceCenter, eServiceReference, eTimer, getDesktop, iPlayableService

from Components.ActionMap import HelpableActionMap
from Components.config import ConfigDirectory, ConfigSelection, ConfigSubDict, ConfigSubsection, ConfigYesNo, config, getConfigListEntry
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.Setup import Setup

from . import _

MODULE_NAME = __name__.split(".")[-1]

config.plugins.e2MDB = ConfigSubsection()


class e2MDBSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="e2MDB", plugin="Extensions/e2MDB")


def setup(session, **kwargs):
	session.open(e2MDBSetup)


def autostart(reason, session):
	pass


def Plugins(**kwargs):
	return [
		PluginDescriptor(name=_("e2MDB"), description=_("e2MDB Settings"), where=[PluginDescriptor.WHERE_PLUGINMENU], icon="plugin.png", fnc=setup),
		PluginDescriptor(name=_("e2MDB"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
	]
