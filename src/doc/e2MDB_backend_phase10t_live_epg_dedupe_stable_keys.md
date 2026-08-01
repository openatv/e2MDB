# e2MDB Backend Phase 10t - Live/EPG stable source keys and duplicate cleanup

## Problem

During the backend migration the same visible Live/EPG event could enter the queue through different GUI contexts:

- ServiceList visible now/next
- ServiceList reserve entries
- InfoBar/EventView ad-hoc requests
- promoted next/now handling
- night prefill

Some contexts expose different or missing Enigma2 `event_id` values. The old key generation included `event_id`, so the same natural event could be stored multiple times with different `source_key` values.

Example duplicate identity:

- same `service_ref`
- same `begin_time`
- same `event_end`
- same title/title_norm
- different `source_key`

## Decision

The Live/EPG `source_key` is now a stable natural key:

```text
source_type | service_ref | begin_time | event_end | normalized title
```

It intentionally does not include:

- Enigma2 event_id
- queue reason
- GUI context
- ad-hoc/promoted/service-list labels

This keeps ServiceList, InfoBar, EventView and prefill converged on the same cache row.

## New CLI diagnostics

Dry-run duplicate report:

```sh
python3 e2mdbctl.py live-duplicates [limit] [query]
```

Merge duplicate rows:

```sh
python3 e2mdbctl.py live-dedupe [limit] [query]
```

Example:

```sh
python3 e2mdbctl.py live-duplicates 100 "James Bond"
python3 e2mdbctl.py live-dedupe 100 "James Bond"
```

## New API/socket commands

Socket commands:

```text
live_duplicates
live_dedupe
```

HTTP API:

```text
GET /api/live/duplicates?limit=100&q=James%20Bond
GET /api/live/dedupe?limit=100&q=James%20Bond
```

## Cleanup behavior

`live-dedupe` keeps the best row per natural event:

1. prefer `done`
2. prefer rows with landscape artwork
3. prefer newer rows

Then it:

- moves the kept row to the canonical source key
- moves provider asset links to the kept event
- removes duplicate event rows
- removes duplicate queue rows

Artwork files are not deleted by this operation.

## Result

Multiple broadcasts on different services may still create separate EPG rows, which is correct.

The same event on the same service/time/title now converges to one row.
