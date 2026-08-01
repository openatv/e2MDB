# e2MDB Backend Phase 8v - Browser filter restore

Fixes MediaBrowser filtering while the optional browser index is building.

- Letter filter is applied in direct SQL fallback.
- Search/year/genre/cast/letter are no longer cleared while the index is not ready.
- Direct fallback now receives the active filters instead of empty values.
- Cast search works through metadata/people tables even without the optional browser people index.

Expected behavior: pressing `B` only lists entries whose display title starts with B.
