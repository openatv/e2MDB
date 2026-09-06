# e2MDB Backend Phase 12f - Revert to Real config.plugins.e2mdb API Key Entries

Base: phase12e (reverted).

## Goal

Phase12e turned the personal API key fields into plain local `ConfigText`
attributes on `E2MDBSetup` (`self.tmdbapikey`, etc.), removing them from
`config.plugins.e2mdb` entirely, reasoning that nothing else read that config
path. That reasoning missed a real caller: **OpenWebif's generic setup API**
lets a user enter plugin settings (including these API keys) without ever
opening the Enigma2 GUI Setup screen. It works purely by evaluating the
`config.*` paths declared in a plugin's `setup.xml` and calling
`configfile.save()` afterwards, which is exactly what triggers this plugin's
registered `setOnSaveCallback("e2MDB", _init_backend_config)` hook. There is
no `self`/screen-instance context in that path at all, so a local
`self.tmdbapikey` attribute on `E2MDBSetup` is unreachable from OpenWebif -
the config entries have to be real, global `config.plugins.e2mdb.*` attributes.

This phase reverts phase12e (and re-establishes phase12d/phase12c) so the API
key fields are real `config.plugins.e2mdb.*apikey` entries again, while
keeping the phase12c/12b guarantee that they are never written to
`/etc/enigma2/settings`.

## Changes

`__init__.py`:

- Restored `config.plugins.e2mdb.tmdbapikey` / `tvdbapikey` / `omdbapikey` /
  `fanartapikey` as `NoSave(ConfigText())` entries (undoing their phase12e
  removal). Restored the `NoSave` import.

`setup.xml`:

- The four API key `<item>` elements reference `config.plugins.e2mdb.*apikey`
  again (undoing the phase12e `self.*apikey` change), so OpenWebif's generic
  config-path evaluation can reach them.

`E2MDBBackendConfig.py`:

- Restored `resolve_api_keys(restore_to_config=False)` and
  `API_KEY_CONFIG_FIELDS` (undoing the phase12e `read_api_keys()`/
  `save_api_keys()` split). `resolve_api_keys()` mirrors a non-empty live
  config value into `api_keys.json`, and (with `restore_to_config=True`)
  restores a persisted value back into an empty live config entry.
- `build_settings_payload()` calls `resolve_api_keys()` again for its
  config-to-JSON sync side-effect (still excludes the keys from the returned
  `settings.json` payload).
- `init_backend_config(reason="sessionstart")` calls
  `resolve_api_keys(restore_to_config=True)` again before exporting settings,
  so the keys are available in the live config early in the session -
  independent of whether `E2MDBSetup` is ever opened, which matters because
  OpenWebif's own settings display also reads `config.plugins.e2mdb.*apikey.value`
  directly.

`E2MDBScanner.py`:

- `init_providers()` calls `resolve_api_keys()` again (personal key from live
  config, falling back to `api_keys.json`, falling back to the bundled
  default key), reverting the phase12e `read_api_keys()` call.

`plugin.py`:

- Reverted the `ConfigText` import and the local `self.tmdbapikey` etc.
  attributes on `E2MDBSetup`.
- `E2MDBSetup.__init__()` calls `resolve_api_keys(restore_to_config=True)`
  again before `Setup.__init__()`, as an extra (idempotent) safety net on top
  of the session-start restore.
- `keySave()` no longer calls a bespoke save function; saving the config list
  via `Setup.keySave(self)` followed by the existing
  `init_backend_config(reason="setup-save")` call already reaches
  `resolve_api_keys()` through `build_settings_payload()`, exactly like the
  OpenWebif/`setOnSaveCallback` path does.

`e2mdbd.py` was never touched by phase12e or this revert - it always read
`api_keys.json` directly via `apply_provider_api_keys()`.

## Result

- Entering a personal API key through OpenWebif's generic settings API (which
  writes `config.plugins.e2mdb.*apikey.value` and calls `configfile.save()`,
  triggering `setOnSaveCallback`) now correctly ends up in
  `/etc/enigma2/e2mdb/api_keys.json`, same as entering it in the Enigma2 GUI
  Setup screen.
- `/etc/enigma2/settings` still never contains a personal API key (`NoSave`).
- `/etc/enigma2/e2mdb/settings.json` still never contains a personal API key
  either (unchanged since phase12c).

## Verification

- `python3 -m py_compile __init__.py plugin.py E2MDBBackendConfig.py E2MDBScanner.py e2mdbd.py`
  completed successfully; `setup.xml` parses as valid XML.
- No remaining reference to `read_api_keys`/`save_api_keys`/`self.*apikey`
  anywhere in the codebase (verified by grep).
- Mocked test simulating the OpenWebif path exactly: setting
  `config.plugins.e2mdb.tmdbapikey.value` directly and calling
  `init_backend_config(reason="setup-save")` (what the registered
  `setOnSaveCallback` handler invokes) writes the key into `api_keys.json`;
  a simulated fresh session (`NoSave` reset) followed by
  `init_backend_config(reason="sessionstart")` restores it back into the live
  config.
