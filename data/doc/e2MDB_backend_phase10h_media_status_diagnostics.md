# e2MDB Backend Phase 10h - Media Status Diagnostics

Stand: 2026-05-31
Basis: phase10g backend cache cleanup

## Ziel

`cache status` zeigt nur den Speicher-/Dateizustand des e2MDB-Cache-Roots.
Für die Umstellung auf Backend-only wird zusätzlich ein echter Medien- und
Diagnosestatus benötigt.

Dafür wurde ein neuer Backend-Befehl eingeführt:

```sh
python3 e2mdbctl.py media status
```

Der neue Status beantwortet nicht nur, ob Cache-Ordner existieren, sondern ob
der Backend-Scan und Provider-Enrich wirklich Daten in SQLite erzeugt haben.

## Neue Backend-Kommandos

Command-Socket:

```text
media_status
current_job
```

CLI:

```sh
python3 e2mdbctl.py media status
python3 e2mdbctl.py jobs current
python3 e2mdbctl.py jobs queue
python3 e2mdbctl.py jobs history
```

HTTP API:

```text
GET /api/media/status
GET /api/jobs/current
GET /api/jobs/queue
GET /api/jobs/history
```

## Unterschied zwischen Cache-Status und Media-Status

`cache status` bleibt ein Cleanup-/Speicherstatus:

- Cache-Root
- bekannte Unterordner
- Dateien
- Ordner
- Bytes
- Sicherheitsprüfung für Cleanup

`media status` ist ein Bestands- und Diagnose-Status:

- importierte Recordings/Medien
- TS-Aufnahmen vs. normale Medienfiles
- Movies/Series/Anime/Manga/Unknown
- lokale Episoden-Erkennung
- META/EIT/CUTS-Sidecars
- Scan-Fehler
- Browser-ready vs. pending
- Provider done/pending/missing/error
- Provider-Matches und Provider-Verteilung
- Artwork-/Asset-Zustand
- Live/EPG-Event- und Queue-Zähler
- letzte Scan-/Provider-State-Dateien
- letzte Job-History-Einträge
- letzter Scheduler-Job
- aktueller Job
- Warnungen für typische Fehlerbilder

## Implementierung

Die eigentliche Auswertung liegt im Backend-DB-Layer:

```python
BackendDatabase.media_status()
```

Der Daemon ergänzt dabei JSON-/Runtime-Zustände:

- `/etc/enigma2/e2mdb/scan_state.json`
- `/etc/enigma2/e2mdb/provider_state.json`
- `/etc/enigma2/e2mdb/job_history.json`
- aktueller Job aus `/tmp/e2mdb/status.json`

Damit bleibt SQLite die führende Quelle für Bestandszahlen, während Status- und
History-Dateien für Diagnose ergänzt werden.

## Beispielauszug

```json
{
  "success": true,
  "media": {
    "recordings_total": 123,
    "ts_recordings": 96,
    "media_files": 27,
    "movies": 82,
    "series": 41,
    "local_episodes": 38
  },
  "browser": {
    "ready": 118,
    "pending": 5
  },
  "provider": {
    "done": 118,
    "pending": 0,
    "missing": 2,
    "errors": 3
  },
  "artwork": {
    "media_with_artwork": 110,
    "missing_artwork": 8
  }
}
```

## Typische Diagnose

Wenn `media.recordings_total` `0` ist, wurde noch kein Scan importiert oder die
Scan-Pfade sind falsch.

Wenn `browser.ready` `0`, aber `media.recordings_total` größer `0` ist, hat der
Scan funktioniert, aber Provider-Enrichment ist noch nicht erfolgreich
abgeschlossen.

Wenn `provider.errors` größer `0` ist, gibt es fehlgeschlagene Provider-Lookups.

Wenn `artwork.missing_artwork` größer `0` ist, gibt es browser-ready Einträge
ohne lokales Artwork.

## Tests

- `python3 -m py_compile` für alle Python-Dateien: 66 Dateien, 0 Fehler
- Backend-Smoke-Test mit temporärer SQLite-DB:
  - Recording importiert
  - Provider-Ergebnis importiert
  - `media_status()` liefert Medien-, Provider-, Browser- und Artwork-Zähler
  - Warnliste bleibt bei vollständigem Testdatensatz leer
