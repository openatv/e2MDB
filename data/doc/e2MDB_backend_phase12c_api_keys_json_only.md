# e2MDB Backend Phase 12c - Personal API Keys Live Only in api_keys.json

Base: phase12b.

## Goal

Phase12b added `/etc/enigma2/e2mdb/api_keys.json` as a clean-flash-surviving
backup of the personal provider API keys, mirrored from
`config.plugins.e2mdb.*apikey` (which lives in `/etc/enigma2/settings`).
Keeping two copies in sync only exists to work around Enigma2 settings
persistence; the API keys don't need to be in `/etc/enigma2/settings` or in
`/etc/enigma2/e2mdb/settings.json` at all, since `settings.json` is always
just a generated copy of the live config. This phase makes
`/etc/enigma2/e2mdb/api_keys.json` the single, sole persistent store.

## Changes

`__init__.py`:

- `config.plugins.e2mdb.tmdbapikey` / `tvdbapikey` / `omdbapikey` /
  `fanartapikey` are now wrapped in `NoSave(...)`. They are never written to
  `/etc/enigma2/settings` anymore; they only exist in memory for the current
  session, populated from `api_keys.json`.

`E2MDBBackendConfig.py`:

- `resolve_api_keys()` (from phase12b) is unchanged in logic, but its role
  changes from "clean-flash backup" to "the only persistent storage": since
  the config entries are `NoSave`, they are empty on every fresh session, not
  just after a clean flash.
- `build_settings_payload()` still calls `resolve_api_keys()` (to keep
  `api_keys.json` in sync whenever the user enters/saves a key), but the
  returned payload's `provider`/`artwork` sections no longer contain
  `tmdb_api_key` / `tvdb_api_key` / `omdb_api_key` / `fanart_api_key` at all.
  `settings.json` therefore never contains a personal API key.
- `init_backend_config(reason="sessionstart")` still calls
  `resolve_api_keys(restore_to_config=True)` first; this is now the primary
  load path (populates the `NoSave` entries for the session) rather than only
  a clean-flash repair.

`e2mdbd.py` (standalone daemon, must not import Enigma2 modules, reads plain
JSON files only):

- Added `API_KEYS_FILE = /etc/enigma2/e2mdb/api_keys.json` and
  `apply_provider_api_keys(settings)`, which merges `tmdb_api_key` /
  `tvdb_api_key` / `omdb_api_key` / `fanart_api_key` from `api_keys.json` into
  an in-memory `settings` dict's `provider`/`artwork` sections (all other
  settings fields are preserved unchanged).
- `main()` and `JobManager._reload_settings_now()` (the two places that load
  `settings.json` before constructing/reconfiguring `BackendProviderEnricher`)
  now call `apply_provider_api_keys()` on the loaded settings before using
  them.
- Removed the `tmdb_api_key` / `tvdb_api_key` / `omdb_api_key` /
  `fanart_api_key` placeholder fields from `ensure_default_files()`'s default
  `settings.json` scaffold; the `*_enabled` flags stay.
- The `GET /api/settings` debug endpoint still echoes the raw `settings.json`
  file content, which as a side effect no longer includes personal API keys.

## Result

- `/etc/enigma2/settings` and `/etc/enigma2/e2mdb/settings.json` never
  contain a personal provider API key.
- `/etc/enigma2/e2mdb/api_keys.json` is the sole persistent store; it
  naturally survives a clean flash of `/etc/enigma2/settings`.
- The Setup screen still shows and edits the keys exactly as before (backed
  by `NoSave` config entries loaded from `api_keys.json` at session start and
  saved back into `api_keys.json` on Setup save via the existing
  `keySave()` -> `init_backend_config(reason="setup-save")` path).
- `E2MDBScanner.init_providers()` (manual "Start scan" GUI path) is
  unaffected: it already reads through `resolve_api_keys()` (phase12b).

## Behavior / trade-off (unchanged from phase12b)

Clearing a key in the Setup screen and saving does not delete the
`api_keys.json` value; only entering a new personal key overwrites it. This
is intentional, since the file is now the only persistent copy and must not
be erased by a momentarily empty field.

## Verification

- `python3 -m py_compile __init__.py E2MDBBackendConfig.py E2MDBScanner.py e2mdbd.py`
  completed successfully.
- Mocked test: `e2mdbd.apply_provider_api_keys()` merges personal keys from
  `api_keys.json` into a settings dict without disturbing existing
  `*_enabled` flags.
- Mocked test: `export_enigma_settings()`'s returned payload no longer
  contains `tmdb_api_key`/`fanart_api_key` in `provider`/`artwork`;
  `api_keys.json` still receives the saved key; simulating a fresh
  (`NoSave`-reset) session followed by `init_backend_config(reason="sessionstart")`
  restores the key into the live config.
