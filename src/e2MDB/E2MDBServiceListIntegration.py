########################################################################################################
# e2MDB optional ServiceList event pixmap provider                                                       #
# ---------------------------------------------------------------------------------------------------- #
# This module uses the neutral OpenATV ServiceList extension point.  It does not monkey patch the core   #
# ServiceList.  If the core placeholder is not available, the plugin simply keeps running without native #
# ServiceList preview pixmaps.                                                                         #
########################################################################################################

# PLUGIN IMPORTS
from . import write_log

_service_list_provider_installed = False
_service_list_provider = None


def _log(message, force=False):
	try:
		write_log("[e2MDB][SERVICELIST]", message)
	except Exception:
		pass


def _service_to_string(service):
	try:
		if isinstance(service, str):
			return service
		return service and service.toString() or ""
	except Exception:
		try:
			return str(service or "")
		except Exception:
			return ""


class E2MDBServiceListEventPixmapProvider:
	def buildServiceListEventPixmap(self, service, begin_time=0, duration=0, title="", short_description="", extended_description="", size=None, next_event=False, fallback_to_picon=False):
		service_ref = _service_to_string(service)
		pixmap = None
		try:
			from .E2MDBServiceListPreview import buildE2MDBServiceListPixmapFromValues
			# 0 means now, 1 means next.
			event_number = 1 if next_event else 0
			pixmap = buildE2MDBServiceListPixmapFromValues(service_ref, begin_time=begin_time, duration=duration, title=title, short_desc=short_description, extended_desc=extended_description, size=size, event_number=event_number)
		except Exception as err:
			_log(f"PROVIDER_ERROR service='{service_ref}' begin={begin_time} duration={duration} title='{title}' next={next_event} error={err}", force=True)
			pixmap = None
		return pixmap


def install_service_list_event_pixmap_provider():
	"""Register the e2MDB ServiceList event pixmap provider with OpenATV."""
	global _service_list_provider_installed, _service_list_provider
	if _service_list_provider_installed:
		return True
	try:
		import Components.ServiceList as ServiceListModule
		register = getattr(ServiceListModule, "registerServiceListEventPixmapProvider", None)
		if register is None:
			_log("PROVIDER_SKIP reason=core-extension-point-missing", force=True)
			return False
		_service_list_provider = E2MDBServiceListEventPixmapProvider()
		register(_service_list_provider)
		_service_list_provider_installed = True
		_log("PROVIDER_INSTALLED mode=core-extension-point", force=True)
		return True
	except Exception as err:
		_log(f"PROVIDER_INSTALL_ERROR error={err}", force=True)
		return False


def uninstall_service_list_event_pixmap_provider():
	"""Unregister the e2MDB ServiceList event pixmap provider if possible."""
	global _service_list_provider_installed, _service_list_provider
	try:
		import Components.ServiceList as ServiceListModule
		unregister = getattr(ServiceListModule, "unregisterServiceListEventPixmapProvider", None)
		if unregister is not None:
			unregister(_service_list_provider)
	except Exception:
		pass
	_service_list_provider_installed = False
	_service_list_provider = None
	return True
