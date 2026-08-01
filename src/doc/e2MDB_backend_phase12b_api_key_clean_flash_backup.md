# e2MDB Backend Phase 12b - Personal API Key Clean-Flash Backup

Base: phase12a.

## Goal

Personal provider API keys (TMDb, TVDb, OMDb, FanArt.tv) live only in
`config.plugins.e2mdb.*`, i.e. `/etc/enigma2/settings`. A clean flash wipes
that file, so the user has to find and re-enter their personal keys again.
`/etc/enigma2/e2mdb/` already survives independently as the backend's own
persistent config directory (`E2MDBBackendConfig.py`), so a sticky backup
copy of the personal keys belongs there.

## Changes

`E2MDBBackendConfig.py`:

- Added `API_KEYS_FILE = /etc/enigma2/e2mdb/api_keys.json` and
  `API_KEY_CONFIG_FIELDS` (`tmdb`, `tvdb`, `omdb`, `fanart` -> their
  `config.plugins.e2mdb.*apikey` field name).
- Added `resolve_api_keys(restore_to_config=False)`:
  - For every provider, if the live config value is non-empty, it is used and
    (if changed) mirrored into `api_keys.json`.
  - If the live config value is empty, the last persisted value from
    `api_keys.json` is used instead.
  - With `restore_to_config=True`, an empty live config value is additionally
    written back into `config.plugins.e2mdb.*apikey` and saved, so the Setup
    screen shows the recovered key instead of an empty field.
- `build_settings_payload()` now fills `provider.tmdb_api_key` /
  `provider.tvdb_api_key` / `provider.omdb_api_key` /
  `artwork.fanart_api_key` from `resolve_api_keys()` instead of reading the
  config values directly, so `settings.json` (read by `e2mdbd`) always
  contains the resolved key.
- `init_backend_config(reason="sessionstart")` now calls
  `resolve_api_keys(restore_to_config=True)` once before exporting the
  settings, so a wiped config is repaired on the first plugin session start
  after a clean flash.

`E2MDBScanner.py`:

- `init_providers()` (used by the manual "Start scan" GUI path) now resolves
  keys through the same `resolve_api_keys()` helper instead of reading
  `config.plugins.e2mdb.*apikey.value` directly, so the manual scan path gets
  the same clean-flash-surviving personal key before ever falling back to the
  plugin's bundled default key.

## Behavior / trade-off

- Whenever a personal key is present in the live config, it is treated as
  authoritative and mirrored into `api_keys.json`.
- Clearing a key in the Setup screen and saving does **not** delete the
  `api_keys.json` backup; the backup is only replaced by a new non-empty key.
  This is intentional: the backup exists specifically to survive an
  unintended config wipe, so a momentary empty field must not silently erase
  it. Only entering a new personal key overwrites the stored backup.

## Verification

- `python3 -m py_compile E2MDBBackendConfig.py E2MDBScanner.py` completed
  successfully.
- Mocked-config test: saving a personal TMDb key mirrors it into
  `api_keys.json`; wiping the live config value still resolves the key from
  the JSON backup for the exported `settings.json`; `init_backend_config(reason="sessionstart")`
  restores the key into the live config and calls `.save()` on it.
- Mocked test for `E2MDBScanner.init_providers()`: with an empty live config
  and a persisted `api_keys.json` backup, the manual scan path picks the
  persisted personal key over the bundled default key.
