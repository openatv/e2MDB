########################################################################################################
# e2MDB backend cleanup task bridge                                                                    #
# ---------------------------------------------------------------------------------------------------- #
# Clean-start build: cleanup and SQLite maintenance run as backend daemon jobs.                         #
########################################################################################################

from . import write_log


def start_cleanup_manager(session=None):
	# Clean-start: no Enigma2 cleanup manager and no GUI-side cleanup timer.
	write_log("[e2MDB][CLEANUP]", "SKIP local manager reason=backend-only")
	return None
