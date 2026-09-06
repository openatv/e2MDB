# e2MDB backend phase11y final readability cleanup

Base: phase11x.

## Goal

Perform a final whole-plugin readability pass based on the review notes:

- Avoid one-line helper functions when they only wrap a fixed default or a single backend command.
- Keep useful boundaries where they describe a real subsystem, public hook, callback or error boundary.
- Remove unnecessary defensive `try/except` blocks only where the operation cannot raise in normal Python code.
- Keep all GUI, provider, database, filesystem and Enigma2 boundary handling intact.

## Changed

- Removed one-line backend command wrappers from `E2MDBBackendClient.py`.
- Updated call sites to use `backend_request()` directly for simple daemon commands.
- Kept non-trivial backend helpers such as scan start path serialization and cleanup payload assembly.
- Replaced internal fixed GUI timing/priority helper methods with named module constants in:
  - `E2MDBInfoBarBridge.py`
  - `E2MDBChannelSelectionBridge.py`
  - `E2MDBEPGBridge.py`
  - `E2MDBComponentMeta.py`
  - `E2MDBPrefillManager.py`
  - `E2MDBLiveEPG.py`
- Removed obsolete scanner accessor methods that had no active call sites.
- Removed redundant `try/except` around `set.discard()` calls in the EventView bridge.
- Inlined two one-line backend display helpers in `plugin.py`.

## Hidden configuration audit

The phase11x hidden-config cleanup was rechecked after this pass:

- Every `config.plugins.e2mdb.*` definition in `__init__.py` is present in `setup.xml`.
- No code reference points to a removed or hidden e2MDB config entry.
- Former internal tuning values are now direct constants/default payload values instead of invisible settings.

## Preserved behavior

- No TVDB/FanArt/backdrop logic change.
- No scan/rescan behavior change.
- No provider interface change.
- No database schema change.
- No setup.xml option change.
- No OpenATV hook or ActionMap callback was removed.
- Error handling at Enigma2, SQLite, provider/network and filesystem boundaries was kept.

## Verification

- Static whole-plugin config audit completed successfully.
- `python3 -m compileall -q .` completed successfully.
- `__pycache__`, `.pyc` and `.pyo` files were removed.
- ZIP integrity test completed successfully.
