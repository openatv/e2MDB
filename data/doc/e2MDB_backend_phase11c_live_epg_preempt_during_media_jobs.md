# e2MDB Backend Phase 11c - Live/EPG Preempt during Media Jobs

## Ziel

Während eines laufenden Media-Refresh oder Provider-Enrich-Jobs sollen neue
Live-/EPG-Ad-hoc-Einträge aus der GUI nicht bis zum Ende des langen Jobs warten.
Das entspricht dem v16-Verhalten: aktuelle, sichtbare GUI-Events haben höhere
Priorität als Hintergrund-/Prefill-Arbeit.

## Änderung

Der Backend-Daemon bleibt Single-Writer und startet keinen zweiten Job parallel.
Stattdessen verarbeitet der laufende Media-Job zwischendurch gezielt
hochpriorisierte Live-/EPG-Queue-Einträge.

Default:

- `live_epg.preempt_min_priority = 80`
- `live_epg.preempt_max_items = 2`

Damit werden bevorzugt verarbeitet:

- InfoBar Now
- ServiceList visible-now
- EPG/EventView/Open-Event
- Ad-hoc Now

Nicht vorgezogen werden:

- ServiceList next/reserve-next
- Prefill/Nachtlauf
- niedrige Hintergrund-Queue

## Technische Umsetzung

- `e2mdb_fetch_queue` kann jetzt mit `min_priority` geclaimt werden.
- `scan_and_enrich` ruft während Scan/Enrich `_process_high_priority_live_epg_queue()` auf.
- Der aktive Job bleibt der Media-Job; die Live-/EPG-Verarbeitung läuft im selben Backend-Thread.
- GUI-Push-Notify bleibt aktiv, sobald ein vorgezogener Eintrag fertig ist.

## Diagnose

`live worker status` zeigt zusätzlich den letzten Preempt-Block:

```sh
python3 e2mdbctl.py live worker status
```

Relevante Ausgabe:

```json
"preempt": {
  "processed": 1,
  "done": 1,
  "min_priority": 80,
  "reason": "metadata-enrich"
}
```
