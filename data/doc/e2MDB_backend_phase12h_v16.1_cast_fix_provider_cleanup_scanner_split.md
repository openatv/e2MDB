# e2MDB Backend Phase 12h (v16.1) - Cast Fix, Season Artwork, IMDB Removal, Cinemeta, Scanner Split, DB Fixes

Base: phase12g.

## Goal

Follow-up fixes and cleanups found while continuing to exercise the phase12g
artwork/scan-path fixes on a real box, plus two requested changes (drop IMDB,
add Cinemeta). Scope stayed on the recording-scan / metadata-enrichment path
(`E2MDBBackendMetadataScanner`, `BackendProviderEnricher`); the Live/EPG
worker path was explicitly left alone throughout, except where it shares code
with the recording path (`download_artwork()`).

## Changes

### Series cast overwritten by episode guest stars

`E2MDBBackendProvider._episode_best_from_series()` merged `episode_details`
into `merged` unconditionally, including the `"cast"` key. Every provider
(TMDB, TVDB, ...) reports a episode's guest stars under the same `"cast"`
field name as the show's main cast (e.g. `TMDB.get_characters()` maps
`guest_stars` straight into the same list as `cast`). Since the last scanned
episode wins, whichever episode was scanned last ended up as the "cast" for
the entire series in the DB. Fixed by excluding `"cast"` from the
episode-details merge, keeping the show-level cast from `series_details`.

### Season poster artwork was never downloaded

`best["seasons"]` (populated by providers like TVDB, reachable e.g. via
Cinemeta's series meta `videos`/season grouping) contains per-season poster
URLs (`cover_src: "season"`, `cover_url`, `season_no`), but
`download_artwork()` never read it. Added `_season_artwork_path()` and
`_season_poster_url()`; `download_artwork()` now downloads the season poster
for the recording's own season to
`cache_root/seasons/<provider>/<series_id>/S<NN>/cover.<ext>`, deduped via
`_download_if_missing()` like series-level artwork.

### `recordings.json` / `job_history.json` moved out of `/etc/enigma2/e2mdb`

Both are scan-result/job-history data dumps that grow with the library, not
small config - they don't belong on the (often small) config partition next
to `settings.json`/`paths.json`. Moved to `<cache_root>/results/`, next to
`results.db`:

- `e2mdbd.py`: new `JobManager._cache_results_dir()` /
  `_recordings_catalog_path()` / `_job_history_path()` helpers (based on
  `self.database.db_path`, falling back to `settings.cache.root` /
  `settings.database.root`). `_run_recording_scan()`, `read_recording_catalog()`,
  `_append_job_history()`, `get_media_status()`, both `jobs/history` endpoints,
  and the startup scaffold (`ensure_default_files()`) all updated. Module-level
  `RECORDINGS_FILE`/`JOB_HISTORY_FILE` constants removed.
- `E2MDBBackendConfig.py`: same move for the GUI-side session-start scaffold
  (`ensure_default_json_files()`), using the existing `_cache_root()` helper.

### IMDB provider disabled (file kept, not deleted)

Commented out everywhere it was wired up, `provider/IMDB.py` itself
untouched:

- `E2MDBProviders.py`: import commented out; `"imdb"` removed from
  `providers_dict`/`all_prov_ids`/`series_search_order`/`movie_search_order`
  (the shared singleton registry used by both the legacy GUI scanner and the
  daemon)
- `E2MDBBackendProvider.py`: `"imdb"` removed from `DEFAULT_SERIES_ORDER`/
  `DEFAULT_MOVIE_ORDER`, API-key mapping, and the `series_order["imdb"]`/
  `movie_order["imdb"]` settings-override lines
- `E2MDBScanner.py` (`init_providers()`, legacy GUI scan path): same removal
  from `api_keys`/`series_search_order`/`movie_search_order`
- `e2mdbd.py`: `"imdb_enabled"` removed from the default `settings.json`
  scaffold
- `E2MDBBackendConfig.py`: `"imdb_enabled"` removed from
  `build_settings_payload()`
- `setup.xml`: "Search in IMDb" checkbox turned into an XML comment
- Deliberately left untouched: generic provider-id fallback tuples like
  `("tvdb", "tmdb", "imdb", ...)` in `E2MDBHelper.py`/`E2MDBBackendProvider.py`/
  `E2MDBDatabase.py` - those are cross-reference lookups for IDs other
  providers report (e.g. TMDB's own `imdb_id` field), not calls into the IMDB
  scraper. Also left alone: the `__main__` CLI test harness in
  `E2MDBProviders.py`, dev-only tooling outside the normal program flow.

### Cinemeta provider added

New file `provider/CINEMETA.py` (`ProviderCINEMETA`, singleton
`provider_cinemeta`), modeled on `provider/TVMAZE.py`'s no-API-key pattern.
Cinemeta (`https://v3-cinemeta.strem.io`, the Stremio metadata addon) is
IMDb-id-keyed and English-only:

- `get_result_dicts()`: search via `/catalog/{movie|series}/top/search={query}.json`
- `get_series_details_index()` / `get_movie_details()`: full details via
  `/meta/{type}/{imdbId}.json`, including bonus cross-reference ids
  (`tvdb_id`, `moviedb_id`) in the series meta
- `get_episode_details()`: no dedicated episode endpoint exists, so this
  re-fetches the full series meta and looks the episode up in its `videos`
  array (by season/episode number, or by the compound id
  `ttXXXXXXX:season:episode`)
- Verified against the real API (search, series/season/episode details,
  movie details, redirect/404 handling not applicable here since it's a
  simple JSON API)

Wired up in parallel with the IMDB removal, defaulting off like TVmaze:
`E2MDBProviders.py`, `E2MDBBackendProvider.py` (`DEFAULT_SERIES_ORDER`/
`DEFAULT_MOVIE_ORDER`, `cinemeta_enabled` settings handling), `E2MDBScanner.py`
(`init_providers()`), `e2mdbd.py` / `E2MDBBackendConfig.py` (settings
scaffold/export), `__init__.py`
(`config.plugins.e2mdb.cinemetaactive = ConfigYesNo(default=False)`),
`setup.xml` (new checkbox, no API-key field needed).

### `E2MDBBackendMetadataScanner` moved to its own file

Was the last class in `E2MDBScanner.py` (historical reasoning: "keep it in
the same module as the v16 scanner logic"); moved verbatim to
`E2MDBBackendMetadataScanner.py`, since only `e2mdbd.py` ever imports it and
it shares no state with the rest of `E2MDBScanner.py`. `E2MDBScanner.py`
shrank from 1781 to ~1219 lines. `e2mdbd.py`'s import updated to
`from E2MDBBackendMetadataScanner import E2MDBBackendMetadataScanner`. The
now-dead `E2MDBRecordingParser`/`default_parse_recording` import block was
removed from `E2MDBScanner.py` (only the moved class used it; `mediadb`/
`MediaNameParser` stay, `E2MDBScanner` itself still uses them). Two
debug-label strings (`scanner_used`, `native_parser_missing_message()`)
updated from `"E2MDBScanner...."` to `"E2MDBBackendMetadataScanner...."` to
match the new module.

### Import/exception-handling simplification (fail-fast where it makes sense)

Removed several relative-import-fallback and try/except-around-import
patterns that were mechanically copy-pasted but no longer (or never) served
a purpose in their new context:

- `E2MDBBackendMetadataScanner.py`: the relative-import branch (`from
  .E2MDBRecordingParser import ...`) can never succeed - only `e2mdbd.py`
  imports this module, always as a plain top-level import with no parent
  package. Reduced `mediadb`/`MediaNameParser`/`default_parse_recording`
  imports to plain absolute imports, no try/except at all - if any of them
  fail, the whole module fails to load, which `e2mdbd.py`'s own import guard
  around `E2MDBBackendMetadataScanner` already handles. `__init__()`
  simplified accordingly (`recording_parser_error` no longer falls back to a
  module-level `DEFAULT_RECORDING_PARSER_IMPORT_ERROR`, which no longer
  exists).
- `e2mdbd.py`: removed the try/except around
  `from E2MDBBackendMetadataScanner import E2MDBBackendMetadataScanner` and
  around `from E2MDBBackendProvider import BackendProviderEnricher` -
  outside a rare corrupted/incomplete install, a missing/broken class here
  means the daemon can't do its core job anyway, so a crash-with-traceback
  at startup is more useful than silently degrading. Both
  `self.metadata_scanner = ... if ... else None` /
  `self.provider_enricher = ... if ... else None` instantiation guards
  simplified to plain instantiation (both call sites), and the two
  `_require_metadata_scanner()`/enrichment `RuntimeError` messages that
  referenced the now-removed `BACKEND_METADATA_SCANNER_IMPORT_ERROR` /
  `BACKEND_PROVIDER_IMPORT_ERROR` module vars simplified accordingly.
  **Deliberately left alone**: `BackendDatabase`'s import try/except and its
  `database = None` / `if BackendDatabase: ...` startup handling in `main()` -
  that one is genuine, working graceful degradation (daemon still starts and
  serves web/command API without a database), not dead defensive code.

### `_resultsdb_get_media_metadata_by_path` was broken, now fixed

`e2mdb_media.file_path` only ever stores the *directory* (`dirname(org_path)`,
written via `add_media(hash, dirname(org_path), basename(org_path), title)`),
never the full path. `_resultsdb_get_media_metadata_by_path(media_path)`
queried `WHERE file_path = ?` with the *full* path, which could never match
anything. Fixed (by the user) to compute the same reduced-path md5 hash as
`get_reduced_org_hash()` and delegate to the hash-based lookup
(`_resultsdb_get_media_metadata`, not `_resultsdb_get_media_display_data` -
matters because callers expect the same raw `metadata_*`-keyed row shape from
both `get_media_metadata()` and `get_media_metadata_by_path()`).

Follow-up simplifications enabled by the fix:

- `plugin.py` (`E2MDBshowEventInformation`): replaced manual
  `e2mdbhelper.get_reduced_org_hash(org_path)` + `get_media_metadata(hash)`
  with a direct `resultsdb.get_media_metadata_by_path(org_path)` call; the
  now-unused local `E2MDBHelper()` instance removed.
- `E2MDBEventViewSimple.py` (`_load_final_dict_from_db`): the two-step
  `get_media_metadata(hash)` + `get_media_metadata_by_path(path)` fallback
  collapsed to a single `get_media_metadata_by_path(org_path)` call (both
  now do the same lookup).

### `E2MDBEventViewSimple` cleanup

- `get_picture_path()` (added `get_full_org_path()` on top of an
  already-fully-resolved `final_dict["<type>_path"]` value from
  `build_eventview_final_dict_from_db()`/`_full_cache_path()` - a harmless
  but redundant no-op) replaced for all four picture types
  (backdrop/cover/titlelogo/image) with direct
  `final_dict.get("<type>_path", "")` reads; the now-unused
  `get_picture_path()` closure removed.
- `E2MDBHelper` dropped from `class E2MDBEventViewSimple(Screen, E2MDBHelper)`
  bases entirely - after the above and an earlier local `_set_dict_key()`
  replacement, nothing in the class used the mixin anymore
  (`get_full_org_path`, `set_dict_key`, `image_download`, `MODULE_NAME` were
  the only past uses). `class E2MDBEventSelection(E2MDBHelper, Screen)` in
  the same file still needs the mixin (`image_download`/`MODULE_NAME`) and
  was deliberately left untouched.

### New (unused-so-far) `E2MDBImageDownloader.py`

Experimental Twisted-only counterpart to `E2MDBHelper.image_download()`,
requested to compare against the `requests`-based original (left completely
untouched) without wiring it in anywhere yet. Same signature
(`image_download(image_url, image_path, callback=None, fail=None)`), same
PIL resize/JPEG-alpha-conversion/save logic, but fetches via Twisted's
`Agent`+`RedirectAgent`+`readBody` instead of blocking `requests`, so no
`callInThread` is needed. Notes from building it:

- `twisted.web.client.getPage`/`downloadPage` (the classic Enigma2-plugin
  idiom for this) are removed from current Twisted versions entirely -
  `Agent`+`readBody` is the current non-deprecated replacement.
- Concurrency limited via `twisted.internet.defer.DeferredSemaphore(2)`
  instead of `threading.BoundedSemaphore(2)`.
- `Agent` alone does not follow redirects (unlike `requests`); wrapped with
  `RedirectAgent` after testing against a redirecting image URL surfaced
  this as a real gap (PIL failed to decode the redirect stub instead of the
  image).
- `callback(image_path)` fires even after a failure, matching the original's
  `finally`-block behavior (not a new bug introduced here).
- `connectTimeout` only bounds the TCP connect phase, not the whole
  request/response, unlike `requests`' `timeout=`.

### Bulk f-string conversion

Converted `%`-style string formatting to f-strings across the whole `e2MDB/`
tree (28 files, 496 of 512 candidate sites; the rest left as `%` deliberately -
multi-line SQL text building in `E2MDBBackendDatabase.py`, `provider/IMDB.py`
per the "don't touch" rule above, two raw-string regex patterns in
`provider/FERNSEHSERIEN.py` needing manual `rf"..."` handling). Done via a
custom AST-based script (finds `BinOp` nodes with a string-literal left side
and a `%` operator, rewrites using `ast.get_source_segment()` for exact
argument text) rather than regex, specifically to avoid corrupting numeric
modulo expressions or multi-line calls. Found and fixed one real bug in the
script itself along the way: `ast` column offsets are UTF-8 *byte* offsets,
not character offsets, which silently mis-sliced two lines containing
non-ASCII characters ("—", "★") until fixed and re-verified.

## Result

- Series "Darsteller"/cast metadata is stable across all of a show's
  episodes instead of flipping to whichever episode was scanned last.
- Season posters download once per season, deduped, under
  `cache_root/seasons/...`.
- `/etc/enigma2/e2mdb/` only holds small config now; scan-result/job-history
  data lives under `<cache_root>/results/` with the database.
- IMDB is fully disabled without deleting `provider/IMDB.py`; Cinemeta is
  available as an opt-in free provider.
- `E2MDBBackendMetadataScanner` is its own module.
- A handful of dead defensive-programming patterns (unreachable relative
  imports, import guards around things that must succeed for the daemon to
  be useful at all) were removed; genuine graceful-degradation code
  (`BackendDatabase`) was explicitly kept.
- `get_media_metadata_by_path()` actually works now, with knock-on
  simplifications in two GUI call sites.
- Whole `e2MDB/` tree uses f-strings except the few deliberately-skipped
  cases above.

## Verification

- `python3 -m py_compile` on every changed file (including full-tree sweep
  after the f-string pass) - all clean.
- Cinemeta provider methods (`get_result_dicts`, `get_series_details_index`,
  `get_episode_details` by season/episode and by compound id,
  `get_movie_details`) exercised against the real `v3-cinemeta.strem.io` API.
- `E2MDBImageDownloader.image_download()` exercised against a real redirecting
  HTTPS image URL (success: correct resize/JPEG conversion/save) and a real
  404 (failure: `fail()` callback fires, no file written).
- f-string conversion verified by reprocessing clean git `HEAD` content
  in-memory for every non-session-touched file and diffing byte-for-byte
  against the applied result (22/25 files identical; the other 2 diffs were
  unrelated pre-existing linter/formatter cosmetics, not from this script);
  the 5 session-touched files verified by confirming zero non-ASCII bytes in
  their diffs (ruling out the byte-offset bug) plus manual diff review.
- Inspected a real on-box `results.db`/cache-folder mirror throughout to
  confirm `path_mode` correctness, artwork dedup file layout, and that
  `seasons`/`series` folders actually populate as expected.
