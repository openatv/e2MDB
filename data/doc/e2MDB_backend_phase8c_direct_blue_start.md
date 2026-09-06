# e2MDB Backend Phase 8c - Direct blue key start

## Change

The scanner screen now keeps the v16 behaviour again:

- Blue starts the backend refresh directly.
- No additional job selection dialog is shown.
- The selected media paths already define the scan scope and media type.
- The backend job is `scan_and_enrich` by default.

## Rationale

The three backend job choices were useful for development and debugging, but they are not the correct default UX for the scanner screen. In v16 the user already selects paths and path modes in the path setup. Therefore the scanner screen should not ask again what type of scan to run.

## Result

Blue key behaviour:

1. If no backend job is running: start `scan_and_enrich` for the selected paths.
2. If a backend job is running: stop the running backend job.
3. If no path is selected: show `No media path selected.`

Path modes are still passed to the backend:

- movie
- series
- movie/series
- anime series
- manga series
- anime movie
- manga movie

The backend keeps the path/mode logic from Phase 8b.
