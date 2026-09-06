# e2MDB Backend Phase 8w - Episode playback restore

This patch restores episode play/stop behavior without changing the v16 MediaBrowser flow.

Changes:

- Episode cards now keep `media_hash` and `file_path` in addition to the visible metadata.
- Episode play buttons prefer `media_hash`, then `id`, then `file_path`.
- Episode stop buttons are always wired, even if an episode has no playable id.
- `season_details` returns explicit playback identifiers per local episode.
- The backend playback lookup can still resolve both media hash and file path.

The fix is intentionally small and does not rebuild the MediaBrowser logic.
