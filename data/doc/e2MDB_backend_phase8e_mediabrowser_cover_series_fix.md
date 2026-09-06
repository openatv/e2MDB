# e2MDB Backend Phase 8e - MediaBrowser Cover/Series Fix

This phase fixes two backend MediaBrowser regressions after moving browser data to `e2mdbd`:

- MediaBrowser cards/details did not reliably expose cover aliases expected by the web UI.
- Series were shown as individual recordings instead of grouped series cards with seasons/episodes.

## Changes

- Backend browser list now groups entries by browser key:
  - `media_type|provider|provider_id` when provider IDs are available.
  - `media_type|normalized_title|year` as fallback.
- Series entries aggregate all local files belonging to the same provider/title group.
- Series cards now expose:
  - `season_count`
  - `episode_count`
  - `seasons`
  - `files`
- `series_details` now returns local inventory from backend grouping.
- `season_details` now returns local episode items for the selected season.
- Cover fields now include multiple aliases:
  - `cover_url`
  - `cover_path`
  - `poster_url`
  - `poster_path`
- Local artwork paths are mapped to `/api/artwork/file?path=...`.
- Remote provider artwork URLs stay unchanged.

## Test commands

Restart daemon:

```sh
/etc/init.d/e2mdbd restart
sleep 2
```

Check browser list:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py browser list 10
```

Check API output:

```sh
wget -qO- 'http://127.0.0.1:8088/api/results?action=browser_list&limit=10&page=1' | python3 -m json.tool
```

Look for:

- `cover_url`
- `browser_key`
- `media_type: series`
- `season_count`
- `episode_count`

Check a series item:

```sh
SERIES_ID='<browser_key from browser list>'
wget -qO- "http://127.0.0.1:8088/api/results?action=series_details&id=$SERIES_ID" | python3 -m json.tool
```

Check one season:

```sh
wget -qO- "http://127.0.0.1:8088/api/results?action=season_details&id=$SERIES_ID&season_no=1" | python3 -m json.tool
```
