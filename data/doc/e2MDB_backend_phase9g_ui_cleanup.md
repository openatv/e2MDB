# e2MDB Backend Phase 9g - MediaBrowser/Scanner UI Cleanup

## Ziel

Kleine UI-Bereinigung ohne Umbau der bestehenden v16-Logik.

## Änderungen

- MediaBrowser-Detailbereich zeigt den internen Hinweis `Lokale Serieninfos aus DB geladen.` nicht mehr sichtbar an.
- Der versteckte `browserExtraHint` bleibt intern vorhanden, damit vorhandene JavaScript-Updates nicht ins Leere laufen.
- Im Scanner-Screen wurde die INFO-Schaltfläche entfernt.
- Die INFO-Taste öffnet im Scanner nicht mehr den alten Scan-Statusscreen.
- Nach Scanende erscheint keine Meldung mehr mit `Press INFO for details.`.

## Nicht geändert

- Service-List-/EPG-Info-Key-Integration bleibt erhalten.
- MediaBrowser-Serien-/Staffel-/Episodenlogik bleibt unverändert.
- Backend-Worker, DB-Schema und Providerlogik bleiben unverändert.
