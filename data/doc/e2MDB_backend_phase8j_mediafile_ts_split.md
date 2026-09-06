# e2MDB backend phase 8j - media file / TS recording split

This phase fixes the scanner source handling.

## Problem

The backend scan iterated over all supported video extensions but still called the native TS recording parser for every file. This made normal media files such as MKV/MP4 appear as if they were TS recordings and the GUI progress text said that TS META/EIT/CUTS parsing was used for all files.

## Fix

The backend now separates the file source from the media content type:

- `source_type = recording` only for `.ts` files.
- `source_type = media_file` for normal media files such as `.mkv`, `.mp4`, `.avi`, `.iso`, etc.
- The native META/EIT/CUTS parser is only used for `.ts` recordings.
- Non-TS files are classified by selected path mode plus MediaNameParser.
- Non-TS files no longer get fake META/EIT/CUTS sidecars in the scan payload.

## Important distinction

`recording` means the file source is an Enigma2 TS recording.

`movie`, `series`, `anime_series`, `manga_series`, `anime_movie`, `manga_movie` describe the content/provider type and still come from the selected path mode and filename parser.

## GUI progress

The progress message no longer says that every file is scanned as TS:

- TS files: `Scanning TS recordings with native META/EIT/CUTS parser`
- non-TS files: `Scanning media files with path mode and filename parser`

The scan summary also stores separate counters:

- `ts_recordings`
- `media_files`
