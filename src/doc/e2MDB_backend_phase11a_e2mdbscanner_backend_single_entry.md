# e2MDB Backend Phase 11a - E2MDBScanner as single backend scan entry

Date: 2026-05-31

## Goal

All backend media scans must enter through `e2MDB/E2MDBScanner.py`.

The daemon must not keep a parallel scanner implementation for TS recordings or
normal media files.  `e2mdbd.py` remains responsible for job orchestration,
progress/status output, scheduler/API handling and SQLite import.  The actual
scan decisions are made by the backend-safe scanner facade in `E2MDBScanner.py`.

## Implemented

### New backend scanner facade

`E2MDBScanner.py` now provides:

```python
E2MDBBackendMetadataScanner
```

This class is safe to use from the daemon and centralizes:

- supported media extension filtering
- ignored sidecar/artwork/subtitle/log files
- excluded folders
- scan path diagnostics
- media file iteration
- TS recording detection
- mandatory native recording parser usage for `.ts`
- META/EIT/CUTS result handling
- MediaNameParser usage for non-TS media files
- OpenATV recording filename cleanup before provider search
- provider title, season/episode and media type preparation
- final scan item construction for backend import

### Daemon changes

`e2mdbd.py` now creates an `E2MDBBackendMetadataScanner` instance in the job
manager and delegates scan work to it.

The daemon uses the scanner facade for:

- `scan paths`
- `scan paths count`
- recording/media file collection
- per-file scan item creation
- native parser availability checks

The daemon no longer calls the native TS parser directly inside the scan loop.
It asks `E2MDBScanner.py` for a scan item and only imports the returned item.

### Progress diagnostics

The runtime scan summaries now include:

```json
"scanner_module": "E2MDBScanner.py"
```

Individual scan items use explicit scanner markers:

```text
E2MDBScanner.native_ts_recording_parser
E2MDBScanner.media_name_parser
```

## Rules

- `.ts` files are handled as Enigma2 TS recordings.
- `.ts` files require the native `_e2mdb_recordingparser` extension.
- normal media files use MediaNameParser/path mode.
- non-media files are ignored, not scanned and not counted as scan errors.
- the daemon must not add a second scanner path next to `E2MDBScanner.py`.

## Test notes

Run on the box:

```sh
python3 e2mdbctl.py scan paths count
python3 e2mdbctl.py refresh run all all-items
cat /tmp/e2mdb/last_recording_scan.json
```

Expected markers:

```json
"scanner_module": "E2MDBScanner.py"
```

and per item:

```json
"scanner_used": "E2MDBScanner.native_ts_recording_parser"
```

or:

```json
"scanner_used": "E2MDBScanner.media_name_parser"
```
