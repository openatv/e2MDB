# e2MDB Backend Phase 8t - v16 Series Browser Behaviour Restore

This phase restores the MediaBrowser interaction model used by v16:

- Selecting a series shows the season overview immediately from the already loaded browser-list payload.
- A season is not opened automatically.
- The episode list is hidden until the user explicitly clicks a season button.
- The local season overview is rendered before the background `series_details` request completes.
- Cast/person clicks start a direct database search even when the optional people index is not ready.

The backend remains the data source, but the web UI no longer rebuilds the series panel in a way that changes the v16 interaction flow.
