########################################################################################################
# e2MDB backend cleanup task bridge                                                                    #
# ---------------------------------------------------------------------------------------------------- #
# Clean-start build: cleanup and SQLite maintenance run as backend daemon jobs.                         #
########################################################################################################

from . import write_log
from .E2MDBSchedulerTasks import (
	start_cleanup_task,
	stop_cleanup_task,
	start_sqlite_maintenance_task,
	stop_sqlite_maintenance_task,
)


def start_cleanup_manager(session=None):
	# Clean-start: no Enigma2 cleanup manager and no GUI-side cleanup timer.
	write_log("[e2MDB][CLEANUP]", "SKIP local manager reason=backend-only")
	return None
