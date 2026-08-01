# e2MDB Backend Phase 11n - DB status and maintenance screen

Date: 2026-06-01
Base: phase11m worker queue button fix

## Goal

The former Live/EPG cleanup status screen is now a broader user-facing database
status and maintenance screen.

The screen should explain the local e2MDB database state in a way an end user can
understand, without making screen opening slow on large libraries.

## Changes

- Renamed the GUI screen/menu entry from Live/EPG cleanup status to DB status and
  maintenance.
- Added a fast database overview to the screen:
  - DB availability and size
  - main DB size and total SQLite sidecar size
  - reusable free space inside the DB
  - imported file count
  - media entry count
  - browser-ready count
  - TS recording vs normal media-file split
  - movie/series/local episode/unknown counters
  - provider done/pending/missing/error counters
  - artwork present/missing counters
  - Live/EPG active/expired/queue counters
- Kept the existing cleanup, dry-run and SQLite maintenance actions.
- Collapsed the queue status into one short line so the screen stays readable.
- Added a note that the screen only reads fast DB counters and does not scan media
  folders when opened.

## Backend implementation

`BackendDatabase.status()` now returns an additional `inventory` object. It uses
only SQLite metadata and aggregate queries. It does not walk scan paths or cache
folders.

Additional lightweight DB metadata is returned:

- `sidecar_size_bytes`
- `total_size_bytes`
- `page_size`
- `page_count`
- `freelist_count`
- `freelist_bytes`

This keeps `database_status` suitable for GUI screen opening even when a user has
large media tables.

## Clean-start note

No legacy repair path and no local GUI-side database writes were added. The GUI
only asks the backend for status and maintenance actions.
