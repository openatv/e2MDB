# e2MDB backend phase 10r - Live/EPG artwork provenance and reason cleanup

## Problem

During the backend migration a queue reason such as `promoted-event-next-now-adhoc`
could be copied into `e2mdb_epg_events.short_desc` when no EPG short description was
available. Screens that use `short_desc` as subtitle then displayed this internal
queue reason to the user.

The Live/EPG result output also showed only the final artwork fields, making it hard
to see whether a poster, backdrop or still came from the event row or from the linked
provider asset row.

## Changes

- The backend no longer stores `queue_item.reason` as `short_desc`.
- Live/EPG provider search no longer uses `queue_item.reason` as event description.
- `e2mdbctl.py live-result <source_key>` now includes `artwork_diagnostics`.
- `artwork_diagnostics` classifies final event artwork fields as portrait, landscape,
  empty or unknown.
- Linked provider asset rows are included with the same artwork classification.

## Notes

Existing rows can still contain old internal reason text in `short_desc`. They can be
cleaned by resetting those values in SQLite or by reprocessing the affected event.
