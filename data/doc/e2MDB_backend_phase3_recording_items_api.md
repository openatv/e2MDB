# e2MDB Backend Phase 3 - RecordingScanItem und Recording-API

Stand: 2026-05-30

Diese Phase erweitert den nativen Recording-Scanner aus Phase 2 zu einer nutzbaren Backend-Datenbasis.
Der Daemon erzeugt jetzt pro Aufnahme ein normalisiertes `RecordingScanItem` und speichert den letzten vollständigen Scan persistent unter `/etc/enigma2/e2mdb/`.

## Neue persistente JSON-Dateien

Alle persistenten JSON-Dateien liegen unter:

```text
/etc/enigma2/e2mdb/
```

Neu oder erweitert:

```text
/etc/enigma2/e2mdb/recordings.json
/etc/enigma2/e2mdb/scan_state.json
/etc/enigma2/e2mdb/job_history.json
```

`/tmp/e2mdb/status.json` bleibt bewusst Runtime/RAMFS und wird weiterhin für schnellen GUI-Progress genutzt.

## RecordingScanItem

Der Daemon erzeugt pro Datei ein Item mit stabiler ID:

```json
{
  "id": "sha1-of-path",
  "type": "recording",
  "path": "/media/hdd/movie/example.ts",
  "folder": "/media/hdd/movie",
  "name": "example.ts",
  "extension": ".ts",
  "size_bytes": 123456789,
  "mtime": 1780000000,
  "mtime_iso": "2026-05-30T12:00:00Z",
  "title": "Example",
  "description": "Short text",
  "extended_description": "Long text",
  "service_ref": "1:0:1:...",
  "recorded_at": 1780000000,
  "recorded_at_iso": "2026-05-30T12:00:00Z",
  "duration_seconds": 3600,
  "duration_source": "eit",
  "search_candidates": ["Example", "example"],
  "sidecars": {
    "meta": {"path": "/media/hdd/movie/example.ts.meta", "exists": true},
    "eit": {"path": "/media/hdd/movie/example.eit", "exists": true},
    "cuts": {"path": "/media/hdd/movie/example.ts.cuts", "exists": true},
    "txt": {"path": "/media/hdd/movie/example.ts.txt", "exists": false}
  },
  "meta": {},
  "eit": {},
  "cuts": {},
  "txt": {},
  "parse_error": "",
  "scan_status": "ok"
}
```

Titelreihenfolge:

1. `.meta` Titel
2. `.eit` Titel
3. bereinigter Dateiname

Beschreibung:

1. `.meta` Beschreibung
2. `.eit` Short Description

Extended Description:

1. `.txt`
2. `.eit` Extended Description

Dauer:

1. `.eit` `duration_seconds`
2. Fallback aus höchstem `.cuts` PTS-Wert / 90000

## Neue Command-Socket-Kommandos

Der Unix-Socket bleibt:

```text
/tmp/e2mdb/e2mdbd.sock
```

Neue Kommandos:

```json
{"command": "recordings", "offset": 0, "limit": 50, "query": ""}
{"command": "recording", "id": "<recording-id-or-path>"}
{"command": "scan_state"}
{"command": "paths"}
{"command": "history"}
```

## Neue HTTP-API-Endpunkte

```text
GET /api/recordings/list?offset=0&limit=50&query=
GET /api/recordings/item?id=<recording-id>
GET /api/scanner/state
GET /api/jobs/history
```

Bestehende Endpunkte bleiben:

```text
GET  /api/status
GET  /api/settings
POST /api/jobs/scan/start
POST /api/jobs/scan/stop
GET  /api/jobs/current
```

## CLI-Erweiterungen

```sh
python3 e2mdbctl.py status
python3 e2mdbctl.py scan start
python3 e2mdbctl.py scan stop
python3 e2mdbctl.py scan state
python3 e2mdbctl.py recordings 20
python3 e2mdbctl.py recordings 20 Tatort
python3 e2mdbctl.py recording <id-or-path>
python3 e2mdbctl.py paths
python3 e2mdbctl.py history
```

## Test auf der Box

```sh
/etc/init.d/e2mdbd restart
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py scan start
cat /tmp/e2mdb/status.json
python3 e2mdbctl.py scan state
python3 e2mdbctl.py recordings 5
wget -qO- 'http://127.0.0.1:8088/api/recordings/list?limit=5'
echo
```

Erwartung:

- `/etc/enigma2/e2mdb/recordings.json` wird nach Scanende geschrieben.
- `/etc/enigma2/e2mdb/scan_state.json` enthält Summary mit total/errors/paths.
- `/etc/enigma2/e2mdb/job_history.json` enthält abgeschlossene Jobs.
- `/tmp/e2mdb/status.json` zeigt weiterhin Live-Progress.

## Zweck dieser Phase

Diese Phase ist bewusst noch kein finaler Provider-/DB-Umbau.
Sie schafft die saubere Übergabeschicht:

```text
Dateisystem + META/EIT/CUTS
        -> native parser
        -> RecordingScanItem
        -> API / recordings.json
        -> später Provider + SQLite Single-Writer
```

Damit können Provider- und DB-Jobs danach ohne Enigma2-Abhängigkeit auf einer stabilen Scan-Datenstruktur arbeiten.
