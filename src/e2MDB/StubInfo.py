########################################################################################################
# e2MDB by jbleyel @OpenATV (c) 2026                                                                   #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from os import stat
from os.path import split

# ENIGMA IMPORTS
from enigma import iServiceInformation


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
			path = serviceref.getPath()
			if w == iServiceInformation.sTimeCreate:
				return stat(path).st_birthtime
			if w == iServiceInformation.sFileSize:
				return stat(path).st_size
			if w == iServiceInformation.sDescription:
				return path
		except Exception:  # nosec # noqa: E722
			pass
		return 0

	def getInfoString(self, serviceref, w):
		return ""


justStubInfo = StubInfo()
