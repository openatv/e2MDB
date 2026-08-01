# e2MDB backend phase 8q - Episode image API cleanup

This phase fixes episode artwork selection and API field semantics.

## Fixes

- Episode cards now prefer episode stills over series posters.
- `*_path` fields are local filesystem paths only.
- `*_url` fields are web/API URLs only.
- Accidental `/api/artwork/file?...` values in path fields are normalized back to local paths.
- Series cards still use series artwork, but episode cards use episode artwork when available.
- Season details no longer inject the series poster into each episode `cover_url` unless the web UI explicitly needs a fallback.

## Notes

The database should store local paths and provider metadata, not derived HTTP URLs. The backend derives HTTP URLs dynamically for API/Web UI responses.
