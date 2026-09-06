# e2MDB Backend Phase 10b - Scheduler default job restore

This phase restores the scheduler defaults from the Phase 10a design into the runtime initialization path.

Problem:

- `doc/e2MDB_backend_phase10a_daemon_scheduler.md` documents the manual test command:

      python3 e2mdbctl.py scheduler run daily-media-refresh

- The daemon and Enigma2 backend config helper created `/etc/enigma2/e2mdb/scheduler.json` with an empty `jobs` list.
- On boxes where that empty file already existed, `scheduler run daily-media-refresh` returned:

      scheduler job not found

Fix:

- `daily-media-refresh` is now restored as the default scan/enrich scheduler job.
- `live-queue-every-15min` is also restored from the Phase 10a example, but remains disabled by default.
- Existing user jobs are preserved.
- If an existing `scheduler.json` is empty or misses one of the default IDs, the missing default job is appended.
- The daemon-side scheduler also merges defaults when loading the scheduler configuration, so manual reloads see the same restored defaults.

Default jobs:

```json
{
  "id": "daily-media-refresh",
  "enabled": true,
  "type": "scan_and_enrich",
  "time": "03:30",
  "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  "options": {
    "limit": 0,
    "only_missing": false
  }
}
```

```json
{
  "id": "live-queue-every-15min",
  "enabled": false,
  "type": "live_epg_worker",
  "interval_minutes": 15,
  "options": {
    "limit": 25
  }
}
```

Validation after install:

```sh
python3 /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scheduler reload
python3 /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scheduler list
python3 /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scheduler run daily-media-refresh
```
