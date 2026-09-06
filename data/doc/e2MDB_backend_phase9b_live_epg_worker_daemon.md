# e2MDB Backend Phase 9b - Live/EPG queue worker in daemon

This phase keeps the existing v16 Enigma2 Live/EPG producers unchanged.
InfoBar, EventView and ChannelSelection still create rows in `e2mdb_fetch_queue`.

New in this phase:

- `e2mdbd` can process pending `e2mdb_fetch_queue` rows manually.
- Provider lookup and artwork download for these Live/EPG rows can run outside the Enigma2 main process.
- Live/EPG result rows are stored as `source_type = live_epg` and kept out of the MediaBrowser with `browser_ready = 0`.
- The old v16 worker is not removed yet. This is a controlled migration step.

CLI:

```sh
python3 e2mdbctl.py live-queue status
python3 e2mdbctl.py live-queue list 50 pending
python3 e2mdbctl.py live-worker start 25
python3 e2mdbctl.py live-worker stop
```

HTTP:

```text
/api/live/queue/status
/api/live/queue/list?limit=50&state=pending
/api/live/queue/reset-running
/api/live/worker/start?limit=25
```

Important:

This worker is intentionally not started automatically yet. During testing, do not run the old Enigma2 Live/EPG worker and the backend Live/EPG worker at the same time for the same queue if you want deterministic diagnostics.
