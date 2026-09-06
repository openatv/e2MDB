# e2MDB backend phase 1 clean-start

This package starts the backend split without a compatibility layer.

## Added files

- `e2MDB/e2mdbd.py` - standalone backend daemon scaffold.
- `e2MDB/e2mdbctl.py` - small Unix socket CLI helper.
- `e2MDB/E2MDBBackendConfig.py` - central JSON configuration helper.
- `e2MDB/E2MDBBackendClient.py` - Enigma2-side backend command client.
- `init.d/e2mdbd` - init.d service script.

## Persistent JSON directory

All persistent e2MDB JSON configuration files are now placed below:

```text
/etc/enigma2/e2mdb/
```

Examples:

```text
/etc/enigma2/e2mdb/settings.json
/etc/enigma2/e2mdb/paths.json
/etc/enigma2/e2mdb/prefill_services.json
/etc/enigma2/e2mdb/prefill_state.json
/etc/enigma2/e2mdb/ignore_epg_titles.json
/etc/enigma2/e2mdb/ignore_service_names.json
/etc/enigma2/e2mdb/ignore_folder_names.json
```

## Runtime directory

Runtime and progress files are placed below:

```text
/tmp/e2mdb/
```

Examples:

```text
/tmp/e2mdb/status.json
/tmp/e2mdb/e2mdbd.sock
/tmp/e2mdb/last_recording_scan.json
```

## Scheduler bridge

The `e2MDB Refresh` FunctionTimer is registered as an external Scheduler task.
The backend daemon watches `/tmp/scheduler_socket_*`, resolves the timer id through `/etc/enigma2/scheduler.xml`, connects to the Scheduler socket and sends JSON progress lines.

The first implemented external job is a lightweight recording scan scaffold. It walks configured paths, reads `.ts`/video files, detects `.meta` and `.eit` sidecar files and writes progress to `/tmp/e2mdb/status.json`.

Provider lookup, DB single-writer migration and full META/EIT import are intentionally the next steps.

## init.d

Start/stop manually:

```sh
/etc/init.d/e2mdbd start
/etc/init.d/e2mdbd stop
/etc/init.d/e2mdbd restart
/etc/init.d/e2mdbd status
```

The service script expects the plugin at:

```text
/usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbd.py
```

## CLI

```sh
python /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py status
python /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scan start
python /usr/lib/enigma2/python/Plugins/Extensions/e2MDB/e2mdbctl.py scan stop
```
