# e2MDB Backend Phase 8 - GUI backend jobs and full provider flow

## Ziel

Diese Phase ersetzt den alten Scannerstart aus der Enigma2-GUI durch Backend-Jobs.
Die GUI startet keine schweren Scanner-/Provider-Arbeiten mehr im Enigma2-Prozess,
sondern spricht nur noch mit `e2mdbd` über den Unix-Command-Socket.

## Enigma2-GUI

Die blaue Taste im Scanner-Screen öffnet jetzt eine Job-Auswahl:

- Scan recordings only
- Scan recordings + provider metadata
- Provider metadata only

Die GUI liest den Fortschritt über den Backend-Status und aktualisiert den
Progress-Bereich per `eTimer`. Der laufende Job kann über die blaue Taste wieder
gestoppt werden.

Der GUI-Scan verwendet die aktuell im Screen selektierten Pfade und übergibt sie
an den Daemon als Job-Option. Damit ist kein alter lokaler Scannerlauf mehr nötig.

## Backend-Client

`E2MDBBackendClient.py` unterstützt jetzt:

- kurze GUI-Status-Timeouts
- serialisierte Scan-Pfade für Backend-Jobs
- `start_backend_scan(..., paths=...)`
- `start_backend_scan_and_enrich(..., paths=..., limit=...)`
- `start_backend_metadata_enrichment(..., limit=..., only_missing=...)`

`limit=0` bedeutet: alle passenden Einträge verarbeiten.

## Daemon

`e2mdbd.py` kann Scan-Pfade jetzt direkt aus den Job-Optionen verwenden. Wenn
keine Pfade übergeben werden, nutzt der Daemon weiter `/etc/enigma2/e2mdb/paths.json`.

Der Scheduler-Refresh startet jetzt `scan_and_enrich` statt nur `recording_scan`.
Damit entspricht ein geplanter e2MDB Refresh wieder dem erwarteten Ablauf:

1. Recordings scannen
2. META/EIT/CUTS parsen
3. SQLite importieren
4. Provider-Metadaten ergänzen
5. Artwork laden

## CLI

Die CLI unterstützt jetzt `all`:

```sh
python3 e2mdbctl.py metadata start all
python3 e2mdbctl.py scan-enrich start all
```

`all` wird intern als `limit=0` an den Daemon übergeben und dort auf einen großen
Sicherheitswert normalisiert.

## Box-Test

```sh
/etc/init.d/e2mdbd restart
sleep 2

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB

python3 e2mdbctl.py status
python3 e2mdbctl.py scan-enrich start all
cat /tmp/e2mdb/status.json
python3 e2mdbctl.py metadata state
python3 e2mdbctl.py db status
```

Während des Jobs sollte `/tmp/e2mdb/status.json` Phasen wie diese zeigen:

- collect
- recording_scan
- db_import
- provider_prepare
- provider_lookup
- done

## GUI-Test

1. e2MDB Scanner-Screen öffnen.
2. Pfade auswählen.
3. Blaue Taste drücken.
4. `Scan recordings + provider metadata` wählen.
5. Progress in der GUI beobachten.
6. Nach Abschluss MediaBrowser/WebUI prüfen.

## Cover-Test danach

Nach einem vollständigen Providerlauf können Cover geprüft werden:

```sh
find /media/hdd/e2MDB -type f \( -name 'poster.*' -o -name 'cover.*' -o -name 'backdrop.*' \) | head
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=3' | grep -o '/api/artwork/file?path=[^" ]*' | head
```

Wenn Artwork-Dateien vorhanden sind und die Browser-API `/api/artwork/file?...`
liefert, ist die Bildauslieferung im Daemon-Pfad korrekt verdrahtet.
