import sqlite3
from typing import Any, Optional
from difflib import SequenceMatcher


class MediaDB:
	def __init__(self):
		self.dbPath = None
		self.table = "media"
		self.fields = {
			"path": "TEXT UNIQUE",   # <- UNIQUE for Upsert
			"fname": "TEXT",
			"ref": "TEXT",
			"title": "TEXT",
			"shortDesc": "TEXT",
			"extDesc": "TEXT",
			"tags": "TEXT",
			"duration": "INTEGER",
			"begin": "INTEGER",
			"fsize": "INTEGER",
		}

	def setPath(self, dbPath: str):
		self.dbPath = dbPath

	def _connect(self):
		"""Create a new SQLite connection."""
		return sqlite3.connect(self.dbPath)

	def createTable(self):
		"""Create table and index if they don't exist."""
		fieldsSql = ", ".join(f"{k} {v}" for k, v in self.fields.items())
		createSql = f"""
			CREATE TABLE IF NOT EXISTS {self.table} (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				{fieldsSql}
			);
		"""
		indexSql = f"CREATE INDEX IF NOT EXISTS idx_{self.table}_fname ON {self.table}(fname);"

		with self._connect() as conn:
			conn.execute(createSql)
			conn.execute(indexSql)
			conn.commit()

	def upsert(self, data: dict[str, Any]) -> int:
		"""
		Insert or update a record based on unique 'path'.
		Returns the row ID of the inserted or updated record.
		"""
		keys = list(data.keys())
		placeholders = ", ".join("?" for _ in keys)
		updates = ", ".join([f"{k}=excluded.{k}" for k in keys if k != "path"])

		sql = f"""
			INSERT INTO {self.table} ({', '.join(keys)})
			VALUES ({placeholders})
			ON CONFLICT(path) DO UPDATE SET {updates};
		"""

		with self._connect() as conn:
			cur = conn.execute(sql, tuple(data.values()))
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
			conn.row_factory = sqlite3.Row
			cur = conn.execute(sql, params)
			return [dict(row) for row in cur.fetchall()]

	def delete(self, where: str, params: tuple = ()) -> int:
		"""Delete records based on a WHERE clause."""
		sql = f"DELETE FROM {self.table} WHERE {where}"
		with self._connect() as conn:
			cur = conn.execute(sql, params)
			conn.commit()
			return cur.rowcount

	def _getTitles(self, title: str) -> list[tuple[Any, ...]]:
		"""
		Returns (ref, title, shortDesc, extDesc) for all with the title.
		"""
		sql = f"SELECT ref, title, shortDesc, extDesc FROM {self.table} WHERE title = ?"
		with self._connect() as conn:
			cur = conn.execute(sql, (title,))
			return cur.fetchall()

	def isTitleInDatabase(
		self,
		title: str,
		shortDesc: str = "",
		extDesc: str = "",
		ratioShortDesc: float = 0.95,
		ratioExtDesc: float = 0.85,
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
		content = self._getTitles(title)
		if not content:
			return None

		if deep_check:
			for ref, t, sdesc, edesc in content:
				if shortDesc:
					if sdesc == shortDesc:
						result = 1
					else:
						sim = SequenceMatcher(None, shortDesc, sdesc).ratio()
						if sim > ratioShortDesc:
							result = 1

				if result:
					if not extDesc:
						break
					else:
						if edesc == extDesc:
							break
						else:
							sim = SequenceMatcher(None, extDesc, edesc).ratio()
							if sim > ratioExtDesc:
								break
					result = None
		else:
			result = 1

		return result


mediadb = MediaDB()


if __name__ == "__main__":
	db = MediaDB("media.db")

	record = {
		"path": "/videos/demo.mp4",
		"fname": "demo.mp4",
		"ref": "123",
		"title": "Demo Video",
		"shortDesc": "Kurze Beschreibung",
		"extDesc": "Längere Beschreibung",
		"tags": "demo, test",
		"duration": 120,
		"begin": 0,
		"fsize": 2048000
	}

	rowid = db.upsert(record)
	print(f"Upsert erfolgreich, Datensatz-ID: {rowid}")

	record["title"] = "Demo Video (aktualisiert)"
	rowid2 = db.upsert(record)
	print(f"Update erfolgreich, Datensatz-ID: {rowid2}")

	print("Einträge:", db.search("path = ?", ("/videos/demo.mp4",)))
