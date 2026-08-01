# e2MDB backend phase11x hidden config cleanup

Base: phase11w.

## Goal

Remove old hidden Enigma2 configuration entries that were no longer exposed in
`setup.xml`. The behavior is kept by using the former defaults directly in code
and in the backend settings payload.

## Changed

- Removed all non-visible `config.plugins.e2mdb.*` definitions from `__init__.py`.
- Kept only configuration keys that are present in `setup.xml`.
- Replaced old hidden GUI/debug/runtime tuning reads with direct defaults in:
  - `E2MDBBackendConfig.py`
  - `E2MDBChannelSelectionBridge.py`
  - `E2MDBComponentMeta.py`
  - `E2MDBEPGBridge.py`
  - `E2MDBEventViewBridge.py`
  - `E2MDBInfoBarBridge.py`
  - `E2MDBLiveEPG.py`
  - `E2MDBPrefillManager.py`
  - `E2MDBServiceListPreview.py`
  - `plugin.py`
- Global logging is now controlled only by the visible log settings:
  - `debugLog`
  - `logTarget`
  - `logRotateSizeMb`
- Cleanup payload now uses fixed internal defaults for non-visible cleanup
  settings while keeping visible SQLite `VACUUM` and `REINDEX` options.
- Updated developer documentation so removed hidden settings are no longer
  documented as active configuration keys.

## Preserved behavior

The previous defaults are kept as direct code defaults, for example:

- Live/EPG backend worker enabled by default when Live/EPG metadata is enabled.
- GUI-visible queue/prefetch delays stay conservative to avoid UI stutter.
- InfoBar metadata is cleared before refresh.
- EPG screens remain cache-only while open to avoid GUI load.
- Short Live/EPG events below 15 minutes are skipped for provider lookup.
- Prefill idle/standby boost, No-EPG cooldown and channel statistics continue
  with their previous default behavior.
- Cleanup remains active with fixed retention/maintenance defaults.

## Not changed

- No TVDB/FanArt/backdrop logic change.
- No scan/rescan behavior change.
- No provider interface change.
- No database schema change.
- No setup.xml option was removed in this phase.

## Verification

- Static config audit: no hidden definitions remain outside `setup.xml`.
- Static reference audit: no code reference points to removed hidden settings.
- `python3 -m compileall -q .` completed successfully.
- ZIP integrity test completed successfully.
