# e2MDB Backend Phase 10i - Refresh Run/Wait Diagnostics

Stand: 2026-05-31
Basis: phase10h media status diagnostics

## Ziel

Der Default-Nachtjob `daily-media-refresh` soll nicht nur gestartet werden können,
sondern für Tests auf der Box eindeutig nachvollziehbar sein.

Bisher musste man nach dem Start manuell mehrere Befehle ausführen:

```sh
python3 e2mdbctl.py scheduler run daily-media-refresh
python3 e2mdbctl.py jobs current
python3 e2mdbctl.py jobs history
python3 e2mdbctl.py media status
```

Phase 10i ergänzt dafür einen Run-and-Wait-Pfad.

## Neue CLI-Befehle

```sh
python3 e2mdbctl.py refresh status
python3 e2mdbctl.py refresh run [limit|all] [only-missing|all-items] [query]
python3 e2mdbctl.py scheduler run-wait <job-id> [limit|all] [only-missing|all-items] [query]
```

`refresh run` ist ein Alias für:

```sh
python3 e2mdbctl.py scheduler run-wait daily-media-refresh
```

Der Befehl startet den Scheduler-Job, wartet auf dessen Ende und gibt danach in
einem JSON-Block aus:

- Startantwort
- finalen Backend-Job
- `media status`
- `refresh status`
- letzten Refresh-Report

## Neue Backend-Kommandos

Unix-Socket/API-intern:

```text
refresh_status
refresh_run
```

HTTP-API:

```text
GET/POST /api/refresh/status
GET/POST /api/refresh/run
```

## Neuer Runtime-Report

Nach `recording_scan`, `metadata_enrich` oder `scan_and_enrich` schreibt der
Daemon zusätzlich:

```text
/tmp/e2mdb/last_media_refresh.json
```

Der Report enthält kompakt:

- Job-ID, Typ, Quelle, Ergebnis
- Scheduler-Job-ID, falls vorhanden
- Scan-State
- Provider-State
- Media-Zusammenfassung
- Warnungen

Diese Datei liegt bewusst unter `/tmp/e2mdb`, weil sie Runtime-/Diagnosedaten
enthält und beim nächsten Lauf neu erzeugt wird.

## Job-History-Erweiterung

Jeder abgeschlossene Job bekommt in `job_history.json` jetzt zusätzlich ein
kompaktes Feld:

```json
"diagnostics": {
    "recordings_total": 0,
    "media_total": 0,
    "browser_ready": 0,
    "provider_done": 0,
    "provider_errors": 0,
    "missing_metadata": 0,
    "media_with_artwork": 0,
    "missing_artwork": 0,
    "warnings": []
}
```

Dadurch ist später in der History direkt sichtbar, ob ein Scheduler-Lauf nur
gestartet wurde oder tatsächlich Medienbestand erzeugt hat.

## Test auf der Box

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py refresh status
python3 e2mdbctl.py refresh run all
python3 e2mdbctl.py jobs history
python3 e2mdbctl.py media status
cat /tmp/e2mdb/last_media_refresh.json
```

Für einen kleineren Testlauf:

```sh
python3 e2mdbctl.py refresh run 10
```

Für komplettes Re-Enrich aller Einträge:

```sh
python3 e2mdbctl.py refresh run all all-items
```

## Erwartung

Nach einem erfolgreichen Lauf sollten mindestens folgende Werte steigen oder
sichtbar werden:

- `media_status.media.recordings_total`
- `media_status.media.total`
- `media_status.provider.done` oder `provider_errors`
- `media_status.browser.ready` nach erfolgreichem Provider-/Artwork-Handling
- `refresh_status.last_refresh_report.job.state = success`

Wenn weiterhin alles `0` bleibt, sind als Nächstes die Scan-Pfade aus
`/etc/enigma2/e2mdb/settings.json` bzw. `paths.json` zu prüfen.
