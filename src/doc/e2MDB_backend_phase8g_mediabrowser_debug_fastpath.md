# e2MDB Backend Phase 8g - MediaBrowser Diagnose und Fast-Path

## Ziel

Diese Phase behebt zwei Regressionspunkte aus dem Backend-MediaBrowser:

- Der MediaBrowser darf beim Öffnen nicht die komplette Library verarbeiten.
- Fehlende Cover müssen eindeutig diagnostizierbar sein: DB leer, Datei fehlt, API-Mapping fehlt oder Frontend lädt falsch.

## Änderungen

### MediaBrowser Fast-Path

`E2MDBBackendDatabase._browser_items_grouped_page()` arbeitet jetzt mit einem begrenzten Row-Window statt mit einem kompletten Tabellenlauf. Dadurch kommt die erste Seite schneller zurück. Die Gruppierung bleibt aktiv, aber bis zum späteren dedizierten Browser-Index ist die Seitennavigation bewusst approximativ.

### Serien-Gruppierung verbessert

Serientitel werden aus typischen Dateinamen wie `S03E01`, `3x01` usw. abgeleitet. Dadurch wird aus Einträgen wie:

```text
12 Monkeys S03E01 GERMAN 720p WEB ...
12 Monkeys S03E02 GERMAN 720p WEB ...
```

wieder ein Serien-Eintrag:

```text
12 Monkeys
```

mit Staffel-/Folgenzählung.

### Cover-Diagnose

Neue Diagnose-Endpunkte:

```text
/api/browser/debug-artwork?limit=30
/api/browser/debug-performance?limit=24
```

Neue CLI-Kommandos:

```sh
python3 e2mdbctl.py browser debug-artwork 30
python3 e2mdbctl.py browser debug-performance 24
```

`debug-artwork` zeigt pro Sample:

- Titel
- Media-Typ
- Provider-Status
- DB-Felder für Cover/Backdrop
- gemappte URL
- lokale Datei vorhanden/nicht vorhanden
- Dateigröße
- gefundene Bilddateien unter e2MDB-Roots

`debug-performance` zeigt:

- DB-Status-Zeit
- erste Browser-Seite in ms
- Anzahl gelieferter Items
- verwendete Quelle

## Box-Test

```sh
/etc/init.d/e2mdbd restart
sleep 2

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB

python3 e2mdbctl.py browser debug-performance 24
python3 e2mdbctl.py browser debug-artwork 20
python3 e2mdbctl.py browser list 16
```

HTTP:

```sh
wget -qO- 'http://127.0.0.1:8088/api/browser/debug-performance?limit=24' | python3 -m json.tool
wget -qO- 'http://127.0.0.1:8088/api/browser/debug-artwork?limit=20' | python3 -m json.tool
wget -qO- 'http://127.0.0.1:8088/api/results?action=browser_list&page=1&limit=16' | python3 -m json.tool
```

## Auswertung Cover

- `with_cover_value = 0`: Provider/Artwork schreibt noch keine Coverpfade in die DB.
- `with_cover_value > 0` und `missing_local_cover_file > 0`: DB hat Pfade, Dateien fehlen.
- `with_local_cover_file > 0`, aber Web zeigt nichts: HTTP-Auslieferung oder Frontend prüfen.
- `image_files` enthält Bilder, aber Samples haben keine Coverwerte: Download existiert, DB-Zuordnung fehlt.

