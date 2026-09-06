# e2MDB Backend Phase 10a - Daemon Scheduler / Cron basis

This phase adds a daemon-side scheduler that reads persistent job definitions from:

    /etc/enigma2/e2mdb/scheduler.json

The scheduler runs inside `e2mdbd`, outside the Enigma2 main process. It does not replace the existing Enigma2 power/scheduler UI yet; it is the clean backend job engine for scan, metadata, and live/EPG queue processing.

Supported job types:

- `recording_scan`
- `scan_and_enrich`
- `metadata_enrich`
- `live_epg_worker`

Example `/etc/enigma2/e2mdb/scheduler.json`:

```json
{
  "version": 1,
  "enabled": true,
  "check_interval_seconds": 30,
  "jobs": [
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
    },
    {
      "id": "live-queue-every-15min",
      "enabled": false,
      "type": "live_epg_worker",
      "interval_minutes": 15,
      "options": {
        "limit": 25
      }
    }
  ]
}
```

State is persisted in:

    /etc/enigma2/e2mdb/scheduler_state.json

Runtime state is also published into:

    /tmp/e2mdb/status.json

CLI:

    python3 e2mdbctl.py scheduler status
    python3 e2mdbctl.py scheduler list
    python3 e2mdbctl.py scheduler reload
    python3 e2mdbctl.py scheduler run daily-media-refresh

HTTP API:

    /api/scheduler/status
    /api/scheduler/list
    /api/scheduler/reload
    /api/scheduler/run?id=daily-media-refresh

Cron can also use the existing CLI or API, for example:

    python3 /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scheduler run daily-media-refresh

or:

    wget -qO- 'http://127.0.0.1:8088/api/scheduler/run?id=daily-media-refresh'

The daemon scheduler respects the single-worker rule. If another backend job is running, the scheduled job is skipped for that check and can run at the next interval/time depending on its definition.
