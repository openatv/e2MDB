# e2MDB Backend Phase 11k - MediaDB GUI Init Fix

## Ziel

MediaDB darf nicht mehr vom GUI-Scan-Button initialisiert werden. Sie ist eine kleine OpenATV-Timer-Hilfsdatenbank und wird vom Backend-Scanner/E2MDBScanner befüllt.

## Änderungen

- `plugin.py`: `mediadb.set_path()` aus `create_cache_paths()` entfernt.
- `plugin.py`: unbenutzten `mediadb`-Import entfernt.
- `E2MDBDatabase.py`: MediaDB-Index korrigiert.
  - vorher falsch: `idx_media_name ON media(name)`
  - jetzt korrekt: `idx_media_path ON media(path)` und `idx_media_title ON media(title)`

## Hintergrund

Nach der MediaDB-Reduktion enthält die Tabelle nur noch:

```python
path TEXT UNIQUE
title TEXT
short TEXT
extended TEXT
```

Ein Index auf `name` verursacht daher beim blauen Scan-Start:

```text
sqlite3.OperationalError: no such column: name
```

## Ergebnis

Der blaue Button erstellt nur noch Cache-/ResultsDB-Pfade und startet den Backend-Refresh. MediaDB wird ausschließlich im Scannerpfad geschrieben.
