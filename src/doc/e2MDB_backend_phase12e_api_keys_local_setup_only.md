# e2MDB Backend Phase 12e - API Keys as Local E2MDBSetup Fields

Base: phase12d.

## Goal

Phase12c/12d still kept `config.plugins.e2mdb.tmdbapikey` /
`tvdbapikey` / `omdbapikey` / `fanartapikey` as `NoSave` entries under the
global `config.plugins.e2mdb` subsection, populated from
`/etc/enigma2/e2mdb/api_keys.json` when `E2MDBSetup` opens. Since
`api_keys.json` is now the only persistent storage and nothing else in the
codebase reads these `config.plugins.e2mdb.*apikey` values, there is no
reason for them to be `config` entries at all - they are purely local state
of the `E2MDBSetup` screen. This phase removes them from `config.plugins.e2mdb`
entirely and turns them into plain local `ConfigText` attributes on
`E2MDBSetup` itself (`self.tmdbapikey`, etc.).

## Changes

`__init__.py`:

- Removed `config.plugins.e2mdb.tmdbapikey` / `tvdbapikey` / `omdbapikey` /
  `fanartapikey` entirely (no `NoSave` wrapper, no config entry at all).
- Removed the now-unused `NoSave` import.
- Removed `get_api_key()` - it read the now-removed config attributes and had
  no callers.

`setup.xml`:

- The four API key `<item>` elements now reference `self.tmdbapikey` /
  `self.tvdbapikey` / `self.omdbapikey` / `self.fanartapikey` instead of
  `config.plugins.e2mdb.*apikey`. `Screens.Setup.addItem()` evaluates the item
  text via a plain `eval(element.text)` inside a method of the `Setup`
  instance, so `self` naturally resolves to the `E2MDBSetup` screen and its
  local attributes - no framework change needed.

`E2MDBBackendConfig.py`:

- Replaced `resolve_api_keys()` / `API_KEY_CONFIG_FIELDS` (the config <->
  JSON merge logic from phase12b/12c, no longer meaningful without a config
  side) with two plain functions:
  - `read_api_keys()` - returns `{"tmdb": ..., "tvdb": ..., "omdb": ...,
    "fanart": ...}` straight from `api_keys.json` (all-empty if the file is
    missing).
  - `save_api_keys(keys)` - writes exactly the given dict to `api_keys.json`.
- `build_settings_payload()` no longer calls anything API-key related; it
  never needed the keys in its return value, only the removed sync
  side-effect.

`E2MDBScanner.py`:

- `init_providers()` (manual "Start scan" GUI path) now calls `read_api_keys()`
  instead of `resolve_api_keys()`, same priority as before: personal key from
  `api_keys.json` over the bundled default key.

`plugin.py`:

- Imported `ConfigText`, `read_api_keys`, `save_api_keys`.
- `E2MDBSetup.__init__()` builds `self.tmdbapikey` / `self.tvdbapikey` /
  `self.omdbapikey` / `self.fanartapikey` as local `ConfigText(default=...)`
  instances from `read_api_keys()`, before calling `Setup.__init__()` (which
  builds the config list from `setup.xml` and needs these attributes to
  already exist on `self`).
- `keySave()` now calls `save_api_keys({...})` with the four fields' current
  `.value` right after `Setup.keySave(self)` applies the edited values, so
  whatever is shown in the Setup screen at save time becomes exactly what is
  persisted to `api_keys.json` - including an intentionally cleared field
  (no more "sticky, can't be erased" behavior from phase12b/12c, since there
  is only one place these values live now).

`e2mdbd.py` is unaffected: it already read `api_keys.json` directly via
`apply_provider_api_keys()` (phase12c) and never touched `config.plugins.e2mdb`.

## Result

- `config.plugins.e2mdb` no longer has any API key entries; `/etc/enigma2/settings`
  and `/etc/enigma2/e2mdb/settings.json` never contained them since phase12c
  and still don't.
- `/etc/enigma2/e2mdb/api_keys.json` is the single, sole location personal
  API keys are ever written to or read from, for both the Setup screen, the
  manual scan path, and the backend daemon.
- Clearing a key in the Setup screen and saving now does exactly what it
  looks like: the field is saved empty in `api_keys.json`.

## Verification

- `python3 -m py_compile __init__.py setup.xml-adjacent plugin.py E2MDBBackendConfig.py E2MDBScanner.py e2mdbd.py` (all `.py` files) completed successfully; `setup.xml` parses as valid XML.
- No remaining reference to `resolve_api_keys` or
  `config.plugins.e2mdb.*apikey` anywhere in the codebase (verified by grep).
- Mocked test: a value entered into a local `ConfigText` and saved via
  `save_api_keys()` is read back identically by a freshly created `ConfigText`
  via `read_api_keys()` (simulating both a new `E2MDBSetup` screen instance
  and a post-clean-flash session); `export_enigma_settings()`'s returned
  `provider`/`artwork` sections contain no API key fields.
