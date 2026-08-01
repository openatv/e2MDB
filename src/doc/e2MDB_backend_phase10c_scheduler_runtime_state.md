# e2MDB Backend Phase 10c - Scheduler runtime state and manual-run hardening

This phase hardens the daemon scheduler after restoring the default jobs in Phase 10b.

Problem:

- `daily-media-refresh` can be started manually through:

      python3 e2mdbctl.py scheduler run daily-media-refresh

- The previous scheduler state mostly stored the start attempt, not the final job result.
- Direct `scheduler list`, `scheduler status` or `scheduler run` immediately after daemon start/reload could still depend on the scheduler thread having already loaded the config.
- Manual scheduler runs could not override small test limits from the CLI.

Fix:

- `scheduler list`, `scheduler status` and `scheduler run` now synchronously load the scheduler config if the scheduler thread has not loaded it yet or a reload is pending.
- The daemon persists repaired scheduler defaults when it loads and merges `scheduler.json`.
- Scheduler-started backend jobs now carry:

      scheduler_job_id
      scheduler_job_name

  into `/tmp/e2mdb/status.json` and `/etc/enigma2/e2mdb/job_history.json`.

- `/etc/enigma2/e2mdb/scheduler_state.json` now stores more useful lifecycle data per scheduler job:

      last_attempt
      last_start_result
      last_run
      last_started
      last_finished
      last_backend_job_id
      last_state
      last_message
      last_percent
      last_duration_seconds
      last_success / last_error_time

- Rejected manual starts, for example while another backend job is running, are stored as `skipped` with `last_error`.
- `scheduler list` now reports `due` and `due_reason` for each job, so diagnostics show why a job is or is not currently due.

CLI extension:

```sh
python3 e2mdbctl.py scheduler run <job-id> [limit|all] [only-missing|all-items] [query]
```

Examples:

```sh
python3 e2mdbctl.py scheduler run daily-media-refresh
python3 e2mdbctl.py scheduler run daily-media-refresh 10 only-missing
python3 e2mdbctl.py scheduler run daily-media-refresh all all-items
python3 e2mdbctl.py scheduler run daily-media-refresh 25 "Tatort"
```

The default `daily-media-refresh` behavior remains unchanged unless CLI overrides are passed.

Validation after install:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py scheduler reload
python3 e2mdbctl.py scheduler list
python3 e2mdbctl.py scheduler run daily-media-refresh 5 only-missing
python3 e2mdbctl.py status
python3 e2mdbctl.py history
python3 e2mdbctl.py scheduler status
```
