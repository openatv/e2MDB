# e2MDB Backend Phase 11m - Live/EPG worker queue button fix

## Goal

The Live/EPG worker queue screen must not modify the SQLite queue directly from
Enigma2. Queue cleanup actions are backend-owned operations.

## Changes

- Added backend command `live_queue_clear`.
- Added HTTP endpoint `/api/live/queue/clear?mode=...`.
- Added CLI command `e2mdbctl.py live-queue clear [finished|failed|prefill|all]`.
- The GUI queue screen now uses backend commands for yellow/blue/OK cleanup.
- Green refresh now writes an explicit last-action message so the key press is visible.
- Blue cleanup now removes failed/error rows and pending retry rows with `last_error`.

## Modes

- `finished`: removes `done`, `no_match`, `ignored`, `short_skipped`, `ended_skipped`.
- `failed`: removes `failed`, `error`, and rows with a non-empty `last_error`.
- `prefill`: removes rows with `reason LIKE 'prefill%'`.
- `all`: removes the whole Live/EPG fetch queue.

## Clean-start note

No legacy DB repair or local GUI worker path was added. The backend remains the
owner of queue writes and cleanup.
