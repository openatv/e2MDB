# e2MDB Backend Phase 10x - Recording scan schema repair and provider diagnostics

## Problem

The debug bundle showed that the configured scan path was valid and contained six TS recordings, but the refresh still failed.

Findings:

- `/media/hdd/movie` was the only active path.
- The NAS path was configured with mode `0` and was correctly excluded.
- Six TS recordings were detected.
- All six scan items failed because `_e2mdb_recordingparser` was missing at runtime.
- The copied SQLite database still used an older `e2mdb_media` schema without columns such as `source_type`, `browser_ready` and `provider_lookup_status`.
- A later refresh therefore failed with `no such column: source_type`.
- Provider enrichment only wrote aggregate counts, so individual provider/download failures were hard to inspect.

## Changes

- Added explicit schema repair support.
- Re-applies additive schema migrations before scan import, provider enrichment, media status and database status/schema calls.
- Added CLI command:

```sh
python3 e2mdbctl.py db repair-schema
```

- Added API endpoint:

```text
/api/database/repair-schema
```

- Provider enrichment now writes per-item diagnostics to:

```text
/tmp/e2mdb/last_provider_enrich.json
```

- `provider_state.json` now includes a bounded `error_items` list.
- Recording provider cover mapping no longer falls back to episode/still images for poster/cover fields.

## Notes

The native `_e2mdb_recordingparser` extension remains required for TS recordings. If it is missing, this is a deployment problem and the scan must fail clearly.
