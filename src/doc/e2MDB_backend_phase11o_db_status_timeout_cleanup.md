# e2MDB Backend Phase 11o - DB status timeout and UI cleanup

Date: 2026-06-01
Base: phase11n DB status and maintenance screen

## Goal

The DB status and maintenance screen must open reliably on large libraries and must
only show user-facing information that is useful on the screen itself.

## Changes

- Removed the yellow dry-run button from the DB status and maintenance screen.
- Removed the dry-run line and the explanatory technical footer from the screen.
- Added DB size to the first status line and always keeps the status line visible
  when the backend returns file metadata.
- Added a lightweight CPU/system-load line.
- Increased the GUI database-status socket timeout from 0.75 seconds to 2.0
  seconds.
- Reworked `database_status` to avoid schema creation and write-side PRAGMAs.
- `database_status` now uses a short read-only SQLite connection for status reads.
- If the backend database lock is busy, `database_status` returns a partial status
  with file size and system load instead of blocking the GUI until a timeout.
- Inventory counters are now collected with compact aggregate queries instead of
  many individual count queries.

## Performance note

The screen still does not walk media paths or cache folders when opened. The DB
size is read from SQLite files only, and CPU/system load is read from `/proc`.
