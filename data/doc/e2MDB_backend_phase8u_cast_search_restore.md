# e2MDB backend phase 8u - Cast search restore

- Restores v16-like cast click behavior: clicking a cast pill filters the MediaBrowser list instead of replacing the detail pane.
- Cast filtering is now SQL-side using `metadata_cast` / `provider_best_json`, so it works even when the optional people index is not built.
- The web UI no longer clears the cast filter when `people_index_ready` is false.
- Client-side visible-page cast post-filter was removed to avoid false empty result pages.
