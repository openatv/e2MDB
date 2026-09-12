########################################################################################################
# e2MDB Live/EPG queue priority tiers                                                                  #
# -----------------------------------------------------------------------------------------------------#
# Keep the active user-visible lookups below 100 so future urgent/internal jobs still have headroom.    #
########################################################################################################

PRIORITY_EVENTVIEW = 94
PRIORITY_EPG_OPEN = 92
PRIORITY_ADHOC_NOW = 90
PRIORITY_SERVICELIST_NOW = 86
PRIORITY_EPG_SELECTION = 82
PRIORITY_INFOBAR_NOW = 80
PRIORITY_CHANNEL_SELECTION = 72
PRIORITY_SERVICELIST_NEXT = 62
PRIORITY_PREFILL_STANDBY = 58
PRIORITY_PREFILL_IDLE = 56
PRIORITY_PREFILL = 50
PRIORITY_MIN = 0
PRIORITY_MAX = 99


def clamp_priority(value, default=PRIORITY_PREFILL, minimum=PRIORITY_MIN, maximum=PRIORITY_MAX):
	try:
		priority = int(value)
	except Exception:
		priority = int(default)
	try:
		minimum = int(minimum)
	except Exception:
		minimum = PRIORITY_MIN
	try:
		maximum = int(maximum)
	except Exception:
		maximum = PRIORITY_MAX
	if priority < minimum:
		return minimum
	if priority > maximum:
		return maximum
	return priority
