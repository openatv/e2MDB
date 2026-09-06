# e2MDB Backend Phase 8d - Worker queue status

This phase adds a backend queue/status inspection endpoint.

The current backend still uses a single worker model. That means there is no multi-job backlog yet: while one job is running, additional jobs are rejected with `job already running`. The queue endpoint therefore reports the current worker state, the active job, and a `pending_jobs` list which is normally empty except during the short queued startup state.

## CLI

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py queue
```

## HTTP

```sh
wget -qO- http://127.0.0.1:8088/api/jobs/queue
echo
```

## Existing related checks

```sh
python3 e2mdbctl.py status
python3 e2mdbctl.py history
wget -qO- http://127.0.0.1:8088/api/jobs/current
echo
wget -qO- http://127.0.0.1:8088/api/jobs/history
echo
```
