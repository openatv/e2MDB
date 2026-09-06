# e2MDB backend phase 10z - supported media file filter before metadata scan

## Goal

The backend scanner must never hand random files from recording/media folders to
the metadata scanner.  Recording folders can contain sidecars, artwork, logs,
NFO files, subtitles, temporary files and other helper files.  Only known local
media files are scan candidates.

## Rules

- `.ts` files are Enigma2 TS recordings.
- `.ts` files are parsed with the native META/EIT/CUTS recording parser.
- Normal media files such as `.mkv`, `.mp4`, `.avi`, `.iso`, `.m2ts` and `.mts`
  are handled as `media_file` items and classified by path mode plus
  MediaNameParser.
- Sidecars such as `.meta`, `.eit`, `.cuts`, `.txt`, `.nfo`, subtitles, artwork
  and temporary files are ignored by the scanner.
- `.stream` files are no longer treated as local scan media because they are
  stream reference files and not stable local media files.
- Hidden folders, trash folders and `__pycache__` are skipped during directory
  traversal.

## Diagnostics

`scan paths count` now reports additional counters:

- `supported_media_files`
- `ignored_files`
- `ignored_by_extension`

The recording scan summary stores the same ignored-file counters in
`scan_state.json` and `/tmp/e2mdb/last_recording_scan.json`.

## Progress

The backend progress can now distinguish:

- `Scanning TS recordings with native META/EIT/CUTS parser`
- `Scanning media files with path mode and filename parser`

Both texts are present in the POT and German translation catalog.
