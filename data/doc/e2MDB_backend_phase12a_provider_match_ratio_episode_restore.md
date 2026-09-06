# e2MDB Backend Phase 12a - Provider Match Ratio and Episode Text-Match Restore

Base: phase11y.

## Goal

During the backend migration, `E2MDBBackendMetadataScanner` / `BackendProviderEnricher`
(`E2MDBBackendProvider.py`) took over TS/media provider matching for `e2mdbd`, but two
qualification steps from the legacy GUI scanner (`E2MDBScanner.py` / `E2MDBHelper.py`)
were not carried over:

- The title **and** description similarity ratio (`get_match_ratio` /
  `create_final_dict`) that decides whether a provider hit is trustworthy enough
  to accept at all.
- The season/episode resolution fallback that matches the EIT/META description
  text against a series' episode index when the recording filename carries no
  explicit `SxxExx` tag.

Without these, the backend accepted the highest-scoring provider hit
unconditionally (even far below a reasonable similarity), and series
recordings without an `SxxExx` filename tag never received episode-level
metadata or artwork.

## Changes

`E2MDBBackendProvider.py`:

- Added `title_desc_ratio()` (module-level), a direct port of the legacy
  `E2MDBScanner.get_match_ratio()` title/description `SequenceMatcher` logic,
  plus the `TITLE_QUALIFY` / `DESC_QUALIFY` / `TITLE_LIMIT` / `DESC_LIMIT`
  constants ported from `E2MDBHelper.create_final_dict()`.
- `BackendProviderEnricher._score_result()` now returns `(title_ratio,
  desc_ratio)` computed via `title_desc_ratio()` instead of the previous
  `normalize_text()` + year-bonus + provider-priority scoring formula.
- `BackendProviderEnricher.choose_best()` now mirrors the legacy
  `create_final_dict()` selection loop: it bypasses the qualify gate only when
  exactly one candidate exists (same as the legacy scanner), otherwise tracks
  the best title/description ratio candidate-by-candidate and rejects the
  whole match (`{}`) unless `TITLE_LIMIT` or `DESC_LIMIT` is cleared. Each
  candidate result is tagged with `_title_ratio` / `_desc_ratio` /
  `_match_score` for debugging (visible in the provider debug JSON).
- `BackendProviderEnricher._episode_best_from_series()` no longer bails out
  immediately when no `SxxExx` tag was parsed from the filename. It now builds
  an `episode_name_text` from `item["short_desc"]`/`item["description"]` and
  passes it to `providers.find_season_episode()` alongside the (possibly
  empty) `plain_season_episode`, so the provider-side free-text episode-index
  match (e.g. `TVDB.find_season_episode()`'s `elif episode_name:` branch) is
  reachable again. The season/episode resolved by the text match is read back
  from the returned index key before fetching episode details.
- `BackendProviderEnricher._tmdb_english_metadata_by_id()` got the same
  season/episode + description text-match fallback for the English-metadata
  fallback path, instead of calling `find_season_episode()` with an empty
  description string.

## Result

- A provider hit that is only weakly similar to the recording title/description
  is rejected instead of silently becoming the accepted match; `search_item()`
  then proceeds to its existing media-type fallback / `"no provider match"`
  handling, same as before whenever no candidate is accepted.
- Series recordings without an `SxxExx` filename tag can resolve season and
  episode purely from the EIT/META short/extended description again, matching
  the pre-migration behavior of `E2MDBHelper.get_secondary_dicts()`.
- Recordings that do carry an `SxxExx` filename tag are unaffected (verified
  with a mocked provider: filename-tag match, text-only match, and no-match
  cases all resolve as expected).

## Verification

- `python3 -m py_compile E2MDBBackendProvider.py` completed successfully.
- Manual mocked-provider tests for `choose_best()` (single weak match bypass,
  multiple weak matches rejected, good match selected) and
  `_episode_best_from_series()` (filename tag, description-text-only match,
  no match at all) all produced the expected result.
