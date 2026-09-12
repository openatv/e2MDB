########################################################################################################
# E2MDBImageDownloader by jbleyel @OpenATV (c) 2026                                                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################
#
# connectTimeout only bounds the TCP connect phase, not the whole request/response.

# PYTHON IMPORTS
from gc import collect
from io import BytesIO
from os import makedirs
from os.path import dirname, isdir
from PIL import Image
from twisted.internet import reactor
from twisted.internet.defer import DeferredSemaphore
from twisted.python.failure import Failure
from twisted.web.client import Agent, RedirectAgent, readBody
from twisted.web.http_headers import Headers

# PLUGIN IMPORTS
from . import write_log, e2mdbglobals


class E2MDBImageDownloader:
	MODULE_NAME = "[E2MDBImageDownloader]"

	def __init__(self):
		self.semaphore = DeferredSemaphore(2)
		# requests follows redirects by default; plain Agent does not, and some
		# provider/CDN image URLs do redirect.
		self.agent = RedirectAgent(Agent(reactor, connectTimeout=6))

	def _desired_pixmap_size(self, path_name):
		for img_category in e2mdbglobals.IMAGE_RESOLUTIONS:
			if img_category in path_name:
				return e2mdbglobals.IMAGE_RESOLUTIONS.get(img_category, (0, 0))
		return ()

	def _supported_pixmap_ext(self, path_name):
		for extension in e2mdbglobals.IMAGE_EXTS:
			if extension in path_name:
				return extension.replace(".", "")
		return ""

	def _prepare_image_for_save(self, img, save_format, image_path):
		# JPEG cannot store alpha/transparency. Some providers return PNG/WebP artwork
		# with an alpha channel even when e2MDB stores it as cover.jpg. Convert safely.
		if (save_format or "").lower() not in ("jpg", "jpeg"):
			return img
		try:
			if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
				rgba = img.convert("RGBA")
				background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
				background.alpha_composite(rgba)
				return background.convert("RGB")
			if img.mode not in ("RGB", "L", "CMYK"):
				return img.convert("RGB")
		except Exception as err_msg:
			write_log(f"{self.MODULE_NAME} WARNING in module 'image_download': JPEG mode conversion failed for '{image_path}': {err_msg}", level="warning")
			try:
				return img.convert("RGB")
			except Exception:
				return img
		return img

	def image_download(self, image_url, image_path, callback=None, fail=None):
		if not image_url:
			write_log(f"{self.MODULE_NAME} IMAGE_MISS in module 'image_download': image_url is empty", level="warning")
			return None
		return self.semaphore.run(self._fetch, image_url, image_path, callback, fail)

	def _fetch(self, image_url, image_path, callback, fail):
		url = image_url.encode("utf-8") if isinstance(image_url, str) else image_url
		headers = Headers({b"User-Agent": [e2mdbglobals.USERAGENT.encode("utf-8")]})
		deferred = self.agent.request(b"GET", url, headers, None)
		deferred.addCallback(self._on_response, image_url, image_path)
		deferred.addErrback(self._on_error, image_url, image_path, fail)
		if callback:
			deferred.addCallback(lambda _result: callback(image_path))
		return deferred

	def _on_response(self, response, image_url, image_path):
		if response.code >= 400:
			raise ConnectionError(f"HTTP {response.code}")
		deferred = readBody(response)
		deferred.addCallback(self._save_image, image_url, image_path)
		return deferred

	def _save_image(self, body, image_url, image_path):
		buffer_io, img, img_to_save = None, None, None
		try:
			if not image_path:
				return
			desired_size = self._desired_pixmap_size(image_path)
			pic_ext = self._supported_pixmap_ext(image_path)
			img_dir = dirname(image_path)
			if not isdir(img_dir):
				makedirs(img_dir)
			if pic_ext:  # supported pixmap type?
				buffer_io = BytesIO(body)
				img = Image.open(buffer_io)
				img.load()
				if desired_size:
					scale_factor = 1.5 if e2mdbglobals.RESOLUTION == "FHD" else 1.0
					img.thumbnail((int(desired_size[0] * scale_factor), int(desired_size[1] * scale_factor)), Image.LANCZOS)
				save_format = pic_ext.replace("jpg", "jpeg") or "jpeg"
				img_to_save = self._prepare_image_for_save(img, save_format, image_path)
				img_to_save.save(image_path, format=save_format, quality=50, optimize=True)
			else:  # all other image types (e.g. '.svg')
				with open(image_path, "wb") as file:
					file.write(body)
		except OSError as err_msg:
			write_log(f"{self.MODULE_NAME} ERROR in module 'image_download': {image_path or image_url} - picture could not be saved: {err_msg}", level="error")
			raise
		finally:
			if img_to_save is not None and img_to_save is not img:
				img_to_save.close()
			if img is not None:
				img.close()
			if buffer_io is not None:
				buffer_io.close()
			collect()

	def _on_error(self, failure: Failure, image_url, image_path, fail):
		write_log(f"{self.MODULE_NAME} IMAGE_MISS in module 'image_download': {image_path or image_url} - picture could not be saved: {failure.getErrorMessage()}", level="warning")
		if fail:
			fail(failure.value)
		return None  # swallow the error, matching the old callInThread variant which never propagated exceptions

