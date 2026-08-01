# e2MDB Backend Phase 10m - Push Notify GUI Refresh

## Ziel

Der alte Ad-hoc-Finish-Pfad durfte nicht einfach durch Polling ersetzt werden.
Offene InfoBar-/EventView-/ComponentMeta-Screens sollen nachgelieferte Backend-Metadaten weiterhin anzeigen, aber ohne Enigma2-Worker, ohne Providerarbeit im GUI-Prozess und ohne periodische GUI-Poller.

## Umsetzung

Phase 10m führt einen Push-basierten Backend-Notify-Weg ein.

### Runtime-Socket

Enigma2 öffnet beim Sessionstart einen blockierenden Unix-Datagram-Listener:

```text
/tmp/e2mdb/gui_notify.sock
```

Der Listener schläft im Normalfall im eigenen Thread und erzeugt keine periodische GUI-Last.

### Backend -> GUI

Wenn der Daemon einen Live/EPG-Queue-Eintrag verarbeitet hat, sendet er eine kleine Notification an den GUI-Socket:

```json
{
  "event": "live_epg_updated",
  "source_key": "...",
  "reason": "backend-live-worker",
  "state": "done"
}
```

Auch `no_match` und `ended_skipped` werden signalisiert, damit offene Screens ihren Status aktualisieren können.

### GUI-Seite

`E2MDBComponentMeta` registriert sichtbare Sources mit ihrem `source_key` beim neuen Notify-Manager.

Bei einer Notification:

1. Listener-Thread empfängt das Push-Event.
2. Listener-Thread holt das fertige Backend-Result per Command-Socket.
3. Listener-Thread baut daraus Skin-Metadaten.
4. Nur das finale `source.setMeta()` und `source.changed()` läuft über `reactor.callFromThread()` im Enigma2-MainThread.

Damit laufen keine Provider-, DB- oder Datei-Sucharbeiten im GUI-MainThread.

## Kein Polling

Dieser Weg ersetzt den alten Ad-hoc-Finish-Callback ohne neue Timer/Poller.

Es gibt keinen periodischen Poller für offene Screens. Aktualisiert wird nur, wenn der Daemon wirklich ein Backend-Result fertig verarbeitet hat.

## MainThread-Härtung

Zusätzlich wurden verbleibende synchrone `exists()`-Prüfungen aus dem Live/EPG-Skin-Datenpfad entfernt. Pfade gelten als Backend-Daten; Renderer sollen sie nicht durch zusätzliche stat-Aufrufe im MainThread validieren.

## Geänderte Dateien

- `e2MDB/E2MDBBackendNotify.py`
- `e2MDB/E2MDBBackendConfig.py`
- `e2MDB/E2MDBComponentMeta.py`
- `e2MDB/E2MDBSkin.py`
- `e2MDB/e2mdbd.py`
- `e2MDB/plugin.py`

## Ergebnis

Offene GUI-Screens können nach Backend-Fertigstellung aktualisiert werden, ohne die alte Enigma2-Worker-Schiene und ohne Pollinglast wieder einzubauen.
