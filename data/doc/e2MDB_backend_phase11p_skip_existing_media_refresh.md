# e2MDB Backend Phase 11p - Skip existing media refresh by default

Date: 2026-06-01
Base: phase11o DB status timeout and UI cleanup

## Goal

A normal media refresh must not download provider metadata/artwork again for files
that are already present in the SQLite database and have not changed. Large
libraries should only process new or changed files unless the user explicitly
requests a full re-scan.

## Changes

- Added the setup option `scannerRescanExisting` / `rescan_existing`.
- Default is `False`: existing unchanged media rows are skipped.
- GUI, OpenATV Scheduler bridge and daemon scheduler now pass `rescan_existing`.
- Legacy scheduler jobs with `only_missing = False` no longer force a full
  metadata re-download unless `rescan_existing` is enabled.
- Recording scan builds a fast SQLite index for the selected scan paths and
  compares file size and mtime before parsing.
- Unchanged existing files are counted as seen for pruning, but their rows are
  not re-imported and their provider/artwork state is not reset.
- Changed/new files are imported normally and their provider state is reset to
  pending so metadata can be refreshed only for those files.
- Provider enrichment now uses `only_missing = not rescan_existing` internally.
- Rows that were left with `browser_ready = 0` by an older scan but already have
  provider status `done` or `no_match` are repaired without a provider download.
- Pruning now uses a temporary SQLite table instead of a huge `NOT IN (...)`
  parameter list, so large libraries do not hit SQLite variable limits.

## User-facing behavior

- Normal scan: new/changed files are scanned, unchanged existing files are
  skipped, provider downloads are only started for missing/pending/error rows.
- Full re-scan: enable "Re-scan existing media entries" in setup. Then the scan
  processes existing rows again and provider metadata/artwork may be downloaded
  again.
