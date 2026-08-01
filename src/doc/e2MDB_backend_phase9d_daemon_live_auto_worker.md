# e2MDB Backend Phase 9d - Daemon Live/EPG Auto Worker

This phase keeps the v16 Live/EPG producers unchanged. Enigma2 still creates rows in `e2mdb_fetch_queue`.

The daemon now has a lightweight auto worker loop that checks the queue periodically and starts small backend batches only when the main backend worker is idle. This prevents Live/EPG internet/provider work from running in the Enigma2 process while avoiding a permanent parallel writer.

## New settings

Stored in `/etc/enigma2/e2mdb/settings.json` under `live_epg`:

```json
{
  "daemon_auto_worker_enabled": true,
  "daemon_worker_batch_limit": 25,
  "daemon_worker_interval_seconds": 30,
  "daemon_reset_running_on_start": true
}
```

## New commands

```sh
python3 e2mdbctl.py live-worker status
python3 e2mdbctl.py live-queue status
python3 e2mdbctl.py live-queue list 50 pending
```

## New HTTP endpoint

```text
/api/live/worker/status
```

The manual start/stop commands from phase 9b remain available.
