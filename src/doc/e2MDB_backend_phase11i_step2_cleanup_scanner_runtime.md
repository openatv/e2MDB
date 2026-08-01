# e2MDB Backend Phase 11i - Step 2 Cleanup: Scanner, Runtime, EventView

## Ziel

Clean-Start ohne Legacy-Ballast. Der Backend-Scanner soll nur nutzbare Werte
weitergeben und keine internen Sidecar-/Debug-Strukturen in Status-JSON oder DB
ablegen.

## Änderungen

- `RUNTIME_DIR` wurde von `/tmp/e2mdb` nach `/var/run/e2mdb` verschoben.
- `E2MDBMain` erbt nicht mehr von `E2MDBScanner`; die GUI nutzt nur noch
  `E2MDBHelper` und startet Backend-Jobs.
- Die alte blaue Ad-hoc-/Rescan-Aktion in `E2MDBEventViewSimple` wurde entfernt.
- Alle bekannten Mediendateien laufen durch `E2MDBScanner.py` und den
  Metadatenparser; META-Dateien sind nicht mehr TS-exklusiv.
- Parser-Werte werden nach fester Reihenfolge gebildet:
  - Titel: EIT -> META -> Dateiname
  - Beschreibung: EIT short -> META description -> TXT
  - Extended: EIT extended -> META description -> TXT
  - Dauer: EIT -> CUTS
- `build_scan_item()` gibt keine internen Parser-/Sidecar-Strukturen mehr aus:
  - kein `sidecars`
  - kein `meta`
  - kein `eit`
  - kein `cuts`
  - kein `txt`
  - kein `duration_source`
- Die Ergebnisdatenbank speichert keine Sidecar-Zähler mehr in
  `e2mdb_recordings`.

## Ergebnis

Die DB und die Scan-Statusdateien enthalten nur noch die Werte, die Backend,
MediaDB, Browser und Provider-Enrichment wirklich benötigen.
