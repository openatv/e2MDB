########################################################################################################
# E2MDBHelper by jbleyel @OpenATV @OpenATV (c) 2026                                                    #
# -----------------------------------------------------------------------------------------------------#
# This plugin is licensed under the GNU version 3.0 <https://www.gnu.org/licenses/gpl-3.0.en.html>.    #
# This plugin is NOT free software. It is open source, you are allowed to modify it (if you keep       #
# the license), but it may not be commercially distributed. Advertise with this plugin is not allowed. #
# For other uses, permission from the authors is necessary.                                            #
########################################################################################################

# PYTHON IMPORTS
from difflib import SequenceMatcher
from json import dumps, loads
from hashlib import md5
from os.path import basename, dirname, join, exists, isfile, splitext
from os import listdir, makedirs
from re import sub
from sqlite3 import connect, OperationalError, Row
from threading import Lock, Thread
from typing import Any, Optional
try:
	from . import write_log
except ImportError:
	def write_log(*args):
		try:
			print(" ".join(str(arg) for arg in args))
		except Exception:
			pass


class MediaDB:
	def __init__(self):
		self.db_path = ""
		self.table = "media"
		# MediaDB is the lightweight OpenATV timer helper database.
		# Keep it intentionally small: timers only need the media path and the
		# title/short/extended text that came from EIT/META/TXT.
		self.fields = {
			"path": "TEXT UNIQUE",
			"title": "TEXT",
			"short": "TEXT",
			"extended": "TEXT",
		}

	def set_path(self, db_path: str):
		if db_path and not exists(db_path):
			makedirs(db_path)
		self.db_path = join(db_path, "media.db")
		self._create_tables()

	def _connect(self):
		"""Create a new SQLite connection."""
		return connect(self.db_path, timeout=30)

	def _normalize_search_text(self, value: str) -> str:
		value = (value or "").strip().lower()
		value = sub(r"[._\-]+", " ", value)
		value = sub(r"[^a-z0-9äöüß ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def _create_tables(self):
		"""Create table and index if they don't exist."""
		fields = ", ".join(f"{k} {v}" for k, v in self.fields.items())
		create = f"""
			CREATE TABLE IF NOT EXISTS {self.table} (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				{fields}
			);
		"""
		indexes = (
			f"CREATE INDEX IF NOT EXISTS idx_{self.table}_path ON {self.table}(path);",
			f"CREATE INDEX IF NOT EXISTS idx_{self.table}_title ON {self.table}(title);",
		)

		with self._connect() as conn:
			conn.execute(create)
			for index in indexes:
				conn.execute(index)
			conn.commit()

	def upsert(self, data: dict[str, Any]) -> int:
		"""
		Insert or update a record based on unique "path".
		Returns the row ID of the inserted or updated record.
		"""
		data = {key: data.get(key, "") for key in self.fields.keys()}
		if not data.get("path"):
			return -1
		keys = list(data.keys())
		placeholders = ", ".join("?" for _ in keys)
		updates = ", ".join([f"{k}=excluded.{k}" for k in keys if k != "path"])

		sql = f"""
			INSERT INTO {self.table} ({', '.join(keys)})
			VALUES ({placeholders})
			ON CONFLICT(path) DO UPDATE SET {updates};
		"""

		with self._connect() as conn:
			conn.execute(sql, tuple(data.values()))
			conn.commit()
			cur = conn.execute(f"SELECT id FROM {self.table} WHERE path = ?", (data["path"],))
			row = cur.fetchone()
			return row[0] if row else -1

	def search(
		self, where: Optional[str] = None, params: tuple = (), limit: Optional[int] = None
	) -> list[dict[str, Any]]:
		"""Search records with optional WHERE clause and limit."""
		sql = f"SELECT * FROM {self.table}"
		if where:
			sql += f" WHERE {where}"
		if limit:
			sql += f" LIMIT {limit}"

		with self._connect() as conn:
			conn.row_factory = Row
			cur = conn.execute(sql, params)
			return [dict(row) for row in cur.fetchall()]

	def delete(self, where: str, params: tuple = ()) -> int:
		"""Delete records based on a WHERE clause."""
		sql = f"DELETE FROM {self.table} WHERE {where}"
		with self._connect() as conn:
			cur = conn.execute(sql, params)
			conn.commit()
			return cur.rowcount

	def _get_titles(self, title: str) -> list[tuple[Any, ...]]:
		"""
		Returns (ref, title, short, extended) for all with the title.
		"""
		sql = f"SELECT ref, title, short, extended FROM {self.table} WHERE title = ?"
		with self._connect() as conn:
			cur = conn.execute(sql, (title,))
			return cur.fetchall()

	def is_title_in_database(
		self,
		title: str,
		short: str = "",
		extended: str = "",
		ratio_short: float = 0.95,
		ratio_extended: float = 0.85,
		enabled: bool = True,
		deep_check: bool = True,
	) -> Optional[int]:
		"""
		Prüft, ob ein Titel (optional mit Beschreibung) schon in der DB existiert.
		Gibt 1 zurück, wenn ein passender oder ähnlicher Eintrag gefunden wird.
		Gibt None zurück, wenn kein Eintrag vorhanden oder Check deaktiviert.
		"""
		if not enabled:
			return None

		result = None
		content = self._get_titles(title)
		if not content:
			return None

		if deep_check:
			for ref, t, sdesc, edesc in content:
				if short:
					if sdesc == short:
						result = 1
					else:
						sim = SequenceMatcher(None, short, sdesc).ratio()
						if sim > ratio_short:
							result = 1

				if result:
					if not extended:
						break
					else:
						if edesc == extended:
							break
						else:
							sim = SequenceMatcher(None, extended, edesc).ratio()
							if sim > ratio_extended:
								break
					result = None
		else:
			result = 1

		return result


mediadb = MediaDB()


def _db_table_columns(conn, table):
	try:
		return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
	except Exception:
		return set()


def _db_people_schema_available(conn):
	try:
		people_cols = _db_table_columns(conn, "e2mdb_people")
		media_people_cols = _db_table_columns(conn, "e2mdb_media_people")
		return all(col in people_cols for col in ("id", "name", "name_norm")) and all(col in media_people_cols for col in ("media_id", "person_id", "role", "ord"))
	except Exception:
		return False


def _db_browser_people_schema_available(conn):
	try:
		return _db_people_schema_available(conn) and all(col in _db_table_columns(conn, "e2mdb_browser_index_people") for col in ("browser_key", "person_id", "role", "ord"))
	except Exception:
		return False


def _safe_int(value, default=0):
	try:
		return int(value or default)
	except Exception:
		return default


def _db_value_to_text(value):
	if value is None:
		return ''
	if isinstance(value, (list, tuple)):
		items = []
		for item in value:
			if isinstance(item, dict):
				text = item.get('name') or item.get('title') or item.get('label') or item.get('value') or ''
			else:
				text = item
			text = str(text or '').strip()
			if text and text not in items:
				items.append(text)
		return ', '.join(items)
	if isinstance(value, dict):
		for key in ('name', 'title', 'label', 'value'):
			text = str(value.get(key) or '').strip()
			if text:
				return text
		return ''
	return str(value or '')


def _db_display_text(data, key, fallback_key=None):
	if not isinstance(data, dict):
		return ''
	value = data.get(key)
	if value:
		return _db_value_to_text(value)
	if fallback_key:
		return _db_value_to_text(data.get(fallback_key))
	return ''


def _db_loads_json(value, fallback=None):
	if fallback is None:
		fallback = {}
	if isinstance(value, (dict, list)):
		return value
	if isinstance(value, str) and value.strip():
		try:
			return loads(value)
		except Exception:
			return fallback
	return fallback


def _db_loads_list(value):
	data = _db_loads_json(value, [])
	if isinstance(data, list):
		return data
	if isinstance(data, dict):
		for key in ("cast", "crew", "credits"):
			items = data.get(key)
			if isinstance(items, list):
				return items
		return [data]
	return []


def _db_normalize_person_name(value):
	value = str(value or "").strip()
	value = sub(r"\s+", " ", value)
	return value


def _db_person_entries(value, role):
	entries = []
	seen = set()
	items = _db_loads_list(value)
	for index, item in enumerate(items):
		name = ""
		character = ""
		job = ""
		department = ""
		if isinstance(item, dict):
			person = item.get("person")
			if isinstance(person, dict):
				name = person.get("name") or ""
			name = name or item.get("name") or item.get("actor") or item.get("person_name") or ""
			character_data = item.get("character") or item.get("role") or ""
			if isinstance(character_data, dict):
				character = character_data.get("name") or ""
			else:
				character = character_data
			job = item.get("job") or item.get("type") or ""
			department = item.get("department") or item.get("known_for_department") or ""
		elif isinstance(item, str):
			name = item
		name = _db_normalize_person_name(name)
		if not name:
			continue
		character = _db_normalize_person_name(character)
		job = _db_normalize_person_name(job)
		department = _db_normalize_person_name(department)
		key = (name.lower(), role, character.lower(), job.lower(), department.lower())
		if key in seen:
			continue
		seen.add(key)
		entries.append({
			"name": name,
			"role": role,
			"character": character,
			"job": job,
			"department": department,
			"ord": index,
		})
	return entries


def _db_extract_people(final_dict):
	if not isinstance(final_dict, dict):
		return []
	return _db_person_entries(final_dict.get("cast") or [], "cast") + _db_person_entries(final_dict.get("crew") or [], "crew")


def _db_create_people_tables(conn):
	"""Create people index tables for a clean e2MDB database."""
	try:
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_people (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				name_norm TEXT DEFAULT '',
				created_at INTEGER DEFAULT 0,
				updated_at INTEGER DEFAULT 0
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_media_people (
				media_id INTEGER NOT NULL,
				person_id INTEGER NOT NULL,
				role TEXT NOT NULL DEFAULT 'cast',
				character TEXT DEFAULT '',
				job TEXT DEFAULT '',
				department TEXT DEFAULT '',
				ord INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
				PRIMARY KEY (media_id, person_id, role, character, job, department)
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_epg_event_people (
				epg_event_id INTEGER NOT NULL,
				person_id INTEGER NOT NULL,
				role TEXT NOT NULL DEFAULT 'cast',
				character TEXT DEFAULT '',
				job TEXT DEFAULT '',
				department TEXT DEFAULT '',
				ord INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
				PRIMARY KEY (epg_event_id, person_id, role, character, job, department)
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_provider_asset_people (
				asset_id INTEGER NOT NULL,
				person_id INTEGER NOT NULL,
				role TEXT NOT NULL DEFAULT 'cast',
				character TEXT DEFAULT '',
				job TEXT DEFAULT '',
				department TEXT DEFAULT '',
				ord INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
				PRIMARY KEY (asset_id, person_id, role, character, job, department)
			)
		""")
	except Exception as e:
		write_log(f"[e2MDB] Error creating people tables: {e}")
		return False

	try:
		cols = _db_table_columns(conn, "e2mdb_people")
		if "name" in cols and "name_norm" in cols:
			conn.execute("UPDATE e2mdb_people SET name_norm = lower(trim(name)) WHERE COALESCE(name_norm, '') = ''")
	except Exception as e:
		write_log(f"[e2MDB] Error normalizing people names: {e}")

	for sql in (
		"CREATE INDEX IF NOT EXISTS idx_e2mdb_people_name_norm ON e2mdb_people(name_norm)",
		"CREATE INDEX IF NOT EXISTS idx_e2mdb_media_people_role ON e2mdb_media_people(role, person_id)",
		"CREATE INDEX IF NOT EXISTS idx_e2mdb_media_people_media_role ON e2mdb_media_people(media_id, role)",
		"CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_people_role ON e2mdb_epg_event_people(role, person_id)",
		"CREATE INDEX IF NOT EXISTS idx_e2mdb_asset_people_role ON e2mdb_provider_asset_people(role, person_id)",
	):
		try:
			conn.execute(sql)
		except Exception as e:
			write_log(f"[e2MDB] Error creating people index: {e}")
	return _db_people_schema_available(conn)


def _db_upsert_person(conn, name, now=None):
	name = _db_normalize_person_name(name)
	if not name:
		return None
	name_norm = sub(r"\s+", " ", name.lower()).strip()
	try:
		now = int(now or _live_epg_now())
	except Exception:
		now = 0
	row = conn.execute("SELECT id FROM e2mdb_people WHERE name_norm = ? LIMIT 1", (name_norm,)).fetchone()
	if row:
		conn.execute("UPDATE e2mdb_people SET name = ?, updated_at = ? WHERE id = ?", (name, now, row[0]))
		return row[0]
	cur = conn.execute("INSERT INTO e2mdb_people (name, name_norm, created_at, updated_at) VALUES (?, ?, ?, ?)", (name, name_norm, now, now))
	return cur.lastrowid


def _db_sync_people_map(conn, map_table, owner_column, owner_id, final_dict):
	try:
		owner_id = int(owner_id or 0)
	except Exception:
		owner_id = 0
	if not owner_id:
		return 0
	if not _db_create_people_tables(conn):
		return 0
	try:
		conn.execute(f"DELETE FROM {map_table} WHERE {owner_column} = ?", (owner_id,))
	except Exception as e:
		write_log(f"[e2MDB] Error clearing people map {map_table}: {e}")
		return 0
	count = 0
	try:
		now = int(_live_epg_now())
	except Exception:
		now = 0
	for entry in _db_extract_people(final_dict):
		try:
			person_id = _db_upsert_person(conn, entry.get("name"), now=now)
			if not person_id:
				continue
			conn.execute(f"""
				INSERT OR REPLACE INTO {map_table}
				({owner_column}, person_id, role, character, job, department, ord, created_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?)
			""", (
				owner_id, person_id, entry.get("role") or "cast", entry.get("character") or "",
				entry.get("job") or "", entry.get("department") or "", int(entry.get("ord") or 0), now
			))
			count += 1
		except Exception as e:
			write_log(f"[e2MDB] Error syncing people map {map_table}: {e}")
	return count


def _db_sync_media_people(conn, media_id, final_dict):
	return _db_sync_people_map(conn, "e2mdb_media_people", "media_id", media_id, final_dict)


def _db_sync_epg_event_people(conn, epg_event_id, final_dict):
	return _db_sync_people_map(conn, "e2mdb_epg_event_people", "epg_event_id", epg_event_id, final_dict)


def _db_sync_provider_asset_people(conn, asset_id, final_dict):
	return _db_sync_people_map(conn, "e2mdb_provider_asset_people", "asset_id", asset_id, final_dict)


def _db_people_names(conn, map_table, owner_column, owner_id, role="cast", limit=100):
	try:
		rows = conn.execute(f"""
			SELECT p.name
			FROM {map_table} mp
			JOIN e2mdb_people p ON p.id = mp.person_id
			WHERE mp.{owner_column} = ? AND mp.role = ?
			ORDER BY mp.ord ASC, p.name COLLATE NOCASE ASC
			LIMIT ?
		""", (owner_id, role, int(limit or 100))).fetchall()
		result = []
		for row in rows:
			name = _db_normalize_person_name(row[0])
			if name and name not in result:
				result.append(name)
		return result
	except Exception:
		return []


def _db_people_text(names, limit=30):
	result = []
	for name in names or []:
		name = _db_normalize_person_name(name)
		if name and name not in result:
			result.append(name)
	return ", ".join(result[:int(limit or 30)])


def _db_media_row_to_display_data(row):
	if not row:
		return {}
	try:
		data = dict(row)
	except Exception:
		data = row if isinstance(row, dict) else {}
	if not isinstance(data, dict):
		return {}
	provider_ids = _db_loads_json(data.get("metadata_provider_ids") or "", {})
	if not isinstance(provider_ids, dict):
		provider_ids = {}
	cast = _db_loads_list(data.get("metadata_cast") or "")
	crew = _db_loads_list(data.get("metadata_crew") or "")
	return {
		"title": data.get("metadata_title") or data.get("search_string") or data.get("file_name") or "",
		"name": data.get("metadata_title") or data.get("search_string") or data.get("file_name") or "",
		"episode_name": data.get("metadata_subtitle") or "",
		"overview": data.get("metadata_overview") or "",
		"description": data.get("metadata_overview") or "",
		"genres": data.get("metadata_genres") or "",
		"provider": data.get("metadata_provider") or "",
		"provider_ids": provider_ids,
		"media_type": data.get("metadata_media_type") or "",
		"year": data.get("metadata_year") or "",
		"runtime": data.get("metadata_runtime") or "",
		"vote_average": data.get("metadata_rating") or "",
		"vote_count": data.get("metadata_vote_count") or "",
		"rating": data.get("metadata_rating") or "",
		"cover_url": data.get("metadata_cover_path") or "",
		"cover_path": data.get("metadata_cover_path") or "",
		"backdrop_url": data.get("metadata_backdrop_path") or "",
		"backdrop_path": data.get("metadata_backdrop_path") or "",
		"titlelogo_path": data.get("metadata_logo_path") or "",
		"logo_path": data.get("metadata_logo_path") or "",
		"image_path": data.get("metadata_image_path") or "",
		"released": data.get("metadata_released") or "",
		"countries": data.get("metadata_countries") or "",
		"age_rating": data.get("metadata_age_rating") or "",
		"cast": cast,
		"crew": crew,
		"cast_text": _db_people_text([entry.get("name") if isinstance(entry, dict) else entry for entry in cast]),
		"season_no": data.get("metadata_season_no") or "",
		"episode_no": data.get("metadata_episode_no") or "",
	}


class ResultsDB:
	"""SQLite database for managing e2MDB search results"""

	# Pagination constant
	ITEMS_PER_PAGE = 25

	def __init__(self):
		self.db_path = None

	def set_path(self, db_path: str):
		"""Set database path and initialize schema"""
		self.db_path = join(db_path, "results.db")
		self._create_tables()

	def _connect(self):
		"""Create a new SQLite connection."""
		conn = connect(self.db_path, timeout=30)
		conn.execute("PRAGMA foreign_keys=ON")
		return conn

	def _normalize_search_text(self, value: str) -> str:
		value = (value or "").strip().lower()
		value = sub(r"[._\-]+", " ", value)
		value = sub(r"[^a-z0-9äöüß ]+", " ", value)
		return sub(r"\s+", " ", value).strip()

	def _create_tables(self):
		"""Create media and results tables if they don't exist"""
		try:
			with self._connect() as conn:
				# Create media table
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
						created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
					)
				""")

				# Create results table
				conn.execute("""
					CREATE TABLE IF NOT EXISTS e2mdb_results (
						id INTEGER PRIMARY KEY AUTOINCREMENT,
						media_id INTEGER NOT NULL,
						provider TEXT NOT NULL,
						title TEXT NOT NULL,
						title_norm TEXT DEFAULT '',
						countries TEXT,
						released TEXT,
						media_type TEXT,
						genres TEXT,
						overview TEXT,
						vote_average REAL DEFAULT 0.0,
						vote_count INTEGER DEFAULT 0,
						cover_url TEXT,
						backdrop_url TEXT,
						provider_ids TEXT,
						created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						FOREIGN KEY (media_id) REFERENCES e2mdb_media(id) ON DELETE CASCADE
					)
				""")

				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_updated_at ON e2mdb_media(updated_at DESC)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_file_name ON e2mdb_media(file_name)")

				conn.execute("UPDATE e2mdb_media SET search_string_norm = lower(trim(replace(replace(replace(search_string, '.', ' '), '_', ' '), '-', ' '))) WHERE COALESCE(search_string_norm, '') = ''")
				conn.execute("UPDATE e2mdb_results SET title_norm = lower(trim(replace(replace(replace(title, '.', ' '), '_', ' '), '-', ' '))) WHERE COALESCE(title_norm, '') = ''")

				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_search_string ON e2mdb_media(search_string)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_search_string_norm ON e2mdb_media(search_string_norm)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_results_media_id ON e2mdb_results(media_id)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_results_media_type ON e2mdb_results(media_type)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_results_title ON e2mdb_results(title)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_results_title_norm ON e2mdb_results(title_norm)")
				conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_results_released ON e2mdb_results(released)")
				_db_create_people_tables(conn)
				conn.commit()
			write_log("[e2MDB] Database schema initialized")
		except Exception as e:
			write_log(f"[e2MDB] Error creating tables: {e}")

	def add_media(self, hash_id: str, file_path: str, file_name: str, search_string: str) -> Optional[int]:
		"""Add or update media entry, returns media_id.

		Keep already stored final display metadata. INSERT OR REPLACE would delete
		the row and clear metadata columns, so use ON CONFLICT UPDATE instead.
		"""
		try:
			with self._connect() as conn:
				search_string_norm = self._normalize_search_text(search_string)
				conn.execute("""
					INSERT INTO e2mdb_media (hash, file_path, file_name, search_string, search_string_norm, updated_at)
					VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
					ON CONFLICT(hash) DO UPDATE SET
						file_path = excluded.file_path,
						file_name = excluded.file_name,
						search_string = excluded.search_string,
						search_string_norm = excluded.search_string_norm,
						updated_at = CURRENT_TIMESTAMP
				""", (hash_id, file_path, file_name, search_string, search_string_norm))
				conn.commit()

			media_id = self.get_media_by_hash(hash_id)
			write_log(f"[e2MDB] Media added/updated: {hash_id} (ID: {media_id})")
			return media_id
		except Exception as e:
			write_log(f"[e2MDB] Error adding media {hash_id}: {e}")
			return None

	def get_media_by_hash(self, hash_id: str) -> Optional[int]:
		"""Get media ID by hash"""
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				cur = conn.execute("SELECT id FROM e2mdb_media WHERE hash = ?", (hash_id,))
				row = cur.fetchone()
				return row["id"] if row else None
		except Exception as e:
			write_log(f"[e2MDB] Error getting media by hash {hash_id}: {e}")
			return None

	def clear_results_for_media(self, media_id: int) -> bool:
		"""Clear all results for a media entry"""
		try:
			with self._connect() as conn:
				conn.execute("DELETE FROM e2mdb_results WHERE media_id = ?", (media_id,))
				conn.commit()
			return True
		except Exception as e:
			write_log(f"[e2MDB] Error clearing results for media {media_id}: {e}")
			return False

	def add_result(self, media_id: int, result_data: dict[str, Any]) -> bool:
		"""Add single search result for media"""
		try:
			with self._connect() as conn:
				# Extract fields from result_data dictionary
				provider = result_data.get("provider", "")
				title = result_data.get("title", "")
				title_norm = self._normalize_search_text(title)
				countries = result_data.get("countries", "")
				released = result_data.get("released", "")
				media_type = result_data.get("media_type", "")
				genres = result_data.get("genres", "")
				overview = result_data.get("overview", "")
				vote_average = float(result_data.get("vote_average", 0.0))
				vote_count = int(result_data.get("vote_count", 0))
				cover_url = result_data.get("cover_url", "")
				backdrop_url = result_data.get("backdrop_url", "")
				provider_ids = dumps(result_data.get("provider_ids", {}))

				conn.execute("""
					INSERT INTO e2mdb_results (
						media_id, provider, title, title_norm, countries, released, media_type,
						genres, overview, vote_average, vote_count, cover_url,
						backdrop_url, provider_ids
					) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""", (
					media_id, provider, title, title_norm, countries, released, media_type,
					genres, overview, vote_average, vote_count, cover_url,
					backdrop_url, provider_ids
				))

				conn.commit()
			return True
		except Exception as e:
			write_log(f"[e2MDB] Error adding result for media {media_id}: {e}")
			return False

	def add_results_from_json(self, media_id: int, results_json: dict[str, Any]) -> int:
		"""Add multiple results from JSON object, returns count"""
		try:
			if not results_json or "results" not in results_json:
				return 0

			count = 0
			for result_data in results_json["results"]:
				if self.add_result(media_id, result_data):
					count += 1

			write_log(f"[e2MDB] Added {count} results for media {media_id}")
			return count
		except Exception as e:
			write_log(f"[e2MDB] Error adding results from JSON for media {media_id}: {e}")
			return 0

	def update_media_record(self, old_hash: str, new_hash: str, file_path: str, file_name: str, search_string: str = "") -> bool:
		"""Update stored media path, filename, hash, and optional search string"""
		try:
			with self._connect() as conn:
				search_string_norm = self._normalize_search_text(search_string)
				conn.execute("""
					UPDATE e2mdb_media
					SET hash = ?, file_path = ?, file_name = ?, search_string = ?, search_string_norm = ?, updated_at = CURRENT_TIMESTAMP
					WHERE hash = ?
				""", (new_hash, file_path, file_name, search_string, search_string_norm, old_hash))
				conn.commit()
			return True
		except Exception as e:
			write_log(f"[e2MDB] Error updating media record {old_hash} -> {new_hash}: {e}")
			return False

	def get_results_for_media(self, media_id: int) -> dict[str, Any]:
		"""Get all results for a media entry as JSON"""
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				cur = conn.execute("SELECT * FROM e2mdb_results WHERE media_id = ? ORDER BY id", (media_id,))
				rows = cur.fetchall()

				results_list = []
				for row in rows:
					result = {
						"provider": row["provider"],
						"title": row["title"],
						"countries": row["countries"],
						"released": row["released"],
						"media_type": row["media_type"],
						"genres": row["genres"],
						"overview": row["overview"],
						"vote_average": str(row["vote_average"]),
						"vote_count": str(row["vote_count"]),
						"cover_url": row["cover_url"],
						"backdrop_url": row["backdrop_url"],
						"provider_ids": loads(row["provider_ids"]),
					}
					results_list.append(result)

				return {"results": results_list}
		except Exception as e:
			write_log(f"[e2MDB] Error getting results for media {media_id}: {e}")
			return {"results": []}

	def get_total_media_count(self) -> int:
		"""Get total count of media entries in database"""
		try:
			with self._connect() as conn:
				cur = conn.execute("SELECT COUNT(*) FROM e2mdb_media")
				count = cur.fetchone()[0]
				return count
		except Exception as e:
			write_log(f"[e2MDB] Error getting media count: {e}")
			return 0

	def get_media_record(self, hash_id: str) -> dict[str, Any]:
		"""Get full media record by hash including result count"""
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				cur = conn.execute("""
					SELECT m.*, COUNT(r.id) as result_count
					FROM e2mdb_media m
					LEFT JOIN e2mdb_results r ON m.id = r.media_id
					WHERE m.hash = ?
					GROUP BY m.id
				""", (hash_id,))
				row = cur.fetchone()
				return dict(row) if row else {}
		except Exception as e:
			write_log(f"[e2MDB] Error getting media record by hash {hash_id}: {e}")
			return {}

	def get_all_media_with_results(self, page: int = 1, status: str = "all", search_term: str = "", limit: Optional[int] = None, letter: str = "", media_type: str = "all") -> dict[str, Any]:
		"""Get a single visible slice of media entries.

		This avoids expensive full COUNT(*) queries for every request.
		The caller gets one page plus a has_more flag.
		"""
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				page = max(1, int(page or 1))
				limit = max(1, min(int(limit or self.ITEMS_PER_PAGE), 100))
				offset = (page - 1) * limit

				where_clauses = []
				params = []

				if status == "matched":
					where_clauses.append("EXISTS (SELECT 1 FROM e2mdb_results r1 WHERE r1.media_id = m.id)")
				elif status == "failed":
					where_clauses.append("NOT EXISTS (SELECT 1 FROM e2mdb_results r1 WHERE r1.media_id = m.id)")

				if search_term:
					like_term = f"%{search_term.lower()}%"
					where_clauses.append("(LOWER(m.file_name) LIKE ? OR LOWER(m.search_string) LIKE ? OR LOWER(m.file_path) LIKE ?)")
					params.extend([like_term, like_term, like_term])

				letter = (letter or "").strip().upper()
				if letter:
					if letter == "0-9":
						where_clauses.append("SUBSTR(UPPER(m.search_string), 1, 1) BETWEEN '0' AND '9'")
					else:
						where_clauses.append("SUBSTR(UPPER(m.search_string), 1, 1) = ?")
						params.append(letter)

				if media_type in ("movie", "series"):
					where_clauses.append("EXISTS (SELECT 1 FROM e2mdb_results r2 WHERE r2.media_id = m.id AND LOWER(COALESCE(r2.media_type, '')) = ?)")
					params.append(media_type)

				where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

				query_params = list(params) + [limit + 1, offset]
				cur = conn.execute(f"""
					SELECT m.id, m.hash, m.file_name, m.file_path, m.search_string,
					m.created_at, m.updated_at,
					COUNT(r.id) as result_count,
					MAX(COALESCE(r.media_type, '')) as media_type,
					MAX(COALESCE(r.genres, '')) as genres
					FROM e2mdb_media m
					LEFT JOIN e2mdb_results r ON m.id = r.media_id
					{where_sql}
					GROUP BY m.id
					ORDER BY m.updated_at DESC, m.created_at DESC
					LIMIT ? OFFSET ?
				""", tuple(query_params))
				rows = cur.fetchall()

				has_more = len(rows) > limit
				rows = rows[:limit]
				media_list = []
				for row in rows:
					media_list.append({
						"id": row["id"],
						"hash": row["hash"],
						"title": row["search_string"],
						"file_name": row["file_name"],
						"file_path": row["file_path"],
						"result_count": row["result_count"],
						"media_type": row["media_type"],
						"genres": row["genres"],
						"scan_status": "failed" if row["result_count"] == 0 else "matched",
						"created_at": row["created_at"],
						"updated_at": row["updated_at"]
					})

				facets = {
					"types": sorted(list({item.get("media_type") for item in media_list if item.get("media_type")})),
					"letters": sorted(list({((item.get("title") or item.get("file_name") or "#")[:1].upper() if (item.get("title") or item.get("file_name"))[:1].isalpha() else "0-9") for item in media_list if item.get("title") or item.get("file_name")})),
				}

				return {
					"count": len(media_list),
					"page": page,
					"limit": limit,
					"has_more": has_more,
					"media": media_list,
					"facets": facets,
				}
		except Exception as e:
			write_log(f"[e2MDB] Error getting paginated media: {e}")
			return {
				"count": 0,
				"page": 1,
				"limit": limit or self.ITEMS_PER_PAGE,
				"has_more": False,
				"media": [],
				"facets": {"types": [], "letters": []}
			}

	def _browser_base_query(self, media_type: str = "all", search_term: str = "", year: str = "", genre: str = "", letter: str = ""):
		where_clauses = ["COALESCE(r.title, '') != ''"]
		params = []
		media_type = (media_type or 'all').strip().lower()
		if media_type in ("movie", "series"):
			where_clauses.append("LOWER(COALESCE(r.media_type, '')) = ?")
			params.append(media_type)
		search_term = self._normalize_search_text(search_term or '')
		if search_term and len(search_term) >= 2:
			prefix_term = f"{search_term}%"
			contains_term = f"% {search_term}%"
			where_clauses.append("("
				"COALESCE(r.title_norm, '') LIKE ? OR COALESCE(m.search_string_norm, '') LIKE ? OR "
				"COALESCE(r.title_norm, '') LIKE ? OR COALESCE(m.search_string_norm, '') LIKE ?"
			")")
			params.extend([prefix_term, prefix_term, contains_term, contains_term])
		year = (year or '').strip()
		if len(year) == 4 and year.isdigit():
			where_clauses.append("SUBSTR(COALESCE(r.released, ''), 1, 4) = ?")
			params.append(year)
		genre = (genre or '').strip().lower()
		if genre:
			where_clauses.append("LOWER(COALESCE(r.genres, '')) LIKE ?")
			params.append(f"%{genre}%")
		letter = (letter or '').strip().upper()
		if letter:
			if letter == '0-9':
				where_clauses.append("SUBSTR(UPPER(COALESCE(r.title, m.search_string, m.file_name, '')), 1, 1) BETWEEN '0' AND '9'")
			else:
				where_clauses.append("SUBSTR(UPPER(COALESCE(r.title, m.search_string, m.file_name, '')), 1, 1) = ?")
				params.append(letter)
		where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
		return where_sql, params

	def _browser_group_key(self, row) -> str:
		provider = (row["provider"] or "").strip().lower()
		provider_ids = (row["provider_ids"] or "").strip().lower()
		title = (row["title"] or row["search_string"] or row["file_name"] or "").strip().lower()
		year = (row["released"] or "")[:4]
		media_type = (row["media_type"] or "").strip().lower()
		if provider and provider_ids:
			return f"{media_type}|{provider}|{provider_ids}"
		return f"{media_type}|{title}|{year}"

	def get_browser_media(self, page: int = 1, limit: Optional[int] = None, media_type: str = "all", search_term: str = "", year: str = "", genre: str = "", letter: str = "") -> dict[str, Any]:
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				page = max(1, int(page or 1))
				limit = max(1, min(int(limit or self.ITEMS_PER_PAGE), 100))
				offset = (page - 1) * limit
				where_sql, params = self._browser_base_query(media_type, search_term, year, genre, letter)

				# Collect enough UNIQUE browser groups for the requested page.
				# A simple LIMIT on raw rows is not sufficient because one series can
				# occupy many rows (episodes), which caused only a handful of unique
				# cards and a wrong has_more=False result.
				chunk_size = max(limit * 8, 250)
				row_offset = 0
				groups = {}
				ordered = []
				exhausted = False

				while len(ordered) < (offset + limit + 1):
					cur = conn.execute(f"""
						SELECT m.hash, m.file_name, m.file_path, m.search_string, m.updated_at,
						r.title, r.released, r.media_type, r.genres, r.overview,
						r.cover_url, r.backdrop_url, r.provider, r.provider_ids,
						r.vote_average, r.vote_count
						FROM e2mdb_media m
						JOIN e2mdb_results r ON m.id = r.media_id
						{where_sql}
						ORDER BY LOWER(COALESCE(r.title, m.search_string, m.file_name)) ASC, m.updated_at DESC
						LIMIT ? OFFSET ?
					""", tuple(list(params) + [chunk_size, row_offset]))
					rows = cur.fetchall()
					if not rows:
						exhausted = True
						break

					for row in rows:
						group_key = self._browser_group_key(row)
						item = groups.get(group_key)
						if item is None:
							item = {
								"id": row["hash"],
								"browser_key": group_key,
								"title": row["title"] or row["search_string"] or row["file_name"],
								"file_name": row["file_name"],
								"file_path": row["file_path"],
								"released": row["released"],
								"year": (row["released"] or '')[:4],
								"media_type": row["media_type"],
								"genres": row["genres"],
								"overview": row["overview"],
								"cover_url": row["cover_url"],
								"backdrop_url": row["backdrop_url"],
								"provider": row["provider"],
								"provider_ids": row["provider_ids"],
								"vote_average": row["vote_average"],
								"vote_count": row["vote_count"],
								"updated_at": row["updated_at"],
								"file_variants": [],
								"season_count": 0,
								"episode_count": 0,
								"series_title": row["title"] or row["search_string"] or row["file_name"],
							}
							groups[group_key] = item
							ordered.append(item)
						else:
							if not item.get("overview") and row["overview"]:
								item["overview"] = row["overview"]
							if not item.get("cover_url") and row["cover_url"]:
								item["cover_url"] = row["cover_url"]
							if not item.get("backdrop_url") and row["backdrop_url"]:
								item["backdrop_url"] = row["backdrop_url"]
							if not item.get("genres") and row["genres"]:
								item["genres"] = row["genres"]
						variant = row["file_name"] or ""
						if variant and variant not in item["file_variants"]:
							item["file_variants"].append(variant)

					row_offset += len(rows)
					if len(rows) < chunk_size:
						exhausted = True
						break

				for item in ordered:
					if item.get("media_type") != "series":
						continue
					inv = self.get_series_inventory(item.get("id", ""))
					if inv.get("season_count"):
						item["season_count"] = inv.get("season_count", 0)
						item["episode_count"] = inv.get("episode_count", 0)
						item["seasons"] = inv.get("seasons", [])
						item["files"] = inv.get("files", [])
						if inv.get("series_title"):
							item["series_title"] = inv.get("series_title")
					else:
						item["season_count"] = len(item.get("file_variants", []))
						item["seasons"] = item.get("seasons", [])
						item["files"] = item.get("files", [])

				has_more = len(ordered) > (offset + limit)
				items = ordered[offset:offset + limit]
				if not has_more and not exhausted:
					has_more = True
				return {"page": page, "limit": limit, "has_more": has_more, "items": items}
		except Exception as e:
			write_log(f"[e2MDB] Error getting browser media: {e}")
			return {"page": 1, "limit": limit or self.ITEMS_PER_PAGE, "has_more": False, "items": []}

	def get_browser_facets(self, media_type: str = "all", search_term: str = "", letter: str = "") -> dict[str, Any]:
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				where_sql, params = self._browser_base_query(media_type, search_term, '', '', letter)
				cur = conn.execute(f"SELECT r.released, r.genres FROM e2mdb_media m JOIN e2mdb_results r ON m.id = r.media_id {where_sql}", tuple(params))
				years, genres = set(), set()
				for row in cur.fetchall():
					rel = row['released'] or ''
					if len(rel) >= 4 and rel[:4].isdigit():
						years.add(rel[:4])
					for part in (row['genres'] or '').split(','):
						part = part.strip()
						if part:
							genres.add(part)
				return {"years": sorted(years, reverse=True), "genres": sorted(genres)}
		except Exception as e:
			write_log(f"[e2MDB] Error getting browser facets: {e}")
			return {"years": [], "genres": []}

	def _parse_season_episode_from_name(self, name: str) -> tuple[Optional[int], Optional[int]]:
		try:
			import re
			text = (name or '')
			m = re.search(r'(?i)[Ss](\d{1,2})[Ee](\d{1,3})', text)
			if m:
				return int(m.group(1)), int(m.group(2))
			m = re.search(r'(?i)(\d{1,2})x(\d{1,3})', text)
			if m:
				return int(m.group(1)), int(m.group(2))
		except Exception:
			pass
		return None, None


def get_series_inventory(self, result_id: str) -> dict[str, Any]:
		inventory = {"series_title": "", "season_count": 0, "episode_count": 0, "seasons": [], "files": []}
		try:
			with self._connect() as conn:
				conn.row_factory = Row
				base = conn.execute("""
					SELECT browser_key, media_hash, title, series_title
					FROM e2mdb_browser_index
					WHERE browser_key = ? OR media_hash = ?
					LIMIT 1
				""", (result_id, result_id)).fetchone()
				if not base:
					return inventory

				browser_key = base["browser_key"]
				inventory["series_title"] = base["series_title"] or base["title"] or ""

				season_rows = conn.execute("""
					SELECT season_no, episode_count
					FROM e2mdb_browser_series_seasons
					WHERE browser_key = ?
					ORDER BY season_no
				""", (browser_key,)).fetchall()

				all_episode_rows = conn.execute("""
					SELECT season_no, episode_no, media_hash, file_name
					FROM e2mdb_browser_series_episodes
					WHERE browser_key = ?
					ORDER BY season_no, episode_no
				""", (browser_key,)).fetchall()

				season_map = {}
				for ep in all_episode_rows:
					season_no = ep["season_no"]
					season = season_map.setdefault(season_no, {"season_no": season_no, "episodes": [], "files": [], "items": []})
					file_name = ep["file_name"] or ""
					file_item = {"id": ep["media_hash"], "file_name": file_name}
					inventory["files"].append(file_item)
					if ep["episode_no"] is not None and ep["episode_no"] not in season["episodes"]:
						season["episodes"].append(ep["episode_no"])
					season["files"].append(file_name)
					season["items"].append({"id": ep["media_hash"], "file_name": file_name, "episode_no": ep["episode_no"]})

				seasons = []
				known_counts = {row["season_no"]: int(row["episode_count"] or 0) for row in season_rows}
				for season_no in sorted(season_map):
					season = season_map[season_no]
					season["episodes"].sort()
					season["episode_count"] = known_counts.get(season_no, len(season["episodes"]))
					seasons.append(season)

				inventory["seasons"] = seasons
				inventory["season_count"] = len(seasons)
				inventory["episode_count"] = sum(int(x.get("episode_count") or 0) for x in seasons)
				return inventory
		except Exception as e:
			write_log(f"[e2MDB] Error getting series inventory: {e}")
			return inventory


# --- Materialized browser cache -------------------------------------------------
def _browser_cache_root(self):
	return dirname(self.db_path) if getattr(self, 'db_path', None) else ''


def _browser_sort_title(self, title):
	norm = self._normalize_search_text(title or '')
	for prefix in ('the ', 'a ', 'an ', 'der ', 'die ', 'das ', 'ein ', 'eine '):
		if norm.startswith(prefix):
			return norm[len(prefix):]
	return norm


def _browser_letter_for_title(self, title):
	norm = self._normalize_search_text(title or '')
	if not norm:
		return '#'
	ch = norm[0].upper()
	return ch if ch.isalpha() else '0-9'


def _browser_decode_provider_ids(raw_value):
	if isinstance(raw_value, dict):
		return raw_value
	if isinstance(raw_value, str):
		try:
			data = loads(raw_value) if raw_value else {}
			return data if isinstance(data, dict) else {}
		except Exception:
			return {}
	return {}


def _browser_normalize_cached_image_path(path_value):
	path_value = str(path_value or '').strip()
	if not path_value:
		return ''
	candidates = [path_value]
	try:
		db_obj = globals().get('resultsdb')
		cache_root = dirname(getattr(db_obj, 'db_path', '') or '')
		if path_value.startswith(('cover/', 'backdrop/', 'titlelogo/', 'image/', 'data/', 'series/', 'seasons/', 'index/')) and cache_root:
			candidates.append(join(cache_root, path_value))
	except Exception:
		pass
	for candidate in candidates:
		if exists(candidate) and isfile(candidate):
			return candidate
	return ''


def _browser_find_preview_path(self, file_path, file_name, hash_id=None, preferred_path=""):
	preferred = _browser_normalize_cached_image_path(preferred_path)
	if preferred:
		return preferred
	# Do not inspect the per-media JSON cache here. Episode previews must come
	# from SQLite metadata or from local sidecar images next to the recording.
	full_path = join(file_path or '', file_name or '')
	if not full_path:
		return ''
	base_name, ext_name = splitext(full_path)
	candidates = []
	for ext in ('.jpg', '.jpeg', '.png', '.webp'):
		candidates.extend([
			f'{base_name}{ext}',
			f'{full_path}{ext}',
			f'{base_name}-thumb{ext}',
			f'{base_name}_thumb{ext}',
			f'{base_name}.eit{ext}',
		])
		if ext_name:
			candidates.extend([
				f'{base_name}{ext_name}_mp{ext}',
				f'{base_name}{ext_name}-mp{ext}',
				f'{base_name}{ext_name}.eit{ext}',
			])
	for candidate in candidates:
		if exists(candidate) and isfile(candidate):
			return candidate
	try:
		directory = dirname(full_path)
		stem = basename(base_name).lower()
		full_lower = basename(full_path).lower()
		for entry in listdir(directory):
			lower = entry.lower()
			if lower.endswith(('.jpg', '.jpeg', '.png', '.webp')) and (lower.startswith(stem) or lower.startswith(full_lower) or stem in lower):
				path = join(directory, entry)
				if isfile(path):
					return path
	except Exception:
		pass
	return ''


_browser_cache_build_lock = Lock()
_browser_cache_rebuild_state_lock = Lock()
_browser_cache_rebuild_running = False


def _browser_create_tables(self):
	with self._connect() as conn:
		conn.execute("CREATE TABLE IF NOT EXISTS e2mdb_meta (key TEXT PRIMARY KEY, value TEXT)")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_browser_index (
				browser_key TEXT PRIMARY KEY,
				media_hash TEXT NOT NULL,
				media_type TEXT,
				provider TEXT,
				provider_id TEXT,
				title TEXT,
				title_norm TEXT,
				sort_title TEXT,
				year TEXT,
				released TEXT,
				genres TEXT,
				overview TEXT,
				cover_url TEXT,
				backdrop_url TEXT,
				vote_average REAL DEFAULT 0.0,
				vote_count INTEGER DEFAULT 0,
				season_count INTEGER DEFAULT 0,
				episode_count INTEGER DEFAULT 0,
				series_title TEXT,
				cast_text TEXT DEFAULT '',
				crew_text TEXT DEFAULT '',
				letter TEXT DEFAULT '',
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_browser_series_seasons (
				browser_key TEXT NOT NULL,
				season_no INTEGER NOT NULL,
				episode_count INTEGER DEFAULT 0,
				PRIMARY KEY (browser_key, season_no)
			)
		""")
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_browser_series_episodes (
				browser_key TEXT NOT NULL,
				season_no INTEGER NOT NULL,
				episode_no INTEGER NOT NULL,
				media_hash TEXT NOT NULL,
				file_name TEXT,
				file_path TEXT,
				preview_path TEXT,
				title TEXT,
				overview TEXT,
				air_date TEXT,
				cover_url TEXT,
				backdrop_url TEXT,
				PRIMARY KEY (browser_key, season_no, episode_no, media_hash)
			)
		""")
		people_schema_ready = False
		try:
			people_schema_ready = bool(_db_create_people_tables(conn))
		except Exception as e:
			write_log(f"[e2MDB] People tables unavailable for browser index: {e}")
		try:
			conn.execute("""
				CREATE TABLE IF NOT EXISTS e2mdb_browser_index_people (
					browser_key TEXT NOT NULL,
					person_id INTEGER NOT NULL,
					role TEXT NOT NULL DEFAULT 'cast',
					ord INTEGER DEFAULT 0,
					PRIMARY KEY (browser_key, person_id, role)
				)
			""")
		except Exception as e:
			people_schema_ready = False
			write_log(f"[e2MDB] Browser people index unavailable: {e}")
		browser_schema_changed = False
		try:
			if people_schema_ready and _db_browser_people_schema_available(conn):
				index_count = _safe_int(conn.execute("SELECT COUNT(*) FROM e2mdb_browser_index").fetchone()[0])
				people_count = _safe_int(conn.execute("SELECT COUNT(*) FROM e2mdb_browser_index_people").fetchone()[0])
				media_people_count = _safe_int(conn.execute("SELECT COUNT(*) FROM e2mdb_media_people").fetchone()[0])
				if index_count and media_people_count and not people_count:
					browser_schema_changed = True
		except Exception:
			pass
		if browser_schema_changed:
			conn.execute("INSERT OR REPLACE INTO e2mdb_meta (key, value) VALUES ('browser_cache_dirty', '1')")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_index_type_sort ON e2mdb_browser_index(media_type, sort_title)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_index_letter ON e2mdb_browser_index(letter)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_index_year ON e2mdb_browser_index(year)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_index_title_norm ON e2mdb_browser_index(title_norm)")
		try:
			conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_people_role ON e2mdb_browser_index_people(role, person_id)")
			conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_people_browser_key ON e2mdb_browser_index_people(browser_key)")
		except Exception as e:
			write_log(f"[e2MDB] Error creating browser people indexes: {e}")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_season_lookup ON e2mdb_browser_series_seasons(browser_key, season_no)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_browser_episode_lookup ON e2mdb_browser_series_episodes(browser_key, season_no, episode_no)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_metadata_browser ON e2mdb_media(metadata_media_type, metadata_title, updated_at)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_metadata_letter ON e2mdb_media(metadata_title)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_media_metadata_year ON e2mdb_media(metadata_year, metadata_released)")
		conn.commit()


def _browser_set_meta(self, key, value):
	with self._connect() as conn:
		conn.execute("INSERT OR REPLACE INTO e2mdb_meta (key, value) VALUES (?, ?)", (key, str(value)))
		conn.commit()


def _browser_get_meta(self, key, default=''):
	with self._connect() as conn:
		row = conn.execute("SELECT value FROM e2mdb_meta WHERE key = ?", (key,)).fetchone()
		return row[0] if row else default


def _mark_browser_cache_dirty(self):
	try:
		_browser_create_tables(self)
		_browser_set_meta(self, 'browser_cache_dirty', '1')
	except Exception as e:
		write_log(f"[e2MDB] Error marking browser cache dirty: {e}")


def _browser_cache_has_rows(self):
	try:
		_browser_create_tables(self)
		with self._connect() as conn:
			row = conn.execute("SELECT COUNT(*) FROM e2mdb_browser_index").fetchone()
			return bool(row and int(row[0] or 0) > 0)
	except Exception:
		return False


def _browser_cache_is_ready(self):
	try:
		_browser_create_tables(self)
		dirty = _browser_get_meta(self, "browser_cache_dirty", "1")
		if dirty != "0":
			return False
		try:
			expected_count = int(_browser_get_meta(self, "browser_cache_count", "0") or 0)
		except Exception:
			expected_count = 0
		if expected_count <= 0:
			return False
		with self._connect() as conn:
			row = conn.execute("SELECT COUNT(*) FROM e2mdb_browser_index").fetchone()
			actual_count = int(row[0] or 0) if row else 0
			return actual_count >= expected_count
	except Exception:
		return False


def _browser_cache_is_rebuilding():
	try:
		with _browser_cache_rebuild_state_lock:
			return bool(_browser_cache_rebuild_running)
	except Exception:
		return False


def _browser_people_index_is_ready(self):
	try:
		if not _browser_cache_is_ready(self):
			return False
		with self._connect() as conn:
			if not _db_browser_people_schema_available(conn):
				return False
			row = conn.execute("SELECT COUNT(*) FROM e2mdb_browser_index_people WHERE role = 'cast'").fetchone()
			return bool(row and int(row[0] or 0) > 0)
	except Exception:
		return False


def _browser_index_status(self):
	ready = _browser_cache_is_ready(self)
	return {
		"index_ready": ready,
		"index_building": (not ready) and _browser_cache_is_rebuilding(),
		"people_index_ready": _browser_people_index_is_ready(self) if ready else False,
	}


def _start_browser_cache_rebuild(self):
	global _browser_cache_rebuild_running
	try:
		with _browser_cache_rebuild_state_lock:
			if _browser_cache_rebuild_running:
				return False
			_browser_cache_rebuild_running = True

		def rebuild_worker():
			global _browser_cache_rebuild_running
			try:
				write_log("[e2MDB] Browser cache rebuild started in background")
				with _browser_cache_build_lock:
					dirty = _browser_get_meta(self, "browser_cache_dirty", "1")
					count = _browser_get_meta(self, "browser_cache_count", "")
					if dirty == "1" or not count:
						_rebuild_browser_cache(self)
			except Exception as e:
				write_log(f"[e2MDB] Error rebuilding browser cache in background: {e}")
			finally:
				with _browser_cache_rebuild_state_lock:
					_browser_cache_rebuild_running = False

		thread = Thread(target=rebuild_worker, name="e2MDBBrowserCache")
		thread.daemon = True
		thread.start()
		return True
	except Exception as e:
		with _browser_cache_rebuild_state_lock:
			_browser_cache_rebuild_running = False
		write_log(f"[e2MDB] Error starting browser cache rebuild: {e}")
		return False


def _ensure_browser_cache(self, allow_rebuild=True, background=False):
	try:
		_browser_create_tables(self)
		dirty = _browser_get_meta(self, "browser_cache_dirty", "1")
		count = _browser_get_meta(self, "browser_cache_count", "")
		if dirty == "1" or not count:
			if background:
				_start_browser_cache_rebuild(self)
				return False
			if not allow_rebuild:
				return False
			with _browser_cache_build_lock:
				dirty = _browser_get_meta(self, "browser_cache_dirty", "1")
				count = _browser_get_meta(self, "browser_cache_count", "")
				if dirty == "1" or not count:
					_rebuild_browser_cache(self)
		return True
	except Exception as e:
		write_log(f"[e2MDB] Error ensuring browser cache: {e}")
		return False


def _rebuild_browser_cache(self):
	_browser_create_tables(self)
	with self._connect() as conn:
		conn.row_factory = Row

		media_rows = conn.execute("""
			SELECT m.id, m.hash, m.file_path, m.file_name, m.search_string, m.search_string_norm, m.updated_at,
				m.metadata_title, m.metadata_subtitle, m.metadata_overview, m.metadata_genres,
				m.metadata_provider, m.metadata_provider_ids, m.metadata_media_type, m.metadata_year,
				m.metadata_runtime, m.metadata_rating, m.metadata_vote_count, m.metadata_cover_path,
				m.metadata_backdrop_path, m.metadata_logo_path, m.metadata_image_path, m.metadata_released,
				m.metadata_countries, m.metadata_age_rating, m.metadata_cast, m.metadata_crew,
				m.metadata_season_no, m.metadata_episode_no
			FROM e2mdb_media m
			ORDER BY LOWER(COALESCE(NULLIF(m.metadata_title, ''), m.search_string, m.file_name)) ASC, m.updated_at DESC
		""").fetchall()

		groups = {}
		skipped_no_final = 0

		for media_row in media_rows:
			row = dict(media_row)

			# The browser index is now built from SQLite display metadata only.
			# JSON files remain debug/catalog artifacts and are not used for search/UI rendering here.
			final_title = row.get('metadata_title') or ''
			final_media_type = (row.get('metadata_media_type') or '').strip().lower()
			final_provider = row.get('metadata_provider') or ''
			final_provider_ids = _browser_decode_provider_ids(row.get('metadata_provider_ids') or '')
			final_released = row.get('metadata_released') or ''
			final_genres = row.get('metadata_genres') or ''
			final_overview = row.get('metadata_overview') or ''
			final_cover_url = row.get('metadata_cover_path') or ''
			final_backdrop_url = row.get('metadata_backdrop_path') or ''
			try:
				final_vote_average = float(row.get('metadata_rating') or 0.0)
			except Exception:
				final_vote_average = 0.0
			try:
				final_vote_count = int(row.get('metadata_vote_count') or 0)
			except Exception:
				final_vote_count = 0

			if final_media_type not in ('movie', 'series'):
				skipped_no_final += 1
				continue

			if not final_title:
				skipped_no_final += 1
				continue

			cast_names = _db_people_names(conn, 'e2mdb_media_people', 'media_id', row.get('id'), 'cast', 100)
			crew_names = _db_people_names(conn, 'e2mdb_media_people', 'media_id', row.get('id'), 'crew', 100)
			if (not cast_names and row.get('metadata_cast')) or (not crew_names and row.get('metadata_crew')):
				_db_sync_media_people(conn, row.get('id'), {'cast': _db_loads_list(row.get('metadata_cast') or ''), 'crew': _db_loads_list(row.get('metadata_crew') or '')})
				cast_names = _db_people_names(conn, 'e2mdb_media_people', 'media_id', row.get('id'), 'cast', 100)
				crew_names = _db_people_names(conn, 'e2mdb_media_people', 'media_id', row.get('id'), 'crew', 100)
			final_cast_text = _db_people_text(cast_names, 30)
			final_crew_text = _db_people_text(crew_names, 30)

			provider = str(final_provider or '').strip().lower()
			provider_ids = final_provider_ids if isinstance(final_provider_ids, dict) else {}
			provider_id = ''
			if provider and provider_ids.get(provider):
				provider_id = str(provider_ids.get(provider) or '')
			if not provider_id:
				for fallback_key in ('tmdb', 'tvdb', 'imdb', 'tvmaze', 'anime', 'anilist', 'kitsu', 'omdb'):
					if provider_ids.get(fallback_key):
						provider = provider or fallback_key
						provider_id = str(provider_ids.get(fallback_key) or '')
						break

			year = str(final_released or row.get('metadata_year') or '')[:4]

			if provider and provider_id:
				browser_key = f'{final_media_type}|{provider}|{provider_id}'
			else:
				browser_key = f'{final_media_type}|{self._normalize_search_text(final_title)}|{year}'

			group = groups.get(browser_key)
			if group is None:
				group = {
					'browser_key': browser_key,
					'media_hash': row.get('hash'),
					'media_type': final_media_type,
					'provider': provider,
					'provider_id': provider_id,
					'title': final_title,
					'released': final_released,
					'genres': final_genres,
					'overview': final_overview,
					'cover_url': final_cover_url,
					'backdrop_url': final_backdrop_url,
					'vote_average': final_vote_average,
					'vote_count': final_vote_count,
					'updated_at': row.get('updated_at') or '',
					'series_title': final_title,
					'cast_names': [],
					'crew_names': [],
					'cast_text': final_cast_text,
					'crew_text': final_crew_text,
					'rows': []
				}
				groups[browser_key] = group

			for name in cast_names:
				if name not in group['cast_names']:
					group['cast_names'].append(name)
			for name in crew_names:
				if name not in group['crew_names']:
					group['crew_names'].append(name)
			group['cast_text'] = _db_people_text(group['cast_names'], 30)
			group['crew_text'] = _db_people_text(group['crew_names'], 30)

			group['rows'].append({
				'id': row.get('id'),
				'hash': row.get('hash'),
				'file_path': row.get('file_path') or '',
				'file_name': row.get('file_name') or '',
				'search_string': row.get('search_string') or '',
				'updated_at': row.get('updated_at') or '',
				'metadata_subtitle': row.get('metadata_subtitle') or '',
				'metadata_overview': row.get('metadata_overview') or '',
				'metadata_image_path': row.get('metadata_image_path') or '',
				'metadata_cover_path': row.get('metadata_cover_path') or '',
				'metadata_backdrop_path': row.get('metadata_backdrop_path') or '',
				'metadata_released': row.get('metadata_released') or '',
			})

			if row.get('updated_at') and row.get('updated_at') > group['updated_at']:
				group['updated_at'] = row.get('updated_at')
				group['media_hash'] = row.get('hash')

			if not group['overview'] and final_overview:
				group['overview'] = final_overview
			if not group['cover_url'] and final_cover_url:
				group['cover_url'] = final_cover_url
			if not group['backdrop_url'] and final_backdrop_url:
				group['backdrop_url'] = final_backdrop_url
			if not group['genres'] and final_genres:
				group['genres'] = final_genres
			if not group['released'] and final_released:
				group['released'] = final_released
			if not group['title'] and final_title:
				group['title'] = final_title

		people_index_enabled = _db_browser_people_schema_available(conn)
		if people_index_enabled:
			try:
				conn.execute('DELETE FROM e2mdb_browser_index_people')
			except Exception as e:
				people_index_enabled = False
				write_log(f'[e2MDB] Browser people index disabled during rebuild: {e}')
		conn.execute('DELETE FROM e2mdb_browser_series_episodes')
		conn.execute('DELETE FROM e2mdb_browser_series_seasons')
		conn.execute('DELETE FROM e2mdb_browser_index')

		browser_count = 0
		for group in groups.values():
			title = group['title'] or ''
			title_norm = self._normalize_search_text(title)
			sort_title = _browser_sort_title(self, title)
			letter = _browser_letter_for_title(self, title)
			year = str(group['released'] or '')[:4]
			season_count = 0
			episode_count = 0

			if (group['media_type'] or '').lower() == 'series':
				season_map = {}
				for row in group['rows']:
					season_no, episode_no = self._parse_season_episode_from_name(row.get('file_name') or row.get('search_string') or '')
					if season_no is None or episode_no is None:
						continue
					preview_path = _browser_find_preview_path(self, row.get('file_path'), row.get('file_name'), None, row.get('metadata_image_path') or row.get('metadata_cover_path') or '')
					cover_url = row.get('metadata_cover_path') or group['cover_url'] or ''
					backdrop_url = row.get('metadata_backdrop_path') or group['backdrop_url'] or ''
					ep_title = row.get('metadata_subtitle') or fileStem(row.get('file_name') or '')
					ep_overview = row.get('metadata_overview') or ''
					ep_air_date = row.get('metadata_released') or ''

					conn.execute("""
						INSERT OR REPLACE INTO e2mdb_browser_series_episodes
						(browser_key, season_no, episode_no, media_hash, file_name, file_path, preview_path, title, overview, air_date, cover_url, backdrop_url)
						VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					""", (
						group['browser_key'],
						int(season_no),
						int(episode_no),
						row.get('hash'),
						row.get('file_name') or '',
						row.get('file_path') or '',
						preview_path,
						ep_title,
						ep_overview,
						ep_air_date,
						cover_url,
						backdrop_url
					))
					season_map.setdefault(int(season_no), 0)
					season_map[int(season_no)] += 1

				if season_map:
					for season_no in sorted(season_map):
						conn.execute(
							"INSERT OR REPLACE INTO e2mdb_browser_series_seasons (browser_key, season_no, episode_count) VALUES (?, ?, ?)",
							(group['browser_key'], season_no, season_map[season_no])
						)
					season_count = len(season_map)
					episode_count = sum(season_map.values())

			conn.execute("""
				INSERT OR REPLACE INTO e2mdb_browser_index
				(browser_key, media_hash, media_type, provider, provider_id, title, title_norm, sort_title, year, released, genres, overview, cover_url, backdrop_url, vote_average, vote_count, season_count, episode_count, series_title, cast_text, crew_text, letter, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""", (
				group['browser_key'],
				group['media_hash'],
				group['media_type'],
				group['provider'],
				group['provider_id'],
				title,
				title_norm,
				sort_title,
				year,
				group['released'],
				group['genres'],
				group['overview'],
				group['cover_url'],
				group['backdrop_url'],
				group['vote_average'],
				group['vote_count'],
				season_count,
				episode_count,
				group['series_title'],
				group['cast_text'],
				group['crew_text'],
				letter,
				group['updated_at']
			))

			if people_index_enabled:
				try:
					for role, names in (('cast', group.get('cast_names') or []), ('crew', group.get('crew_names') or [])):
						for index, name in enumerate(names):
							person_id = _db_upsert_person(conn, name)
							if person_id:
								conn.execute("""
									INSERT OR REPLACE INTO e2mdb_browser_index_people (browser_key, person_id, role, ord)
									VALUES (?, ?, ?, ?)
								""", (group['browser_key'], person_id, role, index))
				except Exception as e:
					people_index_enabled = False
					write_log(f'[e2MDB] Browser people index disabled while adding people: {e}')
			browser_count += 1

		conn.execute("INSERT OR REPLACE INTO e2mdb_meta (key, value) VALUES (?, ?)", ('browser_cache_dirty', '0'))
		conn.execute("INSERT OR REPLACE INTO e2mdb_meta (key, value) VALUES (?, ?)", ('browser_cache_count', str(browser_count)))
		conn.commit()

	write_log(f'[e2MDB] Rebuilt browser cache with {browser_count} visible items from SQLite display data only, skipped {skipped_no_final} non-final items')
	return True


def _browser_filters_sql(self, media_type='all', search_term='', year='', genre='', letter='', cast=''):
	clauses = []
	params = []
	media_type = (media_type or 'all').strip().lower()
	if media_type in ('movie', 'series'):
		clauses.append('LOWER(COALESCE(media_type, "")) = ?')
		params.append(media_type)
	search_term = self._normalize_search_text(search_term or '')
	if search_term:
		prefix = f'{search_term}%'
		contains = f'% {search_term}%'
		clauses.append("""(title_norm LIKE ? OR title_norm LIKE ? OR EXISTS (
			SELECT 1
			FROM e2mdb_browser_index_people bip_search
			JOIN e2mdb_people p_search ON p_search.id = bip_search.person_id
			WHERE bip_search.browser_key = e2mdb_browser_index.browser_key
			AND (p_search.name_norm LIKE ? OR p_search.name_norm LIKE ?)
		))""")
		params.extend([prefix, contains, prefix, contains])
	year = (year or '').strip()
	if len(year) == 4 and year.isdigit():
		clauses.append('year = ?')
		params.append(year)
	genre = (genre or '').strip().lower()
	if genre:
		clauses.append('LOWER(COALESCE(genres, "")) LIKE ?')
		params.append(f'%{genre}%')
	letter = (letter or '').strip().upper()
	if letter:
		clauses.append('letter = ?')
		params.append(letter)
	cast = self._normalize_search_text(cast or '')
	if cast:
		prefix = f'{cast}%'
		contains = f'% {cast}%'
		plain = f'%{cast}%'
		# Fast path through the optional people index, plus a text fallback.
		# The fallback keeps cast search usable while the people index is still being built.
		clauses.append("""(
			EXISTS (
				SELECT 1
				FROM e2mdb_browser_index_people bip_cast
				JOIN e2mdb_people p_cast ON p_cast.id = bip_cast.person_id
				WHERE bip_cast.browser_key = e2mdb_browser_index.browser_key
				AND bip_cast.role = 'cast'
				AND (p_cast.name_norm LIKE ? OR p_cast.name_norm LIKE ? OR LOWER(p_cast.name) LIKE ?)
			)
			OR LOWER(COALESCE(cast_text, '')) LIKE ?
		)""")
		params.extend([prefix, contains, plain, plain])
	where_sql = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
	return where_sql, params


def _browser_direct_key_sql(alias="m"):
	return f"""LOWER(COALESCE({alias}.metadata_media_type, '')) || '|' || CASE
		WHEN COALESCE({alias}.metadata_provider, '') != '' AND COALESCE({alias}.metadata_provider_ids, '') != '' THEN LOWER(COALESCE({alias}.metadata_provider, '')) || '|' || LOWER(COALESCE({alias}.metadata_provider_ids, ''))
		ELSE LOWER(COALESCE(NULLIF({alias}.metadata_title, ''), {alias}.search_string, {alias}.file_name, '')) || '|' || SUBSTR(COALESCE(NULLIF({alias}.metadata_released, ''), {alias}.metadata_year, ''), 1, 4)
	END"""


def _browser_direct_filters_sql(self, media_type="all", search_term="", year="", genre="", letter="", cast=""):
	clauses = ["LOWER(COALESCE(m.metadata_media_type, '')) IN ('movie', 'series')", "COALESCE(m.metadata_title, '') != ''"]
	params = []
	media_type = (media_type or "all").strip().lower()
	if media_type in ("movie", "series"):
		clauses.append("LOWER(COALESCE(m.metadata_media_type, '')) = ?")
		params.append(media_type)
	search_norm = self._normalize_search_text(search_term or "")
	if search_norm:
		search_plain = str(search_term or "").strip().lower()
		prefix = f"{search_norm}%"
		contains = f"% {search_norm}%"
		plain = f"%{search_plain or search_norm}%"
		clauses.append("""(
			COALESCE(m.search_string_norm, '') LIKE ? OR COALESCE(m.search_string_norm, '') LIKE ? OR
			LOWER(COALESCE(m.metadata_title, '')) LIKE ? OR LOWER(COALESCE(m.file_name, '')) LIKE ?
		)""")
		params.extend([prefix, contains, plain, plain])
	year = (year or "").strip()
	if len(year) == 4 and year.isdigit():
		clauses.append("SUBSTR(COALESCE(NULLIF(m.metadata_released, ''), m.metadata_year, ''), 1, 4) = ?")
		params.append(year)
	genre = (genre or "").strip().lower()
	if genre:
		clauses.append("LOWER(COALESCE(m.metadata_genres, '')) LIKE ?")
		params.append(f"%{genre}%")
	letter = (letter or "").strip().upper()
	if letter:
		if letter == "0-9":
			clauses.append("SUBSTR(UPPER(COALESCE(NULLIF(m.metadata_title, ''), m.search_string, m.file_name, '')), 1, 1) BETWEEN '0' AND '9'")
		else:
			clauses.append("SUBSTR(UPPER(COALESCE(NULLIF(m.metadata_title, ''), m.search_string, m.file_name, '')), 1, 1) = ?")
			params.append(letter)
	cast = self._normalize_search_text(cast or "")
	if cast:
		prefix = f"{cast}%"
		contains = f"% {cast}%"
		plain = f"%{cast}%"
		# Direct fallback must still filter by cast. Use both the normalized people
		# table and the raw metadata_cast JSON/text field so the search works even
		# while the browser/people index is not ready yet.
		clauses.append("""(
			LOWER(COALESCE(m.metadata_cast, '')) LIKE ?
			OR EXISTS (
				SELECT 1
				FROM e2mdb_media_people mp_cast
				JOIN e2mdb_people p_cast ON p_cast.id = mp_cast.person_id
				WHERE mp_cast.media_id = m.id
				AND mp_cast.role = 'cast'
				AND (p_cast.name_norm LIKE ? OR p_cast.name_norm LIKE ? OR LOWER(p_cast.name) LIKE ?)
			)
		)""")
		params.extend([plain, prefix, contains, plain])
	where_sql = "WHERE " + " AND ".join(clauses)
	return where_sql, params


def _browser_direct_provider_id(provider, provider_ids_raw):
	provider = str(provider or "").strip().lower()
	provider_ids = _browser_decode_provider_ids(provider_ids_raw or "")
	if isinstance(provider_ids, dict):
		if provider and provider_ids.get(provider):
			return str(provider_ids.get(provider) or "")
		for fallback_key in ("tmdb", "tvdb", "imdb", "tvmaze", "anime", "anilist", "kitsu", "omdb"):
			if provider_ids.get(fallback_key):
				return str(provider_ids.get(fallback_key) or "")
	return ""


def _browser_names_from_metadata(value, limit=120):
	names = []
	for entry in _db_loads_list(value or ""):
		if isinstance(entry, dict):
			person = entry.get("person")
			name = person.get("name") if isinstance(person, dict) else ""
			name = name or entry.get("name") or entry.get("actor") or entry.get("person_name") or entry.get("title") or ""
		else:
			name = entry
		name = _db_normalize_person_name(name)
		if name and name not in names:
			names.append(name)
			if len(names) >= int(limit or 120):
				break
	return names


def _browser_direct_people(self, browser_key, conn=None):
	def read_people(active_conn):
		if not _db_people_schema_available(active_conn):
			return [], []
		key_sql = _browser_direct_key_sql("m")
		rows = active_conn.execute(f"""
			SELECT p.name, mp.role, MIN(COALESCE(mp.ord, 0)) AS ord
			FROM e2mdb_media m
			JOIN e2mdb_media_people mp ON mp.media_id = m.id
			JOIN e2mdb_people p ON p.id = mp.person_id
			WHERE ({key_sql}) = ?
			AND mp.role IN ('cast', 'crew')
			GROUP BY p.name, mp.role
			ORDER BY mp.role ASC, ord ASC, p.name COLLATE NOCASE ASC
			LIMIT 240
		""", (browser_key,)).fetchall()
		cast_names, crew_names = [], []
		for person in rows:
			name = person["name"] or ""
			if person["role"] == "cast" and name not in cast_names:
				cast_names.append(name)
			elif person["role"] == "crew" and name not in crew_names:
				crew_names.append(name)
		return cast_names, crew_names
	try:
		if conn is not None:
			return read_people(conn)
		with self._connect() as local_conn:
			local_conn.row_factory = Row
			return read_people(local_conn)
	except Exception:
		return [], []


def _browser_direct_item_from_row(self, row, conn=None):
	item = dict(row)
	provider = str(item.get("provider") or item.get("metadata_provider") or "").strip().lower()
	provider_ids = item.get("provider_ids") or item.get("metadata_provider_ids") or ""
	released = item.get("released") or item.get("metadata_released") or item.get("metadata_year") or ""
	year = item.get("year") or str(released or "")[:4]
	browser_key = item.get("browser_key") or ""
	if not browser_key:
		media_type = str(item.get("media_type") or item.get("metadata_media_type") or "").strip().lower()
		provider_id = _browser_direct_provider_id(provider, provider_ids)
		if provider and provider_id:
			browser_key = f"{media_type}|{provider}|{provider_id}"
		else:
			browser_key = f"{media_type}|{self._normalize_search_text(item.get('metadata_title') or item.get('title') or item.get('search_string') or item.get('file_name') or '')}|{year}"
	cast_names = _browser_names_from_metadata(item.get("metadata_cast") or "")
	crew_names = _browser_names_from_metadata(item.get("metadata_crew") or "")
	if not cast_names and not crew_names:
		cast_names, crew_names = _browser_direct_people(self, browser_key, conn=conn)
	cover_url = item.get("cover_url") or item.get("metadata_cover_path") or item.get("metadata_image_path") or ""
	media_type = str(item.get("media_type") or item.get("metadata_media_type") or "").strip().lower()
	try:
		vote_average = float(item.get("vote_average") or item.get("metadata_rating") or 0.0)
	except Exception:
		vote_average = 0.0
	try:
		vote_count = int(float(item.get("vote_count") or item.get("metadata_vote_count") or 0))
	except Exception:
		vote_count = 0
	result = {
		"id": item.get("media_hash") or item.get("hash") or browser_key,
		"browser_key": browser_key,
		"media_hash": item.get("media_hash") or item.get("hash") or "",
		"media_type": media_type,
		"provider": provider,
		"provider_id": item.get("provider_id") or _browser_direct_provider_id(provider, provider_ids),
		"title": item.get("title") or item.get("metadata_title") or item.get("search_string") or item.get("file_name") or "",
		"title_norm": item.get("title_norm") or self._normalize_search_text(item.get("title") or item.get("metadata_title") or item.get("search_string") or ""),
		"sort_title": item.get("sort_title") or _browser_sort_title(self, item.get("title") or item.get("metadata_title") or item.get("search_string") or ""),
		"year": str(year or "")[:4],
		"released": released or "",
		"genres": item.get("genres") or item.get("metadata_genres") or "",
		"overview": item.get("overview") or item.get("metadata_overview") or "",
		"cover_url": cover_url,
		"backdrop_url": item.get("backdrop_url") or item.get("metadata_backdrop_path") or "",
		"vote_average": vote_average,
		"vote_count": vote_count,
		"season_count": int(item.get("season_count") or 0),
		"episode_count": int(item.get("episode_count") or item.get("file_count") or 0),
		"series_title": item.get("series_title") or item.get("title") or item.get("metadata_title") or "",
		"cast": cast_names,
		"crew": crew_names,
		"cast_text": _db_people_text(cast_names, 30),
		"crew_text": _db_people_text(crew_names, 30),
		"letter": item.get("letter") or _browser_letter_for_title(self, item.get("title") or item.get("metadata_title") or item.get("search_string") or ""),
		"updated_at": item.get("updated_at") or "",
		"file_name": item.get("file_name") or "",
		"file_path": item.get("file_path") or "",
		"cache_status": "direct",
	}
	return result


def _direct_get_series_inventory_by_item(self, item, conn=None):
	def read_inventory(active_conn):
		browser_key = item.get("browser_key") or ""
		if not browser_key:
			return {"series_title": item.get("title") or "", "season_count": 0, "episode_count": 0, "seasons": [], "files": [], "browser_key": browser_key, "cast": item.get("cast", [])}
		key_sql = _browser_direct_key_sql("m")
		rows = active_conn.execute(f"""
			SELECT m.hash, m.file_name, m.file_path, m.search_string, m.metadata_subtitle, m.metadata_overview,
				m.metadata_image_path, m.metadata_cover_path, m.metadata_backdrop_path, m.metadata_released
			FROM e2mdb_media m
			WHERE ({key_sql}) = ?
			ORDER BY m.file_name COLLATE NOCASE ASC
		""", (browser_key,)).fetchall()
		season_map = {}
		files = []
		for row in rows:
			season_no, episode_no = self._parse_season_episode_from_name(row["file_name"] or row["search_string"] or "")
			if season_no is None or episode_no is None:
				continue
			entry = {
				"id": row["hash"],
				"file_name": row["file_name"] or "",
				"episode_no": int(episode_no),
				"title": row["metadata_subtitle"] or fileStem(row["file_name"] or ""),
				"overview": row["metadata_overview"] or "",
				"released": row["metadata_released"] or "",
				"air_date": row["metadata_released"] or "",
				"preview_path": row["metadata_image_path"] or row["metadata_cover_path"] or "",
			}
			season_map.setdefault(int(season_no), []).append(entry)
			files.append({"id": row["hash"], "file_name": row["file_name"] or ""})
		seasons = []
		for season_no in sorted(season_map):
			items = sorted(season_map[season_no], key=lambda x: int(x.get("episode_no") or 0))
			seasons.append({
				"season_no": season_no,
				"episode_count": len(items),
				"episodes": [item.get("episode_no") for item in items],
				"items": items,
				"files": [item.get("file_name") for item in items],
			})
		episode_count = sum(int(season.get("episode_count") or 0) for season in seasons)
		return {
			"series_title": item.get("series_title") or item.get("title") or "",
			"season_count": len(seasons),
			"episode_count": episode_count,
			"seasons": seasons,
			"files": files,
			"browser_key": browser_key,
			"cast": item.get("cast", []),
		}
	try:
		if conn is not None:
			return read_inventory(conn)
		with self._connect() as local_conn:
			local_conn.row_factory = Row
			return read_inventory(local_conn)
	except Exception as e:
		write_log(f"[e2MDB] Error reading direct series inventory: {e}")
		return {"series_title": item.get("title") or "", "season_count": 0, "episode_count": 0, "seasons": [], "files": [], "browser_key": item.get("browser_key") or "", "cast": item.get("cast", [])}


def _direct_get_browser_media(self, page=1, limit=None, media_type="all", search_term="", year="", genre="", letter="", cast=""):
	try:
		_browser_create_tables(self)
		page = max(1, int(page or 1))
		limit = max(1, min(int(limit or self.ITEMS_PER_PAGE), 100))
		offset = (page - 1) * limit
		key_sql = _browser_direct_key_sql("m")
		where_sql, params = _browser_direct_filters_sql(self, media_type, search_term, year, genre, letter, cast)
		chunk_size = max(limit * 5, 120)
		row_offset = 0
		groups = {}
		ordered = []
		exhausted = False
		with self._connect() as conn:
			conn.row_factory = Row
			while len(ordered) < (offset + limit + 1):
				rows = conn.execute(f"""
					SELECT m.*, {key_sql} AS browser_key
					FROM e2mdb_media m
					{where_sql}
					ORDER BY m.metadata_title COLLATE NOCASE ASC, m.updated_at DESC
					LIMIT ? OFFSET ?
				""", tuple(list(params) + [chunk_size, row_offset])).fetchall()
				if not rows:
					exhausted = True
					break
				for row in rows:
					group_key = row["browser_key"] or row["hash"]
					item = groups.get(group_key)
					if item is None:
						item = _browser_direct_item_from_row(self, row, conn=conn)
						groups[group_key] = item
						ordered.append(item)
					else:
						if not item.get("overview") and row["metadata_overview"]:
							item["overview"] = row["metadata_overview"]
						if not item.get("cover_url") and (row["metadata_cover_path"] or row["metadata_image_path"]):
							item["cover_url"] = row["metadata_cover_path"] or row["metadata_image_path"]
						if not item.get("backdrop_url") and row["metadata_backdrop_path"]:
							item["backdrop_url"] = row["metadata_backdrop_path"]
				row_offset += len(rows)
				if len(rows) < chunk_size:
					exhausted = True
					break
			items = ordered[offset:offset + limit]
			for item in items:
				if item.get("media_type") == "series":
					inventory = _direct_get_series_inventory_by_item(self, item, conn=conn)
					item["season_count"] = inventory.get("season_count", 0)
					item["episode_count"] = inventory.get("episode_count", 0)
					item["seasons"] = [{"season_no": s.get("season_no"), "episode_count": s.get("episode_count")} for s in inventory.get("seasons", [])]
			has_more = len(ordered) > (offset + limit)
			if not has_more and not exhausted:
				has_more = True
			return {"page": page, "limit": limit, "has_more": has_more, "items": items, "cache_status": "direct"}
	except Exception as e:
		write_log(f"[e2MDB] Error getting direct browser media: {e}")
		return {"page": 1, "limit": limit or self.ITEMS_PER_PAGE, "has_more": False, "items": [], "cache_status": "direct-error"}


def _direct_get_browser_item(self, result_id):
	try:
		_browser_create_tables(self)
		key_sql = _browser_direct_key_sql("m")
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute(f"""
				SELECT m.*, {key_sql} AS browser_key
				FROM e2mdb_media m
				WHERE m.hash = ? OR ({key_sql}) = ?
				ORDER BY m.updated_at DESC
				LIMIT 1
			""", (result_id, result_id)).fetchone()
			if not row:
				return {}
			item = _browser_direct_item_from_row(self, row, conn=conn)
			if item.get("media_type") == "series":
				inventory = _direct_get_series_inventory_by_item(self, item, conn=conn)
				item["season_count"] = inventory.get("season_count", 0)
				item["episode_count"] = inventory.get("episode_count", 0)
				item["seasons"] = [{"season_no": s.get("season_no"), "episode_count": s.get("episode_count")} for s in inventory.get("seasons", [])]
			return item
	except Exception as e:
		write_log(f"[e2MDB] Error getting direct browser item: {e}")
		return {}


def _direct_get_browser_facets(self, media_type="all", search_term="", letter="", cast=""):
	try:
		_browser_create_tables(self)
		with self._connect() as conn:
			conn.row_factory = Row
			where_sql, params = _browser_direct_filters_sql(self, media_type, search_term, "", "", letter, cast)
			rows = conn.execute(f"""
				SELECT m.metadata_year, m.metadata_released, m.metadata_genres
				FROM e2mdb_media m
				{where_sql}
				LIMIT 10000
			""", tuple(params)).fetchall()
			years, genres = set(), set()
			for row in rows:
				year = str(row["metadata_released"] or row["metadata_year"] or "")[:4]
				if len(year) == 4 and year.isdigit():
					years.add(year)
				for part in str(row["metadata_genres"] or "").split(","):
					part = part.strip()
					if part:
						genres.add(part)
			return {"years": sorted(years, reverse=True), "genres": sorted(genres), "casts": [], "cache_status": "direct"}
	except Exception as e:
		write_log(f"[e2MDB] Error getting direct browser facets: {e}")
		return {"years": [], "genres": [], "casts": [], "cache_status": "direct-error"}


def _direct_get_browser_season_details(self, result_id, season_no):
	try:
		item = _direct_get_browser_item(self, result_id)
		if not item:
			return {"episodes": []}
		inventory = _direct_get_series_inventory_by_item(self, item)
		selected = []
		for season in inventory.get("seasons", []):
			if str(season.get("season_no")) == str(season_no):
				selected = season.get("items", []) or []
				break
		episodes = []
		for entry in selected:
			episodes.append({
				"id": entry.get("id") or "",
				"episode_no": entry.get("episode_no") or "",
				"episode_name": entry.get("title") or fileStem(entry.get("file_name") or ""),
				"overview": entry.get("overview") or "",
				"released": entry.get("released") or "",
				"cover_url": item.get("cover_url") or "",
				"preview_url": f"api/results?action=preview&id={entry.get('id')}" if entry.get("id") else "",
				"preview_path": entry.get("preview_path") or "",
				"backdrop_url": item.get("backdrop_url") or "",
				"file_name": entry.get("file_name") or "",
			})
		return {"episodes": episodes}
	except Exception as e:
		write_log(f"[e2MDB] Error getting direct browser season details: {e}")
		return {"episodes": []}


def _new_get_browser_media(self, page=1, limit=None, media_type='all', search_term='', year='', genre='', letter='', cast=''):
	try:
		cache_ready = _ensure_browser_cache(self, allow_rebuild=False, background=True)
		status = _browser_index_status(self)
		if not cache_ready or not status.get("index_ready"):
			data = _direct_get_browser_media(self, page=page, limit=limit, media_type=media_type, search_term=search_term, year=year, genre=genre, letter=letter, cast=cast)
			data.update(status)
			data['cache_status'] = 'building' if status.get('index_building') else 'direct'
			return data
		page = max(1, int(page or 1))
		limit = max(1, min(int(limit or self.ITEMS_PER_PAGE), 100))
		offset = (page - 1) * limit
		with self._connect() as conn:
			conn.row_factory = Row
			where_sql, params = _browser_filters_sql(self, media_type, search_term, year, genre, letter, cast)
			rows = conn.execute(f"SELECT * FROM e2mdb_browser_index {where_sql} ORDER BY sort_title ASC, updated_at DESC LIMIT ? OFFSET ?", tuple(list(params) + [limit + 1, offset])).fetchall()
			if not rows and not cache_ready and page == 1:
				data = _direct_get_browser_media(self, page=page, limit=limit, media_type=media_type, search_term=search_term, year=year, genre=genre, letter=letter, cast=cast)
				data.update(status)
				data['cache_status'] = 'building' if status.get('index_building') else 'direct'
				return data
			has_more = len(rows) > limit
			rows = rows[:limit]
			items = []
			for row in rows:
				item = dict(row)
				item['id'] = item.get('media_hash') or item.get('browser_key')
				item['browser_key'] = item.get('browser_key')
				people = conn.execute("""
					SELECT p.name, bip.role
					FROM e2mdb_browser_index_people bip
					JOIN e2mdb_people p ON p.id = bip.person_id
					WHERE bip.browser_key = ?
					ORDER BY bip.role ASC, bip.ord ASC, p.name COLLATE NOCASE ASC
				""", (item['browser_key'],)).fetchall()
				cast_names, crew_names = [], []
				for person in people:
					name = person['name'] or ''
					if person['role'] == 'cast' and name not in cast_names:
						cast_names.append(name)
					elif person['role'] == 'crew' and name not in crew_names:
						crew_names.append(name)
				if not cast_names:
					cast_names = [x.strip() for x in (item.get('cast_text') or '').split(',') if x.strip()]
				if not crew_names:
					crew_names = [x.strip() for x in (item.get('crew_text') or '').split(',') if x.strip()]
				item['cast'] = cast_names
				item['crew'] = crew_names
				item['cast_text'] = _db_people_text(cast_names, 30)
				item['crew_text'] = _db_people_text(crew_names, 30)
				item['cache_status'] = 'ready' if cache_ready else 'stale'
				if item.get('media_type') == 'series':
					seasons = conn.execute("SELECT season_no, episode_count FROM e2mdb_browser_series_seasons WHERE browser_key = ? ORDER BY season_no", (item['browser_key'],)).fetchall()
					item['seasons'] = [{"season_no": s['season_no'], "episode_count": s['episode_count']} for s in seasons]
				items.append(item)
			result = {'page': page, 'limit': limit, 'has_more': has_more, 'items': items, 'cache_status': 'ready' if cache_ready else 'stale'}
			result.update(status)
			return result
	except Exception as e:
		write_log(f'[e2MDB] Error getting browser media: {e}')
		data = _direct_get_browser_media(self, page=page, limit=limit, media_type=media_type, search_term=search_term, year=year, genre=genre, letter=letter, cast=cast)
		try:
			data.update(_browser_index_status(self))
		except Exception:
			pass
		return data


def _new_get_browser_item(self, result_id):
	try:
		cache_ready = _ensure_browser_cache(self, allow_rebuild=False, background=True)
		if not cache_ready or not _browser_cache_is_ready(self):
			return _direct_get_browser_item(self, result_id)
		if _browser_cache_has_rows(self):
			with self._connect() as conn:
				conn.row_factory = Row
				row = conn.execute("SELECT * FROM e2mdb_browser_index WHERE media_hash = ? OR browser_key = ? LIMIT 1", (result_id, result_id)).fetchone()
				if row:
					item = dict(row)
					item['id'] = item.get('media_hash') or item.get('browser_key')
					people = conn.execute("""
						SELECT p.name, bip.role
						FROM e2mdb_browser_index_people bip
						JOIN e2mdb_people p ON p.id = bip.person_id
						WHERE bip.browser_key = ?
						ORDER BY bip.role ASC, bip.ord ASC, p.name COLLATE NOCASE ASC
					""", (item.get('browser_key'),)).fetchall()
					cast_names, crew_names = [], []
					for person in people:
						name = person['name'] or ''
						if person['role'] == 'cast' and name not in cast_names:
							cast_names.append(name)
						elif person['role'] == 'crew' and name not in crew_names:
							crew_names.append(name)
					if not cast_names:
						cast_names = [x.strip() for x in (item.get('cast_text') or '').split(',') if x.strip()]
					if not crew_names:
						crew_names = [x.strip() for x in (item.get('crew_text') or '').split(',') if x.strip()]
					item['cast'] = cast_names
					item['crew'] = crew_names
					item['cast_text'] = _db_people_text(cast_names, 30)
					item['crew_text'] = _db_people_text(crew_names, 30)
					item['cache_status'] = 'ready' if cache_ready else 'stale'
					return item
		return _direct_get_browser_item(self, result_id)
	except Exception as e:
		write_log(f'[e2MDB] Error getting browser item: {e}')
		return _direct_get_browser_item(self, result_id)


def _new_get_browser_facets(self, media_type='all', search_term='', letter='', cast=''):
	try:
		cache_ready = _ensure_browser_cache(self, allow_rebuild=False, background=True)
		status = _browser_index_status(self)
		if not cache_ready or not status.get('index_ready'):
			facets = _direct_get_browser_facets(self, media_type=media_type, search_term=search_term, letter=letter, cast=cast)
			facets.update(status)
			facets['years'] = []
			facets['genres'] = []
			facets['casts'] = []
			return facets
		effective_cast = cast if status.get('people_index_ready') else ''
		with self._connect() as conn:
			conn.row_factory = Row
			where_sql, params = _browser_filters_sql(self, media_type, search_term, '', '', letter, effective_cast)
			rows = conn.execute(f"SELECT year, genres FROM e2mdb_browser_index {where_sql} LIMIT 10000", tuple(params)).fetchall()
			years, genres = set(), set()
			for row in rows:
				year = str(row['year'] or '').strip()
				if len(year) == 4 and year.isdigit():
					years.add(year)
				for part in str(row['genres'] or '').split(','):
					part = part.strip()
					if part:
						genres.add(part)
			casts = []
			if status.get('people_index_ready') and _db_browser_people_schema_available(conn):
				people_where_sql, people_params = _browser_filters_sql(self, media_type, search_term, '', '', letter, '')
				people_rows = conn.execute(f"""
					SELECT DISTINCT p.name
					FROM e2mdb_browser_index
					JOIN e2mdb_browser_index_people bip ON bip.browser_key = e2mdb_browser_index.browser_key AND bip.role = 'cast'
					JOIN e2mdb_people p ON p.id = bip.person_id
					{people_where_sql}
					ORDER BY p.name COLLATE NOCASE ASC
					LIMIT 2000
				""", tuple(people_params)).fetchall()
				casts = [row['name'] for row in people_rows if row['name']]
			result = {'years': sorted(years, reverse=True), 'genres': sorted(genres), 'casts': casts, 'cache_status': 'ready' if cache_ready else 'stale'}
			result.update(status)
			return result
	except Exception as e:
		write_log(f'[e2MDB] Error getting browser facets: {e}')
		facets = _direct_get_browser_facets(self, media_type=media_type, search_term=search_term, letter=letter, cast=cast)
		try:
			facets.update(_browser_index_status(self))
		except Exception:
			pass
		facets['casts'] = []
		return facets


def _new_get_browser_index_status(self):
	try:
		_ensure_browser_cache(self, allow_rebuild=False, background=True)
		return _browser_index_status(self)
	except Exception as e:
		write_log(f"[e2MDB] Error getting browser index status: {e}")
		return {"index_ready": False, "index_building": False, "people_index_ready": False}


def _new_get_series_inventory(self, result_id):
	try:
		item = _new_get_browser_item(self, result_id)
		if not item or (item.get('media_type') or '').lower() != 'series':
			return {'series_title': '', 'season_count': 0, 'episode_count': 0, 'seasons': [], 'files': []}
		if item.get('cache_status') == 'direct' or not _browser_cache_is_ready(self):
			return _direct_get_series_inventory_by_item(self, item)
		with self._connect() as conn:
			conn.row_factory = Row
			browser_key = item.get('browser_key')
			season_rows = conn.execute("SELECT season_no, episode_count FROM e2mdb_browser_series_seasons WHERE browser_key = ? ORDER BY season_no", (browser_key,)).fetchall()
			if not season_rows and not _ensure_browser_cache(self, allow_rebuild=False, background=True):
				return _direct_get_series_inventory_by_item(self, item)
			seasons = []
			files = []
			for season_row in season_rows:
				ep_rows = conn.execute("SELECT media_hash, file_name, episode_no, preview_path FROM e2mdb_browser_series_episodes WHERE browser_key = ? AND season_no = ? ORDER BY episode_no", (browser_key, season_row['season_no'])).fetchall()
				items = []
				episodes = []
				for ep in ep_rows:
					items.append({'id': ep['media_hash'], 'file_name': ep['file_name'], 'episode_no': ep['episode_no'], 'preview_path': ep['preview_path'] or ''})
					files.append({'id': ep['media_hash'], 'file_name': ep['file_name']})
					episodes.append(ep['episode_no'])
				seasons.append({'season_no': season_row['season_no'], 'episode_count': season_row['episode_count'], 'episodes': episodes, 'items': items, 'files': [x['file_name'] for x in items]})
			return {'series_title': item.get('series_title') or item.get('title') or '', 'season_count': int(item.get('season_count') or len(seasons)), 'episode_count': int(item.get('episode_count') or sum(int(x.get('episode_count') or 0) for x in seasons)), 'seasons': seasons, 'files': files, 'browser_key': browser_key, 'cast': item.get('cast', [])}
	except Exception as e:
		write_log(f'[e2MDB] Error getting series inventory: {e}')
		return {'series_title': '', 'season_count': 0, 'episode_count': 0, 'seasons': [], 'files': []}


def _new_get_browser_season_details(self, result_id, season_no):
	try:
		item = _new_get_browser_item(self, result_id)
		if not item:
			return {'episodes': []}
		if item.get('cache_status') == 'direct' or not _browser_cache_is_ready(self):
			return _direct_get_browser_season_details(self, result_id, season_no)
		with self._connect() as conn:
			conn.row_factory = Row
			rows = conn.execute("SELECT * FROM e2mdb_browser_series_episodes WHERE browser_key = ? AND season_no = ? ORDER BY episode_no", (item.get('browser_key'), int(season_no))).fetchall()
			if not rows and not _ensure_browser_cache(self, allow_rebuild=False, background=True):
				return _direct_get_browser_season_details(self, result_id, season_no)
			episodes = []
			for row in rows:
				cover_url = row['preview_path'] or row['cover_url'] or item.get('cover_url') or ''
				episodes.append({
					'id': row['media_hash'],
					'episode_no': row['episode_no'],
					'episode_name': row['title'] or fileStem(row['file_name'] or ''),
					'overview': row['overview'] or '',
					'released': row['air_date'] or '',
					'cover_url': cover_url,
					'preview_url': f"api/results?action=preview&id={row['media_hash']}" if row['media_hash'] else '',
					'preview_path': row['preview_path'] or '',
					'backdrop_url': row['backdrop_url'] or '',
					'file_name': row['file_name'] or ''
				})
			return {'episodes': episodes}
	except Exception as e:
		write_log(f'[e2MDB] Error getting browser season details: {e}')
		return _direct_get_browser_season_details(self, result_id, season_no)


def fileStem(name):
	return sub(r'\.[^.]+$', '', name or '').replace('.', ' ').replace('_', ' ').replace('-', ' ').strip()


def _resultsdb_update_media_metadata(self, hash_id, final_dict):
	"""Write final display-ready metadata for recordings/movies to results.db.

	The primary JSON file is only a debug/cache artifact. EventViewSimple and
	the web media browser must be able to render and search from SQLite alone.
	"""
	try:
		hash_id = str(hash_id or '').strip()
		if not hash_id or not isinstance(final_dict, dict):
			return 0
		metadata_title = _db_display_text(final_dict, 'title', 'name')
		metadata_subtitle = _db_display_text(final_dict, 'episode_name') or _db_display_text(final_dict, 'tagline')
		metadata_overview = _db_display_text(final_dict, 'overview', 'description')
		metadata_genres = _db_display_text(final_dict, 'genres')
		metadata_provider = str(final_dict.get('provider') or '')
		try:
			metadata_provider_ids = dumps(final_dict.get('provider_ids') or {}, ensure_ascii=False)
		except Exception:
			metadata_provider_ids = '{}'
		metadata_media_type = str(final_dict.get('media_type') or '')
		released = str(final_dict.get('released') or final_dict.get('firstAired') or '')
		metadata_year = released[:4] if len(released) >= 4 and released[:4].isdigit() else ''
		metadata_runtime = str(final_dict.get('runtime') or '')
		metadata_rating = str(final_dict.get('vote_average') or final_dict.get('rating') or '')
		metadata_vote_count = str(final_dict.get('vote_count') or '')
		metadata_cover_path = str(final_dict.get('cover_path') or final_dict.get('cover_url') or '')
		metadata_backdrop_path = str(final_dict.get('backdrop_path') or final_dict.get('backdrop_url') or '')
		metadata_logo_path = str(final_dict.get('titlelogo_path') or final_dict.get('logo_path') or final_dict.get('titlelogo_url') or final_dict.get('logo_url') or '')
		metadata_image_path = str(final_dict.get('image_path') or final_dict.get('preview_path') or final_dict.get('still_path') or final_dict.get('image_url') or '')
		metadata_released = released
		metadata_countries = _db_display_text(final_dict, 'countries')
		metadata_age_rating = str(final_dict.get('age_rating') or '')
		try:
			metadata_cast = dumps(final_dict.get('cast') or [], ensure_ascii=False)
		except Exception:
			metadata_cast = '[]'
		try:
			metadata_crew = dumps(final_dict.get('crew') or [], ensure_ascii=False)
		except Exception:
			metadata_crew = '[]'
		metadata_season_no = str(final_dict.get('season_no') or '')
		metadata_episode_no = str(final_dict.get('episode_no') or '')
		with self._connect() as conn:
			cur = conn.execute("""
				UPDATE e2mdb_media
				SET metadata_title = ?, metadata_subtitle = ?, metadata_overview = ?, metadata_genres = ?,
				metadata_provider = ?, metadata_provider_ids = ?, metadata_media_type = ?, metadata_year = ?, metadata_runtime = ?,
				metadata_rating = ?, metadata_vote_count = ?, metadata_cover_path = ?, metadata_backdrop_path = ?, metadata_logo_path = ?,
				metadata_image_path = ?, metadata_released = ?, metadata_countries = ?, metadata_age_rating = ?,
				metadata_cast = ?, metadata_crew = ?, metadata_season_no = ?, metadata_episode_no = ?,
				updated_at = CURRENT_TIMESTAMP
				WHERE hash = ?
			""", (
				metadata_title, metadata_subtitle, metadata_overview, metadata_genres,
				metadata_provider, metadata_provider_ids, metadata_media_type, metadata_year, metadata_runtime,
				metadata_rating, metadata_vote_count, metadata_cover_path, metadata_backdrop_path, metadata_logo_path,
				metadata_image_path, metadata_released, metadata_countries, metadata_age_rating,
				metadata_cast, metadata_crew, metadata_season_no, metadata_episode_no, hash_id
			))
			row = conn.execute("SELECT id FROM e2mdb_media WHERE hash = ? LIMIT 1", (hash_id,)).fetchone()
			if row:
				_db_sync_media_people(conn, row[0], final_dict)
			conn.commit()
			_mark_browser_cache_dirty(self)
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error updating media display metadata {hash_id}: {e}")
		return 0


def _resultsdb_get_media_metadata(self, hash_id):
	"""Return one media row including final display metadata by media hash."""
	try:
		hash_id = str(hash_id or '').strip()
		if not hash_id:
			return {}
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute("SELECT * FROM e2mdb_media WHERE hash = ? LIMIT 1", (hash_id,)).fetchone()
			return dict(row) if row else {}
	except Exception as e:
		write_log(f"[e2MDB] Error reading media display metadata {hash_id}: {e}")
		return {}


def _resultsdb_get_media_metadata_by_path(self, media_path):
	"""Return one media row by absolute file path."""
	try:
		_media_path = str(media_path or "").replace("/media/hdd", "").replace("/media/autofs", "")
		media_hash = md5(_media_path.encode()).hexdigest()
		return _resultsdb_get_media_metadata(self, media_hash)
	except Exception as e:
		write_log(f"[e2MDB] Error reading media display metadata by path {media_path}: {e}")
		return {}


def _resultsdb_get_media_display_data(self, hash_id):
	"""Return final media metadata in provider-like payload shape from SQLite."""
	row = _resultsdb_get_media_metadata(self, hash_id)
	data = _db_media_row_to_display_data(row)
	try:
		media_id = int((row or {}).get("id") or 0)
	except Exception:
		media_id = 0
	if not media_id:
		return data
	try:
		with self._connect() as conn:
			conn.row_factory = Row
			for role in ("cast", "crew"):
				rows = conn.execute("""
					SELECT p.name, mp.character, mp.job, mp.department
					FROM e2mdb_media_people mp
					JOIN e2mdb_people p ON p.id = mp.person_id
					WHERE mp.media_id = ? AND mp.role = ?
					ORDER BY mp.ord ASC, p.name COLLATE NOCASE ASC
				""", (media_id, role)).fetchall()
				entries = []
				for person in rows:
					entry = {"name": person["name"] or ""}
					if role == "cast" and person["character"]:
						entry["character"] = person["character"]
					if role == "crew":
						if person["job"]:
							entry["job"] = person["job"]
						if person["department"]:
							entry["department"] = person["department"]
					if entry.get("name"):
						entries.append(entry)
				if entries:
					data[role] = entries
					if role == "cast":
						data["cast_text"] = _db_people_text([entry.get("name") for entry in entries], 30)
	except Exception as e:
		write_log(f"[e2MDB] Error reading media people for display {hash_id}: {e}")
	return data


# --- Live / EPG metadata cache ----------------------------------------------
def _live_epg_create_tables(self):
	"""Create the separated Live/EPG tables inside the shared results database."""
	with self._connect() as conn:
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_provider_assets (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				asset_key TEXT UNIQUE NOT NULL,
				provider TEXT NOT NULL,
				provider_id TEXT NOT NULL,
				media_type TEXT DEFAULT '',
				title TEXT DEFAULT '',
				original_title TEXT DEFAULT '',
				year INTEGER DEFAULT 0,
				json_path TEXT DEFAULT '',
				episode_name TEXT DEFAULT '',
				tagline TEXT DEFAULT '',
				genres TEXT DEFAULT '',
				overview TEXT DEFAULT '',
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
			CREATE TABLE IF NOT EXISTS e2mdb_media_asset_map (
				media_id INTEGER NOT NULL,
				asset_id INTEGER NOT NULL,
				confidence REAL DEFAULT 0.0,
				provider TEXT DEFAULT '',
				created_at INTEGER DEFAULT 0,
				PRIMARY KEY (media_id, asset_id),
				FOREIGN KEY (media_id) REFERENCES e2mdb_media(id) ON DELETE CASCADE,
				FOREIGN KEY (asset_id) REFERENCES e2mdb_provider_assets(id) ON DELETE CASCADE
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
		conn.execute("""
			CREATE TABLE IF NOT EXISTS e2mdb_channel_stats (
				service_ref TEXT PRIMARY KEY,
				service_name TEXT DEFAULT '',
				zap_count INTEGER DEFAULT 0,
				watch_seconds INTEGER DEFAULT 0,
				last_seen INTEGER DEFAULT 0,
				score REAL DEFAULT 0.0,
				pinned INTEGER DEFAULT 0,
				created_at INTEGER DEFAULT 0,
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
		_db_create_people_tables(conn)
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_assets_provider ON e2mdb_provider_assets(provider, provider_id)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_provider_assets_expires ON e2mdb_provider_assets(expires_at)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_source ON e2mdb_epg_events(source_type, service_ref)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_time ON e2mdb_epg_events(begin_time, event_end)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_status ON e2mdb_epg_events(status)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_search_title ON e2mdb_epg_events(search_title)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_epg_events_expires ON e2mdb_epg_events(expires_at)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_fetch_queue_state ON e2mdb_fetch_queue(state, priority, not_before)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_fetch_queue_event_end ON e2mdb_fetch_queue(event_end)")
		conn.execute("CREATE INDEX IF NOT EXISTS idx_e2mdb_channel_stats_score ON e2mdb_channel_stats(score DESC, last_seen DESC)")
		conn.commit()


def _live_epg_now():
	try:
		from time import time
		return int(time())
	except Exception:
		return 0


def _live_epg_row_to_dict(row):
	return dict(row) if row else {}


def _live_epg_upsert_event(self, event_data):
	"""Insert or update a short-lived EPG/Live event entry."""
	try:
		now = int(event_data.get('updated_at') or _live_epg_now())
		source_key = str(event_data.get('source_key') or '').strip()
		if not source_key:
			return None
		title = str(event_data.get('title') or '')
		search_title = str(event_data.get('search_title') or title)
		title_norm = event_data.get('title_norm') or self._normalize_search_text(title)
		begin_time = int(event_data.get('begin_time') or 0)
		duration = int(event_data.get('duration') or 0)
		event_end = int(event_data.get('event_end') or (begin_time + duration if begin_time and duration else 0))
		created_at = int(event_data.get('created_at') or now)
		updated_at = now
		values = {
			'source_key': source_key,
			'source_type': str(event_data.get('source_type') or 'epg'),
			'service_ref': str(event_data.get('service_ref') or ''),
			'service_name': str(event_data.get('service_name') or ''),
			'event_id': int(event_data.get('event_id') or 0),
			'title': title,
			'title_norm': title_norm,
			'search_title': search_title,
			'short_desc': str(event_data.get('short_desc') or ''),
			'extended_desc': str(event_data.get('extended_desc') or ''),
			'begin_time': begin_time,
			'duration': duration,
			'event_end': event_end,
			'virtual_path': str(event_data.get('virtual_path') or ''),
			'json_path': str(event_data.get('json_path') or ''),
			'status': str(event_data.get('status') or 'unknown'),
			'confidence': float(event_data.get('confidence') or 0.0),
			'last_access': int(event_data.get('last_access') or now),
			'expires_at': int(event_data.get('expires_at') or 0),
			'pinned': int(event_data.get('pinned') or 0),
			'created_at': created_at,
			'updated_at': updated_at,
		}
		columns = list(values.keys())
		placeholders = ', '.join('?' for _ in columns)
		updates = ', '.join([f"{col}=excluded.{col}" for col in columns if col not in ('source_key', 'created_at')])
		with self._connect() as conn:
			conn.execute(f"""
				INSERT INTO e2mdb_epg_events ({', '.join(columns)})
				VALUES ({placeholders})
				ON CONFLICT(source_key) DO UPDATE SET {updates}
			""", tuple(values[col] for col in columns))
			conn.commit()
			row = conn.execute("SELECT id FROM e2mdb_epg_events WHERE source_key = ?", (source_key,)).fetchone()
			return row[0] if row else None
	except Exception as e:
		write_log(f"[e2MDB] Error upserting EPG event: {e}")
		return None


def _live_epg_get_event(self, source_key):
	"""Return one EPG/Live event by source key."""
	try:
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute("SELECT * FROM e2mdb_epg_events WHERE source_key = ?", (source_key,)).fetchone()
			return _live_epg_row_to_dict(row)
	except Exception as e:
		write_log(f"[e2MDB] Error reading EPG event {source_key}: {e}")
		return {}


def _live_epg_get_event_readonly(self, source_key, busy_timeout_ms=0):
	"""Return one EPG row without letting a GUI cache read wait on a writer.

	This is intended for EPG/ChannelSelection preview paths. A short-lived miss
	is preferable there to blocking the Enigma2 main loop behind backend work.
	"""
	try:
		source_key = str(source_key or "").strip()
		if not source_key or not self.db_path:
			return {}
		busy_timeout_ms = max(0, min(int(0 if busy_timeout_ms is None else busy_timeout_ms), 250))
		conn = connect(self.db_path, timeout=float(busy_timeout_ms) / 1000.0)
		try:
			conn.row_factory = Row
			conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
			conn.execute("PRAGMA query_only=ON")
			row = conn.execute("SELECT * FROM e2mdb_epg_events WHERE source_key = ?", (source_key,)).fetchone()
			return _live_epg_row_to_dict(row)
		finally:
			conn.close()
	except OperationalError as e:
		# Lock contention is an expected transient condition while the daemon
		# commits a result. Do not turn it into synchronous file logging here.
		if "locked" not in str(e).lower() and "busy" not in str(e).lower():
			write_log(f"[e2MDB] Error reading EPG preview {source_key}: {e}")
		return {}
	except Exception as e:
		write_log(f"[e2MDB] Error reading EPG preview {source_key}: {e}")
		return {}


def _live_epg_get_event_for_service(self, service_ref, event_id=0, begin_time=0, title=''):
	"""Find the best matching EPG/Live event entry for a service/event identity."""
	try:
		params = [str(service_ref or '')]
		clauses = ["service_ref = ?"]
		if event_id:
			clauses.append("event_id = ?")
			params.append(int(event_id))
		if begin_time:
			clauses.append("begin_time = ?")
			params.append(int(begin_time))
		if title:
			clauses.append("title_norm = ?")
			params.append(self._normalize_search_text(title))
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute(f"""
				SELECT * FROM e2mdb_epg_events
				WHERE {' AND '.join(clauses)}
				ORDER BY updated_at DESC
				LIMIT 1
			""", tuple(params)).fetchone()
			return _live_epg_row_to_dict(row)
	except Exception as e:
		write_log(f"[e2MDB] Error finding EPG event: {e}")
		return {}


def _live_epg_touch_event(self, source_key, now=None):
	"""Update the last access time for a cached EPG/Live event."""
	try:
		now = int(now or _live_epg_now())
		with self._connect() as conn:
			cur = conn.execute("UPDATE e2mdb_epg_events SET last_access = ?, updated_at = ? WHERE source_key = ?", (now, now, source_key))
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error touching EPG event {source_key}: {e}")
		return 0


def _live_epg_update_event_search_title(self, source_key, search_title):
	"""Store the normalized provider search title used for a cached EPG/Live event."""
	try:
		now = _live_epg_now()
		with self._connect() as conn:
			cur = conn.execute("UPDATE e2mdb_epg_events SET search_title = ?, updated_at = ? WHERE source_key = ?", (str(search_title or ''), now, source_key))
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error updating EPG event search title {source_key}: {e}")
		return 0


def _live_epg_update_event_status(self, source_key, status, confidence=None, json_path=None, expires_at=None):
	"""Update the processing state for a cached EPG/Live event."""
	try:
		now = _live_epg_now()
		sets = ["status = ?", "updated_at = ?"]
		params = [str(status or 'unknown'), now]
		if confidence is not None:
			sets.append("confidence = ?")
			params.append(float(confidence or 0.0))
		if json_path is not None:
			sets.append("json_path = ?")
			params.append(str(json_path or ''))
		if expires_at is not None:
			sets.append("expires_at = ?")
			params.append(int(expires_at or 0))
		params.append(source_key)
		with self._connect() as conn:
			cur = conn.execute(f"UPDATE e2mdb_epg_events SET {', '.join(sets)} WHERE source_key = ?", tuple(params))
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error updating EPG event status {source_key}: {e}")
		return 0


def _live_epg_update_event_metadata(self, source_key, final_dict):
	"""Write display-ready metadata to the EPG event row.

	The JSON file remains a cache artifact, but skin output and future EPG
	queries can use SQLite columns/person tables directly without reparsing JSON.
	"""
	try:
		if not source_key or not isinstance(final_dict, dict):
			return 0
		metadata_title = _db_display_text(final_dict, 'title', 'name')
		metadata_subtitle = _db_display_text(final_dict, 'episode_name') or _db_display_text(final_dict, 'tagline')
		metadata_overview = _db_display_text(final_dict, 'overview', 'description')
		metadata_genres = _db_display_text(final_dict, 'genres')
		metadata_provider = str(final_dict.get('provider') or '')
		try:
			metadata_provider_ids = dumps(final_dict.get('provider_ids') or {}, ensure_ascii=False)
		except Exception:
			metadata_provider_ids = '{}'
		metadata_media_type = str(final_dict.get('media_type') or '')
		released = str(final_dict.get('released') or final_dict.get('firstAired') or '')
		metadata_year = released[:4] if len(released) >= 4 and released[:4].isdigit() else ''
		metadata_runtime = str(final_dict.get('runtime') or '')
		metadata_rating = str(final_dict.get('vote_average') or final_dict.get('rating') or '')
		metadata_vote_count = str(final_dict.get('vote_count') or '')
		metadata_cover_path = str(final_dict.get('cover_path') or final_dict.get('cover_url') or '')
		metadata_backdrop_path = str(final_dict.get('backdrop_path') or final_dict.get('backdrop_url') or '')
		metadata_logo_path = str(final_dict.get('titlelogo_path') or final_dict.get('logo_path') or final_dict.get('titlelogo_url') or final_dict.get('logo_url') or '')
		metadata_image_path = str(final_dict.get('image_path') or final_dict.get('preview_path') or final_dict.get('still_path') or final_dict.get('image_url') or '')
		metadata_released = released
		metadata_countries = _db_display_text(final_dict, 'countries')
		metadata_age_rating = str(final_dict.get('age_rating') or '')
		try:
			metadata_cast = dumps(final_dict.get('cast') or [], ensure_ascii=False)
		except Exception:
			metadata_cast = '[]'
		try:
			metadata_crew = dumps(final_dict.get('crew') or [], ensure_ascii=False)
		except Exception:
			metadata_crew = '[]'
		metadata_season_no = str(final_dict.get('season_no') or '')
		metadata_episode_no = str(final_dict.get('episode_no') or '')
		now = _live_epg_now()
		with self._connect() as conn:
			cur = conn.execute("""
				UPDATE e2mdb_epg_events
				SET metadata_title = ?, metadata_subtitle = ?, metadata_overview = ?, metadata_genres = ?,
				metadata_provider = ?, metadata_provider_ids = ?, metadata_media_type = ?, metadata_year = ?, metadata_runtime = ?,
				metadata_rating = ?, metadata_vote_count = ?, metadata_cover_path = ?, metadata_backdrop_path = ?, metadata_logo_path = ?,
				metadata_image_path = ?, metadata_released = ?, metadata_countries = ?, metadata_age_rating = ?,
				metadata_cast = ?, metadata_crew = ?, metadata_season_no = ?, metadata_episode_no = ?,
				updated_at = ?
				WHERE source_key = ?
			""", (
				metadata_title, metadata_subtitle, metadata_overview, metadata_genres,
				metadata_provider, metadata_provider_ids, metadata_media_type, metadata_year, metadata_runtime,
				metadata_rating, metadata_vote_count, metadata_cover_path, metadata_backdrop_path, metadata_logo_path,
				metadata_image_path, metadata_released, metadata_countries, metadata_age_rating,
				metadata_cast, metadata_crew, metadata_season_no, metadata_episode_no, now, source_key
			))
			row = conn.execute("SELECT id FROM e2mdb_epg_events WHERE source_key = ? LIMIT 1", (source_key,)).fetchone()
			if row:
				_db_sync_epg_event_people(conn, row[0], final_dict)
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error updating EPG display metadata {source_key}: {e}")
		return 0


def _live_epg_get_expired_events(self, now=None, limit=500):
	"""Return expired EPG/Live events that may be removed by cleanup."""
	try:
		now = int(now or _live_epg_now())
		limit = max(1, min(int(limit or 500), 5000))
		with self._connect() as conn:
			conn.row_factory = Row
			rows = conn.execute("""
				SELECT * FROM e2mdb_epg_events
				WHERE pinned = 0
				AND expires_at > 0
				AND expires_at < ?
				ORDER BY expires_at ASC
				LIMIT ?
			""", (now, limit)).fetchall()
			return [dict(row) for row in rows]
	except Exception as e:
		write_log(f"[e2MDB] Error reading expired EPG events: {e}")
		return []


def _live_epg_delete_expired_events(self, now=None, limit=500):
	"""Delete expired EPG/Live events; asset records are intentionally kept."""
	try:
		now = int(now or _live_epg_now())
		limit = max(1, min(int(limit or 500), 5000))
		with self._connect() as conn:
			rows = conn.execute("""
				SELECT id FROM e2mdb_epg_events
				WHERE pinned = 0
				AND expires_at > 0
				AND expires_at < ?
				ORDER BY expires_at ASC
				LIMIT ?
			""", (now, limit)).fetchall()
			ids = [row[0] for row in rows]
			for row_id in ids:
				conn.execute("DELETE FROM e2mdb_epg_events WHERE id = ?", (row_id,))
			conn.commit()
			return len(ids)
	except Exception as e:
		write_log(f"[e2MDB] Error deleting expired EPG events: {e}")
		return 0


def _live_epg_upsert_asset(self, asset_data):
	"""Insert or update a shared provider asset record."""
	try:
		now = int(asset_data.get('updated_at') or _live_epg_now())
		provider = str(asset_data.get('provider') or '').strip().lower()
		provider_id = str(asset_data.get('provider_id') or asset_data.get('id') or '').strip()
		media_type = str(asset_data.get('media_type') or '').strip().lower()
		asset_key = str(asset_data.get('asset_key') or f"{media_type}|{provider}|{provider_id}").strip('|')
		if not provider or not provider_id or not asset_key:
			return None
		values = {
			'asset_key': asset_key,
			'provider': provider,
			'provider_id': provider_id,
			'media_type': media_type,
			'title': str(asset_data.get('title') or ''),
			'original_title': str(asset_data.get('original_title') or ''),
			'episode_name': str(asset_data.get('episode_name') or ''),
			'tagline': str(asset_data.get('tagline') or ''),
			'genres': str(asset_data.get('genres') or ''),
			'overview': str(asset_data.get('overview') or ''),
			'year': int(asset_data.get('year') or 0),
			'json_path': str(asset_data.get('json_path') or ''),
			'cover_path': str(asset_data.get('cover_path') or ''),
			'backdrop_path': str(asset_data.get('backdrop_path') or ''),
			'logo_path': str(asset_data.get('logo_path') or ''),
			'image_path': str(asset_data.get('image_path') or ''),
			'last_seen': int(asset_data.get('last_seen') or now),
			'expires_at': int(asset_data.get('expires_at') or 0),
			'created_at': int(asset_data.get('created_at') or now),
			'updated_at': now,
		}
		columns = list(values.keys())
		updates = ', '.join([f"{col}=excluded.{col}" for col in columns if col not in ('asset_key', 'created_at')])
		with self._connect() as conn:
			conn.execute(f"""
				INSERT INTO e2mdb_provider_assets ({', '.join(columns)})
				VALUES ({', '.join('?' for _ in columns)})
				ON CONFLICT(asset_key) DO UPDATE SET {updates}
			""", tuple(values[col] for col in columns))
			row = conn.execute("SELECT id FROM e2mdb_provider_assets WHERE asset_key = ?", (asset_key,)).fetchone()
			if row:
				_db_sync_provider_asset_people(conn, row[0], asset_data)
			conn.commit()
			return row[0] if row else None
	except Exception as e:
		write_log(f"[e2MDB] Error upserting provider asset: {e}")
		return None


def _live_epg_link_event_asset(self, source_key, asset_id, confidence=0.0, provider=''):
	"""Link an EPG/Live event with a shared provider asset."""
	try:
		now = _live_epg_now()
		with self._connect() as conn:
			event_row = conn.execute("SELECT id FROM e2mdb_epg_events WHERE source_key = ?", (source_key,)).fetchone()
			if not event_row or not asset_id:
				return False
			conn.execute("""
				INSERT OR REPLACE INTO e2mdb_epg_event_asset_map
				(epg_event_id, asset_id, confidence, provider, created_at)
				VALUES (?, ?, ?, ?, ?)
			""", (event_row[0], int(asset_id), float(confidence or 0.0), str(provider or ''), now))
			conn.commit()
			return True
	except Exception as e:
		write_log(f"[e2MDB] Error linking EPG event asset: {e}")
		return False


def _live_epg_upsert_fetch_queue(self, item):
	"""Insert or update one provider fetch queue item."""
	try:
		now = int(item.get('updated_at') or _live_epg_now())
		source_key = str(item.get('source_key') or '').strip()
		if not source_key:
			return False
		values = {
			'source_key': source_key,
			'source_type': str(item.get('source_type') or 'epg'),
			'service_ref': str(item.get('service_ref') or ''),
			'title': str(item.get('title') or ''),
			'search_title': str(item.get('search_title') or item.get('title') or ''),
			'short_desc': str(item.get('short_desc') or ''),
			'extended_desc': str(item.get('extended_desc') or ''),
			'begin_time': int(item.get('begin_time') or 0),
			'event_end': int(item.get('event_end') or 0),
			'priority': int(item.get('priority') or 0),
			'reason': str(item.get('reason') or ''),
			'state': str(item.get('state') or 'pending'),
			'attempts': int(item.get('attempts') or 0),
			'not_before': int(item.get('not_before') or 0),
			'last_error': str(item.get('last_error') or ''),
			'created_at': int(item.get('created_at') or now),
			'updated_at': now,
		}
		columns = list(values.keys())
		updates = """
			source_type=excluded.source_type,
			service_ref=excluded.service_ref,
			title=excluded.title,
			search_title=excluded.search_title,
			short_desc=excluded.short_desc,
			extended_desc=excluded.extended_desc,
			begin_time=excluded.begin_time,
			event_end=excluded.event_end,
			priority=CASE
				WHEN e2mdb_fetch_queue.state = 'running' THEN MAX(COALESCE(e2mdb_fetch_queue.priority, 0), excluded.priority)
				ELSE excluded.priority
			END,
			reason=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.reason ELSE excluded.reason END,
			state=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN 'running' ELSE excluded.state END,
			attempts=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.attempts ELSE excluded.attempts END,
			not_before=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.not_before ELSE excluded.not_before END,
			last_error=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.last_error ELSE excluded.last_error END,
			updated_at=CASE WHEN e2mdb_fetch_queue.state = 'running' THEN e2mdb_fetch_queue.updated_at ELSE excluded.updated_at END
		"""
		with self._connect() as conn:
			conn.execute(f"""
				INSERT INTO e2mdb_fetch_queue ({', '.join(columns)})
				VALUES ({', '.join('?' for _ in columns)})
				ON CONFLICT(source_key) DO UPDATE SET {updates}
			""", tuple(values[col] for col in columns))
			conn.commit()
			return True
	except Exception as e:
		write_log(f"[e2MDB] Error upserting fetch queue item: {e}")
		return False


def _live_epg_get_next_fetch_queue_item(self, now=None):
	"""Return the next pending provider fetch queue item."""
	try:
		now = int(now or _live_epg_now())
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute("""
				SELECT * FROM e2mdb_fetch_queue
				WHERE state = 'pending'
				AND COALESCE(not_before, 0) <= ?
				ORDER BY priority DESC, begin_time ASC, updated_at ASC
				LIMIT 1
			""", (now,)).fetchone()
			return _live_epg_row_to_dict(row)
	except Exception as e:
		write_log(f"[e2MDB] Error reading next queue item: {e}")
		return {}


def _live_epg_get_fetch_queue_item(self, source_key):
	"""Return one provider fetch queue item by source key."""
	try:
		source_key = str(source_key or '').strip()
		if not source_key:
			return {}
		with self._connect() as conn:
			conn.row_factory = Row
			row = conn.execute("SELECT * FROM e2mdb_fetch_queue WHERE source_key = ?", (source_key,)).fetchone()
			return _live_epg_row_to_dict(row)
	except Exception as e:
		write_log(f"[e2MDB] Error reading queue item {source_key}: {e}")
		return {}


def _live_epg_update_fetch_queue_state(self, source_key, state, attempts=None, not_before=None, last_error=''):
	"""Update queue item state after a worker processed or skipped it."""
	try:
		now = _live_epg_now()
		sets = ["state = ?", "updated_at = ?"]
		params = [str(state or 'pending'), now]
		if attempts is not None:
			sets.append("attempts = ?")
			params.append(int(attempts or 0))
		if not_before is not None:
			sets.append("not_before = ?")
			params.append(int(not_before or 0))
		if last_error is not None:
			sets.append("last_error = ?")
			params.append(str(last_error or ''))
		params.append(source_key)
		with self._connect() as conn:
			cur = conn.execute(f"UPDATE e2mdb_fetch_queue SET {', '.join(sets)} WHERE source_key = ?", tuple(params))
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error updating queue state {source_key}: {e}")
		return 0


def _live_epg_cleanup_fetch_queue(self, now=None, done_retention=86400, expired_grace=86400):
	"""Remove finished or obsolete fetch queue entries."""
	try:
		now = int(now or _live_epg_now())
		with self._connect() as conn:
			cur1 = conn.execute("""
				DELETE FROM e2mdb_fetch_queue
				WHERE state IN ('done', 'failed', 'skipped', 'ended_skipped', 'no_match', 'short_skipped', 'ignored')
				AND updated_at > 0
				AND updated_at < ?
			""", (now - int(done_retention or 86400),))
			cur2 = conn.execute("""
				DELETE FROM e2mdb_fetch_queue
				WHERE event_end > 0 AND event_end < ?
			""", (now - int(expired_grace or 86400),))
			conn.commit()
			return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)
	except Exception as e:
		write_log(f"[e2MDB] Error cleaning fetch queue: {e}")
		return 0


def _live_epg_get_fetch_queue_stats(self):
	"""Return queue state counts for diagnostics."""
	try:
		with self._connect() as conn:
			rows = conn.execute("SELECT state, COUNT(*) FROM e2mdb_fetch_queue GROUP BY state").fetchall()
			return {str(row[0] or ''): int(row[1] or 0) for row in rows}
	except Exception as e:
		write_log(f"[e2MDB] Error reading queue stats: {e}")
		return {}


def _live_epg_reset_running_queue(self):
	"""Reset interrupted running queue jobs after an Enigma2/plugin restart."""
	try:
		now = _live_epg_now()
		with self._connect() as conn:
			cur = conn.execute("UPDATE e2mdb_fetch_queue SET state = 'pending', updated_at = ? WHERE state = 'running'", (now,))
			conn.commit()
			return cur.rowcount
	except Exception as e:
		write_log(f"[e2MDB] Error resetting running queue: {e}")
		return 0


def _live_epg_upsert_channel_stat(self, service_ref, service_name='', zap_increment=0, watch_seconds_increment=0, pinned=None, now=None):
	"""Update zap/watch statistics used by the EPG prefill scheduler."""
	try:
		now = int(now or _live_epg_now())
		service_ref = str(service_ref or '').strip()
		if not service_ref:
			return False
		with self._connect() as conn:
			row = conn.execute("SELECT zap_count, watch_seconds, pinned, created_at FROM e2mdb_channel_stats WHERE service_ref = ?", (service_ref,)).fetchone()
			if row:
				zap_count = int(row[0] or 0) + int(zap_increment or 0)
				watch_seconds = int(row[1] or 0) + int(watch_seconds_increment or 0)
				pinned_value = int(row[2] or 0) if pinned is None else int(bool(pinned))
				created_at = int(row[3] or now)
			else:
				zap_count = int(zap_increment or 0)
				watch_seconds = int(watch_seconds_increment or 0)
				pinned_value = int(bool(pinned)) if pinned is not None else 0
				created_at = now
			# The score deliberately remains simple; later phases may add recency decay.
			score = float(zap_count) + min(float(watch_seconds) / 600.0, 10.0) + (50.0 if pinned_value else 0.0)
			conn.execute("""
				INSERT OR REPLACE INTO e2mdb_channel_stats
				(service_ref, service_name, zap_count, watch_seconds, last_seen, score, pinned, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
			""", (service_ref, str(service_name or ''), zap_count, watch_seconds, now, score, pinned_value, created_at, now))
			conn.commit()
			return True
	except Exception as e:
		write_log(f"[e2MDB] Error updating channel stats: {e}")
		return False


def _live_epg_get_top_channels(self, limit=10, include_pinned=True):
	"""Return preferred services for scheduled EPG prefill."""
	try:
		limit = max(1, min(int(limit or 10), 100))
		with self._connect() as conn:
			conn.row_factory = Row
			where = "WHERE pinned = 1 OR score > 0" if include_pinned else "WHERE score > 0"
			rows = conn.execute(f"""
				SELECT * FROM e2mdb_channel_stats
				{where}
				ORDER BY pinned DESC, score DESC, last_seen DESC
				LIMIT ?
			""", (limit,)).fetchall()
			return [dict(row) for row in rows]
	except Exception as e:
		write_log(f"[e2MDB] Error reading top channels: {e}")
		return []


def _live_epg_set_cleanup_state(self, key, value):
	"""Store lightweight scheduler/cleanup state."""
	try:
		with self._connect() as conn:
			conn.execute("INSERT OR REPLACE INTO e2mdb_cleanup_state (key, value, updated_at) VALUES (?, ?, ?)", (str(key), str(value), _live_epg_now()))
			conn.commit()
			return True
	except Exception as e:
		write_log(f"[e2MDB] Error setting cleanup state {key}: {e}")
		return False


def _live_epg_get_cleanup_state(self, key, default=''):
	"""Read lightweight scheduler/cleanup state."""
	try:
		with self._connect() as conn:
			row = conn.execute("SELECT value FROM e2mdb_cleanup_state WHERE key = ?", (str(key),)).fetchone()
			return row[0] if row else default
	except Exception as e:
		write_log(f"[e2MDB] Error reading cleanup state {key}: {e}")
		return default


def _sqlite_db_maintenance(self, vacuum=True, analyze=True, reindex=False, label='database'):
	"""Run safe SQLite maintenance for the current database file.

	ANALYZE refreshes query statistics, REINDEX rebuilds existing indexes, and
	VACUUM rewrites the database file to reclaim free pages after cleanup.
	VACUUM requires an exclusive SQLite operation and must not run inside an
	open transaction.
	"""
	from os.path import getsize
	result = {
		"result": "skipped",
		"label": str(label or "database"),
		"path": str(getattr(self, "db_path", "") or ""),
		"analyze": bool(analyze),
		"reindex": bool(reindex),
		"vacuum": bool(vacuum),
		"size_before": 0,
		"size_after": 0,
		"size_saved": 0,
	}
	try:
		db_path = str(getattr(self, "db_path", "") or "")
		if not db_path or not isfile(db_path):
			result["reason"] = "missing-db"
			return result
		result["size_before"] = int(getsize(db_path) or 0)
		conn = connect(db_path, timeout=120, isolation_level=None)
		try:
			conn.execute("PRAGMA busy_timeout=120000")
			if analyze:
				conn.execute("ANALYZE")
			if reindex:
				conn.execute("REINDEX")
			if vacuum:
				conn.execute("VACUUM")
			try:
				conn.execute("PRAGMA optimize")
			except Exception:
				pass
		finally:
			conn.close()
		result["size_after"] = int(getsize(db_path) or 0)
		result["size_saved"] = max(0, int(result["size_before"] or 0) - int(result["size_after"] or 0))
		result["result"] = "ok"
	except Exception as e:
		result["result"] = "failed"
		result["error"] = str(e)
		write_log(f"[e2MDB] SQLite maintenance failed for {result.get('label')}: {e}")
	return result


_original_resultsdb_create_tables = ResultsDB._create_tables
_original_resultsdb_add_media = ResultsDB.add_media
_original_resultsdb_clear_results_for_media = ResultsDB.clear_results_for_media
_original_resultsdb_add_result = ResultsDB.add_result
_original_resultsdb_update_media_record = ResultsDB.update_media_record


def _patched_resultsdb_create_tables(self):
	_original_resultsdb_create_tables(self)
	_browser_create_tables(self)
	_live_epg_create_tables(self)


def _patched_resultsdb_add_media(self, *args, **kwargs):
	result = _original_resultsdb_add_media(self, *args, **kwargs)
	_mark_browser_cache_dirty(self)
	return result


def _patched_resultsdb_clear_results_for_media(self, *args, **kwargs):
	result = _original_resultsdb_clear_results_for_media(self, *args, **kwargs)
	_mark_browser_cache_dirty(self)
	return result


def _patched_resultsdb_add_result(self, *args, **kwargs):
	result = _original_resultsdb_add_result(self, *args, **kwargs)
	_mark_browser_cache_dirty(self)
	return result


def _patched_resultsdb_update_media_record(self, *args, **kwargs):
	result = _original_resultsdb_update_media_record(self, *args, **kwargs)
	_mark_browser_cache_dirty(self)
	return result


ResultsDB._create_tables = _patched_resultsdb_create_tables
ResultsDB.add_media = _patched_resultsdb_add_media
ResultsDB.clear_results_for_media = _patched_resultsdb_clear_results_for_media
ResultsDB.add_result = _patched_resultsdb_add_result
ResultsDB.update_media_record = _patched_resultsdb_update_media_record
ResultsDB.update_media_metadata = _resultsdb_update_media_metadata
ResultsDB.get_media_metadata = _resultsdb_get_media_metadata
ResultsDB.get_media_metadata_by_path = _resultsdb_get_media_metadata_by_path
ResultsDB.get_media_display_data = _resultsdb_get_media_display_data
ResultsDB.get_browser_media = _new_get_browser_media
ResultsDB.get_browser_item = _new_get_browser_item
ResultsDB.get_browser_facets = _new_get_browser_facets
ResultsDB.get_browser_index_status = _new_get_browser_index_status
ResultsDB.get_series_inventory = _new_get_series_inventory
ResultsDB.get_browser_season_details = _new_get_browser_season_details
ResultsDB.rebuild_browser_cache = _rebuild_browser_cache
ResultsDB._ensure_browser_cache = _ensure_browser_cache
ResultsDB._mark_browser_cache_dirty = _mark_browser_cache_dirty
ResultsDB.ensure_live_epg_schema = _live_epg_create_tables
ResultsDB.upsert_epg_event = _live_epg_upsert_event
ResultsDB.get_epg_event = _live_epg_get_event
ResultsDB.get_epg_event_readonly = _live_epg_get_event_readonly
ResultsDB.get_epg_event_for_service = _live_epg_get_event_for_service
ResultsDB.touch_epg_event = _live_epg_touch_event
ResultsDB.update_epg_event_search_title = _live_epg_update_event_search_title
ResultsDB.update_epg_event_status = _live_epg_update_event_status
ResultsDB.update_epg_event_metadata = _live_epg_update_event_metadata
ResultsDB.get_expired_epg_events = _live_epg_get_expired_events
ResultsDB.delete_expired_epg_events = _live_epg_delete_expired_events
ResultsDB.upsert_provider_asset = _live_epg_upsert_asset
ResultsDB.link_epg_event_asset = _live_epg_link_event_asset
ResultsDB.upsert_fetch_queue = _live_epg_upsert_fetch_queue
ResultsDB.get_next_fetch_queue_item = _live_epg_get_next_fetch_queue_item
ResultsDB.get_fetch_queue_item = _live_epg_get_fetch_queue_item
ResultsDB.get_fetch_queue_stats = _live_epg_get_fetch_queue_stats
ResultsDB.update_fetch_queue_state = _live_epg_update_fetch_queue_state
ResultsDB.cleanup_fetch_queue = _live_epg_cleanup_fetch_queue
ResultsDB.reset_running_queue = _live_epg_reset_running_queue
ResultsDB.upsert_channel_stat = _live_epg_upsert_channel_stat
ResultsDB.get_top_channels = _live_epg_get_top_channels
ResultsDB.set_cleanup_state = _live_epg_set_cleanup_state
ResultsDB.get_cleanup_state = _live_epg_get_cleanup_state
ResultsDB.sqlite_maintenance = _sqlite_db_maintenance
MediaDB.sqlite_maintenance = _sqlite_db_maintenance

resultsdb = ResultsDB()
