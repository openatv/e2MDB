# e2MDB Backend Phase 9a - Live/EPG Queue API

This phase does not rewrite the existing v16 Live/EPG worker.

It exposes the existing `e2mdb_fetch_queue` through the backend daemon so the queue can be inspected and maintained without opening SQLite manually. This is the first safe step before moving the Live/EPG worker itself out of Enigma2.

## New CLI commands

```sh
python3 e2mdbctl.py live-queue status
python3 e2mdbctl.py live-queue list 50 all
python3 e2mdbctl.py live-queue list 50 pending
python3 e2mdbctl.py live-queue list 50 running
python3 e2mdbctl.py live-queue list 50 all "Tatort"
python3 e2mdbctl.py live-queue reset-running
```

## New HTTP endpoints

```text
GET /api/live/queue/status
GET /api/live/queue/list?limit=50&state=all&q=
GET /api/live/queue/reset-running
```

## Scope

- Uses the existing v16 queue table: `e2mdb_fetch_queue`.
- Does not change InfoBar, EventView, ChannelSelection, or EPG worker behavior.
- Does not move provider lookups for Live/EPG yet.
- Adds only diagnostics and a safe reset for interrupted `running` rows.

## Why this step

The next migration step can move Live/EPG worker processing to the daemon. Before that, the queue must be visible from the backend so queue pressure, failed rows and pending rows can be diagnosed quickly.
