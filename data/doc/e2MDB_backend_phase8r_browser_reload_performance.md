# e2MDB Backend Phase 8r - MediaBrowser reload/performance cleanup

Fixes:

- Browser page refresh now restores the last active tab instead of always returning to Editor.
- When the active tab is MediaBrowser, the Editor list is no longer loaded first.
- MediaBrowser keeps a short session snapshot and paints cached cards immediately after a page refresh.
- Automatic multi-page viewport preloading was disabled. The list now loads the first page and continues on scroll or via the load-more button.
- Additional SQLite indexes were added for MediaBrowser queries and especially the `e2mdb_recordings.media_hash` join.

Install, restart the daemon, then hard-refresh the web page once.
