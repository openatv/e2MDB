# e2MDB Backend Phase 10y - GUI Backend Progress Translation

Stand: 2026-05-31
Basis: phase10x

## Ziel

Die Backend-Umstellung bleibt Clean-Start. Die Punkte Recording-Scan mit Parser,
Sidecar-/Meta-Pruefung und Provider-Enrichment fuer Recordings wurden als erledigt
markiert. Der naechste Fokus ist die sichtbare GUI-Ausgabe von Backend-Statusdaten.

Backend-Status, Job-Phasen und Fortschrittsmeldungen, die im e2MDB Scanner-/Progress-
Bereich sichtbar sind, duerfen nicht als feste englische Rohtexte in der GUI erscheinen.
Der Daemon kann weiterhin stabile technische Status- und Phasenwerte liefern, aber die
GUI uebersetzt diese Werte ueber die normale e2MDB gettext-Domain.

## Umsetzung

### plugin.py

Neue Uebersetzungs-Mappings fuer Backend-Status:

- Backend-Phasen
- Backend-Jobtypen
- Backend-Meldungen

Die Progress-Anzeige nutzt jetzt uebersetzte Texte fuer:

- Header: Backend job / Phase
- Fortschrittsstatus
- Abschlussdialog
- bekannte Backend-Fehlermeldungen

Dynamische Werte wie Dateiname, Titel, Pfad, Zaehler und Prozentwerte bleiben unveraendert.

### locale/e2MDB.pot

Neue Backend-Progress-Strings wurden in die POT-Datei aufgenommen.

### locale/de.po

Deutsche Uebersetzungen fuer die neuen Backend-Progress-Strings wurden ergaenzt.

### locale/de/LC_MESSAGES/e2MDB.mo

Der deutsche gettext-Katalog wurde neu erzeugt, damit die Texte direkt auf der Box
wirksam sind.

## Abgedeckte sichtbare Backend-Texte

Beispiele:

- Validating media scan paths
- Collecting media files
- Scanning media files
- Importing scan data
- Preparing provider search
- Searching internet metadata
- Provider search finished
- Preparing Live/EPG queue worker
- Searching Live/EPG metadata
- Running SQLite maintenance
- No valid recording/media scan paths found
- No media files found in configured scan paths
- No recordings need provider enrichment

## Nicht geaendert

Der Daemon selbst schreibt weiterhin technische Statuswerte und englische Logtexte.
Das ist beabsichtigt, weil Logs und JSON-Diagnose technisch stabil bleiben sollen.
Uebersetzt wird die Darstellung in der GUI.

## Test

- Python py_compile
- gettext-Katalog neu erzeugt
- ZIP ohne __pycache__, .pyc, .pyo
