# e2MDB backend phase 11w - full plugin readability cleanup pass

## Goal

Continue the readability cleanup across the plugin tree without changing runtime behaviour.
This pass focuses on safe, mechanical cleanup only: unused one-line wrappers, one-shot callbacks,
duplicate imports and small nested helper functions that made the code harder to follow.

## Changes

### Backend client

- Removed unused one-line wrapper functions from `E2MDBBackendClient.py`.
- Kept only the backend client helpers that are currently used by Enigma2 GUI code, cleanup tasks or the Live/EPG bridge.
- Left the generic `backend_request()` function in place for commands that do not need a dedicated wrapper.

### Main plugin GUI

- Removed unused backend-client imports from `plugin.py`.
- Replaced a one-line path setup refresh callback with a direct callback expression.
- Merged the scan-duration conversion helper into the only function that used it.
- Moved the prefill setup refresh callback into a single reusable safe method instead of defining it inline.

### EventViewSimple

- Removed a duplicate `HelpableActionMap` import.
- Removed the one-line local image-download error callback and passed the error logging callback directly.

### Scanner

- Removed the one-line local image-download error callback and passed the error logging callback directly.
- Removed the one-line local `set_result_key()` helper in `write_scan_statistics()`.
- Replaced the repeated setter calls with one explicit `(key, value)` loop using the existing `set_dict_key()` helper.

## Behaviour notes

- No provider lookup logic was changed.
- No TVDB/FanArt/backdrop behaviour was changed.
- No scan/rescan logic was changed.
- No database schema was changed.
- No OpenATV hook signatures, GUI ActionMap names or provider interfaces were changed.

## Validation

- `python3 -m compileall` was run over the complete extracted plugin tree.
- ZIP integrity was checked after packaging.
- `__pycache__`, `.pyc` and `.pyo` files were removed before packaging.
