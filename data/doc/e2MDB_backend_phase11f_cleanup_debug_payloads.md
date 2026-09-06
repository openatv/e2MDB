# e2MDB Backend Phase 11f - Cleanup Debug/Provenance Payloads

## Ziel

Die produktive SQLite-Datenbank soll nur nutzbare Daten enthalten:

- Provider
- Provider-ID
- Medien-Typ
- Titel
- Beschreibung
- lokale Artwork-Pfade
- technische Statusfelder

Debug-/Provenance-Daten wie originale Provider-URLs, Artwork-Quellen, Auswahlgründe
oder Provider-Rohdaten dürfen die produktive DB nicht dauerhaft aufblähen.

## Änderung

`e2mdb_provider_assets` wird nicht mehr mit folgenden Debug-/Provenance-Spalten
befüllt:

- `cover_url`
- `backdrop_url`
- `logo_url`
- `image_url`
- `episode_url`
- `series_poster_url`
- `series_backdrop_url`
- `artwork_json`

Neue Datenbanken bekommen diese Spalten nicht mehr automatisch angelegt.
Bei bestehenden Testdatenbanken werden vorhandene Werte beim Schema-Check bzw.
über den neuen Cleanup-Befehl geleert.

## Debug-JSON

Provider-Rohdaten werden nur noch als Datei behalten, wenn Debug aktiv ist:

```text
/media/hdd/e2MDB/artwork/recordings/<source_key>/provider_result.json
```

Wenn Debug aus ist, werden diese JSON-Dateien entfernt und `json_path` in den
produktiven Tabellen geleert.

## Neuer CLI-Befehl

```sh
python3 e2mdbctl.py db cleanup-debug
python3 e2mdbctl.py db cleanup-debug vacuum
python3 e2mdbctl.py db cleanup-debug keep-json
```

`vacuum` schrumpft die SQLite-Datei nach dem Leeren alter Debug-Spalten.
`keep-json` lässt vorhandene `provider_result.json` Dateien stehen.

## API

```text
/api/database/cleanup-debug
/api/database/cleanup-debug?vacuum=1
/api/database/cleanup-debug?remove_json=0
```

## Ergebnis

Die DB enthält weiterhin alle für GUI, Browser, Timer und ServiceList nutzbaren
Informationen, aber keine großen Debug-/Herkunfts-Payloads mehr.
