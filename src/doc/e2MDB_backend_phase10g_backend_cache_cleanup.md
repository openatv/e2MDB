# e2MDB Backend Phase 10g - Backend Cache Cleanup

Stand: 2026-05-31
Basis: phase10f cleanup/settings backend

## Ziel

Der gelbe `Clean Cache`-Button im e2MDB Scanner-Screen darf keine Cache- oder
SQLite-Löschoperationen mehr direkt im Enigma2-Prozess ausführen.

Die Löschlogik wurde deshalb in den Backend-Daemon verschoben. Enigma2 zeigt nur
noch Auswahl, Bestätigung und Ergebnis an. Die eigentliche Arbeit läuft über den
Backend-Command-Socket.

## Geänderte GUI-Logik

`E2MDBMain.key_yellow()` zeigt weiterhin die bekannten Optionen:

- `all_cache`
- `series_cache`
- `movie_cache`
- `epg_cache`
- `artwork_cache`
- `database_only`
- `all_with_db`

Nach der Bestätigung ruft die GUI aber nicht mehr lokale Helper wie
`remove_cache_paths()` auf. Stattdessen wird ein Backend-Request gestartet:

```python
run_backend_cache_cleanup(action=action, dry_run=False, timeout=180.0)
```

Der Request läuft in einem Thread, damit die Enigma2-GUI während größerer
Cache-Löschungen nicht blockiert. Das Ergebnis wird anschließend per
`reactor.callFromThread()` zurück in die GUI gemeldet.

## Entfernte lokale Löschpfade im Scanner-Screen

Aus `plugin.py` wurden die direkten Löschpfade entfernt:

- lokales `remove_cache_paths()`
- lokales `_remove_epg_live_cache()`
- lokale Hash-/Subdir-Löschlogik
- direkte `rmtree()`-Nutzung aus dem Scanner-Screen
- direkte DB-Zeilenlöschung für Live/EPG-Cache aus der GUI

Damit liegt die Verantwortung für Cache-Cleanup jetzt beim Backend.

## Neue Backend-Kommandos

Command-Socket:

```sh
cache_cleanup_status
cache_cleanup_run
```

CLI:

```sh
python3 e2mdbctl.py cache status
python3 e2mdbctl.py cache dry-run all_cache
python3 e2mdbctl.py cache cleanup all_cache
python3 e2mdbctl.py cache cleanup series_cache
python3 e2mdbctl.py cache cleanup movie_cache
python3 e2mdbctl.py cache cleanup epg_cache
python3 e2mdbctl.py cache cleanup artwork_cache
python3 e2mdbctl.py cache cleanup database_only
python3 e2mdbctl.py cache cleanup all_with_db
```

HTTP API:

```text
GET /api/cache/status
GET /api/cache/cleanup?action=all_cache
GET /api/cache/cleanup?action=all_cache&dry_run=1
```

## Backend-Sicherheitsregeln

Der Daemon akzeptiert Cache-Cleanup nur, wenn der Cache-Root sicher aussieht:

- Root muss auf einen Ordner `e2MDB` enden.
- Root darf nicht `/`, `/tmp`, `/var`, `/media`, `/media/hdd` oder `/media/usb`
  sein.
- Dateien werden nur gelöscht, wenn sie unterhalb dieses Cache-Roots liegen.
- Datenbankdateien werden nur entfernt, wenn sie ebenfalls unterhalb des
  Cache-Roots liegen.

Außerdem lehnt der Daemon Cache-Cleanup ab, wenn gerade ein Backend-Job läuft.
Damit wird verhindert, dass Scan/Enrich und Cleanup gleichzeitig auf dieselben
Dateien oder die SQLite-DB zugreifen.

## Backend-Verhalten pro Aktion

### all_cache

Setzt alle bekannten e2MDB Cache-Unterordner zurück, aber lässt die Datenbank
stehen.

### all_with_db

Setzt alle Cache-Unterordner zurück und löscht zusätzlich die Backend-Datenbank
inklusive WAL/SHM-Dateien. Danach wird das Schema automatisch neu erzeugt.

### series_cache

Ermittelt Serien-/Manga-Hashes aus Backend-DB und Cache-JSONs und entfernt die
primären Cache-Dateien. Zusätzlich werden `series`, `seasons` und `index`
zurückgesetzt.

### movie_cache

Ermittelt Movie-Hashes aus Backend-DB und Cache-JSONs und entfernt die primären
Cache-Dateien.

### epg_cache

Entfernt Live/EPG-Queue, Live/EPG-Eventdaten, Live/EPG-Provider-Assets,
Live/EPG-Provider-Matches und transiente `e2mdb_media`-Rows mit
`source_type=live_epg` aus der Backend-DB. Zugehörige primäre Cache-Dateien
werden ebenfalls entfernt.

### artwork_cache

Setzt nur Artwork-/Bild-Cache-Unterordner zurück.

### database_only

Löscht Backend-Datenbankdateien unterhalb des Cache-Roots und erzeugt das
Backend-Schema danach neu.

## Tests

- `python3 -m py_compile` für alle Python-Dateien: 66 Dateien, 0 Fehler
- Backend-Smoke-Test mit temporärem Cache-Root:
  - `cache_cleanup_status`
  - `movie_cache` dry-run
  - `movie_cache` real cleanup
  - `epg_cache` real cleanup inklusive DB-Zeilen
