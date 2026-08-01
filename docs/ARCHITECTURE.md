# e2MDB Architecture and Internals

## 1. Scope

This document describes the internal architecture of `e2MDB` from the perspective of runtime behavior, data flow, storage model, provider abstraction, UI integration, and maintainability.

It is intended for developers who want to:

- understand the scanner pipeline,
- modify the provider layer,
- adapt the skin/event view,
- debug cache generation,
- or refactor the code for long-term maintenance.

---

## 2. High-level design

The implementation is split into five layers:

1. **Bootstrap and configuration** in `__init__.py`
2. **Scan / cache / UI logic** in `plugin.py`
3. **Provider orchestration** in `e2MDBProviders.py`
4. **Provider adapters** in `provider/*.py`
5. **Optional structured indexing** in `e2MDBDatabase.py`

This is not a strict clean architecture; most orchestration still happens inside `plugin.py`. The provider layer is comparatively well isolated, but the UI, cache, and workflow logic remain tightly coupled.

---

## 3. Bootstrapping and globals

`__init__.py` provides these runtime primitives:

### 3.1 Global constants

`e2MDBGlobals` contains:

- plugin name / module prefix
- Enigma2 service-root constants
- screen-resolution mode (`HD` vs `FHD`)
- plugin paths and icon directory
- cache subdirectory names
- report/log directory
- supported video and image file types
- filename separators used for title extraction
- image target resolutions
- randomized mobile browser user agent

### 3.2 Localization

The module binds the translation domain and exposes `_()` for translated strings.

### 3.3 Configuration namespace

All plugin config keys are registered under `config.plugins.e2mdb`.

### 3.4 API-key access

`getApiKey(provider)` is a simple provider-name lookup for the configured keys.

### 3.5 Logging

`write_log()` appends timestamped log lines to `/home/root/logs/e2MDB.log`.

---

## 4. Plugin integration with Enigma2

The public integration points are implemented in `plugin.py`.

### 4.1 Registered plugin descriptors

`Plugins(**kwargs)` registers:

- a plugin-menu entry opening the scan UI,
- a main-menu entry opening setup,
- and a session-start hook.

### 4.2 Event-view override

The most important integration step happens in `autostart(reason, session)`:

```python
MovieSelection.showEventInformation = e2MDBshowEventInformation
```

This monkey patch intercepts the default Event Information behavior.

### 4.3 Runtime decision path

When the user asks for event information in the movie list:

1. the current service path is read,
2. the primary JSON cache path is derived,
3. if that JSON exists, `e2MDBEventViewSimple` is opened,
4. otherwise the original Enigma2 handler is called.

This design keeps the normal movie-selection workflow intact while upgrading it opportunistically when metadata already exists.

---

## 5. Core helper layer

`e2MDBHelper` is the shared utility base used by scanner and UI classes.

### 5.1 Path handling

Important methods:

- `getCacheDir()`
- `get_full_org_path(path)`
- `get_reduced_org_path(org_path)`
- `getReducedOrgHash(org_path)`
- `getPrimaryDatapath(...)`
- `getSecondaryDatapath(...)`

The central strategy is deterministic path derivation.

#### Primary data

Primary cache uses the original media path, reduced by `/media/hdd`, hashed with MD5, and then sharded by the first hash character.

#### Secondary data

Secondary cache uses provider name plus provider ID and optionally a season path such as `S01`.

### 5.2 JSON IO

`readJsonFile()` loads JSON from disk. `writeJsonFile()` writes JSON and creates parent directories if needed.

### 5.3 Final-dict assembly

`createFinalDict()` is one of the key methods in the plugin. It:

1. reads the aggregated search result set,
2. computes title and description similarity for each result,
3. selects the best hit using threshold logic,
4. fetches movie or series detail data,
5. merges episode → season → series data where required,
6. stores match ratios into the final dictionary.

### 5.4 Match thresholds

The hardcoded thresholds in `createFinalDict()` are:

- qualifying threshold for title: `0.20`
- qualifying threshold for description: `0.20`
- final acceptance threshold for title: `0.60`
- final acceptance threshold for description: `0.60`

These values determine whether a result is considered strong enough to become the final metadata payload.

---

## 6. Scanner pipeline

`e2MDBScanner` contains the main acquisition workflow.

## 6.1 Overall scan sequence

The top-level method is `titleScanner(selected_dirs, ...)`.

Its job is to:

1. enumerate media services for selected directories,
2. extract file-level and event-level metadata,
3. avoid rescanning already cached titles,
4. create provider search requests,
5. resolve the best result,
6. download images,
7. persist primary and secondary cache files,
8. optionally upsert DB rows,
9. emit progress and summary information.

## 6.2 Service enumeration

The scanner uses Enigma2 service references rooted below the movie path and iterates them via `eServiceCenter`.

For each media entry it collects:

- service reference
- display title
- file path
- description
- short description
- extended description
- creation time
- tags
- file size
- duration

If Enigma2 info objects are missing, a fallback `StubInfo` object provides a reduced compatibility layer.

## 6.3 Title derivation

The scanner tries to infer a clean search title from:

- original filename
- path basename
- EPG-like title strings
- filename separators
- year hints
- season/episode patterns

Relevant helper methods include:

- `guessCategory(...)`
- `createBestSearch(...)`
- `createSearchTitles(...)`
- `divideFileBaseInfos(...)`

The code uses multiple separator tables such as `FOREIGN_SEPAS` and `EPGTYPE_SEPAS` to split title-like and episode-like fragments.

## 6.4 Search execution

`getSearchResults(...)` coordinates candidate searches.

Under the hood it calls `createNormResultDicts(...)`, which forwards work to `providers.gatherProvidersInfo(...)`.

The result is a normalized result bundle with provider-neutral keys.

## 6.5 Result scoring

`getMatchRatio(...)` calculates:

- title similarity via normalized text comparison and `SequenceMatcher`
- description similarity via comparison against `desc`, `short_desc`, and `ext_desc`

Both title and overview matching are used in final-hit selection.

## 6.6 Series enrichment

When the best hit is a series, `getSecondaryDicts(...)` is responsible for extra resolution:

1. fetch or load cached series details,
2. fetch or load cached episode index,
3. locate the target episode,
4. download episode details,
5. download season details,
6. store season metadata,
7. inject season identifiers and names back into the episode dict.

The final displayed payload is assembled in this order:

```text
episode details -> season details -> series details
```

This means lower-level episode data wins first, and broader series metadata fills the missing fields afterward.

## 6.7 Image download

`imageDownload(url, image_path, fail=None)`:

- performs an HTTP request with a randomized mobile user agent,
- opens the downloaded data via Pillow,
- resizes selected asset types to target resolution,
- stores the image with lossy optimization,
- supports a raw-write fallback for nonstandard image types.

Configured image target categories are primarily:

- `backdrop`
- `cover`
- `titlelogo`

## 6.8 Scan statistics

`writeScanStatistics(...)` writes a summary JSON that contains success and failure lists plus start time and scan duration.

---

## 7. UI classes

`plugin.py` also contains the main UI classes.

### 7.1 `e2MDBMain`

Main scanner screen responsible for folder selection, scan start, and progress hookup.

### 7.2 `e2MDBScanResults`

Result-oriented UI for presenting scan outcomes.

### 7.3 `e2MDBSetup`

Configuration screen based on Enigma2 `Setup` and `setup.xml`.

### 7.4 `e2MDBInfoBox`

Auxiliary informational popup screen.

### 7.5 `InfoLine`

Custom GUI component used for event-view style presentation.

### 7.6 `e2MDBEventViewSimple`

The most user-visible screen. It renders cached metadata and artwork in a skin-dependent layout.

This is the screen the preview PNGs are effectively demonstrating.

### 7.7 `e2MDBBackroundRefresh`

A placeholder for future background refresh functionality. The related integration code is currently commented out.

---

## 8. Provider orchestration layer

`e2MDBProviders.py` is the abstraction layer between scanner logic and provider-specific adapters.

## 8.1 Responsibilities

It is responsible for:

- instantiating and exposing provider adapters,
- starting active providers with API keys and language,
- preserving separate series/movie search order,
- normalizing multi-provider search collection,
- exposing movie, series, season, and episode detail calls.

## 8.2 Search-order behavior

The orchestration layer reorders the provider dict to put **TMDb first** when present. This is important because TMDb supports a `multi` search mode while the other providers are queried in movie/series sequences.

## 8.3 Public orchestrator methods

- `start(...)`
- `gatherProvidersInfo(...)`
- `getMovieDetails(...)`
- `getSeriesDetailsIndex(...)`
- `findSeasonEpisode(...)`
- `getSeasonDetails(...)`
- `getEpisodeDetails(...)`
- `getDesiredProvider(...)`

## 8.4 CLI helper mode

`e2MDBProviders.py` also contains a small shell/CLI entry point for standalone provider testing.

That is useful for debugging normalization separately from the full Enigma2 runtime.

---

## 9. Provider adapters

Each provider module maps remote API responses into a shared internal schema.

### 9.1 TMDb

Based on the inspected code, the TMDb adapter:

- supports `multi`, `movie`, and `series` searches,
- fetches extra image/logo data,
- collects credits for movies,
- derives localized certification data,
- normalizes provider IDs and image URLs,
- exposes movie, series, season, and episode detail functions.

### 9.2 TVDb

TVDb is used for richer series/episode-oriented workflows and participates in normalized result generation.

### 9.3 OMDb

OMDb acts as an additional metadata source and can complement movie resolution where available.

### 9.4 Shared provider contract

The adapters are expected to provide methods such as:

- `start(...)`
- `getResultDicts(...)`
- `getMovieDetails(...)`
- `getSeriesDetailsIndex(...)`
- `findSeasonEpisode(...)`
- `getSeasonDetails(...)`
- `getEpisodeDetails(...)`

The orchestration layer depends on this informal contract rather than an explicit abstract base class.

---

## 10. Data model and normalization

The plugin uses a provider-independent normalized dictionary model.

There are three main structures:

1. normalized **search result** dictionaries,
2. normalized **final movie** dictionaries,
3. normalized **final series / episode** dictionaries.

The uploaded schema text files should be treated as the authoritative documentation for those structures. See [DATA-SCHEMA.md](DATA-SCHEMA.md).

### 10.1 Search-result purpose

Search-result dicts are lightweight candidates used for matching and provider selection.

### 10.2 Final-data purpose

Final movie/series dicts are richer and can contain:

- runtime
- age rating
- genres
- ratings
- provider IDs
- image URLs
- cast and crew
- cache-relative image paths
- match ratios

### 10.3 Merge strategy for series

Series are assembled from multiple scopes:

- episode
- season
- series

The helper merges non-empty keys and appends `cast` / `crew` lists when later scopes contain more data.

---

## 11. Persistence model

## 11.1 JSON as primary runtime storage

The actual event-view rendering path depends on cached JSON files. If a primary JSON file exists for a media item, the custom Event View opens immediately.

This makes JSON the real runtime persistence layer.

## 11.2 SQLite as optional supplemental index

The SQLite DB stores scan-side media facts and can support deduplication, lookups, or future enhancements, but it does not currently replace JSON.

### 11.3 DB schema

The `media` table stores:

- `path` unique key
- `name`
- `ref`
- `title`
- `short`
- `extended`
- `tags`
- `duration`
- `begin`
- `size`

### 11.4 Upsert behavior

`upsert()` uses `ON CONFLICT(path) DO UPDATE`, which is appropriate for repeated scans of the same file.

---

## 12. Error handling and logging

The codebase relies mostly on:

- log-file writes,
- broad exception handling,
- empty-dict fallbacks,
- existence checks for cache files.

This is pragmatic for a plugin environment but makes strict failure diagnosis harder.

Recommended future improvements:

- structured error returns,
- typed result objects,
- more consistent propagation of write failures,
- isolated provider exceptions.

---

## 13. Maintainability observations

Several implementation details deserve attention before major expansion.

### 13.1 SQLite helper inconsistencies

Observed examples:

- `_get_titles()` is implemented, but `is_title_in_database()` calls `_getTitles()`.
- The query references `extDesc`, while the table field is defined as `extended`.
- The bottom `__main__` demo instantiates `MediaDB("media.db")`, although the constructor takes no path argument.

These are strong indicators that `e2MDBDatabase.py` needs a cleanup pass before being relied on heavily.

### 13.2 Return-value ambiguity

`writeJsonFile()` does not clearly return a success/error object, yet some call sites treat it as if it produced an error string.

### 13.3 Tight coupling

The scanner, cache writer, image downloader, and UI interactions are all strongly coupled inside `plugin.py`. This makes refactoring or unit testing harder than necessary.

### 13.4 Informal provider contract

Provider adapters share expected method names, but there is no explicit abstract interface or test suite to enforce compatibility.

### 13.5 Licensing text

The file headers combine GPL wording with additional restrictions. This should be clarified before public repository publication.

---

## 14. Suggested refactoring roadmap

A sensible next-step roadmap would be:

1. extract cache/storage operations into a dedicated service class,
2. define a formal provider interface,
3. isolate filename parsing into a testable parser module,
4. clean up SQLite naming inconsistencies,
5. separate UI code from scan orchestration,
6. add schema validation for normalized dictionaries,
7. document cache-versioning strategy for future incompatible changes.

---

## 15. Visual-result relation

The uploaded preview PNGs represent the presentation goal after three conditions are met:

1. the media item was scanned successfully,
2. cache JSON plus artwork exist,
3. the skin provides the expected layout/widgets for `e2MDBEventViewSimple`.

That means the screenshots are not just generic mockups; they correspond to the end of the scan/cache/render pipeline described above.

---

## 16. Summary

`e2MDB` is structurally a metadata enrichment and presentation pipeline for Enigma2 media content.

Its strongest technical ideas are:

- provider-neutral normalization,
- deterministic cache paths,
- opportunistic event-view override,
- and multi-stage series enrichment.

Its main engineering risks are:

- coupling inside `plugin.py`,
- partial inconsistency in the database helper,
- and unclear license wording.

Despite those caveats, the codebase is already well suited for documentation, maintenance planning, and a future cleanup-oriented public repository.
