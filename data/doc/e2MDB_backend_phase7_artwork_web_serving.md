# e2MDB Backend Phase 7 - Artwork Web Serving

## Ziel

Phase 6 konnte Browser-Textdaten bereits aus dem Backend liefern, lokale Cover-Dateien wurden im Webbrowser aber nicht angezeigt, wenn die API direkte Dateisystempfade wie `/media/hdd/e2MDB/.../poster.jpg` zurückgegeben hat.

Ein Webbrowser kann solche lokalen Box-Dateipfade nicht laden. Deshalb liefert der Daemon lokale Artwork-Dateien jetzt über einen eigenen HTTP-Endpunkt aus.

## Neuer Endpunkt

```text
GET /api/artwork/file?path=<absolute-local-path>
```

Beispiel:

```text
http://BOX-IP:8088/api/artwork/file?path=%2Fmedia%2Fhdd%2Fe2MDB%2Fartwork%2Frecordings%2Fabc%2Fposter.jpg
```

## Sicherheit

Der Endpunkt liefert nur Dateien aus erlaubten e2MDB-Cache-Wurzeln aus:

- `settings.cache.root`
- `settings.database.root`
- `/media/hdd/e2MDB`
- `/media/usb/e2MDB`

Andere absolute Pfade werden mit `403 forbidden` blockiert.

## API-Ausgabe

`E2MDBBackendDatabase` wandelt lokale Artwork-Pfade automatisch in relative HTTP-URLs um:

```json
{
  "cover_url": "/api/artwork/file?path=%2Fmedia%2Fhdd%2Fe2MDB%2Fartwork%2Frecordings%2F...%2Fposter.jpg",
  "cover_file_path": "/media/hdd/e2MDB/artwork/recordings/.../poster.jpg"
}
```

Remote-URLs wie `https://...` bleiben unverändert.

## Test auf der Box

Daemon neu starten:

```sh
/etc/init.d/e2mdbd restart
sleep 2
```

Browser-Liste prüfen:

```sh
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=3' | grep -o '/api/artwork/file?path=[^" ]*' | head
```

Eine URL direkt testen:

```sh
URL="$(wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=1' | sed -n 's/.*"cover_url": "\([^"]*\)".*/\1/p')"
wget -S -O /tmp/e2mdb-cover-test.img "http://127.0.0.1:8088$URL"
ls -lh /tmp/e2mdb-cover-test.img
```

Im Webbrowser:

```text
http://BOX-IP:8088/
```

Der MediaBrowser sollte jetzt lokale Cover anzeigen, sofern der Metadata-Job bereits Artwork heruntergeladen hat.

## Hinweis

Wenn weiterhin keine Cover angezeigt werden, zuerst prüfen, ob überhaupt lokale Artwork-Dateien existieren:

```sh
find /media/hdd/e2MDB -type f \( -name 'poster.*' -o -name 'cover.*' -o -name 'backdrop.*' \) | head
```

Falls keine Dateien gefunden werden, muss zuerst ein Provider-/Metadata-Job laufen:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py metadata start 20
```
