# e2MDB Backend Phase 9c - Live/EPG Backend Proxy

This phase keeps the existing v16 Live/EPG producers in Enigma2, but moves the
worker trigger path to the backend daemon.

## Changed behaviour

- Enigma2 still creates Live/EPG queue entries in `e2mdb_fetch_queue`.
- Enigma2 no longer starts the heavy Live/EPG provider worker when backend mode is enabled.
- `E2MDBEPGWorker.start_epg_worker_manager()` now creates a thin backend proxy by default.
- The proxy only promotes ad-hoc queue items and asks `e2mdbd` to process the queue.
- Provider lookup, artwork download and DB writes run in `e2mdbd`.

## Settings

The exported backend settings now contain:

```json
"live_epg": {
  "backend_worker_enabled": true,
  "backend_ad_hoc_enabled": true,
  "backend_batch_limit": 25,
  "backend_interval_seconds": 30,
  "backend_ad_hoc_poll_seconds": 1
}
```

Set `backend_worker_enabled` to `false` only for debugging the old Enigma2
worker path.

## Tests

Restart daemon and Enigma2 GUI:

```sh
/etc/init.d/e2mdbd restart
init 4
sleep 3
init 3
```

Check queue:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py live-queue status
python3 e2mdbctl.py live-queue list 20 all
```

When the GUI creates Live/EPG queue entries, `e2mdbd` should process them on the
next proxy tick.

Manual trigger still works:

```sh
python3 e2mdbctl.py live-worker start 25
```

## Notes

This is not a rewrite of the v16 EPG producer logic. InfoBar, EventView,
ChannelSelection and Prefill still create candidates as before. Only the worker
execution path is redirected to the backend daemon.
