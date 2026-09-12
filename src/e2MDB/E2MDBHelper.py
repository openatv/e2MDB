########################################################################################################
# E2MDBHelper by Mr.Servo @OpenATV (c) 2026                                                            #
# Special thanks to jbleyel @OpenATV for his valuable support in creating the code.                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from gc import collect
from hashlib import md5
from io import BytesIO
from json import load, dump
from os import makedirs
from os.path import isfile, isdir, dirname, join, normpath
from re import IGNORECASE, search
from PIL import Image
from requests import get, exceptions
from threading import BoundedSemaphore


# ENIGMA IMPORTS
from Components.config import config

# PLUGIN IMPORTS
from . import write_log, e2mdbglobals
from .E2MDBProviders import providers


class E2MDBHelper:
	MODULE_NAME = "[E2MDBHelper]"

	def get_cache_dir(self):
		cache_dir = config.plugins.e2mdb.cachePath.value or "/media/hdd/"
		cache_dir = cache_dir.rstrip("/")
		return "/e2MDB" if cache_dir == "" else f"{cache_dir}/e2MDB"  # e.g. '/media/hdd/e2MDB'

	def get_image_extension(self, url, fallback="jpg"):
		url = str(url or "")
		match = search(r"\.(jpe?g|png|gif|webp)(?=$|[/?#_;&=,])", url, IGNORECASE)
		if match:
			extension = match.group(1).lower()
			return "jpg" if extension == "webp" else extension
		return fallback

	def get_full_org_path(self, path):
		"""Resolve cache-relative e2MDB paths to the configured cache root."""
		path = str(path or "").strip()
		if not path:
			return ""
		if path.startswith(("cover/", "backdrop/", "titlelogo/", "image/", "data/", "series/", "seasons/", "index/")):
			return normpath(join(normpath(self.get_cache_dir()), path))
		return path

	def get_reduced_org_path(self, org_path):
		return str(org_path or "").replace("/media/hdd", "").replace("/media/autofs", "")

	def get_reduced_cache_path(self, cache_path):
		"""Store cache artifacts relative to the e2MDB cache root, e.g. image/a/file.jpg."""
		cache_path = normpath(str(cache_path or ""))
		if not cache_path:
			return ""
		cache_root = normpath(self.get_cache_dir())
		prefix = cache_root.rstrip("/") + "/"
		if cache_path.startswith(prefix):
			return cache_path[len(prefix):]
		if cache_path == cache_root:
			return ""
		return self.get_reduced_org_path(cache_path)

	def get_reduced_org_hash(self, org_path):
		return md5(self.get_reduced_org_path(org_path).encode()).hexdigest()

	def set_dict_key(self, dictionary, key, value):
		if value:
			dictionary[key] = value
		return dictionary

	def get_primary_datapath(self, org_path, data_type="data", url="", pic_type=""):  # for images and json files (primary data)
		# possible image types: e.g. 'cover', 'backdrop', 'titlelogo', 'image'
		data_path = ""
		org_hash = self.get_reduced_org_hash(org_path)  # for reduced org_path, e.g. '/movie/Wir waren wie Brüder_Kreuzungen.mp4'
		sub_hash = f"{org_hash[0]}/{org_hash}"  # e.g. '/5/59bda60229dff93d3263c78ad9ffb71b'
		if pic_type:  # means image
			if url:
				extension = self.get_image_extension(url)
				data_path = f"{self.get_cache_dir()}/{pic_type}/{sub_hash}.{extension}"  # e.g. '/cover/5/59bda60229dff93d3263c78ad9ffb71b.jpg'
			return data_path
		else:  # means data
			data_path = f"{self.get_cache_dir()}/{data_type}/{sub_hash}.json"
		return data_path

	def get_secondary_datapath(self, pvr_name, pvr_id, category, season_no="", url="", pic_type=""):  # for images and json files (secondary data)
		# possible categories: 'series', 'seasons' and 'index'.
		data_path = ""
		if category == "seasons":
			season_part = f"S{int(season_no):02d}" if str(season_no).isdigit() else ""
			sub_path = f"{category}/{pvr_name}/{pvr_id}/{season_part}" if season_part else f"{category}/{pvr_name}/{pvr_id}"
		else:  # means series or index
			sub_path = f"{category}/{pvr_name}/{pvr_id}"
		if pic_type:  # means image
			if url:
				extension = self.get_image_extension(url)
				data_path = f"{self.get_cache_dir()}/{sub_path}/{pic_type}.{extension}"
		else:  # means data
			data_path = f"{self.get_cache_dir()}/{sub_path}/data.json"
		return data_path

	def get_artwork_cache_category(self, final_dict, pic_type):
		series_id = str(final_dict.get("series_id") or "")
		if not series_id:
			return "primary"
		pic_src = str(final_dict.get(f"{pic_type}_src") or "").strip().lower()
		if pic_src in ("series", "season", "seasons", "episode"):
			return "seasons" if pic_src == "season" else pic_src
		if pic_type == "image":
			return "episode"
		return "series"

	def get_artwork_cache_path(self, org_path, final_dict, pic_type, url=""):
		category = self.get_artwork_cache_category(final_dict, pic_type)
		if category in ("series", "seasons"):
			provider_ids = final_dict.get("provider_ids") or {}
			if not isinstance(provider_ids, dict):
				provider_ids = {}
			pic_src = str(final_dict.get(f"{pic_type}_src") or "").strip().lower()
			provider_name = (
				str(final_dict.get(f"{pic_type}_provider") or "").strip().lower()
				or str(final_dict.get("artwork_provider") or "").strip().lower()
				or (pic_src if pic_src not in ("series", "season", "seasons", "episode") else "")
				or str(final_dict.get("provider") or "").strip().lower()
			)
			provider_id = ""
			for key in (provider_name, "tvdb", "tmdb", "imdb", "omdb"):
				if key and provider_ids.get(key):
					provider_id = str(provider_ids.get(key) or "")
					if not provider_name:
						provider_name = key
					break
			provider_id = provider_id or str(final_dict.get("series_id") or "")
			if provider_name and provider_id:
				return self.get_secondary_datapath(provider_name, provider_id, category, season_no=final_dict.get("season_no", ""), url=url, pic_type=pic_type)
		return self.get_primary_datapath(org_path, url=url, pic_type=pic_type)

	def trim_text(self, text):
		return text.replace("_", "").replace("/", "").replace("|", "").strip()

	def get_se_ep(self, ep_details):
		se_ep = ""
		if ep_details and ep_details.success:
			season_number = ep_details.season_number
			episode_number = ep_details.episode_number
			if season_number and episode_number:
				se_ep = f"S{season_number:02d}E{episode_number:02d}"
# elif season_number:
# se_ep = f"S{season_number:02d}"
# elif episode_number:
# se_ep = f"E{episode_number:02d}"
		return se_ep

	def read_json_file(self, curr_file):
		err_msg, curr_data = "", {}
		try:
			if isfile(curr_file):
				with open(curr_file) as file:
					curr_data = load(file)
			else:
				err_msg = f"ERROR in module 'read_json_file': File not found: '{curr_file}'"
		except Exception as err_msg:
			return err_msg, curr_data
		return err_msg, curr_data

	def write_json_file(self, json_dict, json_path):
		json_dir = dirname(json_path)
		if not isdir(json_dir):
			makedirs(json_dir)
		try:
			with open(json_path, "w") as file:
				dump(json_dict, file)
		except OSError as osError:
			write_log(f"{self.MODULE_NAME} ERROR in module 'write_json_file': JsonFile could not be saved: {osError}")

	def image_download(self, image_url, image_path, callback=None, fail=None):
		def getDesiredPixmapSize(path_name):
			for img_category in e2mdbglobals.IMAGE_RESOLUTIONS:
				if img_category in path_name:
					return e2mdbglobals.IMAGE_RESOLUTIONS.get(img_category, (0, 0))
			return ()

		def is_supported_pixmap_ext(path_name):
			for extension in e2mdbglobals.IMAGE_EXTS:
				if extension in path_name:
					return extension.replace(".", "")
			return ""

		def prepare_image_for_save(img, save_format):
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

		if image_url:
			response, img, buffer_io = None, None, None
			if not hasattr(self, "image_download_semaphore"):
				self.image_download_semaphore = BoundedSemaphore(2)
			with self.image_download_semaphore:
				try:
					headers = {"User-Agent": e2mdbglobals.USERAGENT}
					response = get(image_url, headers=headers, timeout=(3.05, 6), stream=True)
					response.raise_for_status()
					if not image_path:
						return
					desired_size = getDesiredPixmapSize(image_path)
					pic_ext = is_supported_pixmap_ext(image_path)
					img_dir = dirname(image_path)
					if not isdir(img_dir):
						makedirs(img_dir)
					if pic_ext:  # supported pixmap type?
						buffer_io = BytesIO(response.content)
						img = Image.open(buffer_io)
						img.load()
						if desired_size:
							scale_factor = 1.5 if e2mdbglobals.RESOLUTION == "FHD" else 1.0
							img.thumbnail((int(desired_size[0] * scale_factor), int(desired_size[1] * scale_factor)), Image.LANCZOS)
						save_format = pic_ext.replace("jpg", "jpeg") or "jpeg"
						img_to_save = prepare_image_for_save(img, save_format)
						img_to_save.save(image_path, format=save_format, quality=50, optimize=True)
						if img_to_save is not img:
							img_to_save.close()
					else:  # all other image types (e.g. '.svg')
						with open(image_path, "wb") as file:
							for chunk in response.iter_content(chunk_size=65536):
								if chunk:
									file.write(chunk)
				except exceptions.RequestException as err_msg:
					write_log(f"{self.MODULE_NAME} IMAGE_MISS in module 'image_download': {image_path or image_url} - picture could not be saved: {err_msg}", level="warning")
					if fail:
						fail(err_msg)
				except OSError as err_msg:
					write_log(f"{self.MODULE_NAME} ERROR in module 'image_download': {image_path or image_url} - picture could not be saved: {err_msg}", level="error")
					if fail:
						fail(err_msg)
				finally:
					if img is not None:
						img.close()
					if buffer_io is not None:
						buffer_io.close()
					if response is not None:
						response.close()
					collect()
					if callback:
						callback(image_path)
		else:
			write_log(f"{self.MODULE_NAME} IMAGE_MISS in module 'image_download': image_url is empty", level="warning")

	def create_final_dict(self, results_dict, org_title, org_path, ext_desc):  # TODO: org_path might be required elsewhere?
		def tagArtworkSource(meta_dict, source):
			if not isinstance(meta_dict, dict) or not source:
				return meta_dict
			for pic_type in ("cover", "backdrop", "titlelogo", "image"):
				if meta_dict.get(f"{pic_type}_url") and not meta_dict.get(f"{pic_type}_src"):
					meta_dict[f"{pic_type}_src"] = source
			return meta_dict

		def fillupData(main_dict, fill_dict, source=""):
			for key in fill_dict.keys():
				if key in ["seasons", "episodes"]:  # ignore lists of seasons or episodes
					continue
				fill_value = fill_dict.get(key)
				if fill_value:
					if not main_dict.get(key):
						main_dict[key] = fill_value  # set if key not present
						if key.endswith("_url"):
							pic_type = key[:-4]
							src_key = f"{pic_type}_src"
							if not main_dict.get(src_key):
								main_dict[src_key] = fill_dict.get(src_key) or source
						continue
					if key in ["cast", "crew"]:  # expand list
						main_dict[key] += fill_value
			return main_dict

		def addSearchContext(final_dict):
			if not isinstance(final_dict, dict):
				return final_dict
			context_values = {
				"search_title": best_hit_dict.get("_search_title") or search_title,
				"search_year": best_hit_dict.get("_search_year") or search_data.get("year", ""),
				"expected_media_type": best_hit_dict.get("_expected_media_type") or search_data.get("estimated_type", ""),
				"strict_media_type": best_hit_dict.get("_strict_media_type") or strict_media_type,
				"provider_priority": best_hit_dict.get("_provider_priority", ""),
				"match_reason": match_reason,
			}
			for key, value in context_values.items():
				self.set_dict_key(final_dict, key, value)
			# Drop provider-search helper keys before metadata is written to JSON/DB.
			for key in list(final_dict.keys()):
				if str(key).startswith("_"):
					final_dict.pop(key, None)
			return final_dict

		def same_provider_identity(main_dict, alt_dict):
			main_ids = main_dict.get("provider_ids", {}) or {}
			alt_ids = alt_dict.get("provider_ids", {}) or {}
			for key in ("tvdb", "tmdb", "imdb", "tvmaze", "anime", "anilist", "kitsu"):
				if main_ids.get(key) and main_ids.get(key) == alt_ids.get(key):
					return True
			main_title = self.getCleanTitle(main_dict.get("title", "") or main_dict.get("series_title", "")).lower()
			alt_title = self.getCleanTitle(alt_dict.get("title", "") or alt_dict.get("series_title", "")).lower()
			if main_title and alt_title:
				return self.similar(main_title, alt_title) >= 0.88
			return False

		def apply_fanart_artwork(final_dict):
			if not final_dict:
				return final_dict
			try:
				mode = config.plugins.e2mdb.fanartmode.value
			except Exception:
				mode = "missing"
			err_msg, fanart_dict = providers.get_fanart_artwork(final_dict)
			if not fanart_dict:
				return final_dict
			prefer = mode == "prefer"
			changed = []
			for pic_type in ("cover", "backdrop", "titlelogo"):
				url_key = f"{pic_type}_url"
				src_key = f"{pic_type}_src"
				path_key = f"{pic_type}_path"
				new_url = fanart_dict.get(url_key, "")
				if new_url and (prefer or not final_dict.get(url_key)):
					final_dict[url_key] = new_url
					final_dict[f"{pic_type}_provider"] = fanart_dict.get(src_key, "fanart")
					final_dict[src_key] = "fanart"
					final_dict.pop(path_key, None)
					changed.append(pic_type)
					if pic_type == "cover" and final_dict.get("media_type") == "series" and (prefer or not final_dict.get("series_cover_url")):
						final_dict["series_cover_url"] = new_url
						final_dict["series_poster_url"] = new_url
					elif pic_type == "backdrop" and final_dict.get("media_type") == "series" and (prefer or not final_dict.get("series_backdrop_url")):
						final_dict["series_backdrop_url"] = new_url
					elif pic_type == "titlelogo" and final_dict.get("media_type") == "series" and (prefer or not final_dict.get("series_titlelogo_url")):
						final_dict["series_titlelogo_url"] = new_url
			if changed:
				write_log(f"{self.MODULE_NAME} FanArt artwork fill-up ({mode}) for '{org_title}': {', '.join(changed)}")
			return final_dict

		def get_alt_provider_artwork_fill(best_dict, existing_final):
			if not best_dict or not existing_final:
				return {}
			if existing_final.get("backdrop_url") and existing_final.get("cover_url") and existing_final.get("titlelogo_url"):
				return {}
			priority = ("tmdb", "tvmaze", "tvdb", "anime", "kitsu", "imdb")
			for alt_name in priority:
				if alt_name == pvr_name:
					continue
				for alt_result in results_dict.get("results", []):
					if alt_result.get("provider", "") != alt_name or alt_result.get("media_type", "") != "series":
						continue
					if not same_provider_identity(best_dict, alt_result):
						continue
					alt_id = alt_result.get("provider_ids", {}).get(alt_name, "")
					if not alt_id:
						continue
					try:
						alt_series, alt_season, alt_episode = self.get_secondary_dicts(alt_name, alt_id, org_title, match_reason, short_desc, desc)
					except Exception as err_msg:
						write_log(f"{self.MODULE_NAME} ERROR in module 'get_alt_provider_artwork_fill': {alt_name}: {err_msg}")
						continue
					alt_final = {}
					if alt_series:
						alt_final = fillupData(alt_final.copy(), tagArtworkSource(alt_series, alt_name), alt_name)
					if alt_season:
						alt_final = fillupData(alt_final.copy(), tagArtworkSource(alt_season, alt_name), alt_name)
					if not alt_final:
						continue
					fill = {}
					for key in ("cover_url", "poster_url", "backdrop_url", "fanart_url", "titlelogo_url", "logo_url", "clearlogo_url"):
						if alt_final.get(key) and not existing_final.get(key):
							fill[key] = alt_final.get(key)
					if fill:
						for key in list(fill.keys()):
							if key.endswith("_url"):
								fill[key.replace("_url", "_src")] = alt_name
						write_log(f"{self.MODULE_NAME} Artwork fill-up from alternate provider '{alt_name}' for '{org_title}'")
						return fill
			return {}

		def get_alt_provider_episode_fill(best_dict, existing_final):
			# Episode stills are provider-specific. TVDB often has the right metadata but no episode artwork;
			# TVmaze/TMDb may still provide an image for the same series episode. Use them only as fill-up.
			if existing_final.get("image_url"):
				return {}
			priority = ("tvmaze", "tmdb", "tvdb", "anime", "kitsu", "imdb")
			for alt_name in priority:
				if alt_name == pvr_name:
					continue
				for alt_result in results_dict.get("results", []):
					if alt_result.get("provider", "") != alt_name or alt_result.get("media_type", "") != "series":
						continue
					if not same_provider_identity(best_dict, alt_result):
						continue
					alt_id = alt_result.get("provider_ids", {}).get(alt_name, "")
					if not alt_id:
						continue
					try:
						alt_series, alt_season, alt_episode = self.get_secondary_dicts(alt_name, alt_id, org_title, match_reason, short_desc, desc)
					except Exception as err_msg:
						write_log(f"{self.MODULE_NAME} ERROR in module 'get_alt_provider_episode_fill': {alt_name}: {err_msg}")
						continue
					alt_final = tagArtworkSource(alt_episode or {}, "episode")
					if alt_season:
						alt_final = fillupData(alt_final.copy(), tagArtworkSource(alt_season, "season"), "season")
					if alt_series:
						alt_final = fillupData(alt_final.copy(), tagArtworkSource(alt_series, "series"), "series")
					if alt_final.get("image_url") or alt_final.get("cover_url") or alt_final.get("backdrop_url") or alt_final.get("titlelogo_url"):
						write_log(f"{self.MODULE_NAME} Episode artwork/metadata fill-up from '{alt_name}' for '{org_title}'")
						return alt_final
			return {}

		# INFO: As a rule of thumb, a ratio() value over 0.6 means the sequences are close matches
		TITLE_QUALIFY = 0.20  # minimum to qualify title
		DESC_QUALIFY = 0.20  # minimum to qualify description
		TITLE_LIMIT = 0.60  # threshold for title search
		DESC_LIMIT = 0.60  # threshold for desc search
		final_dict, search_marker, best_hit_dict = {}, {}, {}
		if len(results_dict) > 1:
			best_title_ratio, best_desc_ratio, curr_is_best = 0.0, 0.0, False
		else:  # bypass selection process if there is only one search result
			best_title_ratio, best_desc_ratio, curr_is_best = 100.0, 100.0, True
		search_data = results_dict.get("search_data", {})
		search_title = search_data.get("search_title", "")
		short_desc = search_data.get("short_desc", "")
		desc = search_data.get("desc", "")  # 'year' is not used here
		match_reason = search_data.get("match_reason", "")
		strict_media_type = search_data.get("strict_media_type", "")
		if search_title:
			for result_dict in results_dict.get("results", []):  # try to qualify all results of all providers
				pvr_name = result_dict.get("provider", "")
				result_media_type = result_dict.get("media_type", "")
				if strict_media_type and result_media_type != strict_media_type:
					write_log(f"[E2MDBHelper] '{pvr_name}' skipped result '{result_dict.get('title', '')}' because media_type '{result_media_type}' is not '{strict_media_type}'")
					continue
				result_search_title = result_dict.get("_search_title", "") or search_title
				title_ratio, desc_ratio = self.get_match_ratio(result_dict, result_search_title, desc=desc, short_desc=short_desc, ext_desc=ext_desc)
				write_log(f"[E2MDBHelper] '{pvr_name}' Matching results for title '{result_search_title}' - title_ratio: {round(title_ratio * 100)}%, descriptionRatio: {round(desc_ratio * 100)}%")
				if title_ratio > TITLE_QUALIFY and title_ratio > best_title_ratio:
					best_title_ratio, curr_is_best = title_ratio, True
				if desc_ratio > DESC_QUALIFY and desc_ratio > best_desc_ratio:
					best_desc_ratio, curr_is_best = desc_ratio, True
				if curr_is_best:
					curr_is_best = False
					self.set_dict_key(best_hit_dict, "title", result_dict.get("title", ""))
					# check all descriptions
					pvr_desc = result_dict.get("overview", "")
					if len(pvr_desc) > 49:  # ignore short descriptions e.g. 'deutscher Spielfilm'
						desc_dict = best_hit_dict.get("overview", "")
						if desc_dict and pvr_desc and len(pvr_desc) > len(desc_dict):
							self.set_dict_key(best_hit_dict, "overview", pvr_desc)
					best_hit_dict = result_dict
					self.set_dict_key(best_hit_dict, "provider", pvr_name)
				if best_title_ratio == 1.0 or best_desc_ratio == 1.0:  # was the maximum possible already achieved?
					break
		if best_title_ratio >= TITLE_LIMIT or best_desc_ratio >= DESC_LIMIT:
			media_type = best_hit_dict.get("media_type")
			pvr_name = best_hit_dict.get("provider", "")
			asset_id = best_hit_dict.get("provider_ids", {}).get(pvr_name)
			if media_type == "series":  # special treatment for series: find and write episode details
				series_dict, season_dict, episode_dict = self.get_secondary_dicts(pvr_name, asset_id, org_title, match_reason, short_desc, desc)  # get and write series & season details + write season_episodes index
				final_dict = tagArtworkSource(episode_dict or {}, "episode")  # begin with episode details
				if season_dict:  # continue with season details
					final_dict = fillupData(final_dict.copy(), tagArtworkSource(season_dict, "season"), "season")
				if series_dict:  # finish with series details
					final_dict = fillupData(final_dict.copy(), tagArtworkSource(series_dict, "series"), "series")
				# If the winning provider lacks series artwork, try active alternate providers first.
				alt_artwork = get_alt_provider_artwork_fill(best_hit_dict, final_dict)
				if alt_artwork:
					final_dict = fillupData(final_dict.copy(), alt_artwork)
				# If the winning provider has no episode still, try an alternate provider for the same series.
				# This keeps the selected provider/metadata but fills missing image fields.
				alt_final = get_alt_provider_episode_fill(best_hit_dict, final_dict)
				if alt_final:
					final_dict = fillupData(final_dict.copy(), alt_final)
			elif media_type == "manga":
				try:
					err_msg, final_dict = providers.get_asset_details(pvr_name, asset_id, "manga")
				except Exception as e:
					err_msg, final_dict = f"{self.MODULE_NAME} ERROR in 'get_manga_details': {e}", {}
				if err_msg:
					write_log(f"{self.MODULE_NAME} ERROR in module 'create_final_dict': {err_msg}")
			else:  # movie
				try:
					err_msg, final_dict = providers.get_movie_details(pvr_name, asset_id)
				except Exception as e:
					err_msg, final_dict = f"{self.MODULE_NAME} ERROR in 'get_movie_details': {e}", {}
				if err_msg:
					write_log(f"{self.MODULE_NAME} ERROR in module 'create_final_dict': {err_msg}")
				if not final_dict and best_hit_dict:
					# Do not drop a valid search hit only because a provider rejects the
					# follow-up details request. This is especially important for IMDb's
					# anonymous GraphQL endpoint, which can return HTTP 400 for optional
					# detail fields while the search result already contains title, plot
					# and poster metadata.
					final_dict = best_hit_dict.copy()
					if asset_id:
						provider_ids = final_dict.get("provider_ids", {}) or {}
						if isinstance(provider_ids, dict):
							provider_ids[pvr_name] = asset_id
							final_dict["provider_ids"] = provider_ids
					write_log(f"{self.MODULE_NAME} Detail fallback: using '{pvr_name}' search result for '{org_title}' after details download failed.")
			if final_dict:
				final_dict = apply_fanart_artwork(final_dict)
			if final_dict:  # add some evaluation results
				final_dict = addSearchContext(final_dict)
				final_dict = self.set_dict_key(final_dict, "title_ratio", str(best_title_ratio))
				final_dict = self.set_dict_key(final_dict, "desc_ratio", str(best_desc_ratio))
		return final_dict, search_marker  # best hit found: 'movie' or fillup sequence 'episode->season->series'

	def cleanup_cache(self):
		pass  # TODO: muss ich noch machen.
		#  IDEE: Alle vorhandenen .ts-Dateien scannen, dann alle zugehörigen Dateien sammeln und was nicht dazu gehört flight in die Tonne
