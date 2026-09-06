# e2MDB Backend Phase 8h - Scan/Provider/GUI bridge fixes

## Ziel

Diese Phase korrigiert drei Regressionspunkte aus dem Backend-Umbau:

- Serien wurden bei gemischten Pfaden zu oft als generische Recordings/Multi behandelt.
- Der blaue Button startete zwar den Backend-Job, aber der Providerlauf konnte bestehende fehlerhafte/leere Treffer überspringen.
- Web-Play/Stop lieferte nur `Playback control still requires the Enigma2 GUI bridge`.

## Änderungen

### MediaNameParser im Daemon

Der Daemon nutzt jetzt den bestehenden reinen Python `MediaNameParser` aus v16, um vor dem Providerlauf aus dem Pfadmodus und Dateinamen saubere Scan-Informationen zu erzeugen:

- `provider_title`
- `series_title`
- `movie_title`
- `season_no`
- `episode_no`
- `estimated_media_type`
- `provider_media_type`
- `name_parser`

Damit werden `.ts`-Dateien in Serienpfaden nicht mehr nur als `recording`/`multi` behandelt.

### Provider-Enrichment

Der Providerlauf bevorzugt nun `provider_title`, `series_title` und `movie_title` vor dem reinen EIT-/META-Titel. Das ist wichtig, weil der EIT-Titel bei Serien oft nur der Episodentitel ist.

Außerdem werden mehr Bildfelder akzeptiert:

- `cover_url`
- `cover_src`
- `poster_url`
- `image_url`
- `backdrop_url`
- `backdrop_src`
- `fanart_url`
- `titlelogo_url`
- `logo_url`
- `clearlogo_url`

### Blauer Button

Blau startet weiter direkt den v16-typischen Komplettlauf für die ausgewählten Pfade, aber jetzt mit `only_missing=False`. Damit werden bereits vorhandene fehlerhafte/leere Providerstände nicht übersprungen.

### Web Play/Stop Bridge

Der Backend-Webserver queued Play/Stop-Kommandos nach:

```text
/tmp/e2mdb/gui_command.json
```

Die Enigma2-GUI pollt diese Datei, solange e2MDB geöffnet ist, und führt aus:

- `play` über `session.nav.playService()`
- `stop` über `session.nav.stopService()`

Das ist ein erster minimaler GUI-Bridge-Schritt. Die Bridge ist aktiv, wenn die e2MDB-GUI geöffnet ist.

## Test

Nach Installation:

```sh
/etc/init.d/e2mdbd restart
```

Dann in der GUI:

```text
e2MDB Scanner öffnen
Pfade auswählen
Blau drücken
```

Danach prüfen:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py browser debug-artwork 20
python3 e2mdbctl.py browser list 10
```

SQL-Prüfung:

```sh
DB="/media/hdd/e2MDB/results.db"
sqlite3 -header -column "$DB" "select hash,file_name,metadata_media_type,metadata_title,metadata_cover_path,artwork_poster_path,provider_lookup_status from e2mdb_media limit 20;"
```

Wichtig: Für einen sauberen Test bei vorher falschen Providerständen den Scan über Blau neu laufen lassen oder gezielt die Providerstatus-Felder zurücksetzen.
