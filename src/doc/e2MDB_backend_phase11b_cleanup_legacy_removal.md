# e2MDB backend phase 11b - Legacy cleanup after backend scanner switch

This phase removes obsolete clean-start leftovers that were no longer part of the backend-only runtime path.

## Removed

- `e2MDB/E2MDBServiceListIndices.py`
  - Unused bootstrap/helper from the older native ServiceList index experiment.
  - The active integration is `E2MDBServiceListIntegration.py` plus `E2MDBServiceListPreview.py`.

## Simplified

- `e2MDB/E2MDBCleanupManager.py`
  - Removed old local Enigma2 cleanup and SQLite maintenance implementation.
  - The file now only contains OpenATV FunctionTimer bridge tasks that forward cleanup/maintenance to `e2mdbd`.
  - No direct SQLite cleanup, no direct cache deletion and no local cleanup timer remain in Enigma2.

- `e2MDB/plugin.py`
  - Removed obsolete `E2MDBScannerHelper`/`e2mdbscanner.scheduler` state.
  - Removed hidden scan-only / metadata-only backend action branches from the scanner screen.
  - Blue button now always starts the clean backend media refresh (`scan_and_enrich`) for selected paths.
  - Removed stale cleanup TODO and unused backend-client imports.

## Kept intentionally

- `E2MDBScanner.py` stays as the single scanner implementation.
- `E2MDBPrefillManager.py` stays because Enigma2 must still collect Live/EPG candidates from its EPG cache.
- OpenATV core patch/reference files are kept because ServiceList/Event/skin extension points still depend on them in the current test package.
