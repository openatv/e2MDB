# e2MDB Backend Phase 10d - OpenATV GUI Scheduler bridge validation

This phase validates and hardens the OpenATV GUI Scheduler bridge for e2MDB backend jobs.

Problem:

- OpenATV can create GUI Scheduler timers in `/etc/enigma2/scheduler.xml`.
- The provided OpenATV `Scheduler.py` supports `FunctionTimer` entries with `externalTask=True`.
- For external tasks, Enigma2 creates a Unix socket named:

      /tmp/scheduler_socket_<timerid>

  and waits for an external process to connect and report JSON status lines.
- `e2MDB Refresh` already used this external-task mode, but the daemon bridge was too loose and hard to diagnose.
- The daemon only watched sockets and resolved the function name through `/etc/enigma2/scheduler.xml`; there was no direct diagnostic command to verify GUI-created Scheduler timers.

Fix:

- `e2mdbd` now has explicit OpenATV GUI Scheduler parsing for `/etc/enigma2/scheduler.xml`.
- `e2MDB Refresh` / `e2MDB aktualisieren` timers are mapped to the backend job:

      scan_and_enrich

- GUI Scheduler-started refresh jobs now carry backend scheduler metadata:

      scheduler_job_id=openatv-gui-e2mdb-refresh
      scheduler_job_name=<OpenATV function name>
      openatv_timer_id=<timerid>
      openatv_timer_function=<function>

- The daemon socket watcher now retries briefly while resolving the timer from `scheduler.xml` and while connecting to the OpenATV Scheduler socket. This avoids losing a GUI timer because of a short file/socket race.
- Unsupported e2MDB function timers such as Live/EPG Prefill, Cleanup and SQLite Maintenance are not misrouted to the full media refresh.

New diagnostics:

```sh
python3 e2mdbctl.py scheduler e2gui
```

This reads `/etc/enigma2/scheduler.xml` through the daemon and reports:

- `timerid`
- `function`
- `timertype`
- `begin`
- `end`
- `repeated`
- `disabled`
- `supported_by_backend`
- `backend_job_id`
- `backend_job_type`

HTTP equivalent:

```text
GET /api/scheduler/e2gui
```

Expected OpenATV GUI timer flow:

1. The user creates a Scheduler timer in the Enigma2 GUI and selects `e2MDB Refresh` / `e2MDB aktualisieren`.
2. OpenATV writes the timer to:

       /etc/enigma2/scheduler.xml

3. At timer runtime, OpenATV `Scheduler.py` creates:

       /tmp/scheduler_socket_<timerid>

4. `e2mdbd` detects the socket, resolves `<timerid>` from `scheduler.xml`, confirms that the function is an e2MDB Refresh timer, connects to the socket and starts:

       scan_and_enrich

5. Backend progress and terminal state are sent back to OpenATV as JSON lines, so the OpenATV Scheduler can finish the function timer with success or error.

Validation after install:

```sh
cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py scheduler e2gui
```

If no GUI timer exists yet, the command should return an empty `timers` list and `exists` according to whether `/etc/enigma2/scheduler.xml` exists.
After creating a GUI timer for `e2MDB Refresh`, the command should show at least one item with:

```json
{
  "supported_by_backend": true,
  "backend_job_id": "openatv-gui-e2mdb-refresh",
  "backend_job_type": "scan_and_enrich"
}
```
