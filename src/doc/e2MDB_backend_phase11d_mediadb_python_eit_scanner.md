# e2MDB Backend Phase 11d - MediaDB restore and Python EIT scanner

## Ziel

Der Backend-Scan verwendet weiterhin nur `E2MDBScanner.py` als zentralen Scanner, stellt aber die v16-
MediaDB-Funktion für OpenATV-Timer wieder her. Nicht-Media-Dateien werden vorher gefiltert. TS-Dateien
werden über den Python-META/EIT/CUTS/TXT-Parser gelesen.

## MediaDB

Die MediaDB ist absichtlich klein und enthält nur die Felder, die OpenATV-Timer benötigen:

```text
path TEXT UNIQUE
title TEXT
short TEXT
extended TEXT
```

Der Backend-Scanner schreibt diese Werte bei jedem Scan-Item direkt über `mediadb.upsert()`.

## EIT/META/TXT-Reihenfolge

Für die Result-/MediaDB werden aus EIT nur noch diese Werte verwendet:

```text
title
short
extended
duration
```

Reihenfolge:

```text
title:    EIT title -> META title -> filename title
short:    EIT short -> META description -> TXT text
extended: EIT extended -> META description -> TXT text
```

Die Dateigröße kommt direkt von der Mediendatei. Die Dauer kommt bevorzugt aus der EIT und alternativ aus
CUTS. Begin-/End-Zeit wird für die MediaDB nicht benötigt.

## Native C Parser

Der alte native C-EIT-Parser wurde aus dem Paket entfernt. `setup.py` baut keine native Extension mehr.
`E2MDBRecordingParser.py` enthält jetzt den Python-Parser inklusive `EITFileReader`.
