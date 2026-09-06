# e2MDB Backend Phase 10p - Live/EPG Worker Fast Continue

Stand: 2026-05-31

## Ziel

Der Backend-Live/EPG-Worker soll nach einem abgeschlossenen Backend-Job nicht mehr bis zum normalen Idle-Intervall warten. Wenn weitere Queue-Einträge vorhanden sind oder während eines laufenden Jobs neue Kandidaten aus ServiceList/InfoBar/EventView eingehen, soll der nächste Batch spätestens nach ungefähr einer Sekunde starten.

## Umsetzung

- Der normale `daemon_worker_interval_seconds` bleibt ein Idle-Intervall und wird nur verwendet, wenn keine Queue-Einträge offen sind und kein Backend-Job läuft.
- Neu ist `daemon_worker_active_wait_seconds` mit Default `1`.
- Während ein Backend-Job läuft, prüft der Auto-Worker im Active-Wait-Rhythmus.
- Nach jedem abgeschlossenen Backend-Job wird der Auto-Worker zusätzlich per Event geweckt.
- Wenn Enigma2 einen Live/EPG-Worker anfordert, aber gerade ein anderer Backend-Job läuft, wird die Anfrage als akzeptierter Wake behandelt statt als harter Fehler. Die Queue-Daten liegen bereits in SQLite und werden nach Job-Ende durch den Auto-Worker weiterverarbeitet.

## Defaults

```json
{
  "live_epg": {
    "daemon_auto_worker_enabled": true,
    "daemon_worker_batch_limit": 50,
    "daemon_worker_interval_seconds": 30,
    "daemon_worker_active_wait_seconds": 1
  }
}
```

## Ergebnis

Keine Rückkehr zu Enigma2-Workern, kein GUI-Polling und keine Provider-Arbeit im GUI-Prozess. Der Daemon verarbeitet aber aktive Live/EPG-Queues deutlich direkter weiter.
