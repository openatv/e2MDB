# e2MDB Backend Phase 10l - GUI Spinner Callback Cleanup

Stand: 2026-05-31

## Problem

Nach Phase 10k konnte Enigma2 beim Start mit Spinner hängen. Der Stacktrace zeigte,
dass der Backend-Live/EPG-Wakeup im Enigma2-MainThread noch den alten
Ad-hoc-Finish-Pfad auslöste. Dieser Pfad rief direkt `_update_source_meta_now()` und
anschließend `source.changed()` auf. Dadurch wurden Renderer synchron im MainThread
aktiviert und `E2MDBEventInfo` prüfte Bildpfade per `os.path.exists()`.

Das widerspricht dem Clean-Start-Ziel: Enigma2 soll keine Worker-/Provider- oder
schwere Refresh-Logik mehr ausführen.

## Änderung

- `E2MDBBackendLiveBridge.request_backend_live_epg_processing()` ist jetzt ein reiner
  Fire-and-forget-Wakeup für den Backend-Daemon.
- Alte Callback-Finish-Semantik wird nicht mehr ausgeführt.
- `E2MDBComponentMeta`, `E2MDBInfoBarBridge` und `E2MDBEventViewBridge` geben keine
  Finish-Callbacks mehr an den Backend-Wakeup weiter.
- Ad-hoc-Bookkeeping wird nach erfolgreichem Wakeup sofort freigegeben.
- `E2MDBEventInfo` ruft bei Skin-Pfadauswahl kein `os.path.exists()` mehr im
  MainThread auf. Die Backend-/Cache-Schicht ist für gültige Pfade zuständig.

## Ergebnis

Der Backend-Wakeup kann Enigma2 nicht mehr unmittelbar in eine synchrone
Source-/Renderer-Aktualisierung zwingen. Skins aktualisieren weiterhin über den
normalen Enigma2-Source-Lifecycle und die Backend-Daten werden über DB/API/Status
bereitgestellt.
