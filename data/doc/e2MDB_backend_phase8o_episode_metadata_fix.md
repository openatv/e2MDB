# e2MDB Backend Phase 8o - Episode Metadata Fix

Fixes the provider enrichment path for series episodes.

## Problem

Series episodes were matched as series entries only. The backend stored the same
series overview and the same series artwork for every local episode, although the
filename already contained different season/episode numbers.

## Change

For series/anime/manga series entries the provider enrichment now performs an
additional episode step after the series match:

1. Search the series by the parsed series title.
2. Load/cache the provider episode index for the matched series.
3. Resolve the local SxxExx/season-episode number against the provider index.
4. Load the episode details.
5. Store episode-specific title, overview, season, episode and artwork.

The series context is cached per provider/series id during the provider job so a
full season does not reload the episode index for every item.

## Result

The MediaBrowser episode grid should no longer show the same metadata for all
episodes. Each episode should get its own title/overview and, if the provider
supplies it, its own preview image.
