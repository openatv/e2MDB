# e2MDB Backend Phase 8f - Lazy MediaBrowser Performance Fix

This phase fixes a MediaBrowser performance regression introduced by the backend migration.

## Problem

The previous backend browser implementation loaded all media rows, grouped the full library in Python, calculated facets over the complete result set and only then returned the requested page.

That is too slow for large libraries and differs from the v16 behaviour where the first page is shown immediately and additional items are loaded while scrolling.

## Change

`BackendDatabase.list_browser()` now uses a lazy streaming path:

- SQL returns rows in browser order.
- Python groups only until the requested page is complete.
- One look-ahead group is used to set `has_more`.
- Full-library facets are not calculated during list loading.
- Facets in the response are limited to the current page and marked with `facets_scope = "current_page"`.
- The response source is now `sqlite-grouped-lazy`.

## Result

The MediaBrowser should show the first page immediately again. Scrolling continues to request the next page from the backend.

## Notes

Series grouping is still preserved for the loaded page. Complete series/season details remain available through the detail endpoints and can be optimized separately if needed.
