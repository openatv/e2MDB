# e2MDB Normalized Data Schemas

This document summarizes the normalized dictionaries described by the uploaded schema text files and explains how they should be interpreted inside the plugin.

---

## 1. Normalized search result dictionary

A normalized search result is the lightweight structure used during provider search and match scoring.

| Field | Type | Description |
|---|---|---|
| `provider` | `string` | source provider such as `tmdb`, `tvdb`, or `omdb` |
| `title` | `string` | movie or series title |
| `media_type` | `string` | `movie` or `series` |
| `countries` | `string` | production countries |
| `released` | `string` | first known release/publication date |
| `genres` | `string` | comma-separated genres |
| `overview` | `string` | provider long description |
| `voteAverage` | `string` | average user rating |
| `voteCount` | `string` | number of votes |
| `cover_url` | `string` | poster/cover URL |
| `backdrop_url` | `string` | backdrop URL |
| `titlelogo_url` | `string` | title-logo URL |
| `image_url` | `string` | additional still/image URL |
| `providerIds` | `dict` | provider-specific IDs such as TMDb / TVDb / IMDb |

### Purpose

This structure is not the final display payload. It is a provider-neutral candidate format used to compare titles and overviews before selecting the best match.

---

## 2. Normalized final series dictionary

The normalized final series structure is richer and is used after a series match was resolved and detailed provider data was fetched.

| Field | Type | Description |
|---|---|---|
| `provider` | `string` | source provider |
| `title` | `string` | series title |
| `tagline` | `string` | subtitle / tagline |
| `media_type` | `string` | always `series` |
| `countries` | `string` | production countries |
| `released` | `string` | first release date |
| `ageRating` | `string` | localized age rating |
| `voteAverage` | `string` | average rating |
| `voteCount` | `string` | number of votes |
| `genres` | `string` | genre list |
| `overview` | `string` | description |
| `runtime` | `string` | runtime in minutes |
| `cover_url` | `string` | poster/cover URL |
| `cover_path` | `string` | cache-relative cover path |
| `cover_src` | `string` | source classification, usually `series` |
| `backdrop_url` | `string` | backdrop URL |
| `backdrop_path` | `string` | cache-relative backdrop path |
| `backdrop_src` | `string` | source classification |
| `titlelogo_url` | `string` | title-logo URL |
| `titlelogo_path` | `string` | cache-relative title-logo path |
| `titlelogo_src` | `string` | source classification |
| `image_url` | `string` | still/image URL |
| `image_path` | `string` | cache-relative image path |
| `image_src` | `string` | source classification |
| `providerIds` | `dict` | provider IDs |
| `crew` | `list[dict]` | crew members such as director or writer |
| `cast` | `list[dict]` | cast members / actors |
| `title_ratio` | `string` | title matching score |
| `desc_ratio` | `string` | description matching score |

### Crew and cast entry structure

| Field | Type | Description |
|---|---|---|
| `job` | `string` | role such as `Director`, `Writer`, `Actor` |
| `name` | `string` | person name |
| `character` | `string` | played character / role |
| `profileId` | `string` | provider-side profile ID |
| `profile_url` | `string` | profile image URL |

### Interpretation inside e2MDB

For series, the final data often represents a merged payload from multiple scopes:

- episode details
- season details
- series details

This means some fields may originate from the episode layer while others are inherited from the season or series layer.

---

## 3. Normalized final movie dictionary

The movie final-data schema is similar but explicitly fixed to `media_type = movie`.

| Field | Type | Description |
|---|---|---|
| `provider` | `string` | source provider |
| `title` | `string` | movie title |
| `tagline` | `string` | subtitle / tagline |
| `media_type` | `string` | always `movie` |
| `countries` | `string` | production countries |
| `released` | `string` | first release date |
| `ageRating` | `string` | localized age rating |
| `voteAverage` | `string` | average rating |
| `voteCount` | `string` | number of votes |
| `genres` | `string` | genre list |
| `overview` | `string` | description |
| `runtime` | `string` | runtime in minutes |
| `cover_url` | `string` | poster/cover URL |
| `cover_src` | `string` | source classification, usually `movie` |
| `backdrop_url` | `string` | backdrop URL |
| `backdrop_src` | `string` | source classification |
| `titlelogo_srl` | `string` | title-logo URL |
| `titlelogo_src` | `string` | source classification |
| `image_url` | `string` | still/image URL |
| `image_src` | `string` | source classification |
| `providerIds` | `dict` | provider IDs |
| `crew` | `list[dict]` | crew members |
| `cast` | `list[dict]` | cast members |
| `title_ratio` | `string` | title matching score |
| `desc_ratio` | `string` | description matching score |
| `cover_path` | `string` | cache-relative cover path |
| `backdrop_path` | `string` | cache-relative backdrop path |
| `image_path` | `string` | cache-relative image path |

### Crew and cast entry structure

The crew/cast entry format is the same as for series:

| Field | Type | Description |
|---|---|---|
| `job` | `string` | production role |
| `name` | `string` | person name |
| `character` | `string` | played role |
| `profileId` | `string` | provider-side person ID |
| `profile_url` | `string` | image URL |

---

## 4. How the schemas relate to the code

### Search stage

The provider adapters first emit normalized search-result dictionaries.

### Selection stage

The scanner compares the normalized search candidates with file-derived title and description data.

### Final stage

After the best hit is selected:

- movies are expanded into a movie final dict,
- series are expanded into episode/season/series details and merged.

### Render stage

The final normalized dict is what the custom Event View uses for display and what the cache JSON stores for later reuse.

---

## 5. Practical implication for future development

Because the plugin already works with a provider-neutral schema, new providers can be added more safely if they map into the same normalized structures.

The most important compatibility rule is:

> any new provider adapter should produce dictionaries that preserve the same semantic field meaning used by the existing final-data and search-result schemas.
