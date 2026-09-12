
from Components.Element import cached, ElementError
from Components.Converter.Converter import Converter
from Tools.LoadPixmap import LoadPixmap
from Plugins.Extensions.e2MDB import _


class E2MDBEventInfo(Converter):
	COVER = 0
	BACKDROP = 1
	TITLELOGO = 2
	IMAGE = 3
	PREVIEW = 4
	IMAGE_OR_PICON = 5
	TITLE = 20
	SUBTITLE = 21
	OVERVIEW = 22
	DESCRIPTION = 23
	INFOLINE = 24
	STATUS = 25
	PROVIDER = 26
	MEDIA_TYPE = 27
	GENRES = 28
	RUNTIME = 29
	RATING = 30
	YEAR = 31
	CAST = 32
	CREW = 33
	ADV_DESCRIPTION = 34
	HAS_METADATA = 50
	HAS_COVER = 51
	HAS_BACKDROP = 52
	HAS_IMAGE = 53

	def __init__(self, tokens):
		type_map = {
			"Cover": self.COVER,
			"Backdrop": self.BACKDROP,
			"TitleLogo": self.TITLELOGO,
			"Image": self.IMAGE,
			"Preview": self.PREVIEW,
			"ImageOrPicon": self.IMAGE_OR_PICON,
			"Title": self.TITLE,
			"Subtitle": self.SUBTITLE,
			"Overview": self.OVERVIEW,
			"Description": self.DESCRIPTION,
			"InfoLine": self.INFOLINE,
			"Status": self.STATUS,
			"Provider": self.PROVIDER,
			"MediaType": self.MEDIA_TYPE,
			"Genres": self.GENRES,
			"Runtime": self.RUNTIME,
			"Rating": self.RATING,
			"Year": self.YEAR,
			"Cast": self.CAST,
			"Crew": self.CREW,
			"AdvDescription": self.ADV_DESCRIPTION,
			"AdvancedDescription": self.ADV_DESCRIPTION,
			"ADV_DESCRIPTION": self.ADV_DESCRIPTION,
			"HasMetadata": self.HAS_METADATA,
			"HasCover": self.HAS_COVER,
			"HasBackdrop": self.HAS_BACKDROP,
			"HasImage": self.HAS_IMAGE,
		}
		self.token_text = tokens
		if tokens in type_map:
			self.type = type_map[tokens]
		else:
			raise ElementError(f"'{tokens}' is not valid for E2MDBEventInfo converter")
		Converter.__init__(self, tokens)

	def _get_meta(self, key, default=""):
		try:
			value = self.source.getMeta(key)
		except Exception:
			value = default
		return default if value is None else value

	def _first_existing_meta_path(self, keys):
		# Do not call os.path.exists() from the Enigma2 main thread here.
		# e2MDB metadata paths are produced by the backend/cache layer; probing them
		# synchronously can spin up disks or block on slow mounts while renderers run.
		for key in keys:
			path = str(self._get_meta(key, "") or "").strip()
			if path:
				return path
		return None


	def _is_portrait_artwork_path(self, path):
		try:
			text = str(path or "").lower()
		except Exception:
			return False
		if not text:
			return False
		try:
			from os.path import basename
			name = basename(text.split("?", 1)[0])
		except Exception:
			name = text
		portrait_markers = (
			"/poster", "poster.", "poster_", "_poster", "series_poster",
			"/cover", "cover.", "cover_", "_cover", "/covers/",
			"/artwork/poster", "/artwork/cover",
		)
		return any(marker in text for marker in portrait_markers) or name in ("poster.jpg", "poster.png", "poster.webp", "cover.jpg", "cover.png", "cover.webp", "series_poster.jpg", "series_poster.png", "series_poster.webp")

	def _is_landscape_artwork_path(self, path):
		try:
			text = str(path or "").lower()
		except Exception:
			return False
		if not text or self._is_portrait_artwork_path(text):
			return False
		landscape_markers = (
			"/backdrop", "backdrop.", "backdrop_", "_backdrop",
			"/fanart", "fanart.", "fanart_", "_fanart",
			"/image", "image.", "image_", "_image",
			"/preview", "preview.", "preview_", "_preview",
			"/still", "still.", "still_", "_still",
			"/episode", "episode.", "episode_", "_episode",
			"series_backdrop", "background", "landscape",
		)
		return any(marker in text for marker in landscape_markers)

	def _first_landscape_meta_path(self, keys):
		for key in keys:
			path = str(self._get_meta(key, "") or "").strip()
			if path and self._is_landscape_artwork_path(path):
				return path
		return None

	def _get_path_from_meta(self):
		try:
			if self.type == self.COVER:
				return self._first_existing_meta_path(("cover_path",))
			elif self.type == self.BACKDROP:
				# Backdrop must stay a real backdrop/fanart/series background.
				# Episode stills/previews in image_path are handled by Image/Preview only.
				return self._first_landscape_meta_path(("backdrop_path",))
			elif self.type == self.TITLELOGO:
				return self._first_existing_meta_path(("titlelogo_path",))
			elif self.type == self.IMAGE:
				return self._first_landscape_meta_path(("image_path",))
			elif self.type == self.PREVIEW:
				return self._first_landscape_meta_path(("image_path", "backdrop_path"))
			elif self.type == self.IMAGE_OR_PICON:
				landscape = self._first_landscape_meta_path(("image_path", "backdrop_path", "image_or_picon_path"))
				if landscape:
					return landscape
				# image_or_picon_path deliberately contains a service picon when no
				# landscape metadata exists. Picons must not be rejected by the
				# artwork-shape filter.
				return self._first_existing_meta_path(("image_or_picon_path",))
		except Exception:
			pass
		return None


	def _clean_text(self, value):
		try:
			text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
		except Exception:
			return ""
		while "\n\n\n" in text:
			text = text.replace("\n\n\n", "\n\n")
		return text

	def _advanced_description(self):
		sections = []
		for title, key in ((_("Description"), "description"), (_("Cast"), "cast_short"), (_("Crew"), "crew_short")):
			text = self._clean_text(self._get_meta(key, ""))
			if text:
				sections.append(f"{title}\n{text}")
		return "\n\n".join(sections)

	def _is_clear_meta(self):
		try:
			return bool(self.source.getMeta("e2mdb_empty") or self.source.getMeta("e2mdb_clear_reason"))
		except Exception:
			return False

	@cached
	def getText(self):
		if self._is_clear_meta():
			return ""
		if self.type == self.ADV_DESCRIPTION:
			return self._advanced_description()
		key_map = {
			self.TITLE: "title",
			self.SUBTITLE: "subtitle",
			self.OVERVIEW: "overview",
			self.DESCRIPTION: "description",
			self.INFOLINE: "infoline",
			self.STATUS: "status_text",
			self.PROVIDER: "provider",
			self.MEDIA_TYPE: "media_type",
			self.GENRES: "genres",
			self.RUNTIME: "runtime",
			self.RATING: "rating",
			self.YEAR: "year",
			self.CAST: "cast_short",
			self.CREW: "crew_short",
		}
		key = key_map.get(self.type)
		if key:
			return str(self._get_meta(key, "") or "")
		if self.type in (self.HAS_METADATA, self.HAS_COVER, self.HAS_BACKDROP, self.HAS_IMAGE):
			return "1" if self.boolean else ""
		return ""

	text = property(getText)

	@cached
	def getBoolean(self):
		if self._is_clear_meta():
			return False
		try:
			if self.type == self.HAS_METADATA:
				return bool(self._get_meta("source_key", ""))
			if self.type == self.HAS_COVER:
				return bool(self._first_existing_meta_path(("cover_path",)))
			if self.type == self.HAS_BACKDROP:
				return bool(self._first_landscape_meta_path(("backdrop_path",)))
			if self.type == self.HAS_IMAGE:
				return bool(self._first_landscape_meta_path(("image_path",)))
		except Exception:
			pass
		return False

	boolean = property(getBoolean)

	@cached
	def getPixmap(self):
		try:
			if self._is_clear_meta():
				return None
			path = self._get_path_from_meta()
			if path:
				return LoadPixmap(path=path, cached=False, autoDetect=True)
		except Exception:
			pass
		return None

	pixmap = property(getPixmap)
