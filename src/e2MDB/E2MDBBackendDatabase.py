########################################################################################################
# e2MDB backend SQLite layer                                                                           #
# -----------------------------------------------------------------------------------------------------#
# Standalone daemon database helper. It must not import Enigma2 modules.                                #
########################################################################################################

from glob import glob
from hashlib import md5
from json import dump, dumps, load, loads
from os import cpu_count, listdir, makedirs, remove, rename, stat, walk
from os.path import basename, dirname, exists, getsize, isdir, isfile, join, normpath, splitext
from shutil import rmtree
from urllib.parse import quote, unquote
from re import search, sub
from sqlite3 import Row, connect
from threading import RLock
from time import time


DEFAULT_DATABASE_ROOT = "/media/hdd/e2MDB"
DEFAULT_DATABASE_NAME = "results.db"
CACHE_DIRS = ("data", "index", "series", "seasons", "backdrop", "cover", "titlelogo", "image", "preview", "fanart", "fernsehserien", "wikimedia", "wikipedia", "results")
ARTWORK_CACHE_DIRS = ("cover", "backdrop", "titlelogo", "image", "preview", "fanart", "fernsehserien", "wikimedia", "wikipedia")
PRIMARY_HASH_CACHE_DIRS = ("data", "results", "cover", "backdrop", "titlelogo", "image")


def safe_int(value, default=0):
	try:
		return int(value)
	except Exception:
		return default


def truthy(value):
	return str(value or "").strip().lower() in ("1", "true", "yes", "on", "all", "pending")


def normalize_search_text(value):
	value = str(value or "").strip().lower()
	value = sub(r"[._\-]+", " ", value)
	value = sub(r"[^a-z0-9äöüß ]+", " ", value)
	return sub(r"\s+", " ", value).strip()


def resolve_database_path(settings):
	settings = settings if isinstance(settings, dict) else {}
	database = settings.get("database", {}) if isinstance(settings.get("database", {}), dict) else {}
	path = str(database.get("path") or "").strip()
	if path:
		return path
	root = str(database.get("root") or settings.get("cache", {}).get("root") or DEFAULT_DATABASE_ROOT).strip().rstrip("/")
	if not root:
		root = DEFAULT_DATABASE_ROOT
	return join(root, DEFAULT_DATABASE_NAME)


class BackendDatabase:
	def __init__(self, settings=None):
		self.settings = settings if isinstance(settings, dict) else {}
		self.db_path = resolve_database_path(self.settings)
		self.lock = RLock()
		self.busy_timeout_ms = safe_int(self.settings.get("database", {}).get("busy_timeout_ms"), 5000)
		self.journal_mode = str(self.settings.get("database", {}).get("journal_mode") or "wal").lower()
		self._schema_ready = False
		self._journal_mode_ready = False
		self._last_cpu_sample = self._read_cpu_times()
		self._ensure_parent()
		self.create_schema()

	def _ensure_parent(self):
		folder = dirname(self.db_path)
		if folder and not exists(folder):
			makedirs(folder)

	def _connect(self):
		conn = connect(self.db_path, timeout=max(1.0, float(self.busy_timeout_ms) / 1000.0))
		conn.row_factory = Row
		conn.execute("PRAGMA foreign_keys=ON")
		conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
		if self.journal_mode == "wal" and not self._journal_mode_ready:
			try:
				mode_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
				self._journal_mode_ready = bool(mode_row and str(mode_row[0] or "").lower() == "wal")
			except Exception:
				pass
		try:
			conn.execute("PRAGMA synchronous=NORMAL")
		except Exception:
			pass
		return conn

	def create_schema(self):
		with self.lock:
			self._schema_ready = False
			self._journal_mode_ready = False
			with self._connect() as conn:
				self._create_media_schema(conn)
				self._create_recording_schema(conn)
				self._create_provider_schema(conn)
				self._create_live_epg_display_schema(conn)
				self._create_live_epg_queue_schema(conn)
				self._create_state_schema(conn)
				conn.commit()
			self._schema_ready = True

	def ensure_schema(self):
		"""Ensure the clean-start backend schema exists."""
		if self._schema_ready:
			return
		with self.lock:
			if not self._schema_ready:
				self.create_schema()

	def _create_media_schema(self, conn):
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_media (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				hash TEXT UNIQUE NOT NULL,
				file_path TEXT NOT NULL,
				file_name TEXT NOT NULL,
				search_string TEXT NOT NULL,
				search_string_norm TEXT DEFAULT '',
				metadata_title TEXT DEFAULT '',
				metadata_subtitle TEXT DEFAULT '',
				metadata_overview TEXT DEFAULT '',
				metadata_genres TEXT DEFAULT '',
				metadata_provider TEXT DEFAULT '',
				metadata_provider_ids TEXT DEFAULT '',
				metadata_media_type TEXT DEFAULT '',
				metadata_year TEXT DEFAULT '',
				metadata_runtime TEXT DEFAULT '',
				metadata_rating TEXT DEFAULT '',
				metadata_vote_count TEXT DEFAULT '',
				metadata_cover_path TEXT DEFAULT '',
				metadata_backdrop_path TEXT DEFAULT '',
				metadata_logo_path TEXT DEFAULT '',
				metadata_image_path TEXT DEFAULT '',
				metadata_released TEXT DEFAULT '',
				metadata_countries TEXT DEFAULT '',
				metadata_age_rating TEXT DEFAULT '',
				metadata_cast TEXT DEFAULT '',
				metadata_crew TEXT DEFAULT '',
				metadata_season_no TEXT DEFAULT '',
				metadata_episode_no TEXT DEFAULT '',
				metadata_series_cover_path TEXT DEFAULT '',
				metadata_episode_image_path TEXT DEFAULT '',
				provider_lookup_status TEXT DEFAULT '',
				provider_lookup_error TEXT DEFAULT '',
				provider_lookup_updated TEXT DEFAULT '',
				provider_best_json TEXT DEFAULT '',
				browser_ready TEXT DEFAULT '',
				artwork_poster_path TEXT DEFAULT '',
				artwork_backdrop_path TEXT DEFAULT '',
				artwork_logo_path TEXT DEFAULT '',
				artwork_series_poster_path TEXT DEFAULT '',
				artwork_series_backdrop_path TEXT DEFAULT '',
				artwork_episode_path TEXT DEFAULT '',
				source_type TEXT DEFAULT '',
				path_mode TEXT DEFAULT '',
				path_mode_label TEXT DEFAULT '',
				media_family TEXT DEFAULT '',
				estimated_media_type TEXT DEFAULT '',
				provider_media_type TEXT DEFAULT '',
				provider_title TEXT DEFAULT '',
				series_title TEXT DEFAULT '',
				movie_title TEXT DEFAULT '',
				scan_season_no TEXT DEFAULT '',
				scan_episode_no TEXT DEFAULT '',
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			)
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_hash ON e2mdb_media(hash)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_file_path ON e2mdb_media(file_path)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_search_norm ON e2mdb_media(search_string_norm)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_updated_at ON e2mdb_media(updated_at DESC)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_browser_ready ON e2mdb_media(browser_ready)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_ready_type ON e2mdb_media(browser_ready, metadata_media_type, provider_media_type)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_title ON e2mdb_media(metadata_title COLLATE NOCASE)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_series_title ON e2mdb_media(series_title COLLATE NOCASE)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_provider_status ON e2mdb_media(provider_lookup_status)")

	def _create_recording_schema(self, conn):
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_recordings (
				recording_id TEXT PRIMARY KEY,
				media_hash TEXT NOT NULL,
				path TEXT UNIQUE NOT NULL,
				folder TEXT DEFAULT '',
				name TEXT DEFAULT '',
				extension TEXT DEFAULT '',
				title TEXT DEFAULT '',
				description TEXT DEFAULT '',
				extended_description TEXT DEFAULT '',
				service_ref TEXT DEFAULT '',
				recorded_at INTEGER DEFAULT 0,
				duration_seconds INTEGER DEFAULT 0,
				size_bytes INTEGER DEFAULT 0,
				mtime INTEGER DEFAULT 0,
				search_text TEXT DEFAULT '',
				search_text_norm TEXT DEFAULT '',
				scan_status TEXT DEFAULT '',
				parse_error TEXT DEFAULT '',
				payload_json TEXT DEFAULT '{}',
				source_type TEXT DEFAULT '',
				path_mode TEXT DEFAULT '',
				path_mode_label TEXT DEFAULT '',
				media_family TEXT DEFAULT '',
				estimated_media_type TEXT DEFAULT '',
				provider_media_type TEXT DEFAULT '',
				provider_title TEXT DEFAULT '',
				series_title TEXT DEFAULT '',
				movie_title TEXT DEFAULT '',
				season_no TEXT DEFAULT '',
				episode_no TEXT DEFAULT '',
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_media_hash ON e2mdb_recordings(media_hash)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_path ON e2mdb_recordings(path)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_title ON e2mdb_recordings(title)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_path_mode ON e2mdb_recordings(path_mode)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_provider_media_type ON e2mdb_recordings(provider_media_type)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_search_norm ON e2mdb_recordings(search_text_norm)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_mtime ON e2mdb_recordings(mtime DESC)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_recordings_recorded_at ON e2mdb_recordings(recorded_at DESC)")

	def _create_provider_schema(self, conn):
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_provider_matches (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				media_hash TEXT NOT NULL,
				recording_id TEXT DEFAULT '',
				provider TEXT DEFAULT '',
				media_type TEXT DEFAULT '',
				title TEXT DEFAULT '',
				year TEXT DEFAULT '',
				match_score REAL DEFAULT 0,
				is_best INTEGER DEFAULT 0,
				payload_json TEXT DEFAULT '{}',
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_matches_hash ON e2mdb_provider_matches(media_hash)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_matches_best ON e2mdb_provider_matches(media_hash, is_best)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_matches_provider ON e2mdb_provider_matches(provider)")

	def _create_live_epg_display_schema(self, conn):
		"""Create the clean-start Live/EPG display tables used by the Enigma2 GUI."""
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_provider_assets (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				asset_key TEXT UNIQUE NOT NULL,
				provider TEXT NOT NULL,
				provider_id TEXT NOT NULL,
				media_type TEXT DEFAULT '',
				title TEXT DEFAULT '',
				original_title TEXT DEFAULT '',
				episode_name TEXT DEFAULT '',
				tagline TEXT DEFAULT '',
				genres TEXT DEFAULT '',
				overview TEXT DEFAULT '',
				year INTEGER DEFAULT 0,
				json_path TEXT DEFAULT '',
				cover_path TEXT DEFAULT '',
				backdrop_path TEXT DEFAULT '',
				logo_path TEXT DEFAULT '',
				image_path TEXT DEFAULT '',
				last_seen INTEGER DEFAULT 0,
				expires_at INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_epg_events (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				source_key TEXT UNIQUE NOT NULL,
				source_type TEXT DEFAULT 'epg',
				service_ref TEXT NOT NULL,
				service_name TEXT DEFAULT '',
				event_id INTEGER DEFAULT 0,
				title TEXT DEFAULT '',
				title_norm TEXT DEFAULT '',
				search_title TEXT DEFAULT '',
				short_desc TEXT DEFAULT '',
				extended_desc TEXT DEFAULT '',
				begin_time INTEGER DEFAULT 0,
				duration INTEGER DEFAULT 0,
				event_end INTEGER DEFAULT 0,
				virtual_path TEXT DEFAULT '',
				json_path TEXT DEFAULT '',
				status TEXT DEFAULT 'unknown',
				confidence REAL DEFAULT 0.0,
				metadata_title TEXT DEFAULT '',
				metadata_subtitle TEXT DEFAULT '',
				metadata_overview TEXT DEFAULT '',
				metadata_genres TEXT DEFAULT '',
				metadata_provider TEXT DEFAULT '',
				metadata_provider_ids TEXT DEFAULT '',
				metadata_media_type TEXT DEFAULT '',
				metadata_year TEXT DEFAULT '',
				metadata_runtime TEXT DEFAULT '',
				metadata_rating TEXT DEFAULT '',
				metadata_vote_count TEXT DEFAULT '',
				metadata_cover_path TEXT DEFAULT '',
				metadata_backdrop_path TEXT DEFAULT '',
				metadata_logo_path TEXT DEFAULT '',
				metadata_image_path TEXT DEFAULT '',
				metadata_released TEXT DEFAULT '',
				metadata_countries TEXT DEFAULT '',
				metadata_age_rating TEXT DEFAULT '',
				metadata_cast TEXT DEFAULT '',
				metadata_crew TEXT DEFAULT '',
				metadata_season_no TEXT DEFAULT '',
				metadata_episode_no TEXT DEFAULT '',
				last_access INTEGER DEFAULT 0,
				expires_at INTEGER DEFAULT 0,
				pinned INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_epg_event_asset_map (
				epg_event_id INTEGER NOT NULL,
				asset_id INTEGER NOT NULL,
				confidence REAL DEFAULT 0.0,
				provider TEXT DEFAULT '',
				created_at INTEGER DEFAULT 0,
				PRIMARY KEY (epg_event_id, asset_id),
				FOREIGN KEY (epg_event_id) REFERENCES e2mdb_epg_events(id) ON DELETE CASCADE,
				FOREIGN KEY (asset_id) REFERENCES e2mdb_provider_assets(id) ON DELETE CASCADE
			)
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_assets_provider ON e2mdb_provider_assets(provider, provider_id)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_assets_expires ON e2mdb_provider_assets(expires_at)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_source ON e2mdb_epg_events(source_type, service_ref)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_time ON e2mdb_epg_events(begin_time, event_end)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_status ON e2mdb_epg_events(status)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_search_title ON e2mdb_epg_events(search_title)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_expires ON e2mdb_epg_events(expires_at)")

	def _create_live_epg_queue_schema(self, conn):
		"""Create the clean-start Live/EPG queue table owned by the backend."""
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_fetch_queue (
				source_key TEXT PRIMARY KEY,
				source_type TEXT DEFAULT 'epg',
				service_ref TEXT DEFAULT '',
				title TEXT DEFAULT '',
				search_title TEXT DEFAULT '',
				short_desc TEXT DEFAULT '',
				extended_desc TEXT DEFAULT '',
				begin_time INTEGER DEFAULT 0,
				event_end INTEGER DEFAULT 0,
				priority INTEGER DEFAULT 0,
				reason TEXT DEFAULT '',
				state TEXT DEFAULT 'pending',
				attempts INTEGER DEFAULT 0,
				not_before INTEGER DEFAULT 0,
				last_error TEXT DEFAULT '',
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_fetch_queue_state ON e2mdb_fetch_queue(state, priority, not_before)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_fetch_queue_event_end ON e2mdb_fetch_queue(event_end)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_fetch_queue_updated ON e2mdb_fetch_queue(updated_at DESC)")

	def _create_state_schema(self, conn):
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_backend_state (
				key TEXT PRIMARY KEY,
				value_json TEXT NOT NULL,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_cleanup_state (
				key TEXT PRIMARY KEY,
				value TEXT DEFAULT '',
				updated_at INTEGER DEFAULT 0
			)
		""")

	def _json(self, payload):
		try:
			return dumps(payload, ensure_ascii=False, sort_keys=True)
		except Exception:
			return "{}"

	def _media_fields_from_recording(self, item):
		hash_id = str(item.get("id") or "").strip()
		file_path = str(item.get("path") or "")
		file_name = str(item.get("name") or "")
		search_candidates = item.get("search_candidates") if isinstance(item.get("search_candidates"), list) else []
		search_string = search_candidates[0] if search_candidates else (item.get("title") or file_name)
		return hash_id, file_path, file_name, str(search_string or "")

	def _upsert_media(self, conn, item):
		hash_id, file_path, file_name, search_string = self._media_fields_from_recording(item)
		if not hash_id or not file_path:
			return
		search_norm = normalize_search_text(search_string)
		conn.execute("""
			INSERT OR IGNORE INTO e2mdb_media (
				hash, file_path, file_name, search_string, search_string_norm,
				metadata_title, metadata_overview, metadata_runtime, created_at, updated_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
		""", (
			hash_id, file_path, file_name, search_string, search_norm,
			str(item.get("title") or ""), str(item.get("description") or item.get("extended_description") or ""),
			str(item.get("duration_seconds") or "")
		))
		source_type = str(item.get("type") or "recording")
		path_mode = str(item.get("path_mode", item.get("mode", "")) or "")
		path_mode_label = str(item.get("path_mode_label") or "")
		media_family = str(item.get("media_family") or "")
		estimated_media_type = str(item.get("estimated_media_type") or "")
		provider_media_type = str(item.get("provider_media_type") or estimated_media_type or "")
		provider_title = str(item.get("provider_title") or "")
		series_title = str(item.get("series_title") or "")
		movie_title = str(item.get("movie_title") or "")
		season_no = str(item.get("season_no") or "")
		episode_no = str(item.get("episode_no") or "")
		conn.execute("""
			UPDATE e2mdb_media
			SET file_path = ?, file_name = ?, search_string = ?, search_string_norm = ?,
				source_type = ?, path_mode = ?, path_mode_label = ?, media_family = ?,
				estimated_media_type = ?, provider_media_type = ?, provider_title = ?,
				series_title = ?, movie_title = ?, scan_season_no = ?, scan_episode_no = ?,
				browser_ready = '0',
				provider_lookup_status = CASE WHEN COALESCE(provider_lookup_status, '') IN ('done', 'no_match') THEN 'pending' ELSE provider_lookup_status END,
				provider_lookup_error = CASE WHEN COALESCE(provider_lookup_status, '') IN ('done', 'no_match') THEN '' ELSE provider_lookup_error END,
				metadata_title = CASE WHEN COALESCE(metadata_title, '') = '' THEN ? ELSE metadata_title END,
				metadata_overview = CASE WHEN COALESCE(metadata_overview, '') = '' THEN ? ELSE metadata_overview END,
				metadata_runtime = CASE WHEN COALESCE(metadata_runtime, '') = '' THEN ? ELSE metadata_runtime END,
				metadata_media_type = CASE WHEN ? != '' AND (COALESCE(metadata_media_type, '') = '' OR COALESCE(metadata_media_type, '') = 'multi') THEN ? ELSE metadata_media_type END,
				metadata_season_no = CASE WHEN ? != '' AND COALESCE(metadata_season_no, '') = '' THEN ? ELSE metadata_season_no END,
				metadata_episode_no = CASE WHEN ? != '' AND COALESCE(metadata_episode_no, '') = '' THEN ? ELSE metadata_episode_no END,
				updated_at = CURRENT_TIMESTAMP
			WHERE hash = ?
		""", (
			file_path, file_name, search_string, search_norm,
			source_type, path_mode, path_mode_label, media_family, estimated_media_type, provider_media_type, provider_title,
			series_title, movie_title, season_no, episode_no,
			str(item.get("title") or ""), str(item.get("description") or item.get("extended_description") or ""),
			str(item.get("duration_seconds") or ""), provider_media_type, provider_media_type, season_no, season_no, episode_no, episode_no, hash_id
		))

	def recording_index(self, paths=None):
		self.ensure_schema()
		index = {}
		with self.lock:
			with self._connect() as conn:
				where = []
				params = []
				path_sql, path_params = self._path_filter_sql(paths, column_path="path", column_folder="folder", prefix="r.")
				if path_sql:
					where.append(path_sql)
					params.extend(path_params)
				where_sql = "WHERE " + " AND ".join(where) if where else ""
				rows = conn.execute("""
					SELECT r.recording_id, r.media_hash, r.path, r.folder, r.name, r.size_bytes, r.mtime,
						r.title, r.source_type, r.path_mode, r.provider_media_type, r.payload_json,
						COALESCE(m.browser_ready, '') AS browser_ready,
						COALESCE(m.provider_lookup_status, '') AS provider_lookup_status
					FROM e2mdb_recordings r
					LEFT JOIN e2mdb_media m ON m.hash = r.media_hash
					%s
				""" % where_sql, params).fetchall()
		for row in rows:
			item = {key: row[key] for key in row.keys()}
			path = str(item.get("path") or "")
			recording_id = str(item.get("recording_id") or item.get("media_hash") or "")
			if path:
				index[path] = item
			if recording_id:
				index[recording_id] = item
		return index

	def _path_filter_sql(self, paths, column_path="path", column_folder="folder", prefix=""):
		paths = paths if isinstance(paths, list) else []
		clauses = []
		params = []
		for item in paths:
			if not isinstance(item, dict):
				continue
			path = str(item.get("path") or "").rstrip("/")
			if not path:
				continue
			recursive = bool(item.get("recursive", True))
			path_col = f"{prefix}{column_path}"
			folder_col = f"{prefix}{column_folder}"
			if recursive:
				clauses.append(f"({path_col} = ? OR {path_col} LIKE ?)")
				params.extend([path, f"{path}/%"])
			else:
				clauses.append(f"({path_col} = ? OR {folder_col} = ?)")
				params.extend([path, path])
		if not clauses:
			return "", []
		return "(" + " OR ".join(clauses) + ")", params

	def upsert_recordings(self, items, prune_missing=True, prune_paths=None, seen_ids=None):
		self.ensure_schema()
		items = items if isinstance(items, list) else []
		now = int(time())
		seen = []
		for value in (seen_ids if isinstance(seen_ids, list) else []):
			text = str(value or "").strip()
			if text and text not in seen:
				seen.append(text)
		processed = 0
		processed_ids = []
		with self.lock:
			with self._connect() as conn:
				for item in items:
					if not isinstance(item, dict):
						continue
					recording_id = str(item.get("id") or "").strip()
					path = str(item.get("path") or "").strip()
					if not recording_id or not path:
						continue
					if recording_id not in seen:
						seen.append(recording_id)
					processed += 1
					if recording_id not in processed_ids:
						processed_ids.append(recording_id)
					self._upsert_media(conn, item)
					search_candidates = item.get("search_candidates") if isinstance(item.get("search_candidates"), list) else []
					search_text = " ".join([str(value or "") for value in search_candidates]) or str(item.get("title") or "")
					search_text_norm = normalize_search_text(search_text)
					payload_json = self._json(item)
					conn.execute("""
						INSERT OR IGNORE INTO e2mdb_recordings (
							recording_id, media_hash, path, created_at, updated_at
						) VALUES (?, ?, ?, ?, ?)
					""", (recording_id, recording_id, path, now, now))
					conn.execute("""
						UPDATE e2mdb_recordings
						SET media_hash = ?, path = ?, folder = ?, name = ?, extension = ?, title = ?, description = ?,
							extended_description = ?, service_ref = ?, recorded_at = ?, duration_seconds = ?, size_bytes = ?,
							mtime = ?,
							source_type = ?, path_mode = ?, path_mode_label = ?, media_family = ?, estimated_media_type = ?,
							provider_media_type = ?, provider_title = ?, series_title = ?, movie_title = ?, season_no = ?, episode_no = ?,
							search_text = ?, search_text_norm = ?, scan_status = ?, parse_error = ?, payload_json = ?, updated_at = ?
						WHERE recording_id = ?
					""", (
						recording_id, path, str(item.get("folder") or ""), str(item.get("name") or ""), str(item.get("extension") or ""),
						str(item.get("title") or ""), str(item.get("description") or ""), str(item.get("extended_description") or ""),
						str(item.get("service_ref") or ""), safe_int(item.get("recorded_at"), 0), safe_int(item.get("duration_seconds"), 0),
						safe_int(item.get("size_bytes"), 0), safe_int(item.get("mtime"), 0),
						str(item.get("type") or "recording"), str(item.get("path_mode", item.get("mode", "")) or ""), str(item.get("path_mode_label") or ""),
						str(item.get("media_family") or ""), str(item.get("estimated_media_type") or ""), str(item.get("provider_media_type") or item.get("estimated_media_type") or ""),
						str(item.get("provider_title") or ""), str(item.get("series_title") or ""), str(item.get("movie_title") or ""),
						str(item.get("season_no") or ""), str(item.get("episode_no") or ""),
						search_text, search_text_norm, str(item.get("scan_status") or ""), str(item.get("parse_error") or ""), payload_json, now,
						recording_id
					))
				pruned = 0
				conn.execute("DROP TABLE IF EXISTS temp.e2mdb_scan_seen")
				conn.execute("DROP TABLE IF EXISTS temp.e2mdb_scan_processed")
				conn.execute("CREATE TEMP TABLE e2mdb_scan_seen (recording_id TEXT PRIMARY KEY)")
				conn.execute("CREATE TEMP TABLE e2mdb_scan_processed (recording_id TEXT PRIMARY KEY)")
				if seen:
					conn.executemany("INSERT OR IGNORE INTO e2mdb_scan_seen(recording_id) VALUES (?)", [(value,) for value in seen])
				if processed_ids:
					conn.executemany("INSERT OR IGNORE INTO e2mdb_scan_processed(recording_id) VALUES (?)", [(value,) for value in processed_ids])
				if seen:
					conn.execute("""
						UPDATE e2mdb_media
						SET browser_ready = '1'
						WHERE hash IN (SELECT recording_id FROM e2mdb_scan_seen)
						AND hash NOT IN (SELECT recording_id FROM e2mdb_scan_processed)
						AND provider_lookup_status IN ('done', 'no_match')
						AND COALESCE(browser_ready, '') != '1'
					""")
				if prune_missing:
					path_sql, path_params = self._path_filter_sql(prune_paths, column_path="path", column_folder="folder")
					where = []
					params = []
					if seen:
						where.append("NOT EXISTS (SELECT 1 FROM e2mdb_scan_seen s WHERE s.recording_id = e2mdb_recordings.recording_id)")
					if path_sql:
						where.append(path_sql)
						params.extend(path_params)
					if where:
						cur = conn.execute("DELETE FROM e2mdb_recordings WHERE " + " AND ".join(where), params)
						pruned = cur.rowcount if cur.rowcount is not None else 0
					elif not seen:
						cur = conn.execute("DELETE FROM e2mdb_recordings")
						pruned = cur.rowcount if cur.rowcount is not None else 0
				self.set_state(conn, "recording_scan", {
					"version": 1,
					"updated": now,
					"total": len(seen),
					"pruned": pruned,
				})
				conn.commit()
		return {"inserted_or_updated": processed, "seen": len(seen), "pruned": pruned, "db_path": self.db_path}

	def set_state(self, conn, key, payload):
		conn.execute("""
			INSERT OR REPLACE INTO e2mdb_backend_state (key, value_json, updated_at)
			VALUES (?, ?, ?)
		""", (str(key or ""), self._json(payload), int(time())))

	def list_recordings(self, offset=0, limit=50, query=""):
		offset = max(0, safe_int(offset, 0))
		limit = max(1, min(500, safe_int(limit, 50)))
		query_norm = normalize_search_text(query)
		with self.lock:
			with self._connect() as conn:
				where_sql = ""
				params = []
				if query_norm:
					where_sql = "WHERE search_text_norm LIKE ? OR lower(path) LIKE ?"
					params = [f"%{query_norm}%", f"%{str(query or "").lower()}%"]
				total_row = conn.execute(f"SELECT COUNT(*) AS total FROM e2mdb_recordings {where_sql}", params).fetchone()
				total = int(total_row["total"] if total_row else 0)
				rows = conn.execute("""
					SELECT payload_json FROM e2mdb_recordings
					%s
					ORDER BY COALESCE(recorded_at, 0) DESC, COALESCE(mtime, 0) DESC, title COLLATE NOCASE ASC
					LIMIT ? OFFSET ?
				""" % where_sql, params + [limit, offset]).fetchall()
		items = []
		for row in rows:
			try:
				items.append(loads(row["payload_json"] or "{}"))
			except Exception:
				items.append({})
		return {
			"success": True,
			"source": "sqlite",
			"db_path": self.db_path,
			"total": total,
			"offset": offset,
			"limit": limit,
			"items": items,
		}

	def get_recording(self, recording_id):
		recording_id = str(recording_id or "")
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("""
					SELECT payload_json FROM e2mdb_recordings
					WHERE recording_id = ? OR path = ?
					LIMIT 1
				""", (recording_id, recording_id)).fetchone()
		if not row:
			return {"success": False, "error": "recording not found"}
		try:
			item = loads(row["payload_json"] or "{}")
		except Exception:
			item = {}
		return {"success": True, "source": "sqlite", "item": item}

	def list_recordings_for_enrichment(self, limit=100, query="", only_missing=True, paths=None, retry_no_match=False, retry_missing_artwork=False):
		self.ensure_schema()
		limit = safe_int(limit, 100)
		if limit <= 0:
			limit = 100000
		else:
			limit = max(1, min(100000, limit))
		query_norm = normalize_search_text(query)
		with self.lock:
			with self._connect() as conn:
				where = []
				params = []
				if only_missing:
					missing = ["""(
						m.hash IS NULL
						OR m.provider_lookup_status IS NULL
						OR m.provider_lookup_status = ''
						OR m.provider_lookup_status = 'pending'
						OR m.provider_lookup_status = 'error'
						OR (COALESCE(m.browser_ready, '0') != '1' AND COALESCE(m.provider_lookup_status, '') NOT IN ('done', 'no_match'))
					)"""]
					if truthy(retry_no_match):
						missing.append("COALESCE(m.provider_lookup_status, '') = 'no_match'")
					if truthy(retry_missing_artwork):
						missing.append("""(
							COALESCE(m.provider_lookup_status, '') = 'done'
							AND COALESCE(m.metadata_cover_path, '') = ''
							AND COALESCE(m.metadata_backdrop_path, '') = ''
							AND COALESCE(m.metadata_image_path, '') = ''
							AND COALESCE(m.metadata_series_cover_path, '') = ''
							AND COALESCE(m.metadata_episode_image_path, '') = ''
							AND COALESCE(m.artwork_poster_path, '') = ''
							AND COALESCE(m.artwork_backdrop_path, '') = ''
							AND COALESCE(m.artwork_series_poster_path, '') = ''
							AND COALESCE(m.artwork_series_backdrop_path, '') = ''
							AND COALESCE(m.artwork_episode_path, '') = ''
						)""")
					where.append("(" + " OR ".join(missing) + ")")
				if query_norm:
					where.append("(r.search_text_norm LIKE ? OR lower(r.path) LIKE ?)")
					params.extend([f"%{query_norm}%", f"%{str(query or "").lower()}%"])
				path_sql, path_params = self._path_filter_sql(paths, column_path="path", column_folder="folder", prefix="r.")
				if path_sql:
					where.append(path_sql)
					params.extend(path_params)
				where_sql = "WHERE " + " AND ".join(where) if where else ""
				rows = conn.execute("""
					SELECT r.payload_json
					FROM e2mdb_recordings r
					LEFT JOIN e2mdb_media m ON m.hash = r.media_hash
					%s
					ORDER BY COALESCE(r.recorded_at, 0) DESC, COALESCE(r.mtime, 0) DESC, r.title COLLATE NOCASE ASC
					LIMIT ?
				""" % where_sql, params + [limit]).fetchall()
		items = []
		for row in rows:
			try:
				items.append(loads(row["payload_json"] or "{}"))
			except Exception:
				pass
		return items

	def upsert_provider_result(self, recording_item, provider_result):
		self.ensure_schema()
		recording_item = recording_item if isinstance(recording_item, dict) else {}
		provider_result = provider_result if isinstance(provider_result, dict) else {}
		media_hash = str(recording_item.get("id") or provider_result.get("recording_id") or "").strip()
		if not media_hash:
			return {"success": False, "error": "missing media hash"}
		now = int(time())
		best = provider_result.get("best") if isinstance(provider_result.get("best"), dict) else {}
		artwork = provider_result.get("artwork") if isinstance(provider_result.get("artwork"), dict) else {}
		matches = provider_result.get("matches") if isinstance(provider_result.get("matches"), list) else []
		error = str(provider_result.get("error") or "")
		status = "done" if provider_result.get("success") else ("no_match" if error == "no provider match" else "error")
		provider_ids = best.get("provider_ids", {}) if isinstance(best.get("provider_ids", {}), dict) else {}
		episode_image_value = self._first_non_empty(
			artwork.get("episode_path"), best.get("episode_image_url"), best.get("episode_still_url"), best.get("still_url"), best.get("preview_url")
		)
		if not episode_image_value and str(best.get("image_src") or "").strip().lower() == "episode":
			episode_image_value = self._first_non_empty(best.get("image_url"), best.get("image_path"))
		if not episode_image_value and str(best.get("cover_src") or "").strip().lower() == "episode":
			episode_image_value = self._first_non_empty(best.get("cover_url"), best.get("cover_path"))
		series_cover_value = self._first_non_empty(
			artwork.get("series_poster_path"), best.get("series_cover_path"), best.get("series_cover_url"), best.get("series_poster_path"), best.get("series_poster_url")
		)
		series_backdrop_value = self._first_non_empty(artwork.get("series_backdrop_path"), best.get("series_backdrop_path"), best.get("series_backdrop_url"))
		# Cover/poster widgets must not receive episode stills or previews.  Those
		# belong to metadata_episode_image_path/artwork_episode_path only.
		cover_value = self._first_non_empty(artwork.get("poster_path"), series_cover_value, best.get("cover_path"), best.get("poster_path"), best.get("cover_url"), best.get("poster_url"))
		backdrop_value = self._first_non_empty(artwork.get("backdrop_path"), series_backdrop_value, best.get("backdrop_path"), best.get("backdrop_url"), best.get("fanart_url"))
		logo_value = self._first_non_empty(artwork.get("logo_path"), best.get("titlelogo_path"), best.get("logo_path"), best.get("titlelogo_url"), best.get("logo_url"), best.get("clearlogo_url"))
		with self.lock:
			with self._connect() as conn:
				conn.execute("DELETE FROM e2mdb_provider_matches WHERE media_hash = ?", (media_hash,))
				for index, match in enumerate(matches):
					if not isinstance(match, dict):
						continue
					conn.execute("""
						INSERT INTO e2mdb_provider_matches (
							media_hash, recording_id, provider, media_type, title, year, match_score, is_best, payload_json, created_at, updated_at
						) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					""", (
						media_hash,
						str(recording_item.get("id") or ""),
						str(match.get("provider") or ""),
						str(match.get("media_type") or ""),
						str(match.get("title") or match.get("original_title") or ""),
						str(match.get("year") or ""),
						float(match.get("_match_score") or 0),
						1 if match is best or match == best else 0,
						self._json(match),
						now,
						now,
					))
				conn.execute("""
					UPDATE e2mdb_media
					SET provider_lookup_status = ?, provider_lookup_error = ?, provider_lookup_updated = ?, provider_best_json = ?,
						browser_ready = '1',
						metadata_title = CASE WHEN ? != '' THEN ? ELSE metadata_title END,
						metadata_subtitle = CASE WHEN ? != '' THEN ? ELSE metadata_subtitle END,
						metadata_overview = CASE WHEN ? != '' THEN ? ELSE metadata_overview END,
						metadata_provider = ?, metadata_provider_ids = ?, metadata_media_type = ?, metadata_year = ?,
						metadata_runtime = ?, metadata_rating = ?, metadata_vote_count = ?, metadata_cover_path = ?,
						metadata_backdrop_path = ?, metadata_logo_path = ?, metadata_released = ?, metadata_genres = ?,
						metadata_countries = ?, metadata_age_rating = ?, metadata_season_no = ?, metadata_episode_no = ?,
						metadata_series_cover_path = ?, metadata_episode_image_path = ?,
						metadata_cast = ?, metadata_crew = ?, artwork_poster_path = ?, artwork_backdrop_path = ?,
						artwork_logo_path = ?, artwork_series_poster_path = ?, artwork_series_backdrop_path = ?, artwork_episode_path = ?,
						updated_at = CURRENT_TIMESTAMP
					WHERE hash = ?
				""", (
					status,
					error,
					now,
					self._json(best),
					str(best.get("title") or best.get("episode_name") or ""), str(best.get("title") or best.get("episode_name") or ""),
					str(best.get("series_title") or best.get("show_title") or ""), str(best.get("series_title") or best.get("show_title") or ""),
					str(best.get("overview") or best.get("description") or ""), str(best.get("overview") or best.get("description") or ""),
					str(best.get("provider") or ""), self._json(provider_ids), str(best.get("media_type") or provider_result.get("media_type") or ""),
					str(best.get("year") or provider_result.get("year") or ""), str(best.get("runtime") or ""),
					str(best.get("vote_average") or ""), str(best.get("vote_count") or ""),
					cover_value,
					backdrop_value,
					logo_value,
					str(best.get("released") or best.get("releaseDate") or ""), self._json(best.get("genres") or []),
					self._json(best.get("countries") or []), str(best.get("age_rating") or ""),
					str(best.get("season_no") or recording_item.get("season_no") or ""), str(best.get("episode_no") or recording_item.get("episode_no") or ""),
					str(series_cover_value or ""), str(episode_image_value or ""),
					self._json(best.get("cast") or []), self._json(best.get("crew") or []),
					str(artwork.get("poster_path") or cover_value or ""), str(artwork.get("backdrop_path") or backdrop_value or ""), str(artwork.get("logo_path") or logo_value or ""),
					str(artwork.get("series_poster_path") or series_cover_value or ""), str(artwork.get("series_backdrop_path") or series_backdrop_value or ""), str(artwork.get("episode_path") or episode_image_value or ""),
					media_hash,
				))
				self.set_state(conn, "provider_enrichment", {
					"version": 1,
					"updated": now,
					"last_recording_id": media_hash,
					"status": status,
				})
				conn.commit()
		return {"success": True, "status": status, "media_hash": media_hash, "matches": len(matches)}

	def _decode_json_value(self, value, fallback=None):
		if fallback is None:
			fallback = {} if isinstance(value, str) and value.strip().startswith("{") else []
		try:
			if value is None or value == "":
				return fallback
			return loads(value) if isinstance(value, str) else value
		except Exception:
			return fallback

	def _text_from_json_or_string(self, value):
		if value is None:
			return ""
		decoded = self._decode_json_value(value, fallback=value)
		if isinstance(decoded, list):
			items = []
			for item in decoded:
				if isinstance(item, dict):
					name = item.get("name") or item.get("title") or item.get("label") or ""
					if name:
						items.append(str(name))
				elif item:
					items.append(str(item))
			return ", ".join(items)
		if isinstance(decoded, dict):
			return ", ".join([str(v) for v in decoded.values() if v])
		return str(decoded or "")

	def _first_non_empty(self, *values):
		for value in values:
			if value is None:
				continue
			value = str(value).strip()
			if value:
				return value
		return ""

	def _media_type_from_payload(self, payload, fallback=""):
		payload = payload if isinstance(payload, dict) else {}
		fallback = str(fallback or "").strip().lower()
		if fallback in ("movie", "series"):
			return fallback
		parsed_type = str(payload.get("provider_media_type") or payload.get("estimated_media_type") or "").strip().lower()
		mode = safe_int(payload.get("path_mode", payload.get("mode", 0)), 0)
		if parsed_type in ("series", "anime_series", "manga_series") and mode in (0, 2, 3, 4, 5):
			return "series"
		if parsed_type in ("movie", "anime_movie", "manga_movie") and mode in (0, 1, 3, 6, 7):
			return "movie"
		if mode in (2, 4, 5):
			return "series"
		if mode in (1, 6, 7):
			return "movie"
		family = str(payload.get("media_family") or "").strip().lower()
		if family in ("series", "anime_series", "manga_series"):
			return "series"
		if family in ("movie", "anime_movie", "manga_movie"):
			return "movie"
		text = " ".join([str(payload.get(key) or "") for key in ("name", "title", "path")])
		if self._parse_season_episode_from_name(text) != (None, None):
			return "series"
		return fallback or "movie"

	def _browser_where_sql(self, query="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		query_norm = normalize_search_text(query)
		media_type = str(media_type or "all").strip().lower()
		year = str(year or "").strip()
		genre_norm = normalize_search_text(genre)
		cast_text = str(cast or "").strip()
		cast_norm = normalize_search_text(cast_text)
		letter = str(letter or "").strip().upper()
		where = []
		params = []
		# The MediaBrowser is a consumer view. Rows from the fast filesystem scan are
		# intentionally hidden until provider/artwork handling has finished for that item.
		# browser_ready is reset to 0 during the scan import and set to 1 only after
		# provider enrichment has written a final result for the item.
		if not truthy(include_pending):
			where.append("COALESCE(m.browser_ready, '0') = '1'")
		if query_norm:
			where.append("(m.search_string_norm LIKE ? OR r.search_text_norm LIKE ? OR lower(m.file_path) LIKE ? OR lower(COALESCE(m.series_title, '')) LIKE ? OR lower(COALESCE(m.provider_title, '')) LIKE ? OR lower(m.metadata_title) LIKE ?)")
			query_plain = f"%{str(query or "").lower()}%"
			params.extend([f"%{query_norm}%", f"%{query_norm}%", query_plain, query_plain, query_plain, query_plain])
		if media_type and media_type != "all":
			if media_type in ("movie", "series"):
				where.append("(lower(COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, '')) = ? OR COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, '') = '' OR lower(COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, '')) = 'multi')")
				params.append(media_type)
			else:
				where.append("lower(COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, '')) = ?")
				params.append(media_type)
		if year:
			where.append("(COALESCE(m.metadata_year, '') = ? OR substr(COALESCE(m.metadata_released, ''), 1, 4) = ?)")
			params.extend([year, year])
		if genre_norm:
			where.append("lower(COALESCE(m.metadata_genres, '')) LIKE ?")
			params.append(f"%{genre_norm}%")
		if cast_norm:
			# Cast search must be SQL-side, not a post-filter on the current page.
			# Otherwise clicking an actor may return an empty first page even though
			# matching rows exist later in the library. Search both the normalized name
			# and the raw text because metadata_cast is stored as JSON.
			cast_like_raw = f"%{cast_text.lower()}%"
			cast_like_norm_parts = [part for part in cast_norm.split() if part]
			if cast_like_norm_parts:
				where.append("(" + " AND ".join(["lower(COALESCE(m.metadata_cast, '') || ' ' || COALESCE(m.provider_best_json, '')) LIKE ?" for _ in cast_like_norm_parts]) + " OR lower(COALESCE(m.metadata_cast, '') || ' ' || COALESCE(m.provider_best_json, '')) LIKE ?)")
				params.extend([f"%{part}%" for part in cast_like_norm_parts])
				params.append(cast_like_raw)
			else:
				where.append("lower(COALESCE(m.metadata_cast, '') || ' ' || COALESCE(m.provider_best_json, '')) LIKE ?")
				params.append(cast_like_raw)
		if letter:
			# Alphabet filter must use the visible/group title. For series this is the
			# series title, not the per-episode metadata title. Otherwise a series with
			# an episode named "B..." appears under B although the card title starts
			# with S.
			display_title_sql = "COALESCE(NULLIF(m.series_title, ''), NULLIF(m.provider_title, ''), NULLIF(m.metadata_title, ''), NULLIF(r.title, ''), m.search_string, m.file_name)"
			if letter == "0-9":
				where.append(f"substr(upper({display_title_sql}), 1, 1) BETWEEN '0' AND '9'")
			else:
				where.append(f"substr(upper({display_title_sql}), 1, 1) = ?")
				params.append(letter[:1])
		return ("WHERE " + " AND ".join(where) if where else ""), params

	def _browser_select_sql(self, where_sql=""):
		return """
			SELECT
				m.hash AS media_hash, m.file_path AS media_file_path, m.file_name AS media_file_name,
				m.search_string, m.metadata_title, m.metadata_subtitle, m.metadata_overview,
				m.metadata_genres, m.metadata_provider, m.metadata_provider_ids, m.metadata_media_type,
				m.source_type, m.path_mode, m.path_mode_label, m.media_family, m.estimated_media_type,
				m.provider_media_type, m.provider_title, m.series_title AS media_series_title, m.movie_title, m.scan_season_no, m.scan_episode_no,
				m.metadata_year, m.metadata_runtime, m.metadata_rating, m.metadata_vote_count,
				m.metadata_cover_path, m.metadata_backdrop_path, m.metadata_logo_path, m.metadata_image_path,
				m.metadata_series_cover_path, m.metadata_episode_image_path,
				m.metadata_released, m.metadata_countries, m.metadata_age_rating, m.metadata_cast,
				m.metadata_season_no, m.metadata_episode_no,
				m.provider_lookup_status, m.provider_lookup_error, m.provider_lookup_updated, m.provider_best_json,
				m.browser_ready,
				m.artwork_poster_path, m.artwork_backdrop_path, m.artwork_logo_path,
				m.artwork_series_poster_path, m.artwork_series_backdrop_path, m.artwork_episode_path,
				r.recording_id, r.path AS recording_path, r.folder, r.name AS recording_name, r.extension,
				r.title AS recording_title, r.description AS recording_description, r.extended_description,
				r.service_ref, r.recorded_at, r.duration_seconds, r.size_bytes, r.mtime,
				r.search_text, r.scan_status, r.parse_error, r.payload_json
			FROM e2mdb_media m
			LEFT JOIN e2mdb_recordings r ON r.media_hash = m.hash
			%s
			ORDER BY COALESCE(NULLIF(m.series_title, ''), NULLIF(m.provider_title, ''), NULLIF(m.metadata_title, ''), NULLIF(r.title, ''), m.search_string, m.file_name) COLLATE NOCASE ASC,
				COALESCE(r.recorded_at, 0) DESC, COALESCE(r.mtime, 0) DESC
		""" % where_sql

	def _browser_rows(self, query="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		where_sql, params = self._browser_where_sql(query=query, media_type=media_type, year=year, genre=genre, cast=cast, letter=letter, include_pending=include_pending)
		with self.lock:
			with self._connect() as conn:
				return conn.execute(self._browser_select_sql(where_sql), params).fetchall()

	def _decode_provider_id(self, provider, provider_ids_raw):
		provider = str(provider or "").strip().lower()
		provider_ids = self._decode_json_value(provider_ids_raw, fallback={})
		if isinstance(provider_ids, dict):
			if provider and provider_ids.get(provider):
				return str(provider_ids.get(provider) or "")
			for key in ("tmdb", "tvdb", "imdb", "tvmaze", "anime", "anilist", "kitsu", "omdb"):
				if provider_ids.get(key):
					return str(provider_ids.get(key) or "")
		return ""

	def _parse_season_episode_from_name(self, name):
		text = str(name or "")
		match = search(r"(?i)[Ss](\d{1,2})[Ee](\d{1,3})", text)
		if match:
			return safe_int(match.group(1), 0), safe_int(match.group(2), 0)
		match = search(r"(?i)(\d{1,2})x(\d{1,3})", text)
		if match:
			return safe_int(match.group(1), 0), safe_int(match.group(2), 0)
		match = search(r"(?i)(?:staffel|season)\s*(\d{1,2}).{0,20}(?:folge|episode|ep\.?|e)\s*(\d{1,3})", text)
		if match:
			return safe_int(match.group(1), 0), safe_int(match.group(2), 0)
		return None, None

	def _clean_release_title(self, value):
		text = str(value or "").strip()
		if not text:
			return ""
		text = sub(r"[._]+", " ", text)
		text = sub(r"\s+", " ", text).strip(" -_.")
		return text

	def _series_title_from_text(self, value):
		text = self._clean_release_title(value)
		if not text:
			return ""
		match = search(r"(?i)\b[S](\d{1,2})[ ._-]*[E](\d{1,3})\b", text)
		if not match:
			match = search(r"(?i)\b(\d{1,2})x(\d{1,3})\b", text)
		if not match:
			return text
		series = text[:match.start()].strip(" -_.")
		series = sub(r"(?i)\b(german|english|multi|dubbed|subbed|720p|1080p|2160p|web|webrip|web-dl|hdtv|bluray|x264|x265|h264|h265|hevc|ac3|dts)\b.*$", "", series).strip(" -_.")
		return series or text

	def _browser_group_key(self, item, row=None):
		row = dict(row) if row is not None else {}
		media_type = str(item.get("media_type") or "movie").strip().lower()
		provider = str(item.get("provider") or "").strip().lower()
		provider_id = self._decode_provider_id(provider, row.get("metadata_provider_ids"))
		if provider and provider_id:
			return f"{media_type}|{provider}|{provider_id}"
		if media_type == "series":
			title_source = self._first_non_empty(item.get("series_title"), item.get("title"), item.get("name"), item.get("search_string"), item.get("file_name"), item.get("file_path"))
			title = normalize_search_text(self._series_title_from_text(title_source))
			return f"{media_type}|{title}"
		title = normalize_search_text(item.get("title") or item.get("name") or item.get("search_string") or item.get("file_name") or "")
		year = str(item.get("year") or item.get("released") or "")[:4]
		return f"{media_type}|{title}|{year}"

	def _image_file_path(self, value):
		value = str(value or "").strip()
		if not value:
			return ""
		if value.startswith("/api/artwork/file?") and "path=" in value:
			encoded = value.split("path=", 1)[1].split("&", 1)[0]
			decoded = unquote(encoded)
			return decoded if decoded.startswith("/") else ""
		value_lower = value.lower()
		if value_lower.startswith(("http://", "https://", "data:")) or value.startswith("/api/"):
			return ""
		return value if value.startswith("/") else ""

	def _web_image_url(self, value):
		value = str(value or "").strip()
		if not value:
			return ""
		file_path = self._image_file_path(value)
		if file_path:
			return f"/api/artwork/file?path={quote(file_path, safe="")}"
		value_lower = value.lower()
		if value_lower.startswith(("http://", "https://", "data:")) or value.startswith("/api/"):
			return value
		return value

	def _row_to_browser_item(self, row):
		row = dict(row)
		best = self._decode_json_value(row.get("provider_best_json"), fallback={})
		if not isinstance(best, dict):
			best = {}
		payload = self._decode_json_value(row.get("payload_json"), fallback={})
		if not isinstance(payload, dict):
			payload = {}
		title = self._first_non_empty(row.get("metadata_title"), best.get("title"), best.get("name"), row.get("recording_title"), row.get("search_string"), row.get("media_file_name"))
		overview = self._first_non_empty(row.get("metadata_overview"), best.get("overview"), best.get("description"), row.get("recording_description"), row.get("extended_description"))
		media_type = self._media_type_from_payload(payload, self._first_non_empty(row.get("metadata_media_type"), row.get("provider_media_type"), row.get("estimated_media_type"), best.get("media_type")))
		series_title = title
		if media_type == "series":
			series_title = self._first_non_empty(best.get("series_title"), best.get("series_name"), best.get("show_title"), row.get("media_series_title"), payload.get("series_title"), payload.get("series_name"), title, row.get("media_file_name"), row.get("recording_path"))
			series_title = self._series_title_from_text(series_title)
		year = self._first_non_empty(row.get("metadata_year"), best.get("year"), str(row.get("metadata_released") or "")[:4])
		genres = self._text_from_json_or_string(row.get("metadata_genres") or best.get("genres") or "")
		episode_cover = self._first_non_empty(
			row.get("artwork_episode_path"), row.get("metadata_episode_image_path"),
			best.get("episode_image_path"), best.get("episode_image_url"), best.get("episode_still_url"), best.get("still_url"), best.get("preview_url")
		)
		if not episode_cover and str(best.get("image_src") or "").strip().lower() == "episode":
			episode_cover = self._first_non_empty(best.get("image_path"), best.get("image_url"))
		if not episode_cover and str(best.get("cover_src") or "").strip().lower() == "episode":
			episode_cover = self._first_non_empty(best.get("cover_path"), best.get("cover_url"))
		series_cover = self._first_non_empty(
			row.get("artwork_series_poster_path"), row.get("metadata_series_cover_path"),
			best.get("series_cover_path"), best.get("series_cover_url"), best.get("series_poster_path"), best.get("series_poster_url")
		)
		cover = self._first_non_empty(episode_cover, row.get("artwork_poster_path"), row.get("metadata_cover_path"), row.get("metadata_image_path"), best.get("cover_path"), best.get("cover_url"), best.get("poster_path"), best.get("poster_url"))
		series_backdrop = self._first_non_empty(row.get("artwork_series_backdrop_path"), best.get("series_backdrop_path"), best.get("series_backdrop_url"))
		backdrop = self._first_non_empty(row.get("artwork_backdrop_path"), row.get("metadata_backdrop_path"), best.get("backdrop_path"), best.get("backdrop_url"), series_backdrop)
		logo = self._first_non_empty(row.get("artwork_logo_path"), row.get("metadata_logo_path"), best.get("titlelogo_path"), best.get("titlelogo_url"), best.get("logo_path"), best.get("logo_url"))
		media_hash = row.get("media_hash") or row.get("recording_id") or ""
		cover_url = self._web_image_url(cover)
		episode_cover_url = self._web_image_url(episode_cover)
		series_cover_url = self._web_image_url(series_cover)
		backdrop_url = self._web_image_url(backdrop)
		series_backdrop_url = self._web_image_url(series_backdrop)
		logo_url = self._web_image_url(logo)
		episode_cover_file_path = self._image_file_path(episode_cover)
		series_cover_file_path = self._image_file_path(series_cover)
		cover_file_path = self._image_file_path(cover)
		backdrop_file_path = self._image_file_path(backdrop)
		logo_file_path = self._image_file_path(logo)
		return {
			"id": media_hash,
			"browser_key": media_hash,
			"media_hash": media_hash,
			"recording_id": row.get("recording_id") or media_hash,
			"title": title,
			"name": title,
			"series_title": series_title,
			"file_name": row.get("media_file_name") or row.get("recording_name") or "",
			"file_path": row.get("media_file_path") or row.get("recording_path") or "",
			"overview": overview,
			"description": overview,
			"media_type": media_type,
			"year": year,
			"released": self._first_non_empty(row.get("metadata_released"), best.get("released"), best.get("releaseDate"), year),
			"genres": genres,
			"provider": self._first_non_empty(row.get("metadata_provider"), best.get("provider")),
			"provider_lookup_status": row.get("provider_lookup_status") or "",
			"browser_ready": row.get("browser_ready") or "",
			"provider_lookup_error": row.get("provider_lookup_error") or "",
			"cover_url": cover_url,
			"cover_path": cover_file_path,
			"cover_file_path": cover_file_path,
			"poster_url": cover_url,
			"poster_path": cover_file_path,
			"poster_file_path": cover_file_path,
			"episode_cover_url": episode_cover_url,
			"episode_preview_url": episode_cover_url,
			"episode_cover_path": episode_cover_file_path,
			"episode_cover_file_path": episode_cover_file_path,
			"series_cover_url": series_cover_url,
			"series_poster_url": series_cover_url,
			"series_cover_path": series_cover_file_path,
			"series_cover_file_path": series_cover_file_path,
			"backdrop_url": backdrop_url,
			"backdrop_path": backdrop_file_path,
			"backdrop_file_path": backdrop_file_path,
			"series_backdrop_url": series_backdrop_url,
			"series_backdrop_path": self._image_file_path(series_backdrop),
			"titlelogo_url": logo_url,
			"logo_path": logo_file_path,
			"logo_file_path": logo_file_path,
			"runtime": self._first_non_empty(row.get("metadata_runtime"), best.get("runtime"), row.get("duration_seconds")),
			"vote_average": self._first_non_empty(row.get("metadata_rating"), best.get("vote_average")),
			"vote_count": self._first_non_empty(row.get("metadata_vote_count"), best.get("vote_count")),
			"season_no": self._first_non_empty(row.get("metadata_season_no"), row.get("scan_season_no"), payload.get("season_no")),
			"episode_no": self._first_non_empty(row.get("metadata_episode_no"), row.get("scan_episode_no"), payload.get("episode_no")),
			"path_mode": row.get("path_mode") or payload.get("path_mode") or "",
			"path_mode_label": row.get("path_mode_label") or payload.get("path_mode_label") or "",
			"media_family": row.get("media_family") or payload.get("media_family") or "",
			"provider_media_type": row.get("provider_media_type") or payload.get("provider_media_type") or "",
			"scan_status": row.get("scan_status") or ("matched" if row.get("provider_lookup_status") == "done" else "pending"),
			"result_count": 1 if row.get("provider_best_json") else 0,
			"recorded_at": row.get("recorded_at") or 0,
			"duration_seconds": row.get("duration_seconds") or 0,
			"size_bytes": row.get("size_bytes") or 0,
			"parse_error": row.get("parse_error") or "",
			"cast": self._decode_json_value(row.get("metadata_cast"), fallback=[]),
			"_payload": payload,
		}

	def _merge_browser_group(self, group, item, row):
		for key in ("overview", "description", "cover_url", "cover_path", "poster_url", "poster_path", "backdrop_url", "backdrop_path", "titlelogo_url", "logo_path", "genres", "released", "year", "provider", "vote_average", "vote_count"):
			if not group.get(key) and item.get(key):
				group[key] = item.get(key)
		if item.get("recorded_at", 0) and safe_int(item.get("recorded_at"), 0) > safe_int(group.get("recorded_at"), 0):
			group["recorded_at"] = item.get("recorded_at")
			if item.get("media_hash"):
				group["media_hash"] = item.get("media_hash")
				group["id"] = item.get("media_hash")
		variant = item.get("file_name") or ""
		if variant and variant not in group.setdefault("file_variants", []):
			group["file_variants"].append(variant)
		files = group.setdefault("files", [])
		if item.get("media_hash") and not any(entry.get("id") == item.get("media_hash") for entry in files):
			files.append({"id": item.get("media_hash"), "file_name": item.get("file_name") or "", "file_path": item.get("file_path") or ""})

	def _add_series_episode_to_group(self, group, item):
		if item.get("media_type") != "series":
			return
		season_no = safe_int(item.get("season_no"), 0)
		episode_no = safe_int(item.get("episode_no"), 0)
		if not season_no or not episode_no:
			season_no, episode_no = self._parse_season_episode_from_name(" ".join([item.get("file_name") or "", item.get("title") or "", item.get("file_path") or ""]))
		if not season_no or not episode_no:
			return
		season_map = group.setdefault("_season_map", {})
		season = season_map.setdefault(int(season_no), {"season_no": int(season_no), "episodes": [], "items": [], "files": []})
		if int(episode_no) not in season["episodes"]:
			season["episodes"].append(int(episode_no))
		episode_image_url = item.get("episode_cover_url") or item.get("episode_preview_url") or ""
		episode_image_path = self._image_file_path(item.get("episode_cover_file_path") or item.get("episode_cover_path") or "")
		entry = {
			"id": item.get("media_hash") or item.get("id") or item.get("file_path") or "",
			"media_hash": item.get("media_hash") or item.get("id") or "",
			"file_name": item.get("file_name") or "",
			"file_path": item.get("file_path") or "",
			"episode_no": int(episode_no),
			"title": item.get("title") or item.get("file_name") or "",
			"episode_name": item.get("title") or item.get("file_name") or "",
			"overview": item.get("overview") or "",
			"released": item.get("released") or "",
			"air_date": item.get("released") or "",
			"cover_url": episode_image_url,
			"episode_cover_url": episode_image_url,
			"episode_preview_url": episode_image_url,
			"episode_cover_path": episode_image_path,
			"episode_cover_file_path": episode_image_path,
			"preview_path": episode_image_path,
			"preview_url": episode_image_url,
			"series_cover_url": group.get("cover_url") or "",
			"backdrop_url": item.get("backdrop_url") or group.get("backdrop_url") or "",
		}
		if entry["id"] and not any(existing.get("id") == entry["id"] for existing in season["items"]):
			season["items"].append(entry)
		if item.get("file_name") and item.get("file_name") not in season["files"]:
			season["files"].append(item.get("file_name"))

	def _finalize_browser_group(self, group):
		season_map = group.pop("_season_map", {})
		seasons = []
		for season_no in sorted(season_map):
			season = season_map[season_no]
			season["episodes"] = sorted(season.get("episodes", []))
			season["items"] = sorted(season.get("items", []), key=lambda entry: safe_int(entry.get("episode_no"), 0))
			season["episode_count"] = len(season.get("items", [])) or len(season.get("episodes", []))
			seasons.append(season)
		if group.get("media_type") == "series":
			group["seasons"] = [{"season_no": item.get("season_no"), "episode_count": item.get("episode_count")} for item in seasons]
			group["season_count"] = len(seasons)
			group["episode_count"] = sum(safe_int(item.get("episode_count"), 0) for item in seasons)
		else:
			group["seasons"] = []
			group["season_count"] = 0
			group["episode_count"] = 0
		group["_full_seasons"] = seasons
		group["browser_key"] = group.get("browser_key") or group.get("id") or group.get("media_hash") or ""
		return group

	def _browser_init_group(self, item, key):
		group = dict(item)
		if group.get("media_type") == "series" and item.get("series_title"):
			group["title"] = item.get("series_title")
			group["name"] = item.get("series_title")
			# Series cards should use series artwork. Episode cards below keep their own stills.
			series_cover = item.get("series_cover_url") or item.get("series_poster_url") or ""
			series_cover_path = item.get("series_cover_path") or item.get("series_cover_file_path") or ""
			if series_cover:
				group["cover_url"] = series_cover
				group["poster_url"] = series_cover
			if series_cover_path:
				group["cover_path"] = series_cover_path
				group["poster_path"] = series_cover_path
			series_backdrop = item.get("series_backdrop_url") or ""
			if series_backdrop:
				group["backdrop_url"] = series_backdrop
				group["backdrop_path"] = series_backdrop
		group["id"] = item.get("media_hash") or key
		group["browser_key"] = key
		group["file_variants"] = []
		group["files"] = []
		return group

	def _browser_items_grouped(self, query="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		rows = self._browser_rows(query=query, media_type=media_type, year=year, genre=genre, cast=cast, letter=letter, include_pending=include_pending)
		groups = {}
		ordered = []
		for row in rows:
			item = self._row_to_browser_item(row)
			key = self._browser_group_key(item, row)
			item["browser_key"] = key
			if key not in groups:
				groups[key] = self._browser_init_group(item, key)
				ordered.append(groups[key])
			self._merge_browser_group(groups[key], item, row)
			self._add_series_episode_to_group(groups[key], item)
		items = [self._finalize_browser_group(group) for group in ordered]
		cast_filter = normalize_search_text(cast)
		if cast_filter:
			items = [item for item in items if cast_filter in normalize_search_text(" ".join([str(x) for x in item.get("cast", [])]))]
		return items

	def _browser_items_grouped_page(self, offset=0, limit=50, query="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		# Fast MediaBrowser path: only inspect a bounded row window. The old fallback scanned the
		# complete media table before returning the first page, which blocks initial rendering on
		# large libraries. Page offsets are approximate until the dedicated browser index is built,
		# but the GUI gets visible cards immediately and continues loading during scrolling.
		offset = max(0, safe_int(offset, 0))
		limit = max(1, min(500, safe_int(limit, 50)))
		cast_filter = normalize_search_text(cast)
		where_sql, params = self._browser_where_sql(query=query, media_type=media_type, year=year, genre=genre, cast=cast, letter=letter, include_pending=include_pending)
		row_window = max(limit * 12, limit + 80)
		row_window = min(1500, row_window)
		row_offset = max(0, offset * 3)
		groups = {}
		ordered = []
		with self.lock:
			with self._connect() as conn:
				sql = self._browser_select_sql(where_sql) + " LIMIT ? OFFSET ?"
				for row in conn.execute(sql, tuple(params + [row_window + 1, row_offset])):
					item = self._row_to_browser_item(row)
					key = self._browser_group_key(item, row)
					item["browser_key"] = key
					if key not in groups:
						if len(ordered) >= limit + 1:
							break
						groups[key] = self._browser_init_group(item, key)
						ordered.append(groups[key])
					self._merge_browser_group(groups[key], item, row)
					self._add_series_episode_to_group(groups[key], item)
		items = [self._finalize_browser_group(group) for group in ordered]
		if cast_filter:
			items = [item for item in items if cast_filter in normalize_search_text(" ".join([str(x) for x in item.get("cast", [])]))]
		has_more = len(items) > limit
		return items[:limit], has_more

	def _browser_facets_from_items(self, items):
		years = set()
		genres = set()
		casts = set()
		for item in items:
			if item.get("year"):
				years.add(str(item.get("year")))
			for part in str(item.get("genres") or "").replace("/", ",").split(","):
				part = part.strip()
				if part:
					genres.add(part)
			cast_list = item.get("cast") if isinstance(item.get("cast"), list) else []
			for cast in cast_list:
				if isinstance(cast, dict):
					name = cast.get("name") or cast.get("actor") or ""
				else:
					name = str(cast or "")
				if name:
					casts.add(name)
		return {
			"years": sorted(years, reverse=True),
			"genres": sorted(genres, key=lambda value: value.lower()),
			"casts": sorted(casts, key=lambda value: value.lower())[:500],
			"index_ready": True,
			"index_building": False,
			"people_index_ready": bool(casts),
		}

	def browser_status(self):
		status = self.status()
		counts = status.get("counts", {}) if isinstance(status, dict) else {}
		provider_counts = status.get("provider_counts", {}) if isinstance(status, dict) else {}
		visible = provider_counts.get("done", 0)
		pending = counts.get("e2mdb_media", 0) - visible if isinstance(counts.get("e2mdb_media", 0), int) else 0
		return {
			"success": True,
			"index_ready": True,
			"index_building": False,
			"people_index_ready": False,
			"database": status,
			"total": visible,
			"total_visible": visible,
			"total_raw": counts.get("e2mdb_media", 0),
			"hidden_pending": max(0, pending),
			"provider_counts": provider_counts,
			"recordings": counts.get("e2mdb_recordings", 0),
		}

	def list_browser(self, page=1, offset=None, limit=50, q="", media_type="all", year="", genre="", cast="", letter="", include_pending=False):
		limit = max(1, min(500, safe_int(limit, 50)))
		if offset is None:
			page = max(1, safe_int(page, 1))
			offset = (page - 1) * limit
		else:
			offset = max(0, safe_int(offset, 0))
		items, has_more = self._browser_items_grouped_page(offset=offset, limit=limit, query=q, media_type=media_type, year=year, genre=genre, cast=cast, letter=letter, include_pending=include_pending)
		# Do not calculate full-library facets here. The MediaBrowser list must stay lazy so the
		# first page can be displayed immediately. Detailed filter/facet indexes can be rebuilt
		# later as a separate backend index job.
		facets = self._browser_facets_from_items(items)
		for item in items:
			# Keep a compact local inventory preview for the visible MediaBrowser page.
			# The web UI can render series seasons/episodes immediately from this payload
			# instead of waiting for an additional browser_item/series_details round-trip.
			# This preserves lazy loading because it is only attached to the current page.
			if item.get("media_type") == "series":
				preview = self._series_inventory_from_group(item)
				item["local_inventory_preview"] = preview
			item.pop("_full_seasons", None)
			item.pop("_payload", None)
		estimated_total = offset + len(items) + (1 if has_more else 0)
		return {
			"success": True,
			"source": "sqlite-grouped-lazy-ready-only" if not truthy(include_pending) else "sqlite-grouped-lazy-all",
			"visibility": "ready_only" if not truthy(include_pending) else "all",
			"db_path": self.db_path,
			"items": items,
			"total": estimated_total,
			"total_is_estimate": True,
			"offset": offset,
			"limit": limit,
			"page": int(offset / limit) + 1,
			"has_more": has_more,
			"facets": facets,
			"facets_scope": "current_page",
			"index_ready": True,
			"index_building": False,
			"people_index_ready": facets.get("people_index_ready", False),
		}

	def _browser_group_from_rows(self, rows):
		groups = {}
		ordered = []
		for row in rows:
			item = self._row_to_browser_item(row)
			key = self._browser_group_key(item, row)
			item["browser_key"] = key
			if key not in groups:
				groups[key] = self._browser_init_group(item, key)
				ordered.append(groups[key])
			self._merge_browser_group(groups[key], item, row)
			self._add_series_episode_to_group(groups[key], item)
		if not ordered:
			return None
		return self._finalize_browser_group(ordered[0])

	def _rows_for_browser_group(self, item_id, include_pending=True):
		item_id = str(item_id or "").strip()
		if not item_id:
			return []
		where_ready, ready_params = self._browser_where_sql(include_pending=include_pending)
		base_select = self._browser_select_sql(where_ready)
		with self.lock:
			with self._connect() as conn:
				# Fast path for an exact media hash or file path. This is used by episode play buttons
				# and must not scan/group the complete library.
				exact_where = where_ready + (" AND " if where_ready else "WHERE ") + "(m.hash = ? OR m.file_path = ?)"
				exact = conn.execute(self._browser_select_sql(exact_where) + " LIMIT 1", tuple(ready_params + [item_id, item_id])).fetchall()
				if exact:
					item = self._row_to_browser_item(exact[0])
					key = self._browser_group_key(item, exact[0])
					if key and key != item_id:
						return self._rows_for_browser_group(key, include_pending=include_pending)
					return exact

				parts = item_id.split("|")
				if len(parts) >= 3:
					media_type = parts[0].strip().lower()
					provider = parts[1].strip().lower()
					provider_id = "|".join(parts[2:]).strip()
					where = where_ready + (" AND " if where_ready else "WHERE ") + "lower(COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, m.estimated_media_type, '')) = ? AND lower(COALESCE(m.metadata_provider, '')) = ? AND COALESCE(m.metadata_provider_ids, '') LIKE ?"
					rows = conn.execute(self._browser_select_sql(where), tuple(ready_params + [media_type, provider, f"%{provider_id}%"])).fetchall()
					if rows:
						return rows

				if len(parts) >= 2:
					media_type = parts[0].strip().lower()
					norm_title = "|".join(parts[1:]).strip()
					terms = [term for term in norm_title.split() if len(term) >= 2][:3]
					if not terms and norm_title:
						terms = [norm_title[:12]]
					clauses = []
					params = list(ready_params)
					if media_type in ("movie", "series"):
						clauses.append("lower(COALESCE(NULLIF(m.metadata_media_type, ''), m.provider_media_type, m.estimated_media_type, '')) = ?")
						params.append(media_type)
					for term in terms:
						clauses.append("(m.search_string_norm LIKE ? OR r.search_text_norm LIKE ? OR lower(COALESCE(m.series_title, '')) LIKE ? OR lower(COALESCE(m.provider_title, '')) LIKE ? OR lower(COALESCE(m.metadata_title, '')) LIKE ? OR lower(COALESCE(m.file_name, '')) LIKE ?)")
						needle = f"%{term.lower()}%"
						params.extend([needle, needle, needle, needle, needle, needle])
					where = where_ready
					if clauses:
						where += (" AND " if where else "WHERE ") + " AND ".join(clauses)
					candidates = conn.execute(self._browser_select_sql(where) + " LIMIT 1000", tuple(params)).fetchall()
					matched = []
					for row in candidates:
						item = self._row_to_browser_item(row)
						if self._browser_group_key(item, row) == item_id:
							matched.append(row)
					if matched:
						return matched
					# Fallback for older rows where the grouping key was produced from a slightly
					# different title source. Return the bounded candidate set instead of scanning all rows.
					if candidates:
						return candidates
		return []

	def _find_browser_group(self, item_id):
		rows = self._rows_for_browser_group(item_id, include_pending=True)
		return self._browser_group_from_rows(rows)

	def get_browser_item(self, item_id):
		item = self._find_browser_group(item_id)
		if not item:
			return {"success": False, "error": "browser item not found"}
		public_item = dict(item)
		public_item.pop("_full_seasons", None)
		public_item.pop("_payload", None)
		media = {
			"id": public_item.get("media_hash"),
			"hash": public_item.get("media_hash"),
			"file_path": public_item.get("file_path"),
			"file_name": public_item.get("file_name"),
			"search_string": public_item.get("title"),
			"scan_status": public_item.get("scan_status"),
		}
		data = dict(public_item)
		result = dict(public_item)
		return {
			"success": True,
			"source": "sqlite-grouped",
			"media_hash": public_item.get("media_hash"),
			"media_type": public_item.get("media_type"),
			"provider": public_item.get("provider"),
			"media": media,
			"data": data,
			"result": result,
			"raw": public_item,
			"local_inventory": self._series_inventory_from_group(item) if public_item.get("media_type") == "series" else {},
		}

	def get_playback_target(self, item_id):
		item_id = str(item_id or "").strip()
		if not item_id:
			return {"success": False, "error": "playback item not found"}
		# Fast path: episode play buttons pass the concrete media hash. Do not build a
		# complete browser group for playback, otherwise the web command can feel delayed.
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("""
					SELECT hash, file_path, file_name, metadata_title, search_string
					FROM e2mdb_media
					WHERE hash = ? OR file_path = ?
					LIMIT 1
				""", (item_id, item_id)).fetchone()
				if row and row["file_path"]:
					return {
						"success": True,
						"id": row["hash"] or item_id,
						"file_path": row["file_path"] or "",
						"file_name": row["file_name"] or "",
						"title": row["metadata_title"] or row["search_string"] or row["file_name"] or "",
					}

		group = self._find_browser_group(item_id)
		if not group:
			return {"success": False, "error": "playback item not found"}
		# Prefer the exact episode/file that was clicked. For a grouped series card,
		# fall back to the first local file so the GUI bridge can still start playback.
		for season in group.get("_full_seasons", []) if isinstance(group.get("_full_seasons"), list) else []:
			for ep in season.get("items", []) if isinstance(season, dict) else []:
				if item_id in (str(ep.get("id") or ""), str(ep.get("media_hash") or ""), str(ep.get("file_path") or "")):
					return {"success": True, "id": item_id, "file_path": ep.get("file_path") or "", "file_name": ep.get("file_name") or "", "title": ep.get("title") or ep.get("episode_name") or group.get("title") or ""}
		file_path = group.get("file_path") or ""
		file_name = group.get("file_name") or ""
		if not file_path:
			for season in group.get("_full_seasons", []) if isinstance(group.get("_full_seasons"), list) else []:
				items = season.get("items", []) if isinstance(season, dict) else []
				if items:
					ep = items[0]
					file_path = ep.get("file_path") or ""
					file_name = ep.get("file_name") or ""
					break
		if not file_path:
			return {"success": False, "error": "playback target has no file path"}
		return {"success": True, "id": item_id, "file_path": file_path, "file_name": file_name, "title": group.get("title") or file_name}

	def _artwork_candidate_info(self, value):
		value = str(value or "").strip()
		info = {"raw": value, "url": self._web_image_url(value), "kind": "empty", "exists": False, "size": 0, "reason": "empty"}
		if not value:
			return info
		lower = value.lower()
		if lower.startswith(("http://", "https://", "data:")):
			info.update({"kind": "remote", "reason": "remote-url"})
			return info
		if value.startswith("/api/"):
			info.update({"kind": "api", "reason": "api-url"})
			return info
		if value.startswith("/"):
			info["kind"] = "local"
			try:
				if isfile(value):
					info["exists"] = True
					info["size"] = stat(value).st_size
					info["reason"] = "ok"
				else:
					info["reason"] = "file-missing"
			except Exception as err:
				info["reason"] = f"stat-error: {str(err)}"
			return info
		info.update({"kind": "relative", "reason": "relative-path"})
		return info

	def debug_artwork(self, limit=30, q=""):
		limit = max(1, min(200, safe_int(limit, 30)))
		q = str(q or "")
		where_sql, params = self._browser_where_sql(query=q)
		samples = []
		counts = {"rows_checked": 0, "with_cover_value": 0, "with_local_cover_file": 0, "with_remote_cover_url": 0, "missing_local_cover_file": 0}
		with self.lock:
			with self._connect() as conn:
				rows = conn.execute(self._browser_select_sql(where_sql) + " LIMIT ?", tuple(params + [limit])).fetchall()
				for row in rows:
					counts["rows_checked"] += 1
					item = self._row_to_browser_item(row)
					cover_raw = item.get("cover_file_path") or item.get("cover_url") or item.get("poster_url") or ""
					cover_info = self._artwork_candidate_info(cover_raw)
					if cover_raw:
						counts["with_cover_value"] += 1
					if cover_info.get("kind") == "local" and cover_info.get("exists"):
						counts["with_local_cover_file"] += 1
					elif cover_info.get("kind") == "local" and not cover_info.get("exists"):
						counts["missing_local_cover_file"] += 1
					elif cover_info.get("kind") == "remote":
						counts["with_remote_cover_url"] += 1
					samples.append({
						"media_hash": item.get("media_hash"),
						"title": item.get("title"),
						"media_type": item.get("media_type"),
						"provider_status": item.get("provider_lookup_status"),
						"cover": cover_info,
						"backdrop": self._artwork_candidate_info(item.get("backdrop_file_path") or item.get("backdrop_url") or ""),
						"db_fields": {
							"metadata_cover_path": row["metadata_cover_path"],
							"metadata_image_path": row["metadata_image_path"],
							"metadata_series_cover_path": row["metadata_series_cover_path"],
							"metadata_episode_image_path": row["metadata_episode_image_path"],
							"artwork_poster_path": row["artwork_poster_path"],
							"artwork_episode_path": row["artwork_episode_path"],
							"artwork_series_poster_path": row["artwork_series_poster_path"],
							"artwork_backdrop_path": row["artwork_backdrop_path"],
						},
					})
		image_files = []
		roots = []
		try:
			settings = self.settings if isinstance(self.settings, dict) else {}
			database = settings.get("database", {}) if isinstance(settings.get("database", {}), dict) else {}
			cache = settings.get("cache", {}) if isinstance(settings.get("cache", {}), dict) else {}
			for root in (database.get("root"), cache.get("root"), dirname(self.db_path), DEFAULT_DATABASE_ROOT, "/media/usb/e2MDB"):
				root = str(root or "").rstrip("/")
				if root and root not in roots and exists(root):
					roots.append(root)
		except Exception:
			pass
		for root in roots:
			try:
				for current, dirs, files in walk(root):
					if len(image_files) >= 50:
						break
					for name in files:
						if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
							path = join(current, name)
							try:
								size = stat(path).st_size
							except Exception:
								size = 0
							image_files.append({"path": path, "size": size, "url": self._web_image_url(path)})
							if len(image_files) >= 50:
								break
			except Exception:
				continue
		return {"success": True, "db_path": self.db_path, "counts": counts, "samples": samples, "image_roots": roots, "image_files": image_files}

	def debug_performance(self, limit=24):
		limit = max(1, min(200, safe_int(limit, 24)))
		start = time()
		status = self.status()
		status_ms = int((time() - start) * 1000)
		start = time()
		browser = self.list_browser(page=1, limit=limit)
		browser_ms = int((time() - start) * 1000)
		return {
			"success": True,
			"db_path": self.db_path,
			"status_ms": status_ms,
			"browser_first_page_ms": browser_ms,
			"browser_source": browser.get("source"),
			"items": len(browser.get("items", [])),
			"has_more": browser.get("has_more", False),
			"counts": status.get("counts", {}) if isinstance(status, dict) else {},
		}

	def list_editor(self, page=1, limit=30, q="", status="all", media_type="all", letter=""):
		payload = self.list_browser(page=page, limit=limit, q=q, media_type=media_type, letter=letter)
		results = []
		for item in payload.get("items", []):
			if status and status != "all" and str(item.get("scan_status") or "") != str(status):
				continue
			results.append({
				"id": item.get("media_hash"),
				"browser_key": item.get("browser_key"),
				"title": item.get("title"),
				"file_name": item.get("file_name"),
				"file_path": item.get("file_path"),
				"scan_status": item.get("scan_status"),
				"estimated_type": item.get("media_type"),
				"genres": item.get("genres"),
				"result_count": item.get("result_count", 0),
			})
		return {
			"success": True,
			"results": results,
			"page": payload.get("page", page),
			"limit": payload.get("limit", limit),
			"has_more": payload.get("has_more", False),
			"total": payload.get("total", 0),
		}

	def get_editor_item(self, item_id):
		item = self.get_browser_item(item_id)
		if not item.get("success"):
			return item
		provider_results = []
		with self.lock:
			with self._connect() as conn:
				rows = conn.execute("""
					SELECT provider, media_type, title, year, match_score, payload_json
					FROM e2mdb_provider_matches
					WHERE media_hash = ?
					ORDER BY is_best DESC, match_score DESC, id ASC
				""", (item.get("media_hash"),)).fetchall()
		for row in rows:
			payload = self._decode_json_value(row["payload_json"], fallback={})
			if not isinstance(payload, dict):
				payload = {}
			payload.setdefault("provider", row["provider"])
			payload.setdefault("media_type", row["media_type"])
			payload.setdefault("title", row["title"])
			payload.setdefault("year", row["year"])
			payload.setdefault("_match_score", row["match_score"])
			provider_results.append(payload)
		return {
			"success": True,
			"media": item.get("media", {}),
			"data": item.get("data", {}),
			"result": item.get("result", {}),
			"results": {"success": True, "results": provider_results},
			"scan_info": item.get("raw", {}),
		}

	def _series_inventory_from_group(self, group):
		group = group if isinstance(group, dict) else {}
		seasons = group.get("_full_seasons") if isinstance(group.get("_full_seasons"), list) else []
		files = []
		for season in seasons:
			for item in season.get("items", []):
				files.append({"id": item.get("id"), "media_hash": item.get("id"), "file_name": item.get("file_name"), "file_path": item.get("file_path")})
		return {
			"series_title": group.get("series_title") or group.get("title") or "",
			"season_count": len(seasons),
			"episode_count": sum(safe_int(season.get("episode_count"), 0) for season in seasons),
			"seasons": seasons,
			"files": files,
			"browser_key": group.get("browser_key") or "",
			"cast": group.get("cast", []),
		}

	def get_series_details(self, item_id):
		group = self._find_browser_group(item_id)
		if not group:
			return {"success": False, "error": "series not found", "details": {"seasons": []}, "local_inventory": {"seasons": [], "files": [], "season_count": 0, "episode_count": 0}}
		inventory = self._series_inventory_from_group(group)
		return {
			"success": True,
			"error": "",
			"details": {
				"name": group.get("title") or inventory.get("series_title") or "",
				"title": group.get("title") or inventory.get("series_title") or "",
				"overview": group.get("overview") or "",
				"seasons": [{"season_no": s.get("season_no"), "episode_count": s.get("episode_count")} for s in inventory.get("seasons", [])],
				"cast": group.get("cast") if isinstance(group.get("cast"), list) else [],
			},
			"episode_index": {},
			"provider": group.get("provider") or "",
			"provider_id": self._decode_provider_id(group.get("provider"), ""),
			"local_inventory": inventory,
		}

	def get_season_details(self, item_id, season_no):
		group = self._find_browser_group(item_id)
		wanted = safe_int(season_no, 0)
		if not group or not wanted:
			return {"success": True, "error": "", "details": {"season_no": str(season_no or ""), "episodes": []}, "season_no": str(season_no or "")}
		inventory = self._series_inventory_from_group(group)
		episodes = []
		for season in inventory.get("seasons", []):
			if safe_int(season.get("season_no"), 0) != wanted:
				continue
			for ep in season.get("items", []):
				episode_image_url = ep.get("episode_cover_url") or ep.get("episode_preview_url") or ep.get("preview_url") or ""
				episode_image_path = self._image_file_path(ep.get("episode_cover_file_path") or ep.get("episode_cover_path") or ep.get("preview_path") or "")
				episodes.append({
					"id": ep.get("id") or ep.get("media_hash") or ep.get("file_path") or "",
					"media_hash": ep.get("media_hash") or ep.get("id") or "",
					"file_path": ep.get("file_path") or "",
					"episode_no": ep.get("episode_no") or "",
					"episode_name": ep.get("episode_name") or ep.get("title") or ep.get("file_name") or "",
					"overview": ep.get("overview") or "",
					"released": ep.get("released") or ep.get("air_date") or "",
					"cover_url": episode_image_url,
					"episode_cover_url": episode_image_url,
					"episode_preview_url": episode_image_url,
					"episode_cover_path": episode_image_path,
					"episode_cover_file_path": episode_image_path,
					"preview_url": episode_image_url,
					"preview_path": episode_image_path,
					"series_cover_url": group.get("cover_url") or "",
					"backdrop_url": ep.get("backdrop_url") or group.get("backdrop_url") or "",
					"file_name": ep.get("file_name") or "",
				})
		return {"success": True, "error": "", "details": {"season_no": str(season_no or ""), "episodes": episodes}, "season_no": str(season_no or "")}

	def provider_state(self):
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("SELECT value_json FROM e2mdb_backend_state WHERE key = 'provider_enrichment'").fetchone()
				counts = {}
				for status_name in ("done", "error", "pending", ""):
					try:
						if status_name:
							count_row = conn.execute("SELECT COUNT(*) AS total FROM e2mdb_media WHERE provider_lookup_status = ?", (status_name,)).fetchone()
						else:
							count_row = conn.execute("SELECT COUNT(*) AS total FROM e2mdb_media WHERE provider_lookup_status IS NULL OR provider_lookup_status = ''").fetchone()
						counts[status_name or "missing"] = int(count_row["total"] if count_row else 0)
					except Exception:
						counts[status_name or "missing"] = -1
		try:
			state = loads(row["value_json"] or "{}") if row else {}
		except Exception:
			state = {}
		return {"success": True, "state": state, "counts": counts}

	def schema(self):
		self.ensure_schema()
		with self.lock:
			with self._connect() as conn:
				tables = {}
				for table in ("e2mdb_media", "e2mdb_recordings", "e2mdb_provider_matches", "e2mdb_backend_state"):
					try:
						tables[table] = [dict(row) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
					except Exception as err:
						tables[table] = [{"error": str(err)}]
		return {"success": True, "db_path": self.db_path, "tables": tables}

	def _live_epg_canonical_source_key(self, source_type, service_ref, begin_time, event_end, title_norm):
		identity = f"{str(source_type or "epg")}|{str(service_ref or "")}|{safe_int(begin_time, 0)}|{safe_int(event_end, 0)}|{normalize_search_text(title_norm or "")}"
		return md5(identity.encode("utf-8")).hexdigest()

	def live_epg_duplicates(self, limit=100, query="", fix=False):
		"""Report or merge duplicate Live/EPG rows that describe the same natural event.

		The natural key intentionally ignores Enigma2 event_id and queue reason.  The same
		visible event can be queued by ServiceList, EventView, InfoBar and prefill with
		different transient event_id values; those must converge to one source_key.
		"""
		limit = max(1, min(500, safe_int(limit, 100)))
		query = str(query or "").strip()
		fix = bool(fix)
		where = ["source_type = 'epg'", "service_ref != ''", "begin_time > 0", "title != ''"]
		params = []
		if query:
			like = f"%{query}%"
			where.append("(title LIKE ? OR search_title LIKE ? OR metadata_title LIKE ? OR service_ref LIKE ? OR source_key LIKE ?)")
			params.extend([like, like, like, like, like])
		where_sql = " WHERE " + " AND ".join(where)
		groups = []
		fixed = {"groups": 0, "events_removed": 0, "keys_canonicalized": 0, "queue_removed": 0, "asset_links_moved": 0}
		with self.lock:
			with self._connect() as conn:
				group_rows = conn.execute("""
					SELECT source_type, service_ref, begin_time, event_end, COALESCE(NULLIF(title_norm, ''), lower(title)) AS title_norm,
						COUNT(*) AS total
					FROM e2mdb_epg_events
					%s
					GROUP BY source_type, service_ref, begin_time, event_end, COALESCE(NULLIF(title_norm, ''), lower(title))
					HAVING COUNT(*) > 1
					ORDER BY MAX(updated_at) DESC
					LIMIT ?
				""" % where_sql, tuple(params + [limit])).fetchall()
				for group in group_rows:
					rows = conn.execute("""
						SELECT * FROM e2mdb_epg_events
						WHERE source_type = ? AND service_ref = ? AND begin_time = ? AND event_end = ?
							AND COALESCE(NULLIF(title_norm, ''), lower(title)) = ?
						ORDER BY
							CASE WHEN status = 'done' THEN 0 WHEN status = 'matched' THEN 1 WHEN status = 'pending' THEN 2 ELSE 3 END,
							CASE WHEN COALESCE(metadata_backdrop_path, '') != '' THEN 0 WHEN COALESCE(metadata_image_path, '') != '' THEN 1 ELSE 2 END,
							updated_at DESC
					""", (group["source_type"], group["service_ref"], group["begin_time"], group["event_end"], group["title_norm"])).fetchall()
					items = [dict(row) for row in rows]
					canonical = self._live_epg_canonical_source_key(group["source_type"], group["service_ref"], group["begin_time"], group["event_end"], group["title_norm"])
					keeper = None
					for item in items:
						if item.get("source_key") == canonical:
							keeper = item
							break
					if not keeper and items:
						keeper = items[0]
					duplicate_keys = [item.get("source_key") for item in items if keeper and item.get("id") != keeper.get("id")]
					entry = {
						"canonical_source_key": canonical,
						"keeper_source_key": keeper.get("source_key") if keeper else "",
						"source_type": group["source_type"],
						"service_ref": group["service_ref"],
						"begin_time": int(group["begin_time"] or 0),
						"event_end": int(group["event_end"] or 0),
						"title_norm": group["title_norm"],
						"count": int(group["total"] or 0),
						"duplicate_source_keys": duplicate_keys,
						"items": [{
							"id": item.get("id"),
							"source_key": item.get("source_key"),
							"title": item.get("title"),
							"status": item.get("status"),
							"metadata_provider": item.get("metadata_provider"),
							"metadata_title": item.get("metadata_title"),
							"metadata_cover_path": item.get("metadata_cover_path"),
							"metadata_backdrop_path": item.get("metadata_backdrop_path"),
							"metadata_image_path": item.get("metadata_image_path"),
							"updated_at": item.get("updated_at"),
						} for item in items],
					}
					if fix and keeper:
						keeper_id = int(keeper.get("id") or 0)
						keeper_key = str(keeper.get("source_key") or "")
						# Move the best row to the new canonical source_key when possible.
						if keeper_key != canonical:
							target = conn.execute("SELECT id FROM e2mdb_epg_events WHERE source_key = ?", (canonical,)).fetchone()
							if not target:
								conn.execute("UPDATE e2mdb_epg_events SET source_key = ?, virtual_path = ?, updated_at = ? WHERE id = ?", (canonical, f"live://{canonical}", int(time()), keeper_id))
								old_queue = conn.execute("SELECT source_key FROM e2mdb_fetch_queue WHERE source_key = ?", (keeper_key,)).fetchone()
								new_queue = conn.execute("SELECT source_key FROM e2mdb_fetch_queue WHERE source_key = ?", (canonical,)).fetchone()
								if old_queue and not new_queue:
									conn.execute("UPDATE e2mdb_fetch_queue SET source_key = ?, updated_at = ? WHERE source_key = ?", (canonical, int(time()), keeper_key))
								elif old_queue and new_queue:
									conn.execute("DELETE FROM e2mdb_fetch_queue WHERE source_key = ?", (keeper_key,))
									fixed["queue_removed"] += 1
								keeper_key = canonical
								entry["keeper_source_key"] = canonical
								fixed["keys_canonicalized"] += 1
						# Merge duplicate event rows into the keeper.
						for item in items:
							item_id = int(item.get("id") or 0)
							item_key = str(item.get("source_key") or "")
							if not item_id or item_id == keeper_id:
								continue
							asset_rows = conn.execute("SELECT asset_id, confidence, provider, created_at FROM e2mdb_epg_event_asset_map WHERE epg_event_id = ?", (item_id,)).fetchall()
							for asset in asset_rows:
								conn.execute("INSERT OR IGNORE INTO e2mdb_epg_event_asset_map (epg_event_id, asset_id, confidence, provider, created_at) VALUES (?, ?, ?, ?, ?)", (keeper_id, asset["asset_id"], asset["confidence"], asset["provider"], asset["created_at"]))
								fixed["asset_links_moved"] += 1
							conn.execute("DELETE FROM e2mdb_epg_event_asset_map WHERE epg_event_id = ?", (item_id,))
							conn.execute("DELETE FROM e2mdb_epg_events WHERE id = ?", (item_id,))
							qcur = conn.execute("DELETE FROM e2mdb_fetch_queue WHERE source_key = ?", (item_key,))
							fixed["queue_removed"] += int(qcur.rowcount or 0)
							fixed["events_removed"] += 1
						fixed["groups"] += 1
					groups.append(entry)
				if fix:
					conn.commit()
		return {"success": True, "fix": fix, "limit": limit, "query": query, "groups_total": len(groups), "fixed": fixed, "groups": groups}

	def live_epg_queue_status(self):
		"""Return compact v16 Live/EPG worker queue diagnostics."""
		now = int(time())
		live_epg = self.settings.get("live_epg", {}) if isinstance(self.settings.get("live_epg", {}), dict) else {}
		preempt_min_priority = max(1, min(99, safe_int(live_epg.get("preempt_min_priority", live_epg.get("daemon_preempt_min_priority", 80)), 80)))
		with self.lock:
			with self._connect() as conn:
				try:
					rows = conn.execute("SELECT state, COUNT(*) AS total FROM e2mdb_fetch_queue GROUP BY state ORDER BY state").fetchall()
				except Exception as err:
					return {"success": False, "error": str(err), "queue": {}}
				counts = {str(row["state"] or ""): int(row["total"] or 0) for row in rows}
				total = sum(counts.values())
				due_row = conn.execute("""
					SELECT
						COUNT(*) AS due_pending,
						SUM(CASE WHEN priority >= ? THEN 1 ELSE 0 END) AS due_high_priority
					FROM e2mdb_fetch_queue
					WHERE state = 'pending'
						AND (not_before IS NULL OR not_before <= ?)
				""", (preempt_min_priority, now)).fetchone()
				next_due_row = conn.execute("""
					SELECT MIN(not_before) AS next_due
					FROM e2mdb_fetch_queue
					WHERE state = 'pending' AND COALESCE(not_before, 0) > ?
				""", (now,)).fetchone()
				stale_running_row = conn.execute("""
					SELECT COUNT(*) AS stale_running
					FROM e2mdb_fetch_queue
					WHERE state = 'running' AND COALESCE(updated_at, 0) < ?
				""", (now - 900,)).fetchone()
				next_row = conn.execute("""
					SELECT source_key, source_type, service_ref, title, search_title, short_desc, extended_desc, begin_time,
						event_end, priority, reason, state, attempts, not_before,
						last_error, created_at, updated_at
					FROM e2mdb_fetch_queue
					WHERE state IN ('pending', 'running')
					ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,
						priority DESC, not_before ASC, updated_at ASC
					LIMIT 1
				""").fetchone()
				return {
					"success": True,
					"queue": {
						"mode": "v16_live_epg_fetch_queue",
						"total": total,
						"counts": counts,
						"pending": counts.get("pending", 0),
						"due_pending": int(due_row["due_pending"] or 0) if due_row else 0,
						"eligible_pending": int(due_row["due_pending"] or 0) if due_row else 0,
						"due_high_priority": int(due_row["due_high_priority"] or 0) if due_row else 0,
						"due_high_priority_min": preempt_min_priority,
						"next_due": int(next_due_row["next_due"] or 0) if next_due_row else 0,
						"running": counts.get("running", 0),
						"stale_running": int(stale_running_row["stale_running"] or 0) if stale_running_row else 0,
						"failed": counts.get("failed", 0),
						"done": counts.get("done", 0),
						"next": dict(next_row) if next_row else None,
						"note": "This is the existing v16 Live/EPG queue. Enigma2 produces entries; the backend daemon can process them."
					}
				}

	def live_epg_queue_list(self, limit=50, state="all", query=""):
		limit = max(1, min(500, safe_int(limit, 50)))
		state = str(state or "all").strip().lower()
		query = str(query or "").strip()
		where = []
		params = []
		if state and state != "all":
			where.append("state = ?")
			params.append(state)
		if query:
			like = f"%{query}%"
			where.append("(title LIKE ? OR search_title LIKE ? OR service_ref LIKE ? OR source_key LIKE ? OR reason LIKE ? OR last_error LIKE ?)")
			params.extend([like, like, like, like, like, like])
		where_sql = " WHERE " + " AND ".join(where) if where else ""
		with self.lock:
			with self._connect() as conn:
				rows = conn.execute("""
					SELECT source_key, source_type, service_ref, title, search_title, short_desc, extended_desc, begin_time,
						event_end, priority, reason, state, attempts, not_before,
						last_error, created_at, updated_at
					FROM e2mdb_fetch_queue
					%s
					ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
						priority DESC, not_before ASC, updated_at DESC
					LIMIT ?
				""" % where_sql, tuple(params + [limit])).fetchall()
				count_row = conn.execute(f"SELECT COUNT(*) AS total FROM e2mdb_fetch_queue{where_sql}", tuple(params)).fetchone()
				return {
					"success": True,
					"total": int(count_row["total"] if count_row else 0),
					"limit": limit,
					"state": state,
					"query": query,
					"items": [dict(row) for row in rows],
				}

	def live_epg_queue_reset_running(self):
		"""Reset interrupted Live/EPG worker rows after a GUI crash/restart."""
		now = int(time())
		with self.lock:
			with self._connect() as conn:
				cur = conn.execute("""
					UPDATE e2mdb_fetch_queue
					SET state = 'pending', updated_at = ?, last_error = 'reset-running-by-backend'
					WHERE state = 'running'
				""", (now,))
				conn.commit()
				return {"success": True, "reset": int(cur.rowcount or 0)}

	def live_epg_queue_retry_no_match(self, active_only=True, priority=90):
		"""Requeue cached Live/EPG no-match rows for a deliberate provider retry.

		The display row must leave its terminal ``no_match`` state as part of the
		same transaction. Otherwise Enigma2 keeps treating the negative cache as
		valid even though the worker queue was reopened.
		"""
		now = int(time())
		priority = max(1, min(99, safe_int(priority, 90)))
		active_only = truthy(active_only)
		where = "status = 'no_match'"
		params = []
		if active_only:
			where += " AND (event_end IS NULL OR event_end = 0 OR event_end > ?)"
			params.append(now)
		with self.lock:
			with self._connect() as conn:
				rows = conn.execute("""
					SELECT source_key, source_type, service_ref, title, search_title,
						short_desc, extended_desc, begin_time, event_end
					FROM e2mdb_epg_events
					WHERE %s
					ORDER BY begin_time ASC, updated_at ASC
				""" % where, tuple(params)).fetchall()
				for row in rows:
					conn.execute("""
						INSERT INTO e2mdb_fetch_queue (
							source_key, source_type, service_ref, title, search_title,
							short_desc, extended_desc, begin_time, event_end, priority,
							reason, state, attempts, not_before, last_error, created_at, updated_at
						) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual-no-match-retry', 'pending', 0, 0, '', ?, ?)
						ON CONFLICT(source_key) DO UPDATE SET
							source_type = excluded.source_type,
							service_ref = excluded.service_ref,
							title = excluded.title,
							search_title = excluded.search_title,
							short_desc = excluded.short_desc,
							extended_desc = excluded.extended_desc,
							begin_time = excluded.begin_time,
							event_end = excluded.event_end,
							priority = MAX(COALESCE(e2mdb_fetch_queue.priority, 0), excluded.priority),
							reason = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.reason ELSE excluded.reason END,
							state = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN 'running' ELSE 'pending' END,
							attempts = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.attempts ELSE 0 END,
							not_before = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.not_before ELSE 0 END,
							last_error = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.last_error ELSE '' END,
							updated_at = CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.updated_at ELSE excluded.updated_at END
					""", (
						row["source_key"], row["source_type"], row["service_ref"], row["title"],
						row["search_title"], row["short_desc"], row["extended_desc"],
						safe_int(row["begin_time"], 0), safe_int(row["event_end"], 0),
						priority, now, now,
					))
				source_keys = [str(row["source_key"] or "") for row in rows if row["source_key"]]
				if source_keys:
					conn.executemany("""
						UPDATE e2mdb_epg_events
						SET status = 'unknown', confidence = 0.0, expires_at = 0, updated_at = ?
						WHERE source_key = ? AND status = 'no_match'
					""", [(now, source_key) for source_key in source_keys])
				conn.commit()
				return {
					"success": True,
					"matched": len(rows),
					"requeued": len(source_keys),
					"active_only": active_only,
					"priority": priority,
				}

	def live_epg_queue_clear(self, mode="failed"):
		"""Delete Live/EPG queue rows owned by the backend.

		The GUI must not write to the SQLite queue directly.  Keep the
		semantics small and explicit so the worker queue screen can remove
		finished, failed/error, prefill or all queue rows without needing SQL.
		"""
		mode = str(mode or "failed").strip().lower().replace("-", "_")
		if mode in ("done", "finished", "completed"):
			where = "state IN ('done','no_match','ignored','short_skipped','ended_skipped')"
			label = "finished"
		elif mode in ("failed", "error", "errors"):
			# Worker exceptions are normally retried as pending with last_error set.
			# Treat these rows as failed for the GUI cleanup button too.
			where = "state IN ('failed','error') OR COALESCE(last_error, '') != ''"
			label = "failed"
		elif mode in ("prefill", "prefill_queue"):
			where = "reason LIKE 'prefill%'"
			label = "prefill"
		elif mode in ("all", "queue"):
			where = "1=1"
			label = "all"
		else:
			return {"success": False, "error": f"unknown queue clear mode: {mode}", "removed": 0}
		with self.lock:
			with self._connect() as conn:
				cur = conn.execute("DELETE FROM e2mdb_fetch_queue WHERE " + where)
				conn.commit()
				return {"success": True, "mode": mode, "label": label, "removed": int(cur.rowcount or 0)}

	def live_epg_queue_next_item(self, now=None, min_priority=None):
		"""Claim the next pending Live/EPG queue item for daemon-side processing.

		When min_priority is given, only items at or above that priority are
		claimed. This keeps ad-hoc/current-screen requests able to jump ahead of
		long media refresh jobs without draining low-priority prefill rows.
		"""
		now = safe_int(now, int(time()))
		where_extra = ""
		params = [now]
		if min_priority is not None:
			where_extra = " AND priority >= ?"
			params.append(safe_int(min_priority, 0))
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("""
					SELECT source_key, source_type, service_ref, title, search_title, short_desc, extended_desc, begin_time,
						event_end, priority, reason, state, attempts, not_before,
						last_error, created_at, updated_at
					FROM e2mdb_fetch_queue
					WHERE state = 'pending'
						AND (not_before IS NULL OR not_before <= ?)
						%s
					ORDER BY priority DESC,
						CASE WHEN priority >= 90 THEN updated_at ELSE 0 END DESC,
						CASE WHEN priority >= 90 THEN rowid ELSE 0 END DESC,
						not_before ASC, updated_at ASC
					LIMIT 1
				""" % where_extra, tuple(params)).fetchone()
				if not row:
					return None
				attempts = safe_int(row["attempts"], 0) + 1
				conn.execute("""
					UPDATE e2mdb_fetch_queue
					SET state = 'running', attempts = ?, updated_at = ?, last_error = ''
					WHERE source_key = ?
				""", (attempts, now, row["source_key"]))
				conn.commit()
				item = dict(row)
				item["attempts"] = attempts
				item["state"] = "running"
				item["updated_at"] = now
				return item

	def live_epg_queue_update_state(self, source_key, state, attempts=None, not_before=None, last_error=""):
		"""Update one Live/EPG queue row from daemon-side worker code."""
		source_key = str(source_key or "").strip()
		if not source_key:
			return {"success": False, "error": "missing source_key"}
		now = int(time())
		sets = ["state = ?", "updated_at = ?"]
		params = [str(state or "pending"), now]
		if attempts is not None:
			sets.append("attempts = ?")
			params.append(safe_int(attempts, 0))
		if not_before is not None:
			sets.append("not_before = ?")
			params.append(safe_int(not_before, 0))
		sets.append("last_error = ?")
		params.append(str(last_error or ""))
		params.append(source_key)
		with self.lock:
			with self._connect() as conn:
				cur = conn.execute(f"UPDATE e2mdb_fetch_queue SET {", ".join(sets)} WHERE source_key = ?", tuple(params))
				conn.commit()
				return {"success": True, "updated": int(cur.rowcount or 0), "source_key": source_key, "state": state}

	def live_epg_queue_release_running(self, source_key, attempts=None, not_before=None, last_error="worker-interrupted"):
		"""Return only a still-claimed row to pending.

		The conditional state guard prevents recovery code from overwriting a row
		that was already completed successfully.
		"""
		source_key = str(source_key or "").strip()
		if not source_key:
			return {"success": False, "error": "missing source_key", "updated": 0}
		now = int(time())
		retry_at = safe_int(not_before, now + 60)
		params = [now, retry_at, str(last_error or "worker-interrupted")]
		attempt_sql = ""
		if attempts is not None:
			attempt_sql = ", attempts = ?"
			params.append(safe_int(attempts, 0))
		params.append(source_key)
		with self.lock:
			with self._connect() as conn:
				cur = conn.execute("""
					UPDATE e2mdb_fetch_queue
					SET state = 'pending', updated_at = ?, not_before = ?, last_error = ?%s
					WHERE source_key = ? AND state = 'running'
				""" % attempt_sql, tuple(params))
				conn.commit()
				return {"success": True, "updated": int(cur.rowcount or 0), "source_key": source_key, "state": "pending"}

	def _provider_best_id(self, provider_name, best):
		best = best if isinstance(best, dict) else {}
		provider_name = str(provider_name or best.get("provider") or "").strip().lower()
		for key in ("provider_id", "id", "tmdb_id", "tvdb_id", "imdb_id"):
			value = str(best.get(key) or "").strip()
			if value:
				return value
		provider_ids = best.get("provider_ids") if isinstance(best.get("provider_ids"), dict) else {}
		for key in (provider_name, "tmdb", "tvdb", "imdb", "omdb", "tvmaze"):
			value = str(provider_ids.get(key) or "").strip()
			if value:
				return value
		return ""

	def _is_portrait_artwork_ref(self, value):
		try:
			text = str(value or "").lower()
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

	def _is_landscape_artwork_ref(self, value):
		try:
			text = str(value or "").lower()
		except Exception:
			return False
		if not text or self._is_portrait_artwork_ref(text):
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

	def _first_landscape_artwork(self, *values):
		for value in values:
			value = str(value or "").strip()
			if value and self._is_landscape_artwork_ref(value):
				return value
		return ""

	def _first_portrait_artwork(self, *values):
		for value in values:
			value = str(value or "").strip()
			if not value:
				continue
			if self._is_landscape_artwork_ref(value):
				continue
			if self._is_portrait_artwork_ref(value):
				return value
			# Remote provider poster URLs do not always contain a descriptive filename.
			# Accept them only when they came from an explicit poster/cover field.
			return value
		return ""

	def _live_epg_cover_candidates(self, artwork, best):
		artwork = artwork if isinstance(artwork, dict) else {}
		best = best if isinstance(best, dict) else {}
		candidates = []
		for value in (artwork.get("series_poster_path"), artwork.get("poster_path"), best.get("series_cover_path"), best.get("series_cover_url"), best.get("series_poster_path"), best.get("series_poster_url")):
			if value:
				candidates.append(value)
		cover_src = str(best.get("cover_src") or "").strip().lower()
		poster_src = str(best.get("poster_src") or "").strip().lower()
		if cover_src != "episode":
			for value in (best.get("cover_path"), best.get("cover_url")):
				if value:
					candidates.append(value)
		if poster_src != "episode":
			for value in (best.get("poster_path"), best.get("poster_url")):
				if value:
					candidates.append(value)
		return candidates

	def _live_epg_final_metadata(self, queue_item, provider_result):
		queue_item = queue_item if isinstance(queue_item, dict) else {}
		provider_result = provider_result if isinstance(provider_result, dict) else {}
		best = provider_result.get("best") if isinstance(provider_result.get("best"), dict) else {}
		artwork = provider_result.get("artwork") if isinstance(provider_result.get("artwork"), dict) else {}
		provider_ids = best.get("provider_ids") if isinstance(best.get("provider_ids"), dict) else {}
		title = self._first_non_empty(best.get("title"), best.get("name"), best.get("episode_name"), queue_item.get("search_title"), queue_item.get("title"))
		subtitle = self._first_non_empty(best.get("episode_name"), best.get("tagline"), best.get("series_title"), best.get("show_title"))
		cover_path = self._first_portrait_artwork(*self._live_epg_cover_candidates(artwork, best))
		image_src = str(best.get("image_src") or best.get("image_provider") or "").strip().lower()
		image_path = self._first_landscape_artwork(
			artwork.get("image_path"), artwork.get("preview_path"), artwork.get("still_path"), artwork.get("episode_path"),
			best.get("episode_image_path"), best.get("episode_image_url"), best.get("episode_still_url"),
			best.get("still_path"), best.get("still_url"), best.get("preview_path"), best.get("preview_url")
		)
		if not image_path and image_src in ("episode", "fernsehserien", "wikimedia", "tvspielfilm", "still", "preview"):
			image_path = self._first_landscape_artwork(best.get("image_path"), best.get("image_url"))
		backdrop_path = self._first_landscape_artwork(artwork.get("backdrop_path"), artwork.get("series_backdrop_path"), best.get("backdrop_path"), best.get("backdrop_url"), best.get("fanart_url"), best.get("series_backdrop_path"), best.get("series_backdrop_url"))
		logo_path = self._first_non_empty(artwork.get("logo_path"), best.get("titlelogo_path"), best.get("logo_path"), best.get("titlelogo_url"), best.get("logo_url"), best.get("clearlogo_url"))
		released = str(best.get("released") or best.get("releaseDate") or best.get("firstAired") or "")
		return {
			"json_path": str(provider_result.get("json_path") or ""),
			"title": title,
			"episode_name": str(best.get("episode_name") or ""),
			"tagline": str(best.get("tagline") or ""),
			"overview": str(best.get("overview") or best.get("description") or ""),
			"genres": self._json(best.get("genres") or []),
			"provider": str(best.get("provider") or ""),
			"provider_ids": self._json(provider_ids),
			"provider_id": self._provider_best_id(best.get("provider"), best),
			"media_type": str(best.get("media_type") or provider_result.get("media_type") or ""),
			"year": str(best.get("year") or provider_result.get("year") or (released[:4] if len(released) >= 4 and released[:4].isdigit() else "")),
			"runtime": str(best.get("runtime") or ""),
			"rating": str(best.get("vote_average") or best.get("rating") or ""),
			"vote_count": str(best.get("vote_count") or ""),
			"cover_path": str(cover_path or ""),
			"backdrop_path": str(backdrop_path or ""),
			"logo_path": str(logo_path or ""),
			"image_path": str(image_path or ""),
			"released": released,
			"countries": self._json(best.get("countries") or []),
			"age_rating": str(best.get("age_rating") or ""),
			"cast": self._json(best.get("cast") or []),
			"crew": self._json(best.get("crew") or []),
			"season_no": str(best.get("season_no") or ""),
			"episode_no": str(best.get("episode_no") or ""),
			"best": best,
			"artwork": artwork,
		}

	def _live_epg_upsert_display_result(self, conn, queue_item, provider_result):
		"""Write daemon Live/EPG results into the v16 display cache tables."""
		queue_item = queue_item if isinstance(queue_item, dict) else {}
		provider_result = provider_result if isinstance(provider_result, dict) else {}
		source_key = str(queue_item.get("source_key") or "").strip()
		if not source_key:
			return {"success": False, "error": "missing source_key"}
		now = int(time())
		title = str(queue_item.get("title") or queue_item.get("search_title") or "")
		search_title = str(queue_item.get("search_title") or title)
		begin_time = safe_int(queue_item.get("begin_time"), 0)
		event_end = safe_int(queue_item.get("event_end"), 0)
		duration = max(0, event_end - begin_time) if begin_time and event_end else 0
		status = "done" if provider_result.get("success") else "no_match"
		live_epg_settings = self.settings.get("live_epg", {}) if isinstance(self.settings.get("live_epg", {}), dict) else {}
		if status == "no_match":
			no_match_hours = max(1, min(72, safe_int(live_epg_settings.get("no_match_retry_hours"), 1)))
			expires_at = now + no_match_hours * 3600
		else:
			retention_days = max(1, min(30, safe_int(live_epg_settings.get("retention_days"), 3)))
			expires_at = (event_end if event_end else now) + retention_days * 86400
		confidence = 1.0 if provider_result.get("success") else 0.0
		metadata = self._live_epg_final_metadata(queue_item, provider_result)
		conn.execute("""
			INSERT INTO e2mdb_epg_events (
				source_key, source_type, service_ref, service_name, event_id, title, title_norm, search_title,
				short_desc, extended_desc, begin_time, duration, event_end, virtual_path, json_path,
				status, confidence, last_access, expires_at, pinned, created_at, updated_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(source_key) DO UPDATE SET
				source_type = excluded.source_type,
				service_ref = excluded.service_ref,
				service_name = excluded.service_name,
				event_id = excluded.event_id,
				title = excluded.title,
				title_norm = excluded.title_norm,
				search_title = excluded.search_title,
				short_desc = excluded.short_desc,
				extended_desc = excluded.extended_desc,
				begin_time = excluded.begin_time,
				duration = excluded.duration,
				event_end = excluded.event_end,
				json_path = excluded.json_path,
				status = excluded.status,
				confidence = excluded.confidence,
				last_access = excluded.last_access,
				expires_at = excluded.expires_at,
				updated_at = excluded.updated_at
		""", (
			source_key, str(queue_item.get("source_type") or "epg"), str(queue_item.get("service_ref") or ""), str(queue_item.get("service_name") or ""),
			safe_int(queue_item.get("event_id"), 0), title, normalize_search_text(title), search_title,
			str(queue_item.get("short_desc") or ""), str(queue_item.get("extended_desc") or ""),
			begin_time, duration, event_end, f"live://{source_key}", metadata.get("json_path", ""), status, confidence, now, expires_at, 0, now, now
		))
		conn.execute("""
			UPDATE e2mdb_epg_events
			SET metadata_title = ?, metadata_subtitle = ?, metadata_overview = ?, metadata_genres = ?,
				metadata_provider = ?, metadata_provider_ids = ?, metadata_media_type = ?, metadata_year = ?, metadata_runtime = ?,
				metadata_rating = ?, metadata_vote_count = ?, metadata_cover_path = ?, metadata_backdrop_path = ?, metadata_logo_path = ?,
				metadata_image_path = ?, metadata_released = ?, metadata_countries = ?, metadata_age_rating = ?,
				metadata_cast = ?, metadata_crew = ?, metadata_season_no = ?, metadata_episode_no = ?, updated_at = ?
			WHERE source_key = ?
		""", (
			metadata.get("title", ""), metadata.get("episode_name") or metadata.get("tagline") or "", metadata.get("overview", ""), metadata.get("genres", ""),
			metadata.get("provider", ""), metadata.get("provider_ids", "{}"), metadata.get("media_type", ""), metadata.get("year", ""), metadata.get("runtime", ""),
			metadata.get("rating", ""), metadata.get("vote_count", ""), metadata.get("cover_path", ""), metadata.get("backdrop_path", ""), metadata.get("logo_path", ""),
			metadata.get("image_path", ""), metadata.get("released", ""), metadata.get("countries", "[]"), metadata.get("age_rating", ""),
			metadata.get("cast", "[]"), metadata.get("crew", "[]"), metadata.get("season_no", ""), metadata.get("episode_no", ""), now, source_key
		))
		asset_id = None
		if provider_result.get("success") and metadata.get("provider") and metadata.get("provider_id"):
			asset_key = f"{metadata.get("media_type") or "multi"}|{metadata.get("provider")}|{metadata.get("provider_id")}"
			artwork = metadata.get("artwork") if isinstance(metadata.get("artwork"), dict) else {}
			best = metadata.get("best") if isinstance(metadata.get("best"), dict) else {}
			# Do not persist provider artwork URLs/provenance in SQLite.
			# Raw provider payloads are only kept as provider_result.json when debug is enabled.
			conn.execute("""
				INSERT INTO e2mdb_provider_assets (
					asset_key, provider, provider_id, media_type, title, original_title, episode_name, tagline,
					genres, overview, year, json_path, cover_path, backdrop_path, logo_path, image_path,
					last_seen, expires_at, created_at, updated_at
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(asset_key) DO UPDATE SET
					media_type = excluded.media_type,
					title = excluded.title,
					episode_name = excluded.episode_name,
					tagline = excluded.tagline,
					genres = excluded.genres,
					overview = excluded.overview,
					year = excluded.year,
					json_path = excluded.json_path,
					cover_path = excluded.cover_path,
					backdrop_path = excluded.backdrop_path,
					logo_path = excluded.logo_path,
					image_path = excluded.image_path,
					last_seen = excluded.last_seen,
					expires_at = excluded.expires_at,
					updated_at = excluded.updated_at
			""", (
				asset_key, metadata.get("provider", ""), metadata.get("provider_id", ""), metadata.get("media_type", ""), metadata.get("title", ""),
				str(best.get("original_title") or ""), metadata.get("episode_name", ""), metadata.get("tagline", ""),
				metadata.get("genres", ""), metadata.get("overview", ""), safe_int(metadata.get("year"), 0), metadata.get("json_path", ""),
				metadata.get("cover_path", ""), metadata.get("backdrop_path", ""), metadata.get("logo_path", ""), metadata.get("image_path", ""),
				now, expires_at, now, now
			))
			row = conn.execute("SELECT id FROM e2mdb_provider_assets WHERE asset_key = ?", (asset_key,)).fetchone()
			asset_id = int(row["id"] if row and "id" in row.keys() else row[0]) if row else None
			if asset_id:
				event_row = conn.execute("SELECT id FROM e2mdb_epg_events WHERE source_key = ?", (source_key,)).fetchone()
				event_id = int(event_row["id"] if event_row and "id" in event_row.keys() else event_row[0]) if event_row else 0
				if event_id:
					conn.execute("""
						INSERT OR REPLACE INTO e2mdb_epg_event_asset_map
						(epg_event_id, asset_id, confidence, provider, created_at)
						VALUES (?, ?, ?, ?, ?)
					""", (event_id, asset_id, confidence, metadata.get("provider", ""), now))
		return {"success": True, "source_key": source_key, "status": status, "asset_id": asset_id}

	def live_epg_queue_upsert_backend_result(self, queue_item, provider_result):
		"""Store a daemon-side Live/EPG provider result without making it a MediaBrowser row.

		The normal recording provider path writes into e2mdb_media and also sets browser_ready=1.
		Live/EPG rows are transient lookup cache rows, not library items, so keep browser_ready=0.
		"""
		queue_item = queue_item if isinstance(queue_item, dict) else {}
		provider_result = provider_result if isinstance(provider_result, dict) else {}
		source_key = str(queue_item.get("source_key") or "").strip()
		if not source_key:
			return {"success": False, "error": "missing source_key"}
		now = int(time())
		title = str(queue_item.get("search_title") or queue_item.get("title") or "").strip()
		file_path = f"live://{source_key}"
		search_norm = normalize_search_text(" ".join([title, str(queue_item.get("service_ref") or ""), str(queue_item.get("reason") or "")]))
		with self.lock:
			with self._connect() as conn:
				conn.execute("""
					INSERT INTO e2mdb_media (
						hash, file_path, file_name, search_string, search_string_norm,
						source_type, provider_media_type, provider_title, metadata_title,
						browser_ready, provider_lookup_status, updated_at
					) VALUES (?, ?, ?, ?, ?, 'live_epg', 'multi', ?, ?, '0', 'pending', CURRENT_TIMESTAMP)
					ON CONFLICT(hash) DO UPDATE SET
						file_path = excluded.file_path,
						file_name = excluded.file_name,
						search_string = excluded.search_string,
						search_string_norm = excluded.search_string_norm,
						source_type = 'live_epg',
						provider_title = excluded.provider_title,
						browser_ready = '0',
						updated_at = CURRENT_TIMESTAMP
				""", (source_key, file_path, title, title, search_norm, title, title))
				conn.commit()
		# Reuse the normal provider storage for matches/artwork/cache fields.
		item = {
			"id": source_key,
			"path": file_path,
			"title": title,
			"provider_title": title,
			"provider_media_type": "multi",
			"source_type": "live_epg",
		}
		result = self.upsert_provider_result(item, provider_result)
		# Keep Live/EPG cache rows out of the MediaBrowser even after upsert_provider_result().
		with self.lock:
			with self._connect() as conn:
				conn.execute("UPDATE e2mdb_media SET browser_ready = '0', source_type = 'live_epg' WHERE hash = ?", (source_key,))
				display_result = self._live_epg_upsert_display_result(conn, queue_item, provider_result)
				self.set_state(conn, "live_epg_worker", {
					"version": 1,
					"updated": now,
					"last_source_key": source_key,
					"last_title": title,
					"provider_success": bool(provider_result.get("success")),
					"provider_error": str(provider_result.get("error") or ""),
					"display_cache": display_result,
				})
				conn.commit()
		return result

	def _live_epg_classify_artwork_path(self, path):
		text = str(path or "").strip().lower()
		if not text:
			return "empty"
		portrait_markers = (
			"/poster", "poster.", "poster_", "_poster", "series_poster",
			"/cover", "cover.", "cover_", "_cover", "/covers/",
		)
		landscape_markers = (
			"/backdrop", "backdrop.", "backdrop_", "_backdrop",
			"/fanart", "fanart.", "fanart_", "_fanart",
			"/image", "image.", "image_", "_image",
			"/preview", "preview.", "preview_", "_preview",
			"/still", "still.", "still_", "_still",
			"/episode", "episode.", "episode_", "_episode",
			"series_backdrop", "background", "landscape",
		)
		if any(marker in text for marker in portrait_markers):
			return "portrait"
		if any(marker in text for marker in landscape_markers):
			return "landscape"
		return "unknown"

	def _live_epg_path_exists(self, path):
		try:
			from os.path import isfile
			return bool(path and isfile(str(path)))
		except Exception:
			return False

	def _live_epg_artwork_diagnostics(self, event_row, asset_rows):
		event_row = event_row if isinstance(event_row, dict) else dict(event_row or {})
		asset_rows = [dict(asset) for asset in (asset_rows or [])]
		fields = []
		for field, expected in (("metadata_cover_path", "portrait"), ("metadata_backdrop_path", "landscape"), ("metadata_image_path", "landscape")):
			path = str(event_row.get(field) or "")
			classification = self._live_epg_classify_artwork_path(path)
			fields.append({
				"field": field,
				"path": path,
				"exists": self._live_epg_path_exists(path),
				"classification": classification,
				"expected": expected,
				"valid_for_service_list": field in ("metadata_backdrop_path", "metadata_image_path") and classification == "landscape",
				"valid_for_cover_widget": field == "metadata_cover_path" and classification in ("portrait", "unknown"),
			})
		asset_debug = []
		for asset in asset_rows:
			asset_debug.append({
				"asset_key": asset.get("asset_key") or "",
				"provider": asset.get("provider") or "",
				"provider_id": asset.get("provider_id") or "",
				"media_type": asset.get("media_type") or "",
				"title": asset.get("title") or "",
				"json_path": asset.get("json_path") or "",
				"cover_path": asset.get("cover_path") or "",
				"cover_classification": self._live_epg_classify_artwork_path(asset.get("cover_path") or ""),
				"backdrop_path": asset.get("backdrop_path") or "",
				"backdrop_classification": self._live_epg_classify_artwork_path(asset.get("backdrop_path") or ""),
				"logo_path": asset.get("logo_path") or "",
				"image_path": asset.get("image_path") or "",
				"image_classification": self._live_epg_classify_artwork_path(asset.get("image_path") or ""),
				"confidence": asset.get("confidence") or 0,
				"link_provider": asset.get("link_provider") or "",
			})
		return {
			"source_key": event_row.get("source_key") or "",
			"provider": event_row.get("metadata_provider") or "",
			"provider_ids": event_row.get("metadata_provider_ids") or "",
			"media_type": event_row.get("metadata_media_type") or "",
			"title": event_row.get("metadata_title") or event_row.get("title") or "",
			"fields": fields,
			"assets": asset_debug,
		}

	def live_epg_result(self, source_key):
		source_key = str(source_key or "").strip()
		if not source_key:
			return {"success": False, "error": "missing source_key"}
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("SELECT * FROM e2mdb_epg_events WHERE source_key = ? LIMIT 1", (source_key,)).fetchone()
				if not row:
					return {"success": False, "error": "not found", "source_key": source_key}
				assets = conn.execute("""
					SELECT a.*, m.confidence, m.provider AS link_provider
					FROM e2mdb_epg_events e
					JOIN e2mdb_epg_event_asset_map m ON m.epg_event_id = e.id
					JOIN e2mdb_provider_assets a ON a.id = m.asset_id
					WHERE e.source_key = ?
					ORDER BY m.confidence DESC, a.updated_at DESC
				""", (source_key,)).fetchall()
		event = dict(row)
		assets_list = [self._sanitize_provider_asset_row(dict(asset)) for asset in assets]
		return {
			"success": True,
			"event": event,
			"assets": assets_list,
			"artwork_diagnostics": self._live_epg_artwork_diagnostics(event, assets_list),
		}

	def _sanitize_provider_asset_row(self, asset):
		asset = asset if isinstance(asset, dict) else {}
		for key in (
			"cover_url", "backdrop_url", "logo_url", "image_url", "episode_url",
			"series_poster_url", "series_backdrop_url", "artwork_json"
		):
			asset.pop(key, None)
		return asset

	def _debug_json_enabled(self):
		try:
			return bool(self.settings.get("debug") or self.settings.get("debug_log") or self.settings.get("debug_json"))
		except Exception:
			return False

	def _connect_status(self):
		conn = None
		if isfile(self.db_path):
			try:
				conn = connect(f"file:{quote(self.db_path)}?mode=ro", uri=True, timeout=0.25)
			except Exception:
				conn = connect(self.db_path, timeout=0.25)
		else:
			conn = connect(self.db_path, timeout=0.25)
		conn.row_factory = Row
		try:
			conn.execute("PRAGMA busy_timeout=250")
		except Exception:
			pass
		try:
			conn.execute("PRAGMA query_only=ON")
		except Exception:
			pass
		return conn

	def _read_cpu_times(self):
		try:
			with open("/proc/stat", "r") as handle:
				line = handle.readline().strip()
			parts = line.split()
			if not parts or parts[0] != "cpu":
				return None
			values = [safe_int(value, 0) for value in parts[1:]]
			if len(values) < 4:
				return None
			idle = values[3] + (values[4] if len(values) > 4 else 0)
			total = sum(values)
			return (int(total), int(idle), int(time()))
		except Exception:
			return None

	def _system_load_status(self):
		load1 = load5 = load15 = 0.0
		try:
			with open("/proc/loadavg", "r") as handle:
				parts = handle.read().strip().split()
			if len(parts) >= 3:
				load1 = float(parts[0])
				load5 = float(parts[1])
				load15 = float(parts[2])
		except Exception:
			pass
		try:
			cores = int(cpu_count() or 1)
		except Exception:
			cores = 1
		if cores <= 0:
			cores = 1
		cpu_percent = None
		sample = self._read_cpu_times()
		previous = getattr(self, "_last_cpu_sample", None)
		try:
			if sample and previous:
				total_delta = int(sample[0]) - int(previous[0])
				idle_delta = int(sample[1]) - int(previous[1])
				if total_delta > 0:
					cpu_percent = max(0.0, min(100.0, (float(total_delta - idle_delta) * 100.0) / float(total_delta)))
		except Exception:
			cpu_percent = None
		if sample:
			self._last_cpu_sample = sample
		load_percent = 0.0
		try:
			load_percent = max(0.0, (float(load1) * 100.0) / float(cores))
		except Exception:
			load_percent = 0.0
		return {
			"cpu_percent": round(cpu_percent, 1) if cpu_percent is not None else None,
			"load1": round(load1, 2),
			"load5": round(load5, 2),
			"load15": round(load15, 2),
			"load_percent": round(load_percent, 1),
			"cores": cores,
		}

	def _database_file_status(self):
		size_bytes = 0
		sidecar_size_bytes = 0
		try:
			size_bytes = stat(self.db_path).st_size if isfile(self.db_path) else 0
		except Exception:
			size_bytes = 0
		for suffix in ("-wal", "-shm", "-journal"):
			try:
				sidecar_size_bytes += stat(self.db_path + suffix).st_size if isfile(self.db_path + suffix) else 0
			except Exception:
				pass
		return size_bytes, sidecar_size_bytes

	def status(self):
		size_bytes, sidecar_size_bytes = self._database_file_status()
		base = {
			"success": True,
			"db_path": self.db_path,
			"exists": isfile(self.db_path),
			"size_bytes": size_bytes,
			"sidecar_size_bytes": sidecar_size_bytes,
			"total_size_bytes": size_bytes + sidecar_size_bytes,
			"page_size": 0,
			"page_count": 0,
			"freelist_count": 0,
			"freelist_bytes": 0,
			"journal_mode": "",
			"busy_timeout_ms": self.busy_timeout_ms,
			"counts": {},
			"provider_counts": {},
			"inventory": {},
			"system": self._system_load_status(),
			"busy": False,
		}
		if not base["exists"]:
			return base
		if not self.lock.acquire(False):
			base["busy"] = True
			return base
		try:
			with self._connect_status() as conn:
				def row_int(row, key, default=0):
					try:
						return int(row[key] if row and row[key] is not None else default)
					except Exception:
						return default

				counts = {}
				for table in ("e2mdb_media", "e2mdb_recordings", "e2mdb_provider_matches", "e2mdb_backend_state"):
					try:
						row = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
						counts[table] = row_int(row, "total", 0)
					except Exception:
						counts[table] = -1

				provider_counts = {"browser_ready": -1, "browser_pending": -1, "done": -1, "error": -1, "pending": -1, "missing": -1}
				inventory = {
					"recordings_total": -1,
					"media_total": -1,
					"ts_recordings": -1,
					"media_files": -1,
					"local_episodes": -1,
					"bytes_total": 0,
					"movies": -1,
					"series": -1,
					"unknown": -1,
					"browser_ready": -1,
					"browser_pending": -1,
					"provider_done": -1,
					"provider_pending": -1,
					"provider_missing": -1,
					"provider_errors": -1,
					"provider_matches_total": counts.get("e2mdb_provider_matches", -1),
					"provider_best_matches": -1,
					"missing_metadata": -1,
					"media_with_artwork": -1,
					"missing_artwork": -1,
					"live_epg_total": -1,
					"live_epg_active": -1,
					"live_epg_expired": -1,
					"queue_total": -1,
				}

				media_type_expr = self._media_type_expression()
				try:
					media_row = conn.execute("""
						SELECT
							COUNT(*) AS media_total,
							SUM(CASE WHEN COALESCE(browser_ready, '0') = '1' THEN 1 ELSE 0 END) AS browser_ready,
							SUM(CASE WHEN COALESCE(browser_ready, '0') != '1' THEN 1 ELSE 0 END) AS browser_pending,
							SUM(CASE WHEN provider_lookup_status = 'done' THEN 1 ELSE 0 END) AS provider_done,
							SUM(CASE WHEN provider_lookup_status = 'pending' THEN 1 ELSE 0 END) AS provider_pending,
							SUM(CASE WHEN provider_lookup_status = 'error' THEN 1 ELSE 0 END) AS provider_errors,
							SUM(CASE WHEN provider_lookup_status IS NULL OR provider_lookup_status = '' THEN 1 ELSE 0 END) AS provider_missing,
							SUM(CASE WHEN %s IN ('movie', 'film') THEN 1 ELSE 0 END) AS movies,
							SUM(CASE WHEN (%s IN ('series', 'tv', 'tv_series', 'anime_series', 'manga_series') OR LOWER(COALESCE(media_family, '')) IN ('series', 'anime', 'manga')) THEN 1 ELSE 0 END) AS series,
							SUM(CASE WHEN %s IN ('', 'missing', 'multi', 'unknown') THEN 1 ELSE 0 END) AS unknown,
							SUM(CASE WHEN (COALESCE(metadata_title, '') = '' OR provider_lookup_status IS NULL OR provider_lookup_status = '' OR provider_lookup_status = 'error') THEN 1 ELSE 0 END) AS missing_metadata,
							SUM(CASE WHEN (COALESCE(metadata_cover_path, '') != '' OR COALESCE(metadata_backdrop_path, '') != '' OR COALESCE(metadata_logo_path, '') != '' OR COALESCE(metadata_image_path, '') != '' OR COALESCE(artwork_poster_path, '') != '' OR COALESCE(artwork_backdrop_path, '') != '' OR COALESCE(artwork_logo_path, '') != '' OR COALESCE(artwork_series_poster_path, '') != '' OR COALESCE(artwork_series_backdrop_path, '') != '' OR COALESCE(artwork_episode_path, '') != '' OR COALESCE(metadata_series_cover_path, '') != '' OR COALESCE(metadata_episode_image_path, '') != '') THEN 1 ELSE 0 END) AS media_with_artwork,
							SUM(CASE WHEN COALESCE(browser_ready, '0') = '1' AND NOT (COALESCE(metadata_cover_path, '') != '' OR COALESCE(metadata_backdrop_path, '') != '' OR COALESCE(metadata_logo_path, '') != '' OR COALESCE(metadata_image_path, '') != '' OR COALESCE(artwork_poster_path, '') != '' OR COALESCE(artwork_backdrop_path, '') != '' OR COALESCE(artwork_logo_path, '') != '' OR COALESCE(artwork_series_poster_path, '') != '' OR COALESCE(artwork_series_backdrop_path, '') != '' OR COALESCE(artwork_episode_path, '') != '' OR COALESCE(metadata_series_cover_path, '') != '' OR COALESCE(metadata_episode_image_path, '') != '') THEN 1 ELSE 0 END) AS missing_artwork
						FROM e2mdb_media
						WHERE COALESCE(source_type, '') != 'live_epg'
					""" % (media_type_expr, media_type_expr, media_type_expr)).fetchone()
					for key in ("media_total", "browser_ready", "browser_pending", "provider_done", "provider_pending", "provider_errors", "provider_missing", "movies", "series", "unknown", "missing_metadata", "media_with_artwork", "missing_artwork"):
						inventory[key] = row_int(media_row, key, 0)
					provider_counts["browser_ready"] = inventory.get("browser_ready", 0)
					provider_counts["browser_pending"] = inventory.get("browser_pending", 0)
					provider_counts["done"] = inventory.get("provider_done", 0)
					provider_counts["pending"] = inventory.get("provider_pending", 0)
					provider_counts["error"] = inventory.get("provider_errors", 0)
					provider_counts["missing"] = inventory.get("provider_missing", 0)
				except Exception:
					pass

				try:
					rec_row = conn.execute("""
						SELECT
							COUNT(*) AS recordings_total,
							SUM(CASE WHEN source_type = 'recording' OR extension = '.ts' THEN 1 ELSE 0 END) AS ts_recordings,
							SUM(CASE WHEN source_type = 'media_file' AND extension != '.ts' THEN 1 ELSE 0 END) AS media_files,
							SUM(CASE WHEN CAST(COALESCE(NULLIF(season_no, ''), '0') AS INTEGER) > 0 OR CAST(COALESCE(NULLIF(episode_no, ''), '0') AS INTEGER) > 0 THEN 1 ELSE 0 END) AS local_episodes,
							COALESCE(SUM(size_bytes), 0) AS bytes_total
						FROM e2mdb_recordings
					""").fetchone()
					for key in ("recordings_total", "ts_recordings", "media_files", "local_episodes", "bytes_total"):
						inventory[key] = row_int(rec_row, key, 0)
				except Exception:
					pass

				try:
					row = conn.execute("SELECT COUNT(*) AS total FROM e2mdb_provider_matches WHERE is_best = 1").fetchone()
					inventory["provider_best_matches"] = row_int(row, "total", 0)
				except Exception:
					pass

				now = int(time())
				try:
					epg_row = conn.execute("""
						SELECT
							COUNT(*) AS live_epg_total,
							SUM(CASE WHEN expires_at = 0 OR expires_at >= ? THEN 1 ELSE 0 END) AS live_epg_active,
							SUM(CASE WHEN pinned = 0 AND expires_at > 0 AND expires_at < ? THEN 1 ELSE 0 END) AS live_epg_expired
						FROM e2mdb_epg_events
					""", (now, now)).fetchone()
					for key in ("live_epg_total", "live_epg_active", "live_epg_expired"):
						inventory[key] = row_int(epg_row, key, 0)
				except Exception:
					pass

				try:
					row = conn.execute("SELECT COUNT(*) AS total FROM e2mdb_fetch_queue").fetchone()
					inventory["queue_total"] = row_int(row, "total", 0)
				except Exception:
					pass

				try:
					base["journal_mode"] = str(conn.execute("PRAGMA journal_mode").fetchone()[0] or "")
				except Exception:
					base["journal_mode"] = ""
				try:
					base["page_size"] = int(conn.execute("PRAGMA page_size").fetchone()[0] or 0)
				except Exception:
					base["page_size"] = 0
				try:
					base["page_count"] = int(conn.execute("PRAGMA page_count").fetchone()[0] or 0)
				except Exception:
					base["page_count"] = 0
				try:
					base["freelist_count"] = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
				except Exception:
					base["freelist_count"] = 0
				base["freelist_bytes"] = int(base.get("page_size") or 0) * int(base.get("freelist_count") or 0)
				base["counts"] = counts
				base["provider_counts"] = provider_counts
				base["inventory"] = inventory
		except Exception as err:
			base["success"] = False
			base["error"] = str(err)
		finally:
			try:
				self.lock.release()
			except Exception:
				pass
		return base

	def _count_table_rows(self, conn, table, where="", params=None):
		params = params or []
		try:
			row = conn.execute(f"SELECT COUNT(*) AS total FROM {table} {where}", tuple(params)).fetchone()
			return int(row["total"] if row else 0)
		except Exception:
			return -1

	def _sum_table_integer(self, conn, table, column, where="", params=None):
		params = params or []
		try:
			row = conn.execute(f"SELECT COALESCE(SUM({column}), 0) AS total FROM {table} {where}", tuple(params)).fetchone()
			return int(row["total"] if row else 0)
		except Exception:
			return 0

	def _group_counts(self, conn, table, column, where="", params=None, limit=20):
		params = params or []
		result = {}
		try:
			rows = conn.execute("""
				SELECT COALESCE(NULLIF(%s, ''), 'missing') AS key_value, COUNT(*) AS total
				FROM %s
				%s
				GROUP BY key_value
				ORDER BY total DESC, key_value COLLATE NOCASE ASC
				LIMIT ?
			""" % (column, table, where), tuple(params + [int(limit)])).fetchall()
			for row in rows:
				result[str(row["key_value"] or "missing")] = int(row["total"] or 0)
		except Exception:
			pass
		return result

	def _backend_state_value(self, conn, key):
		try:
			row = conn.execute("SELECT value_json, updated_at FROM e2mdb_backend_state WHERE key = ?", (str(key or ""),)).fetchone()
			if not row:
				return {}
			try:
				value = loads(row["value_json"] or "{}")
			except Exception:
				value = {}
			if isinstance(value, dict):
				value["state_updated_at"] = int(row["updated_at"] or 0)
				return value
		except Exception:
			pass
		return {}

	def _media_type_expression(self):
		return "LOWER(COALESCE(NULLIF(metadata_media_type, ''), NULLIF(provider_media_type, ''), NULLIF(estimated_media_type, ''), NULLIF(media_family, ''), 'missing'))"

	def _media_artwork_where(self):
		return """
			WHERE COALESCE(source_type, '') != 'live_epg'
			AND (
				COALESCE(metadata_cover_path, '') != '' OR COALESCE(metadata_backdrop_path, '') != '' OR
				COALESCE(metadata_logo_path, '') != '' OR COALESCE(metadata_image_path, '') != '' OR
				COALESCE(artwork_poster_path, '') != '' OR COALESCE(artwork_backdrop_path, '') != '' OR
				COALESCE(artwork_logo_path, '') != '' OR COALESCE(artwork_series_poster_path, '') != '' OR
				COALESCE(artwork_series_backdrop_path, '') != '' OR COALESCE(artwork_episode_path, '') != '' OR
				COALESCE(metadata_series_cover_path, '') != '' OR COALESCE(metadata_episode_image_path, '') != ''
			)
		"""

	def _count_cache_files_for_media_status(self, subdirs):
		cache_base = self._cache_root()
		result = {"cache_root": cache_base, "files": 0, "folders": 0, "bytes": 0, "dirs": {}}
		for sub_path in subdirs:
			path = join(cache_base, sub_path)
			files, folders, bytes_total = self._count_tree_for_cleanup(path)
			result["dirs"][sub_path] = {"exists": isdir(path), "files": files, "folders": folders, "bytes": bytes_total}
			result["files"] += files
			result["folders"] += folders
			result["bytes"] += bytes_total
		return result

	def media_status(self, scan_state=None, provider_state=None, job_history=None, current_job=None, include_cache=True):
		self.ensure_schema()
		"""Return a high-level inventory/status view for real e2MDB media content.

		This is intentionally different from cache_cleanup_status(): cache status is a
		storage/cleanup view, while media_status tells whether scan/enrich actually
		populated the SQLite inventory and provider/artwork metadata.
		"""
		now = int(time())
		scan_state = scan_state if isinstance(scan_state, dict) else {}
		provider_state = provider_state if isinstance(provider_state, dict) else {}
		job_history = job_history if isinstance(job_history, dict) else {"version": 1, "items": []}
		current_job = current_job if isinstance(current_job, dict) else None
		media_type_expr = self._media_type_expression()
		with self.lock:
			with self._connect() as conn:
				recordings_total = self._count_table_rows(conn, "e2mdb_recordings")
				media_total = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg'")
				provider_matches_total = self._count_table_rows(conn, "e2mdb_provider_matches")
				provider_best_matches = self._count_table_rows(conn, "e2mdb_provider_matches", "WHERE is_best = 1")
				provider_assets_total = self._count_table_rows(conn, "e2mdb_provider_assets")
				live_epg_total = self._count_table_rows(conn, "e2mdb_epg_events")
				live_epg_active = self._count_table_rows(conn, "e2mdb_epg_events", "WHERE expires_at = 0 OR expires_at >= ?", [now])
				live_epg_expired = self._count_table_rows(conn, "e2mdb_epg_events", "WHERE pinned = 0 AND expires_at > 0 AND expires_at < ?", [now])
				fetch_queue_total = self._count_table_rows(conn, "e2mdb_fetch_queue")
				browser_ready = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND COALESCE(browser_ready, '0') = '1'")
				browser_pending = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND COALESCE(browser_ready, '0') != '1'")
				provider_done = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND provider_lookup_status = 'done'")
				provider_error = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND provider_lookup_status = 'error'")
				provider_pending = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND provider_lookup_status = 'pending'")
				provider_missing = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND (provider_lookup_status IS NULL OR provider_lookup_status = '')")
				recording_errors = self._count_table_rows(conn, "e2mdb_recordings", "WHERE scan_status = 'error' OR COALESCE(parse_error, '') != ''")
				ts_recordings = self._count_table_rows(conn, "e2mdb_recordings", "WHERE source_type = 'recording' OR extension = '.ts'")
				plain_media_files = self._count_table_rows(conn, "e2mdb_recordings", "WHERE source_type = 'media_file' AND extension != '.ts'")
				local_episodes = self._count_table_rows(conn, "e2mdb_recordings", "WHERE CAST(COALESCE(NULLIF(season_no, ''), '0') AS INTEGER) > 0 OR CAST(COALESCE(NULLIF(episode_no, ''), '0') AS INTEGER) > 0")
				bytes_total = self._sum_table_integer(conn, "e2mdb_recordings", "size_bytes")
				movies = self._count_table_rows(conn, "e2mdb_media", f"WHERE COALESCE(source_type, '') != 'live_epg' AND {media_type_expr} IN ('movie', 'film')")
				series = self._count_table_rows(conn, "e2mdb_media", f"WHERE COALESCE(source_type, '') != 'live_epg' AND ({media_type_expr} IN ('series', 'tv', 'tv_series', 'anime_series', 'manga_series') OR LOWER(COALESCE(media_family, '')) IN ('series', 'anime', 'manga'))")
				anime = self._count_table_rows(conn, "e2mdb_media", f"WHERE COALESCE(source_type, '') != 'live_epg' AND ({media_type_expr} LIKE 'anime%' OR LOWER(COALESCE(media_family, '')) = 'anime')")
				manga = self._count_table_rows(conn, "e2mdb_media", f"WHERE COALESCE(source_type, '') != 'live_epg' AND ({media_type_expr} LIKE 'manga%' OR LOWER(COALESCE(media_family, '')) = 'manga')")
				unknown_media = self._count_table_rows(conn, "e2mdb_media", f"WHERE COALESCE(source_type, '') != 'live_epg' AND {media_type_expr} IN ('', 'missing', 'multi', 'unknown')")
				missing_metadata = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND (COALESCE(metadata_title, '') = '' OR provider_lookup_status IS NULL OR provider_lookup_status = '' OR provider_lookup_status = 'error')")
				with_artwork = self._count_table_rows(conn, "e2mdb_media", self._media_artwork_where())
				missing_artwork = self._count_table_rows(conn, "e2mdb_media", "WHERE COALESCE(source_type, '') != 'live_epg' AND COALESCE(browser_ready, '0') = '1' AND NOT (COALESCE(metadata_cover_path, '') != '' OR COALESCE(metadata_backdrop_path, '') != '' OR COALESCE(metadata_logo_path, '') != '' OR COALESCE(metadata_image_path, '') != '' OR COALESCE(artwork_poster_path, '') != '' OR COALESCE(artwork_backdrop_path, '') != '' OR COALESCE(artwork_logo_path, '') != '' OR COALESCE(artwork_series_poster_path, '') != '' OR COALESCE(artwork_series_backdrop_path, '') != '' OR COALESCE(artwork_episode_path, '') != '' OR COALESCE(metadata_series_cover_path, '') != '' OR COALESCE(metadata_episode_image_path, '') != '')")
				media_types = self._group_counts(conn, "e2mdb_media", "COALESCE(NULLIF(metadata_media_type, ''), NULLIF(provider_media_type, ''), NULLIF(estimated_media_type, ''), NULLIF(media_family, ''), 'missing')", "WHERE COALESCE(source_type, '') != 'live_epg'")
				providers = self._group_counts(conn, "e2mdb_provider_matches", "provider")
				queue_states = self._group_counts(conn, "e2mdb_fetch_queue", "state")
				live_statuses = self._group_counts(conn, "e2mdb_epg_events", "status")
				recording_scan_state = self._backend_state_value(conn, "recording_scan")
				provider_enrichment_state = self._backend_state_value(conn, "provider_enrichment")
		try:
			db_size = stat(self.db_path).st_size if isfile(self.db_path) else 0
		except Exception:
			db_size = 0
		if include_cache:
			cache_files = self._count_cache_files_for_media_status(CACHE_DIRS)
			artwork_files = self._count_cache_files_for_media_status(ARTWORK_CACHE_DIRS)
		else:
			# Job-finalization uses the database summary only. Recursive cache walks
			# remain available for the explicit media-status API.
			cache_files = {"cache_root": self._cache_root(), "files": 0, "folders": 0, "bytes": 0, "dirs": {}, "skipped": True}
			artwork_files = {"cache_root": self._cache_root(), "files": 0, "folders": 0, "bytes": 0, "dirs": {}, "skipped": True}
		history_items = job_history.get("items") if isinstance(job_history.get("items"), list) else []
		last_jobs = history_items[:10]
		last_scan_job = None
		last_enrich_job = None
		last_scheduler_job = None
		last_error = ""
		for item in history_items:
			if not isinstance(item, dict):
				continue
			job_type = str(item.get("type") or "")
			if not last_scan_job and job_type in ("recording_scan", "scan_and_enrich"):
				last_scan_job = item
			if not last_enrich_job and job_type in ("metadata_enrich", "scan_and_enrich"):
				last_enrich_job = item
			if not last_scheduler_job and item.get("scheduler_job_id"):
				last_scheduler_job = item
			if not last_error and str(item.get("state") or "") == "error":
				last_error = str(item.get("message") or "")
		warnings = []
		path_status = scan_state.get("path_status") if isinstance(scan_state.get("path_status"), dict) else {}
		if path_status.get("invalid_count", 0):
			warnings.append(f"Some configured scan paths are invalid or unavailable: {path_status.get("invalid_count", 0)}")
		if recordings_total == 0:
			if path_status.get("valid_count", 0) == 0 and path_status:
				warnings.append("No valid scan path is available. Check /etc/enigma2/e2mdb/settings.json and mounted media paths.")
			elif path_status.get("video_files", 0) == 0 and path_status:
				warnings.append("Configured scan paths are reachable, but no supported media files were found.")
			else:
				warnings.append("No recordings/media files are imported yet. Run daily-media-refresh or scan_and_enrich.")
		if media_total > 0 and browser_ready == 0:
			warnings.append("Media rows exist, but nothing is browser-ready yet. Provider enrichment has not completed successfully.")
		if provider_error > 0:
			warnings.append(f"Provider lookup errors exist: {provider_error}")
		if missing_metadata > 0:
			warnings.append(f"Some media rows are missing metadata: {missing_metadata}")
		if browser_ready > 0 and missing_artwork > 0:
			warnings.append(f"Some browser-ready rows have no artwork path: {missing_artwork}")
		return {
			"success": True,
			"version": 1,
			"updated": now,
			"db": {
				"path": self.db_path,
				"exists": isfile(self.db_path),
				"size_bytes": db_size,
			},
			"media": {
				"total": media_total,
				"recordings_total": recordings_total,
				"ts_recordings": ts_recordings,
				"media_files": plain_media_files,
				"movies": movies,
				"series": series,
				"local_episodes": local_episodes,
				"anime": anime,
				"manga": manga,
				"unknown": unknown_media,
				"bytes_total": bytes_total,
				"types": media_types,
				"recording_errors": recording_errors,
			},
			"browser": {
				"ready": browser_ready,
				"pending": browser_pending,
			},
			"provider": {
				"matches_total": provider_matches_total,
				"best_matches": provider_best_matches,
				"done": provider_done,
				"pending": provider_pending,
				"missing": provider_missing,
				"errors": provider_error,
				"providers": providers,
				"missing_metadata": missing_metadata,
			},
			"artwork": {
				"provider_assets": provider_assets_total,
				"media_with_artwork": with_artwork,
				"missing_artwork": missing_artwork,
				"cache_files": artwork_files.get("files", 0),
				"cache_bytes": artwork_files.get("bytes", 0),
				"dirs": artwork_files.get("dirs", {}),
				"inventory_skipped": bool(artwork_files.get("skipped")),
			},
			"cache": {
				"root": cache_files.get("cache_root", ""),
				"files": cache_files.get("files", 0),
				"bytes": cache_files.get("bytes", 0),
				"inventory_skipped": bool(cache_files.get("skipped")),
			},
			"live_epg": {
				"events_total": live_epg_total,
				"events_active": live_epg_active,
				"events_expired": live_epg_expired,
				"statuses": live_statuses,
				"queue_total": fetch_queue_total,
				"queue_states": queue_states,
			},
			"state": {
				"scan_state": scan_state,
				"provider_state": provider_state,
				"backend_recording_scan": recording_scan_state,
				"backend_provider_enrichment": provider_enrichment_state,
				"current_job": current_job,
				"last_scan_job": last_scan_job,
				"last_enrich_job": last_enrich_job,
				"last_scheduler_job": last_scheduler_job,
				"last_error": last_error,
			},
			"history": {
				"total": len(history_items),
				"items": last_jobs,
			},
			"warnings": warnings,
		}

	def _cleanup_settings(self):
		cleanup = self.settings.get("cleanup", {}) if isinstance(self.settings.get("cleanup", {}), dict) else {}
		live_epg = self.settings.get("live_epg", {}) if isinstance(self.settings.get("live_epg", {}), dict) else {}
		return {
			"enabled": bool(cleanup.get("enabled", True) and cleanup.get("epg_meta_enabled", live_epg.get("enabled", True))),
			"queue_done_retention_seconds": max(1, safe_int(cleanup.get("queue_done_retention_seconds"), 86400)),
			"expired_event_limit": max(10, min(safe_int(cleanup.get("expired_event_limit"), 1000), 10000)),
			"remove_primary_cache": bool(cleanup.get("remove_primary_cache", False)),
			"prefill_state_retention_seconds": max(1, safe_int(cleanup.get("prefill_state_retention_seconds"), 14 * 86400)),
			"sqlite_maintenance": bool(cleanup.get("sqlite_maintenance", True)),
			"sqlite_vacuum": bool(cleanup.get("sqlite_vacuum", True)),
			"sqlite_reindex": bool(cleanup.get("sqlite_reindex", False)),
		}

	def _cache_root(self):
		cache = self.settings.get("cache", {}) if isinstance(self.settings.get("cache", {}), dict) else {}
		database = self.settings.get("database", {}) if isinstance(self.settings.get("database", {}), dict) else {}
		root = str(cache.get("root") or database.get("root") or dirname(self.db_path) or DEFAULT_DATABASE_ROOT).strip()
		return normpath(root) if root else ""

	def _safe_cache_path(self, path):
		try:
			path = normpath(str(path or ""))
			root = self._cache_root()
			if not path or not root or not path.startswith(root + "/"):
				return False
			rel = path[len(root) + 1:]
			return rel.split("/", 1)[0] in ("data", "cover", "backdrop", "titlelogo", "image", "preview", "results", "fernsehserien", "wikimedia", "wikipedia")
		except Exception:
			return False

	def _hash_from_virtual_path(self, virtual_path):
		try:
			value = str(virtual_path or "")
			if not value:
				return ""
			return md5(value.encode("utf-8", "replace")).hexdigest()
		except Exception:
			return ""

	def _hash_from_file_path(self, path):
		try:
			stem = splitext(basename(str(path or "")))[0]
			if len(stem) == 32 and all(char in "0123456789abcdef" for char in stem.lower()):
				return stem.lower()
		except Exception:
			pass
		return ""

	def _collect_primary_cache_candidates(self, rows):
		root = self._cache_root()
		paths = set()
		if not root:
			return paths
		for row in rows or []:
			hashes = set()
			virtual_hash = self._hash_from_virtual_path(row.get("virtual_path") or "")
			file_hash = self._hash_from_file_path(row.get("json_path") or "")
			if virtual_hash:
				hashes.add(virtual_hash)
			if file_hash:
				hashes.add(file_hash)
			for media_hash in hashes:
				if not media_hash:
					continue
				for cache_type in ("data", "cover", "backdrop", "titlelogo", "image", "results"):
					folder = join(root, cache_type, media_hash[0])
					for candidate in glob(join(folder, media_hash + ".*")):
						if self._safe_cache_path(candidate):
							paths.add(candidate)
		return paths

	def _cache_path_still_referenced(self, conn, path):
		path = normpath(str(path or ""))
		if not path:
			return True
		media_hash = self._hash_from_file_path(path)
		if path.endswith(".json"):
			row = conn.execute("SELECT 1 FROM e2mdb_epg_events WHERE json_path = ? LIMIT 1", (path,)).fetchone()
			if row:
				return True
		if media_hash:
			like = "%" + media_hash + "%"
			row = conn.execute("""
				SELECT 1 FROM e2mdb_epg_events
				WHERE json_path LIKE ? OR metadata_cover_path LIKE ? OR metadata_backdrop_path LIKE ?
				OR metadata_logo_path LIKE ? OR metadata_image_path LIKE ?
				LIMIT 1
			""", (like, like, like, like, like)).fetchone()
			if row:
				return True
			row = conn.execute("""
				SELECT 1 FROM e2mdb_provider_assets
				WHERE json_path LIKE ? OR cover_path LIKE ? OR backdrop_path LIKE ? OR logo_path LIKE ? OR image_path LIKE ?
				LIMIT 1
			""", (like, like, like, like, like)).fetchone()
			if row:
				return True
		return False

	def _analyze_primary_cache_candidates(self, candidates):
		stats = {"candidates": 0, "deletable": 0, "kept": 0, "errors": 0, "bytes": 0}
		with self._connect() as conn:
			for path in sorted(candidates or []):
				try:
					if not exists(path) or not self._safe_cache_path(path):
						continue
					stats["candidates"] += 1
					try:
						stats["bytes"] += int(getsize(path) or 0)
					except Exception:
						pass
					if self._cache_path_still_referenced(conn, path):
						stats["kept"] += 1
					else:
						stats["deletable"] += 1
				except Exception:
					stats["errors"] += 1
		return stats

	def _delete_primary_cache_files(self, candidates):
		deleted = 0
		kept = 0
		errors = 0
		with self._connect() as conn:
			for path in sorted(candidates or []):
				try:
					if not exists(path) or not self._safe_cache_path(path):
						continue
					if self._cache_path_still_referenced(conn, path):
						kept += 1
						continue
					remove(path)
					deleted += 1
				except Exception:
					errors += 1
		return deleted, kept, errors

	def cleanup_state_get(self, key, default=""):
		with self.lock:
			with self._connect() as conn:
				row = conn.execute("SELECT value FROM e2mdb_cleanup_state WHERE key = ?", (str(key),)).fetchone()
				return row[0] if row else default

	def cleanup_state_set(self, key, value):
		with self.lock:
			with self._connect() as conn:
				conn.execute("INSERT OR REPLACE INTO e2mdb_cleanup_state (key, value, updated_at) VALUES (?, ?, ?)", (str(key), str(value), int(time())))
				conn.commit()
		return True

	def _expired_epg_events(self, now, limit):
		with self._connect() as conn:
			rows = conn.execute("""
				SELECT * FROM e2mdb_epg_events
				WHERE pinned = 0
				AND expires_at > 0
				AND expires_at < ?
				ORDER BY expires_at ASC
				LIMIT ?
			""", (int(now), int(limit))).fetchall()
			return [dict(row) for row in rows]

	def _expired_epg_count(self, now):
		with self._connect() as conn:
			row = conn.execute("""
				SELECT COUNT(*) AS total FROM e2mdb_epg_events
				WHERE pinned = 0 AND expires_at > 0 AND expires_at < ?
			""", (int(now),)).fetchone()
			return int(row["total"] if row else 0)

	def _queue_cleanup_candidate_count(self, now, done_retention=86400, expired_grace=86400):
		with self._connect() as conn:
			row = conn.execute("""
				SELECT COUNT(*) AS total
				FROM e2mdb_fetch_queue
				WHERE (state IN ('done', 'failed', 'skipped', 'ended_skipped', 'no_match', 'short_skipped', 'ignored')
				AND updated_at > 0
				AND updated_at < ?)
				OR (event_end > 0 AND event_end < ?)
			""", (int(now) - int(done_retention or 86400), int(now) - int(expired_grace or 86400))).fetchone()
			return int(row["total"] if row else 0)

	def _delete_expired_epg_events(self, now, limit):
		with self._connect() as conn:
			rows = conn.execute("""
				SELECT id FROM e2mdb_epg_events
				WHERE pinned = 0
				AND expires_at > 0
				AND expires_at < ?
				ORDER BY expires_at ASC
				LIMIT ?
			""", (int(now), int(limit))).fetchall()
			ids = [row[0] for row in rows]
			for row_id in ids:
				conn.execute("DELETE FROM e2mdb_epg_events WHERE id = ?", (row_id,))
			conn.commit()
			return len(ids)

	def _cleanup_fetch_queue(self, now, done_retention=86400, expired_grace=86400):
		with self._connect() as conn:
			cur1 = conn.execute("""
				DELETE FROM e2mdb_fetch_queue
				WHERE state IN ('done', 'failed', 'skipped', 'ended_skipped', 'no_match', 'short_skipped', 'ignored')
				AND updated_at > 0
				AND updated_at < ?
			""", (int(now) - int(done_retention or 86400),))
			cur2 = conn.execute("""
				DELETE FROM e2mdb_fetch_queue
				WHERE event_end > 0 AND event_end < ?
			""", (int(now) - int(expired_grace or 86400),))
			conn.commit()
			return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)

	def _fetch_queue_stats(self):
		with self._connect() as conn:
			rows = conn.execute("SELECT state, COUNT(*) AS total FROM e2mdb_fetch_queue GROUP BY state ORDER BY state").fetchall()
			return {str(row["state"] or ""): int(row["total"] or 0) for row in rows}

	def _cleanup_prefill_state(self, now, dry_run=False):
		path = "/etc/enigma2/e2mdb/prefill_state.json"
		settings = self._cleanup_settings()
		retention = int(settings.get("prefill_state_retention_seconds") or 14 * 86400)
		removed = 0
		kept = 0
		blocked = 0
		tracked = 0
		try:
			if not isfile(path):
				return {"removed": 0, "kept": 0, "tracked": 0, "blocked": 0, "path": path}
			with open(path, "r", encoding="utf-8") as handle:
				data = load(handle) or {}
			services = data.get("services") if isinstance(data.get("services"), dict) else {}
			tracked = len(services)
			new_services = {}
			for service_ref, state in services.items():
				state = state if isinstance(state, dict) else {}
				no_epg_until = safe_int(state.get("no_epg_until"), 0)
				last_no_epg = safe_int(state.get("last_no_epg"), 0)
				last_has_events = safe_int(state.get("last_has_events"), 0)
				if no_epg_until > now:
					blocked += 1
				last_seen = max(last_no_epg, last_has_events)
				if no_epg_until <= now and last_seen and now - last_seen > retention:
					removed += 1
					continue
				new_services[service_ref] = state
				kept += 1
			if removed and not dry_run:
				data["services"] = new_services
				data["updated"] = now
				tmp_path = path + ".tmp"
				with open(tmp_path, "w", encoding="utf-8") as handle:
					dump(data, handle, indent=2, sort_keys=True)
					handle.write("\n")
				rename(tmp_path, path)
		except Exception as err:
			return {"removed": removed, "kept": kept, "tracked": tracked, "blocked": blocked, "path": path, "error": str(err)}
		return {"removed": removed, "kept": kept, "tracked": tracked, "blocked": blocked, "path": path}

	def live_epg_cleanup_status(self):
		now = int(time())
		settings = self._cleanup_settings()
		result = {
			"success": True,
			"enabled": bool(settings.get("enabled")),
			"last_cleanup": 0,
			"last_dry_run": 0,
			"last_sqlite_maintenance": 0,
			"last_cleanup_stats": "",
			"last_dry_run_stats": "",
			"last_sqlite_maintenance_stats": "",
			"expired_events": 0,
			"queue_cleanup_candidates": 0,
			"cache_candidates": 0,
			"queue_states": {},
			"prefill_state_tracked": 0,
			"prefill_state_blocked": 0,
			"sqlite_maintenance_enabled": bool(settings.get("sqlite_maintenance")),
			"sqlite_vacuum_enabled": bool(settings.get("sqlite_vacuum")),
			"sqlite_reindex_enabled": bool(settings.get("sqlite_reindex")),
		}
		with self.lock:
			result["last_cleanup"] = safe_int(self.cleanup_state_get("last_epg_cleanup", "0"), 0)
			result["last_dry_run"] = safe_int(self.cleanup_state_get("last_epg_cleanup_dry_run", "0"), 0)
			result["last_sqlite_maintenance"] = safe_int(self.cleanup_state_get("last_sqlite_maintenance", "0"), 0)
			result["last_cleanup_stats"] = self.cleanup_state_get("last_epg_cleanup_stats", "")
			result["last_dry_run_stats"] = self.cleanup_state_get("last_epg_cleanup_dry_run_stats", "")
			result["last_sqlite_maintenance_stats"] = self.cleanup_state_get("last_sqlite_maintenance_stats", "")
			result["expired_events"] = self._expired_epg_count(now)
			result["queue_cleanup_candidates"] = self._queue_cleanup_candidate_count(now, done_retention=settings.get("queue_done_retention_seconds"), expired_grace=86400)
			expired_rows = self._expired_epg_events(now, min(settings.get("expired_event_limit"), 10000))
			result["cache_candidates"] = len(self._collect_primary_cache_candidates(expired_rows))
			result["queue_states"] = self._fetch_queue_stats()
			prefill = self._cleanup_prefill_state(now, dry_run=True)
			result["prefill_state_tracked"] = int(prefill.get("tracked") or 0)
			result["prefill_state_blocked"] = int(prefill.get("blocked") or 0)
		return result

	def run_live_epg_cleanup(self, reason="manual", force=False, dry_run=False, remove_primary_cache=None):
		settings = self._cleanup_settings()
		if not force and not settings.get("enabled"):
			return {"success": True, "result": "disabled", "reason": reason}
		now = int(time())
		limit = int(settings.get("expired_event_limit") or 1000)
		remove_files = bool(settings.get("remove_primary_cache")) if remove_primary_cache is None else bool(remove_primary_cache)
		with self.lock:
			expired_rows = self._expired_epg_events(now, limit)
			file_candidates = self._collect_primary_cache_candidates(expired_rows) if (remove_files or dry_run) else set()
			queue_candidates = self._queue_cleanup_candidate_count(now, done_retention=settings.get("queue_done_retention_seconds"), expired_grace=86400)
			if dry_run:
				deleted_events = len(expired_rows)
				deleted_queue = queue_candidates
				prefill = self._cleanup_prefill_state(now, dry_run=True)
				cache_stats = self._analyze_primary_cache_candidates(file_candidates) if file_candidates else {"candidates": 0, "deletable": 0, "kept": 0, "errors": 0, "bytes": 0}
				cache_deleted = int(cache_stats.get("deletable") or 0)
				cache_kept = int(cache_stats.get("kept") or 0)
				cache_errors = int(cache_stats.get("errors") or 0)
				cache_bytes = int(cache_stats.get("bytes") or 0)
			else:
				deleted_events = self._delete_expired_epg_events(now, limit)
				deleted_queue = self._cleanup_fetch_queue(now, done_retention=settings.get("queue_done_retention_seconds"), expired_grace=86400)
				prefill = self._cleanup_prefill_state(now, dry_run=False)
				cache_deleted = cache_kept = cache_errors = cache_bytes = 0
				if remove_files and file_candidates:
					cache_deleted, cache_kept, cache_errors = self._delete_primary_cache_files(file_candidates)
			maintenance_result = {}
			if not dry_run and settings.get("sqlite_maintenance"):
				maintenance_result = self.maintenance(vacuum=settings.get("sqlite_vacuum"), analyze=True, reindex=settings.get("sqlite_reindex"))
			result = {
				"success": True,
				"result": "dry_run" if dry_run else "ok",
				"dry_run": bool(dry_run),
				"reason": reason,
				"events": int(deleted_events or 0),
				"queue": int(deleted_queue or 0),
				"queue_candidates": int(queue_candidates or 0),
				"prefill_state_removed": int(prefill.get("removed") or 0),
				"cache_candidates": len(file_candidates),
				"cache_deleted": int(cache_deleted or 0),
				"cache_kept": int(cache_kept or 0),
				"cache_errors": int(cache_errors or 0),
				"cache_bytes": int(cache_bytes or 0),
				"sqlite_maintenance": maintenance_result,
				"sqlite_size_saved": int((maintenance_result or {}).get("size_saved") or 0),
				"time": now,
			}
			if dry_run:
				self.cleanup_state_set("last_epg_cleanup_dry_run", str(now))
				self.cleanup_state_set("last_epg_cleanup_dry_run_stats", dumps(result, sort_keys=True))
			else:
				self.cleanup_state_set("last_epg_cleanup", str(now))
				self.cleanup_state_set("last_epg_cleanup_stats", dumps(result, sort_keys=True))
			return result

	def _is_safe_cache_base(self, cache_base):
		try:
			cache_base = normpath(str(cache_base or ""))
			return bool(cache_base and basename(cache_base) == "e2MDB" and cache_base not in ("/", "/tmp", "/var", "/media", "/media/hdd", "/media/usb"))
		except Exception:
			return False

	def _empty_cache_cleanup_stats(self, action=""):
		return {
			"success": True,
			"action": str(action or ""),
			"cache_root": self._cache_root(),
			"files": 0,
			"folders": 0,
			"bytes": 0,
			"db_rows": 0,
			"errors": [],
		}

	def _safe_remove_file_for_cleanup(self, path, cache_base, stats, dry_run=False):
		try:
			path = normpath(str(path or ""))
			cache_base = normpath(str(cache_base or ""))
			if not path or not cache_base or not path.startswith(cache_base + "/") or not isfile(path):
				return
			try:
				stats["bytes"] = int(stats.get("bytes", 0)) + int(getsize(path) or 0)
			except Exception:
				pass
			stats["files"] = int(stats.get("files", 0)) + 1
			if not dry_run:
				remove(path)
		except Exception as err:
			stats.setdefault("errors", []).append(str(err))

	def _count_tree_for_cleanup(self, path):
		files = 0
		folders = 0
		bytes_total = 0
		if not isdir(path):
			return files, folders, bytes_total
		for root, dirs, names in walk(path):
			folders += len(dirs)
			for name in names:
				files += 1
				try:
					bytes_total += int(getsize(join(root, name)) or 0)
				except Exception:
					pass
		return files, folders + 1, bytes_total

	def _reset_cache_subdir_for_cleanup(self, cache_base, sub_path, stats, dry_run=False):
		try:
			cache_path = normpath(join(cache_base, sub_path))
			if not cache_path.startswith(normpath(cache_base) + "/"):
				return
			if isdir(cache_path):
				files, folders, bytes_total = self._count_tree_for_cleanup(cache_path)
				stats["files"] = int(stats.get("files", 0)) + files
				stats["folders"] = int(stats.get("folders", 0)) + folders
				stats["bytes"] = int(stats.get("bytes", 0)) + bytes_total
				if not dry_run:
					rmtree(cache_path)
			if not dry_run and not isdir(cache_path):
				makedirs(cache_path)
		except Exception as err:
			stats.setdefault("errors", []).append(str(err))

	def _hashes_from_cache_json_by_media_type(self, cache_base, media_types):
		media_types = {str(item or "").lower() for item in (media_types or []) if item}
		hashes = set()
		data_root = join(cache_base, "data")
		if not isdir(data_root):
			return hashes
		for root, _dirs, files in walk(data_root):
			for file_name in files:
				if not file_name.endswith(".json"):
					continue
				json_path = join(root, file_name)
				try:
					with open(json_path, "r", encoding="utf-8") as handle:
						data = load(handle) or {}
				except Exception:
					continue
				if not isinstance(data, dict):
					continue
				current_type = str(data.get("media_type") or data.get("type") or "").lower()
				if current_type in media_types:
					hashes.add(splitext(file_name)[0])
		return hashes

	def _hashes_from_database_by_media_type(self, media_types):
		media_types = {str(item or "").lower() for item in (media_types or []) if item}
		hashes = set()
		if not media_types:
			return hashes
		with self._connect() as conn:
			try:
				rows = conn.execute("""
					SELECT hash, metadata_media_type, estimated_media_type, media_family
					FROM e2mdb_media
				""").fetchall()
			except Exception:
				return hashes
			for row in rows:
				values = {str(row[key] or "").lower() for key in ("metadata_media_type", "estimated_media_type", "media_family") if key in row.keys()}
				if values.intersection(media_types):
					hashes.add(str(row["hash"] or ""))
		return {item for item in hashes if item}

	def _remove_primary_hash_files_for_cleanup(self, cache_base, hashes, stats, subdirs=None, dry_run=False):
		subdirs = subdirs or PRIMARY_HASH_CACHE_DIRS
		for media_hash in sorted(hashes or []):
			media_hash = str(media_hash or "").strip()
			if not media_hash or len(media_hash) < 2:
				continue
			for sub_path in subdirs:
				folder = join(cache_base, sub_path, media_hash[0])
				if not isdir(folder):
					continue
				try:
					names = listdir(folder)
				except Exception as err:
					stats.setdefault("errors", []).append(str(err))
					continue
				for file_name in names:
					if file_name.startswith(media_hash + "."):
						self._safe_remove_file_for_cleanup(join(folder, file_name), cache_base, stats, dry_run=dry_run)

	def _collect_live_epg_cache_references(self, conn, cache_base):
		paths = set()
		hashes = set()
		try:
			rows = conn.execute("""
				SELECT virtual_path, json_path, metadata_cover_path, metadata_backdrop_path, metadata_logo_path, metadata_image_path
				FROM e2mdb_epg_events
			""").fetchall()
			for row in rows:
				virtual_path = row["virtual_path"] if "virtual_path" in row.keys() else ""
				if virtual_path:
					hashes.add(self._hash_from_virtual_path(virtual_path))
				for key in ("json_path", "metadata_cover_path", "metadata_backdrop_path", "metadata_logo_path", "metadata_image_path"):
					value = row[key] if key in row.keys() else ""
					if value:
						paths.add(value)
		except Exception:
			pass
		try:
			rows = conn.execute("SELECT json_path, cover_path, backdrop_path, logo_path, image_path FROM e2mdb_provider_assets").fetchall()
			for row in rows:
				for key in ("json_path", "cover_path", "backdrop_path", "logo_path", "image_path"):
					value = row[key] if key in row.keys() else ""
					if value:
						paths.add(value)
		except Exception:
			pass
		for path in list(paths):
			hash_id = self._hash_from_file_path(path)
			if hash_id:
				hashes.add(hash_id)
		for hash_id in sorted(hashes):
			if not hash_id:
				continue
			for cache_type in PRIMARY_HASH_CACHE_DIRS:
				folder = join(cache_base, cache_type, hash_id[0])
				for candidate in glob(join(folder, hash_id + ".*")):
					paths.add(candidate)
		return paths

	def _delete_live_epg_cache_rows(self, conn, stats, dry_run=False):
		operations = (
			("e2mdb_fetch_queue", "", ""),
			("e2mdb_epg_event_asset_map", "", ""),
			("e2mdb_epg_events", "", ""),
			("e2mdb_provider_assets", "", ""),
			("e2mdb_provider_matches", "WHERE media_hash IN (SELECT hash FROM e2mdb_media WHERE source_type = 'live_epg')", ""),
			("e2mdb_media", "WHERE source_type = 'live_epg'", ""),
			("e2mdb_channel_stats", "", ""),
		)
		for table, where_clause, _note in operations:
			try:
				if dry_run:
					row = conn.execute(f"SELECT COUNT(*) AS total FROM {table} {where_clause}").fetchone()
					stats["db_rows"] = int(stats.get("db_rows", 0)) + int(row["total"] if row else 0)
				else:
					cur = conn.execute(f"DELETE FROM {table} {where_clause}")
					stats["db_rows"] = int(stats.get("db_rows", 0)) + int(cur.rowcount or 0)
			except Exception:
				pass
		if not dry_run:
			conn.commit()

	def _remove_live_epg_cache_for_cleanup(self, cache_base, remove_files, stats, dry_run=False):
		try:
			with self._connect() as conn:
				file_paths = self._collect_live_epg_cache_references(conn, cache_base)
				self._delete_live_epg_cache_rows(conn, stats, dry_run=dry_run)
		except Exception as err:
			stats.setdefault("errors", []).append(str(err))
			file_paths = set()
		if remove_files:
			for path in sorted(file_paths):
				self._safe_remove_file_for_cleanup(path, cache_base, stats, dry_run=dry_run)

	def _remove_database_files_for_cleanup(self, cache_base, stats, dry_run=False):
		for path in (self.db_path, self.db_path + "-wal", self.db_path + "-shm", join(cache_base, "media.db"), join(cache_base, "media.db-wal"), join(cache_base, "media.db-shm")):
			self._safe_remove_file_for_cleanup(path, cache_base, stats, dry_run=dry_run)
		if not dry_run:
			self._ensure_parent()
			self.create_schema()

	def cache_cleanup_status(self):
		cache_base = self._cache_root()
		result = self._empty_cache_cleanup_stats("status")
		result.update({"safe": self._is_safe_cache_base(cache_base), "exists": isdir(cache_base), "dirs": {}})
		for sub_path in CACHE_DIRS:
			path = join(cache_base, sub_path)
			files, folders, bytes_total = self._count_tree_for_cleanup(path)
			result["dirs"][sub_path] = {"exists": isdir(path), "files": files, "folders": folders, "bytes": bytes_total}
		return result

	def run_cache_cleanup(self, action="all_cache", dry_run=False):
		action = str(action or "all_cache").strip()
		dry_run = bool(dry_run)
		stats = self._empty_cache_cleanup_stats(action)
		stats["dry_run"] = dry_run
		cache_base = normpath(self._cache_root())
		stats["cache_root"] = cache_base
		if not self._is_safe_cache_base(cache_base):
			return {"success": False, "error": f"unsafe cache path: {cache_base}", "stats": stats}
		if not isdir(cache_base) and not dry_run:
			makedirs(cache_base)
		with self.lock:
			if action in ("all_cache", "all_with_db"):
				for sub_path in CACHE_DIRS:
					self._reset_cache_subdir_for_cleanup(cache_base, sub_path, stats, dry_run=dry_run)
			elif action == "series_cache":
				media_hashes = self._hashes_from_database_by_media_type(("series", "manga"))
				media_hashes.update(self._hashes_from_cache_json_by_media_type(cache_base, ("series", "manga")))
				self._remove_primary_hash_files_for_cleanup(cache_base, media_hashes, stats, dry_run=dry_run)
				for sub_path in ("series", "seasons", "index"):
					self._reset_cache_subdir_for_cleanup(cache_base, sub_path, stats, dry_run=dry_run)
			elif action == "movie_cache":
				media_hashes = self._hashes_from_database_by_media_type(("movie",))
				media_hashes.update(self._hashes_from_cache_json_by_media_type(cache_base, ("movie",)))
				self._remove_primary_hash_files_for_cleanup(cache_base, media_hashes, stats, dry_run=dry_run)
			elif action == "epg_cache":
				self._remove_live_epg_cache_for_cleanup(cache_base, True, stats, dry_run=dry_run)
			elif action == "artwork_cache":
				for sub_path in ARTWORK_CACHE_DIRS:
					self._reset_cache_subdir_for_cleanup(cache_base, sub_path, stats, dry_run=dry_run)
			elif action == "database_only":
				self._remove_database_files_for_cleanup(cache_base, stats, dry_run=dry_run)
			else:
				return {"success": False, "error": f"unknown cleanup action: {action}", "stats": stats}
			if action == "all_with_db":
				self._remove_database_files_for_cleanup(cache_base, stats, dry_run=dry_run)
			if not dry_run:
				for sub_path in CACHE_DIRS:
					path = join(cache_base, sub_path)
					if not isdir(path):
						makedirs(path)
		if stats.get("errors"):
			return {"success": False, "error": "; ".join(stats.get("errors")[:5]), "stats": stats}
		stats["success"] = True
		stats["result"] = "dry_run" if dry_run else "ok"
		try:
			self.cleanup_state_set("last_cache_cleanup", str(int(time())))
			self.cleanup_state_set("last_cache_cleanup_stats", dumps(stats, sort_keys=True))
		except Exception:
			pass
		return stats

	def maintenance(self, vacuum=False, analyze=True, reindex=False):
		size_before = int(getsize(self.db_path) or 0) if isfile(self.db_path) else 0
		with self.lock:
			with self._connect() as conn:
				if analyze:
					conn.execute("ANALYZE")
				if reindex:
					conn.execute("REINDEX")
				conn.commit()
			if vacuum:
				with self._connect() as conn:
					conn.execute("VACUUM")
		size_after = int(getsize(self.db_path) or 0) if isfile(self.db_path) else 0
		result = {"success": True, "result": "ok", "db_path": self.db_path, "vacuum": bool(vacuum), "analyze": bool(analyze), "reindex": bool(reindex), "size_before": size_before, "size_after": size_after, "size_saved": max(0, size_before - size_after)}
		try:
			self.cleanup_state_set("last_sqlite_maintenance", str(int(time())))
			self.cleanup_state_set("last_sqlite_maintenance_stats", dumps(result, sort_keys=True))
		except Exception:
			pass
		return result
