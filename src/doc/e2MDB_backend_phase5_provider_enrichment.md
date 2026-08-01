# e2MDB Backend Phase 5 - Provider Enrichment Job

## Goal

Phase 5 moves the internet metadata lookup into `e2mdbd` without putting it directly into every recording scan.

The recording scan remains a fast local filesystem/META/EIT/CUTS job. Internet metadata lookup is now a separate daemon job:

```text
recording_scan     -> local parser + SQLite import
metadata_enrich    -> provider lookup + artwork download + SQLite update
scan_and_enrich    -> scan first, then provider enrichment
```

This keeps scanner stability independent from internet/API/provider issues.

## New files

```text
e2MDB/E2MDBBackendProvider.py
doc/e2MDB_backend_phase5_provider_enrichment.md
```

## Changed files

```text
e2MDB/e2mdbd.py
e2MDB/e2mdbctl.py
e2MDB/E2MDBBackendClient.py
e2MDB/E2MDBBackendConfig.py
e2MDB/E2MDBBackendDatabase.py
```

## Persistent files

Provider job state is stored under:

```text
/etc/enigma2/e2mdb/provider_state.json
```

The database remains the single writer target:

```text
/media/hdd/e2MDB/results.db
```

or the custom path from:

```text
/etc/enigma2/e2mdb/settings.json
```

## Runtime status

Live progress remains in RAMFS:

```text
/tmp/e2mdb/status.json
```

During enrichment the GUI/API will see:

```text
phase: provider_prepare
phase: provider_lookup
phase: provider_done
```

## New CLI commands

```sh
python3 e2mdbctl.py metadata start [limit] [query]
python3 e2mdbctl.py metadata state
python3 e2mdbctl.py scan-enrich start [limit]
```

Examples:

```sh
python3 e2mdbctl.py metadata start 25
python3 e2mdbctl.py metadata start 10 Tatort
python3 e2mdbctl.py metadata state
python3 e2mdbctl.py scan-enrich start 50
```

## New HTTP API

```text
POST/GET /api/jobs/metadata/start?limit=100&query=
POST/GET /api/jobs/scan-enrich/start?limit=100
GET      /api/provider/state
```

Examples:

```sh
wget -qO- 'http://127.0.0.1:8088/api/jobs/metadata/start?limit=25'
wget -qO- 'http://127.0.0.1:8088/api/provider/state'
wget -qO- 'http://127.0.0.1:8088/api/jobs/scan-enrich/start?limit=50'
```

## Database additions

The database now contains provider result data:

```text
e2mdb_provider_matches
```

Additional `e2mdb_media` columns include:

```text
provider_lookup_status
provider_lookup_error
provider_lookup_updated
provider_best_json
artwork_poster_path
artwork_backdrop_path
artwork_logo_path
```

## Provider handling

The daemon uses the existing provider modules, but outside Enigma2.

Settings are read from:

```text
/etc/enigma2/e2mdb/settings.json
```

The Enigma2 GUI export still writes the provider keys/settings into this file.

Providers that require API keys are not queried if the key is empty. This prevents avoidable provider errors in a fresh test setup.

## Artwork

The provider job can download artwork returned by the selected provider result.

Default target:

```text
/media/hdd/e2MDB/artwork/recordings/<recording-id>/poster.jpg
/media/hdd/e2MDB/artwork/recordings/<recording-id>/backdrop.jpg
/media/hdd/e2MDB/artwork/recordings/<recording-id>/logo.png
```

Artwork download can be disabled in:

```json
{
  "artwork": {
    "download_enabled": false
  }
}
```

## Recommended box test

```sh
/etc/init.d/e2mdbd restart
sleep 2

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB

python3 e2mdbctl.py db status
python3 e2mdbctl.py metadata state
python3 e2mdbctl.py metadata start 5
cat /tmp/e2mdb/status.json
python3 e2mdbctl.py metadata state
python3 e2mdbctl.py db status
```

If API keys are missing, the job should still finish cleanly but report provider lookup errors/no matches instead of blocking Enigma2.

## Combined test

```sh
python3 e2mdbctl.py scan-enrich start 10
cat /tmp/e2mdb/status.json
python3 e2mdbctl.py history
```

## Notes

This is not yet the final MediaBrowser migration. Phase 5 creates the backend metadata foundation first.
The next phase can switch MediaBrowser list/detail views to the daemon API/SQLite metadata fields.
