# e2MDB Backend Phase 11v - Plugin-wide readability audit

Stand: 2026-06-02

## Goal

Review the complete plugin tree for avoidable fragmentation from tiny one-use helpers and defensive code that no longer adds value, while keeping public Enigma2/OpenATV hooks and provider interfaces stable.

## Changes

- Removed unused internal helpers that were not referenced anywhere in the plugin:
  - `E2MDBBackendProvider.get_result_field()`
  - `E2MDBDatabase._db_table_exists()`
  - `E2MDBDatabase._browser_data_file()`
  - `E2MDBDatabase._browser_read_cached_data()`
  - `E2MDBDatabase._browser_extract_cast()`
  - `E2MDBDatabase._browser_group_key_from_joined_row()`
  - `E2MDBDatabase._browser_display_value()`
  - `E2MDBEPGBridge._as_skin_name_list()`
  - `E2MDBSkin._first_value()`
  - `E2MDBComponentMeta._current_source_key()`
  - `E2MDBComponentMeta._ad_hoc_finished()`
- Replaced two one-use dummy `closeCallback()` function definitions with direct no-op callback assignments.
- Left the real-backdrop behaviour from phase 11t unchanged.
- Left the phase 11u cleanup unchanged.

## Kept deliberately

The audit found several categories of short functions that look trivial but are intentionally kept:

- Backend client wrapper functions such as `get_backend_*()` are public command helpers used by GUI and command-line code.
- Scheduler entry functions are referenced indirectly by OpenATV scheduler/task configuration.
- ActionMap key handlers and screen callback methods must remain named methods for Enigma2 integration.
- Provider methods such as `get_name()`, `is_active()`, `start()`, `stop()` and `set_dict_key()` are part of the provider interface.
- Skin parser/renderer attribute methods are dispatch targets and must not be inlined based on simple call-count checks.
- Defensive `try/except` blocks were kept where Enigma2 sources, screens, config objects, network providers, SQLite, filesystem operations or background callbacks can fail at runtime.

## Verification

- `python3 -m compileall` completed successfully for the complete extracted plugin tree.
- ZIP integrity was checked after packaging.
- No runtime test on an actual receiver was performed here.
