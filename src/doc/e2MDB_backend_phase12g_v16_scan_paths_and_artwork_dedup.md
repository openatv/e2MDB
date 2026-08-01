# e2MDB Backend Phase 12g (v16) - Scan Path Fix, Artwork Dedup Restore, Debug Flag

Base: phase12f.

## Goal

Two regressions from the `E2MDBScanner`/`E2MDBHelper` (v15.x, Enigma2 GUI) to
`E2MDBBackendMetadataScanner`/`BackendProviderEnricher` (headless daemon)
migration surfaced on a running box:

1. Per-folder `mode` values configured in `paths.json` (e.g. `/media/hdd/movie/Filme`
   = movie, `/media/hdd/movie/Serien` = series) were silently overridden and every
   scanned recording ended up with `path_mode = 3` ("movie_series") in
   `e2mdb_recordings`, regardless of its actual folder.
2. Provider artwork (cover/backdrop/titlelogo) was downloaded into a fresh
   `artwork/recordings/<recording-id>/` folder for every single recording, so a
   20-episode series downloaded the same show poster/backdrop/logo 20 times
   instead of once. The old GUI scanner never had this problem: its
   `get_primary_datapath`/`get_secondary_datapath` scheme in `E2MDBHelper.py`
   stored series-level artwork at a path derived from provider+series id, so
   every episode of the same show resolved to the identical file path and only
   the first episode ever triggered a download.

This phase fixes both, scoped only to the recording-scan / metadata-enrichment
path (`E2MDBBackendMetadataScanner`, `_run_recording_scan`,
`_run_metadata_enrich`, `BackendProviderEnricher.download_artwork`). The
Live/EPG worker path (`_run_live_epg_worker`, `e2mdb_provider_assets` /
`e2mdb_epg_event_asset_map`) was deliberately left untouched - it already has
its own, separate asset-dedup mechanism and was not reported as broken.

A temporary debug switch was also added to help verify the fix on a real box.

## Changes

`e2mdbd.py`:

- `_load_scan_paths()`: removed the additive merge of `settings.json`
  `scanner.recording_paths` into the `paths.json` list. Previously, if
  `settings.json` still had a legacy `recording_paths` entry (typically the
  parent folder `/media/hdd/movie`), it was appended as an extra scan path
  with a hardcoded `mode=3, recursive=True`. Because it's a parent directory
  of the properly-configured `paths.json` subfolders and was scanned *after*
  them, its recursive walk re-visited every file and its `mode=3` overwrote
  the correct per-folder `path_mode` on every `upsert_recordings()` call
  (`UPDATE ... SET path_mode = ?` in `E2MDBBackendDatabase.py` is
  unconditional). `paths.json` is now the single source of truth for scan
  paths and their modes; the `/media/hdd/movie` fallback only applies when
  `paths.json` itself is empty/missing.
- `get_scan_paths_status()`: `source` field changed from `"settings-json"` to
  `"paths-json"` and the now-unused `settings_file` diagnostics key was
  dropped, to match the above.
- Added a temporary debug switch, file-gated on `/tmp/e2MDB.flag`, marked
  `TEMP DEBUG SWITCH ... Remove later` at each site:
  - In `_run_recording_scan()`, per scanned file: logs the resolved
    `paths.json` entry (`path`, `mode`, `mode_label`, `recursive`), what
    `E2MDBBackendMetadataScanner.scan_media_file()` parsed (title, source_type,
    estimated_media_type, media_family, series/movie title, season/episode,
    year, parse_error), and the provider search candidate titles
    (`BackendProviderEnricher.candidate_titles()`).
  - In `_run_metadata_enrich()`, per item: logs the raw
    `provider_enricher.search_item()` result.
  - This flag briefly also skipped the provider-enrichment phase entirely
    (scanner-only mode) during debugging; that skip was reverted in this same
    phase - the flag now only adds logging, `scan_and_enrich` jobs run
    unchanged (scan + provider enrichment).

`E2MDBBackendProvider.py` (`BackendProviderEnricher`):

- Added imports: `hashlib.md5`, `re.IGNORECASE`. Removed the now-unused
  `os.path.splitext` import.
- Removed `_download_named_artwork()` (built `artwork_root/<recording_id>/<name>.<ext>`
  for every recording, no reuse).
- Added `_download_if_missing(url, target_path)`: downloads only if
  `target_path` doesn't already exist - the actual dedup mechanism, mirroring
  the old scanner's `if not exists(pic_path): download`.
- Added `_artwork_image_extension()`, `_reduced_org_path()`: ported from
  `E2MDBHelper.get_image_extension()` / `get_reduced_org_path()`, without the
  `Components.config` dependency (the daemon must stay Enigma2-import-free).
- Added `_primary_artwork_path(org_path, pic_type, url)`: per-file artwork
  path, `cache_root/<pic_type>/<hash[0]>/<hash>.<ext>` where `hash` is the
  md5 of the reduced recording path - equivalent to the old
  `get_primary_datapath()`. Used for movies and episode-only stills, which are
  legitimately unique per file.
- Added `_secondary_artwork_path(provider_name, provider_id, pic_type, url)`:
  series-level artwork path, `cache_root/series/<provider>/<series_id>/<pic_type>.<ext>`
  - equivalent to the old `get_secondary_datapath()`. Identical for every
    episode of the same show.
- Added `_series_artwork_target(item, best, pic_type, url)`: the equivalent of
  the old `get_artwork_cache_path()` / `get_artwork_cache_category()` pair -
  picks the secondary (shared) path when `best` identifies a series with a
  resolvable provider id (`_is_series_type()` + `_provider_id_from_best()`),
  otherwise falls back to the primary (per-file) path.
- Rewrote `download_artwork()`: episode stills stay per-file
  (`_primary_artwork_path`); series poster/backdrop/cover/backdrop/titlelogo
  now resolve through `_series_artwork_target()` and go through
  `_download_if_missing()`. Return dict keys are unchanged
  (`poster_path`, `backdrop_path`, `logo_path`, `episode_path`,
  `series_poster_path`, `series_backdrop_path`, `image_path`, ...), so
  `E2MDBBackendDatabase.upsert_provider_result()` needed no changes.

`E2MDBBackendDatabase.py`, `E2MDBScanner.py` (`E2MDBBackendMetadataScanner`):
unchanged - the scan-item shape and DB columns already matched what
`download_artwork()` now produces.

## Result

- `path_mode` in `e2mdb_recordings` now matches the per-folder `paths.json`
  configuration and is no longer overwritten by a broader parent-path scan.
- Series/episode artwork (cover, backdrop, titlelogo) is downloaded once per
  show under `<cache_root>/series/<provider>/<provider_id>/`, not once per
  recording. Movie and episode-still artwork keeps its old, per-file
  `<cache_root>/<pic_type>/<hash[0]>/<hash>.<ext>` layout.
- `/tmp/e2MDB.flag`, if present, adds `[e2MDB.flag] ...` log lines for path
  resolution, the media-name-parser result, provider search candidates, and
  the raw provider result, without changing scan/enrichment behavior
  otherwise. To be removed once no longer needed for on-box verification.
- Live/EPG worker artwork/asset handling is unchanged.

## Verification

- `python3 -m py_compile e2mdbd.py E2MDBBackendProvider.py` completed
  successfully.
- Inspected a real `results.db` pulled from a box: prior to the fix, all 381
  `e2mdb_recordings` rows had `path_mode = 3` regardless of folder, even
  though `paths.json` had `mode = 1` for `/media/hdd/movie/Filme` and
  `mode = 2` for `/media/hdd/movie/Serien` - confirmed the root cause was the
  `settings.json` merge in `_load_scan_paths()`, not `paths.json` itself.
- `_download_named_artwork` / `artwork_root/<recording_id>` no longer appear
  anywhere in `E2MDBBackendProvider.py` except `artwork_root`'s remaining use
  for the separate, debug-only `provider_result.json` sidecar
  (`_write_provider_debug_json`), which was intentionally left as-is.
