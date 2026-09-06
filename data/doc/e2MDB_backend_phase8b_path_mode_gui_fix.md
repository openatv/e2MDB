# e2MDB backend phase 8b - GUI path/mode handling fix

This phase fixes the GUI/backend handover for selected media paths.

Changes:

- The blue-key job labels now use "media paths" instead of "recordings".
- The selected GUI paths are passed to all three backend jobs:
  - selected media path scan only
  - selected media path scan + provider metadata
  - provider metadata for selected paths only
- Provider-only enrichment no longer ignores the selected GUI path list.
- SQLite pruning after a partial scan is scoped to the selected scan paths, so entries from non-selected paths are not removed accidentally.
- RecordingScanItem now stores `path_mode`, `path_mode_label` and `media_family`.
- Provider media-type detection now uses the v16 path modes:
  - 1 = movie
  - 2 = series
  - 3 = multi
  - 4 = anime_series
  - 5 = manga_series
  - 6 = anime_movie
  - 7 = manga_movie

Notes:

- The backend still uses the internal term `recording` for TS/media items because the DB/API schema was introduced with that name.
- In the GUI the wording is now more precise: selected paths can contain movies, series, anime, manga or mixed content, depending on the configured path mode.
