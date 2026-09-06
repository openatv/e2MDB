# e2MDB Backend Phase 11t - Real backdrop provider retry

Stand: 2026-06-01

## Problem

Live/EPG events like `Sturm der Liebe` can be matched as TVDB series and still end up with an empty `metadata_backdrop_path` while `metadata_image_path` contains an episode still/preview.

That still/preview is not a backdrop and must not be used as backdrop fallback.

## Changes

- Reverted the display fallback that used `metadata_image_path` as backdrop.
- The `Backdrop` converter now only returns real `backdrop_path` data.
- TVDB series details now retry the official `/series/{id}/artworks` endpoint when the extended series payload does not expose a backdrop.
- TVDB artwork type ids are resolved through `/artwork/types` so numeric TVDB artwork types can be classified as poster/background/logo instead of being ignored.
- Backend provider enrichment now tries active alternate series providers for missing real artwork fields before FanArt fallback is applied.
- FanArt fallback keeps `*_src`/`*_provider` as `fanart` and mirrors series artwork to `series_*_url` where useful.
- TMDB detail lookup condition fixed so series/movie/episode details are actually fetched even when no extra params are needed.
- Existing older Live/EPG provider-result JSON can trigger one retry for missing series backdrops. New result JSON writes `artwork_lookup_version = 2` to avoid endless retry loops.

## Intended mapping

- `metadata_backdrop_path`: real backdrop/fanart/series background only.
- `metadata_image_path`: episode still/preview/landscape editorial image only.
- `metadata_image_path` must not be used as backdrop.

## Verification hint

For a cached EPG row with a missing backdrop, open the EPG/EventInfo once after installing this phase. If the existing JSON was written by an older phase and the event is still fresh, the Live/EPG queue should retry it once with reason `fresh-missing-images:backdrop`.
