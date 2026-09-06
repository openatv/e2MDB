# e2MDB Backend Phase 10j - Scan-Path Diagnostics

Stand: 2026-05-31

## Ziel

Nach `media status` und `refresh run` war noch unklar, warum ein Scan leer bleibt,
wenn keine Medien importiert werden. Bisher konnte ein falscher, nicht gemounteter
oder leerer Aufnahmepfad nur indirekt über `0 media` erkannt werden.

Phase 10j ergänzt deshalb eine eigene Scan-Pfad-Diagnose vor dem eigentlichen
Recording-/Media-Import.

## Neue CLI

```sh
python3 e2mdbctl.py scan paths
python3 e2mdbctl.py scan paths count
```

`scan paths` prüft die konfigurierten Pfade aus:

```text
/etc/enigma2/e2mdb/paths.json
/etc/enigma2/e2mdb/settings.json -> scanner.recording_paths
```

`scan paths count` zählt zusätzlich unterstützte Video-Dateien pro Pfad.

## Neue API

```text
GET/POST /api/scanner/paths
GET/POST /api/scanner/paths?count=1
```

## Backend-Verhalten

Der Recording-Scan beginnt jetzt mit der Phase:

```text
validate_paths
```

Dabei werden pro Pfad ermittelt:

```text
path
mode
mode_label
recursive
exists
is_dir
valid
reason
video_files
ts_recordings
media_files
errors
```

Wenn kein gültiger Scan-Pfad vorhanden ist, endet der Job jetzt mit Fehler und
einer eindeutigen Meldung:

```text
No valid recording/media scan paths found
```

Wenn Pfade gültig sind, aber keine unterstützten Mediendateien enthalten, wird
der Scan-State trotzdem geschrieben:

```text
No media files found in configured scan paths
```

## Statusdateien

`scan_state.json` und `/tmp/e2mdb/last_recording_scan.json` enthalten jetzt:

```json
{
  "path_status": {
    "valid_count": 1,
    "invalid_count": 0,
    "video_files": 42,
    "ts_recordings": 40,
    "media_files": 2,
    "paths": []
  }
}
```

## Media Status

`media status` nutzt diese Information für bessere Warnungen:

```text
Some configured scan paths are invalid or unavailable
No valid scan path is available
Configured scan paths are reachable, but no supported media files were found
```

Damit ist direkt sichtbar, ob ein leerer Bestand durch falsche Pfade,
nicht gemountete Devices oder wirklich leere Medienordner verursacht wird.
