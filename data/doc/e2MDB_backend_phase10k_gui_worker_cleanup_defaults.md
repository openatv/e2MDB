# e2MDB Backend Phase 10k - GUI worker cleanup and sane defaults

## Ziel

Clean-Start ohne Kompatibilitätsschicht:

- kein lokaler Enigma2 Provider-/EPG-Worker mehr
- kein Fallback auf alte GUI-Worker-Progress-Logik
- Enigma2 erzeugt nur noch Live-/EPG-Kandidaten und Queue-Einträge
- e2mdbd verarbeitet Queue, Provider, Artwork und Jobs
- normale GUI zeigt nur noch die wichtigsten Einstellungen

## Entfernt/abgeschaltet

- `start_epg_worker_manager()` wird nicht mehr beim Sessionstart gestartet.
- Der alte direkte `E2MDBBackroundRefresh` Scanner im Enigma2-Prozess wurde entfernt.
- Ad-hoc-Aufrufe aus InfoBar, EventView, ComponentMeta und ChannelSelection gehen jetzt an `E2MDBBackendLiveBridge`.
- Die normale `setup.xml` zeigt keine lokalen Worker-/Prioritäts-/Timing-Optionen mehr.

## Backend-Live-Bridge

Neue Datei:

```text
E2MDBBackendLiveBridge.py
```

Sie enthält nur leichte Backend-Anfragen:

```text
request_backend_live_epg_processing()
poke_backend_live_epg_worker()
```

Diese Funktionen starten keinen lokalen Provider-Worker. Sie wecken nur den Daemon über den Backend-Socket.

## Neue Defaults

Für den Clean-Start sind die Defaults jetzt auf Backend-Betrieb ausgelegt:

- Media Database: enabled
- Live/EPG metadata: enabled
- Live/EPG daemon batch: 50
- Daemon interval: 20 seconds
- `live-queue-every-15min`: enabled, limit 50
- Prefill: enabled
- Prefill mode: night
- Prefill start hour: 04:00
- Prefill horizon: 2 days
- Prefill max events: 1500
- Max events per service: 120
- Zap history top channels: 25

Damit kann der Nachtlauf deutlich mehr Ereignisse erfassen als die alten konservativen Testwerte.

## Bewusst nicht entfernt

Die Config-Objekte bleiben intern vorhanden, damit bestehende Module beim Import nicht brechen. Sie sind aber nicht mehr normale GUI-Optionen und dienen nur noch als technische Default-/Export-Werte während der weiteren Backend-Umstellung.


## Nachtbetrieb

Der normale Medienrefresh bleibt der Backend-Job:

```text
daily-media-refresh -> scan_and_enrich -> 03:30
```

Die Live/EPG-Queue wird danach automatisch durch den Backend-Scheduler/Daemon verarbeitet:

```text
live-queue-every-15min -> live_epg_worker -> limit 50
```

Das Anlegen vieler zukünftiger Live/EPG-Kandidaten benötigt weiterhin Enigma2, weil nur Enigma2 die EPG-Datenbank sicher kennt. Das ist kein Provider-Worker mehr: Es werden nur Queue-Kandidaten erzeugt. Provider/Artwork/DB-Verarbeitung bleibt im Daemon.
