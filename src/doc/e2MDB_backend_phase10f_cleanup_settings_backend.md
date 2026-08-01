# e2MDB Backend Phase 10f - Cleanup, SQLite maintenance and settings reload

Date: 2026-05-31

## Goal

Continue the clean-start migration by moving Live/EPG cleanup and SQLite
maintenance control to the backend daemon. Enigma2 should no longer perform
those database write/maintenance operations directly from the GUI tools or the
OpenATV function timer task wrappers.

## Changes

### Backend settings export

`E2MDBBackendConfig.py` now exports the relevant Live/EPG and cleanup settings
into `/etc/enigma2/e2mdb/settings.json`:

```json
"cleanup": {
  "enabled": true,
  "epg_meta_enabled": false,
  "queue_done_retention_seconds": 86400,
  "expired_event_limit": 1000,
  "remove_primary_cache": false,
  "prefill_state_retention_seconds": 1209600,
  "sqlite_maintenance": true,
  "sqlite_vacuum": true,
  "sqlite_reindex": false
}
```

The e2MDB setup screen now exports the backend JSON settings on Save and asks the
running daemon to reload them. This avoids requiring a daemon restart after
changing cleanup-related options in the GUI.

### Backend database cleanup owner

`E2MDBBackendDatabase.py` now owns the Live/EPG cleanup operations:

- count expired Live/EPG display events
- delete expired `e2mdb_epg_events` rows
- clean finished/obsolete `e2mdb_fetch_queue` rows
- maintain `e2mdb_cleanup_state`
- optionally remove unreferenced primary cache files
- cleanup stale `/etc/enigma2/e2mdb/prefill_state.json` entries
- run SQLite ANALYZE/VACUUM/REINDEX from the daemon

`e2mdb_cleanup_state` is created by the backend schema so existing diagnostics
keys remain available without Enigma2 doing the DB writes.

### New daemon commands

Unix command socket:

```sh
python3 e2mdbctl.py cleanup status
python3 e2mdbctl.py cleanup dry-run
python3 e2mdbctl.py cleanup run
python3 e2mdbctl.py db maintenance vacuum reindex
```

HTTP API:

```text
GET/POST /api/cleanup/status
GET/POST /api/cleanup/run?dry_run=1
GET/POST /api/settings-reload
```

### GUI/tools migration

The Live/EPG cleanup status screen now reads diagnostics from the backend daemon
instead of calling the local cleanup manager diagnostics path.

The manual buttons in that screen now call backend commands:

- Yellow: backend cleanup dry-run
- Blue: backend cleanup run
- OK: backend SQLite maintenance

The OpenATV function timer wrappers for:

- `e2MDB Live/EPG Cleanup`
- `e2MDB SQLite Maintenance`

now call the backend daemon as well. They no longer execute the cleanup or SQLite
maintenance directly in the Enigma2 process.

## Validation

Syntax check:

```sh
python3 -m py_compile ...
```

All Python files compile successfully.

Backend cleanup smoke test with a temporary SQLite database:

- one expired EPG event inserted
- one old finished queue row inserted
- `cleanup status` reports both candidates
- dry-run reports both without deleting
- real cleanup deletes both
- final status reports zero candidates

## Notes

General cache deletion from the scanner screen still has legacy GUI-side paths
for now. This phase specifically moves Live/EPG cleanup and SQLite maintenance,
because those were still direct database write/maintenance operations from
Enigma2.
