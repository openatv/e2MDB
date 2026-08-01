# e2MDB backend phase 4 - SQLite single writer

## Goal

Phase 4 moves the first persistent data layer into the daemon. The daemon now imports the native recording scan result into SQLite and exposes the data through socket/API endpoints.

Enigma2 should still only display status and request jobs. SQLite writes are handled by `e2mdbd`.

## New file

```text
Plugins/Extensions/e2MDB/E2MDBBackendDatabase.py
```

This module has no Enigma2 imports and can run inside the daemon process.

## Database path

The daemon resolves the database path in this order:

1. `/etc/enigma2/e2mdb/settings.json` -> `database.path`
2. `/etc/enigma2/e2mdb/settings.json` -> `database.root` + `/results.db`
3. `/etc/enigma2/e2mdb/settings.json` -> `cache.root` + `/results.db`
4. `/media/hdd/e2MDB/results.db`

The GUI export now writes:

```json
"database": {
  "root": "/media/hdd/e2MDB",
  "path": "/media/hdd/e2MDB/results.db",
  "journal_mode": "wal",
  "busy_timeout_ms": 5000,
  "single_writer": true
}
```

## Tables

The daemon creates or reuses:

```text
e2mdb_media
e2mdb_recordings
e2mdb_backend_state
```

`e2mdb_media` is kept compatible with the existing `results.db` media table where practical.

`e2mdb_recordings` stores one row per parsed recording, including raw JSON payload from the native META/EIT/CUTS parser result.

## Scan flow

```text
Recording scan
  -> native parser
  -> RecordingScanItem list
  -> /etc/enigma2/e2mdb/recordings.json
  -> /etc/enigma2/e2mdb/scan_state.json
  -> SQLite import into results.db
```

The JSON files remain useful as debug/cache artifacts, but the API prefers SQLite when available.

## New socket commands

```text
database_status
database_maintenance
```

## New CLI commands

```sh
python3 e2mdbctl.py db status
python3 e2mdbctl.py db maintenance
python3 e2mdbctl.py db maintenance vacuum
python3 e2mdbctl.py db maintenance reindex
python3 e2mdbctl.py db maintenance vacuum reindex
```

## New HTTP API endpoints

```text
GET/POST /api/database/status
GET/POST /api/database/maintenance?vacuum=1&reindex=1
GET/POST /api/browser/list?offset=0&limit=50&query=
```

`/api/recordings/list` and `/api/recordings/item` now read from SQLite when the database is available.

## Box test

```sh
/etc/init.d/e2mdbd restart
sleep 2

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB

python3 e2mdbctl.py db status
python3 e2mdbctl.py scan start
python3 e2mdbctl.py scan state
python3 e2mdbctl.py db status
python3 e2mdbctl.py recordings 5

wget -qO- http://127.0.0.1:8088/api/database/status
echo
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=5'
echo
```

Expected:

- `db status` returns `success: true`
- `e2mdb_recordings` count increases after scan
- `e2mdb_media` contains/update media rows
- `/api/browser/list` returns recording items from SQLite
- `/tmp/e2mdb/status.json` shows `db_import` near the end of a scan

## Notes

Provider lookup and artwork download are not moved in this phase. This phase prepares the database layer so provider results can later be written by the daemon without involving the Enigma2 process.
