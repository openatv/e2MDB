# e2MDB backend phase 6 - MediaBrowser API from e2mdbd

## Goal

This phase moves the MediaBrowser read path to the backend daemon. The Enigma2 process should no longer build large browser lists from SQLite. The daemon reads the backend SQLite database and returns prepared JSON structures for the Web UI, CLI and later the Enigma2 GUI.

## New/extended parts

- `E2MDBBackendDatabase.py`
  - `browser_status()`
  - `list_browser()`
  - `get_browser_item()`
  - `list_editor()`
  - `get_editor_item()`
  - `get_series_details()`
  - `get_season_details()`

- `e2mdbd.py`
  - command socket support for browser/editor queries
  - Twisted endpoints for browser status/list/item
  - lightweight `/api/results?action=...` bridge for the existing `index.html`

- `e2mdbctl.py`
  - `browser status`
  - `browser list [limit] [query]`
  - `browser item <id-or-path>`
  - `editor list [limit] [query]`
  - `editor item <id-or-path>`

- `web/index.html`
  - fixed duplicate `const payload` declaration in `selectBrowser()`

## HTTP endpoints

Native backend endpoints:

```text
GET /api/browser/status
GET /api/browser/list?limit=24&page=1&q=
GET /api/browser/item?id=<media_hash>
GET /api/browser/series?id=<media_hash>
GET /api/browser/season?id=<media_hash>&season_no=1
```

The existing web frontend still calls:

```text
GET /api/results?action=browser_status
GET /api/results?action=browser_list&page=1&limit=24&q=
GET /api/results?action=browser_item&id=<media_hash>
GET /api/results?action=series_details&id=<media_hash>
GET /api/results?action=season_details&id=<media_hash>&season_no=1
```

This is not a legacy scanner or DB compatibility layer. It is only the HTTP shape required by the current `index.html` while the UI is being moved to daemon data.

## CLI examples

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB

python3 e2mdbctl.py browser status
python3 e2mdbctl.py browser list 10
python3 e2mdbctl.py browser list 10 Tatort
python3 e2mdbctl.py browser item <media_hash>

python3 e2mdbctl.py editor list 10
python3 e2mdbctl.py editor item <media_hash>
```

## Test via web server

```sh
wget -qO- 'http://127.0.0.1:8088/api/browser/status'
echo
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=5'
echo
wget -qO- 'http://127.0.0.1:8088/api/results?action=browser_list&limit=5&page=1'
echo
```

Open the daemon web frontend:

```text
http://BOX-IP:8088/
```

The Media Browser tab should now load from `e2mdbd`/SQLite.

## Current limits

- Playback buttons still need an Enigma2 GUI bridge and return a controlled error from the daemon.
- Preview generation is not migrated yet.
- Editor write actions such as apply result, set images, rename and rescan are not migrated yet.
- Series/season endpoints currently return local-safe empty structures unless the database has enough structured series data later.

## Next phase

The next step should be the Enigma2 GUI-side backend reader:

- add a small GUI client for browser/status polling
- replace heavy local browser DB reads with backend calls
- keep Enigma2 only for display and playback/live bridge actions
