# e2MDB Backend Phase 8i - DB Path Mode / Media Type Fix

This phase fixes the distinction between the physical source type and the logical media type.

`recording` is only the source/container type for `.ts` recordings with `.meta/.eit/.cuts` sidecar files.
The logical media type is now stored separately in SQLite:

- `path_mode`
- `path_mode_label`
- `media_family`
- `estimated_media_type`
- `provider_media_type`
- `provider_title`
- `series_title`
- `movie_title`
- `scan_season_no`
- `scan_episode_no`

The daemon adds missing columns automatically during schema initialization. Existing rows are populated on the next backend scan.

The Enigma2 GUI also maps the internal phase name `recording_scan` to the user-facing label `media_scan` to avoid confusion.

## Test

Restart the daemon:

```sh
/etc/init.d/e2mdbd restart
```

Run a new scan from the Enigma2 GUI using the blue key.

Then check:

```sh
DB="/media/hdd/e2MDB/results.db"
sqlite3 -header -column "$DB" "select file_name, source_type, path_mode, path_mode_label, media_family, provider_media_type, metadata_media_type, series_title, scan_season_no, scan_episode_no from e2mdb_media limit 20;"
```

For series paths, `provider_media_type` and `metadata_media_type` should be `series`.

