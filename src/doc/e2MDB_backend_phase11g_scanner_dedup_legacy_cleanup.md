# e2MDB Backend Phase 11g - Scanner Deduplication and Legacy File Cleanup

## Goal

Keep all media-name, media-file and TS metadata scanning logic in
`E2MDBScanner.py`.  The daemon must only orchestrate jobs, progress and API
calls.  It must not contain a second copy of the MediaNameParser / recording
parser logic.

## Changes

- Removed duplicated MediaNameParser imports and scan helper functions from
  `e2mdbd.py`.
- Removed duplicated media-file extension constants from `e2mdbd.py`.
- `e2mdbd.py` now creates `E2MDBBackendMetadataScanner()` without injecting
  parser functions.
- `E2MDBScanner.py` imports `E2MDBRecordingParser.parse_recording` directly and
  remains the single backend scan entry.
- Added runtime cleanup for legacy files that may remain on boxes after ZIP
  overwrite installations:
  - `E2MDBWeb.py`
  - `E2MDBEPGWorker.py`
  - `E2MDBServiceListIndices.py`
  - old native parser source leftovers
  - `__pycache__`, `.pyc`, `.pyo`

## Result

The active scan chain is now:

```text
scan job -> e2mdbd job orchestration -> E2MDBScanner.py -> MediaNameParser.py / E2MDBRecordingParser.py -> backend DB import
```

The old OpenWebif resource file is no longer shipped and any stale copy left on
the target box is removed at plugin session start.
