# e2MDB Backend Phase 11u - Code readability cleanup

Stand: 2026-06-02

## Goal

Reduce unnecessary fragmentation and defensive code added around the Live/EPG real-backdrop retry without changing the intended behaviour from phase 11t.

## Changes

- Removed the tiny one-use `_has_real_backdrop()` helper and kept the missing-backdrop check directly in the alternate-provider artwork fill path.
- Removed a redundant `try/except` around `_get_series_context()` because that method already normalizes provider exceptions into an error result.
- Removed the defensive `try/except` around TVDB `get_pictures_list()` during the series artwork retry check.
- Replaced the `artwork_lookup_version` conversion `try/except` with explicit digit parsing.
- Replaced TVDB artwork dimension parsing `try/except` with explicit numeric string parsing.

## Kept deliberately

- Provider/API boundary `try/except` blocks stay in place where network calls, provider plug-ins, JSON files or filesystem access can fail.
- The real-backdrop logic from phase 11t stays unchanged: still/preview images are not used as backdrop fallback.
- The TVDB `/series/{id}/artworks` retry and alternate-provider artwork fill remain active.
