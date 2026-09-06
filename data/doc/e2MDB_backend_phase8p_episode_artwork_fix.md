# e2MDB Backend Phase 8p - Episode artwork fix

This phase fixes episode-specific artwork handling in the backend provider and MediaBrowser path.

## Problem

Series episodes were matched correctly, including episode title and episode overview, but all episodes could still show the same image. The provider result merged the selected series artwork with the episode metadata and the generic artwork downloader preferred `cover_url` before `image_url`. For episode rows this could download the series poster as the row poster.

## Fix

- Store series artwork and episode artwork separately.
- Prefer provider episode stills for episode rows.
- Keep series poster/backdrop as series-card fallback.
- Add DB columns for explicit episode/series artwork separation:
  - `metadata_series_cover_path`
  - `metadata_episode_image_path`
  - `artwork_series_poster_path`
  - `artwork_series_backdrop_path`
  - `artwork_episode_path`
- MediaBrowser episode cards prefer:
  1. `artwork_episode_path`
  2. `metadata_episode_image_path`
  3. episode still/preview/image URL from `provider_best_json`
  4. generic row poster fallback
  5. series poster fallback
- Series cards prefer:
  1. `artwork_series_poster_path`
  2. `metadata_series_cover_path`
  3. series cover/poster URL from `provider_best_json`

## Required after installing

Restart the daemon and refresh provider metadata so existing rows get new episode artwork fields.

```sh
/etc/init.d/e2mdbd restart
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py metadata start all
```

## Debug

```sh
python3 e2mdbctl.py browser debug-artwork 20
```

SQL check:

```sh
DB="/media/hdd/e2MDB/results.db"
sqlite3 -header -column "$DB" "select file_name,metadata_title,metadata_season_no,metadata_episode_no,artwork_episode_path,artwork_poster_path,artwork_series_poster_path from e2mdb_media where provider_media_type='series' limit 20;"
```
