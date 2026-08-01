# e2MDB Backend Phase 12d - API Key Restore Scoped to E2MDBSetup

Base: phase12c.

## Goal

Phase12c made `/etc/enigma2/e2mdb/api_keys.json` the sole persistent store for
personal provider API keys and restored them into the (now `NoSave`)
`config.plugins.e2mdb.*apikey` entries via a global
`init_backend_config(reason="sessionstart")` hook. That restore is only ever
observed in one place: the `E2MDBSetup` config list built from `setup.xml`.
Neither the daemon (`e2mdbd.py` via `apply_provider_api_keys()`) nor the
manual scan path (`E2MDBScanner.init_providers()` via `resolve_api_keys()`)
read `config.plugins.e2mdb.*apikey.value` at all - they resolve personal keys
straight from `api_keys.json` every time. So the restore was effectively a
local concern of the Setup screen, not a global session-start concern.

## Changes

`E2MDBBackendConfig.py`:

- `init_backend_config()` no longer special-cases `reason == "sessionstart"`.
  It is back to unconditionally calling `ensure_default_json_files()` and
  `export_enigma_settings(reason=reason)`.

`plugin.py`:

- Imported `resolve_api_keys` from `.E2MDBBackendConfig`.
- `E2MDBSetup.__init__()` now calls `resolve_api_keys(restore_to_config=True)`
  before `Setup.__init__(...)`, so the `NoSave` API key entries are populated
  from `api_keys.json` right before the generic `Setup` framework reads their
  `.value` to build the config list from `setup.xml`. `keySave()` is
  unchanged and still writes any entered key back via
  `init_backend_config(reason="setup-save")` -> `resolve_api_keys()`.

## Result

- Opening the e2MDB Setup screen always shows the personal keys currently
  stored in `api_keys.json`, without any global state depending on it.
- Plugin session start (`sessionstart()` in `plugin.py`) no longer touches
  the API key config entries at all; it only exports the (key-free)
  `settings.json` as before.
- Daemon and manual-scan behavior is unaffected, since both already resolve
  keys independently from `api_keys.json`.

## Verification

- `python3 -m py_compile plugin.py E2MDBBackendConfig.py` completed
  successfully; the "imported but unused" lint warning for `resolve_api_keys`
  in `plugin.py` is resolved now that `E2MDBSetup.__init__()` uses it.
