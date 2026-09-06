# e2MDB Backend Phase 10u - Artwork Provenance and Debug Provider JSON

## Goal

Live/EPG artwork must be traceable after provider processing. When a wrong
still/image/backdrop appears in the GUI, the backend must be able to show which
provider result, source URL and local file produced the final display fields.

## Changes

- Provider result JSON is written to the per-source artwork folder while debug
  logging is enabled.
- When debug logging is disabled, the provider result JSON is removed/omitted.
- Live/EPG event rows now keep `json_path` for the provider result JSON.
- Provider asset rows now store original source URLs:
  - `cover_url`
  - `backdrop_url`
  - `logo_url`
  - `image_url`
  - `episode_url`
  - `series_poster_url`
  - `series_backdrop_url`
  - `artwork_json`
- `live-result` artwork diagnostics now include local paths and source URLs.
- New diagnostic command:

```sh
python3 e2mdbctl.py live-artwork <source_key>
```

## Debug JSON behaviour

Debug on:

```text
/media/hdd/e2MDB/artwork/recordings/<source_key>/provider_result.json
```

Debug off:

```text
provider_result.json is not kept and existing debug JSON for that source is removed
```

## Artwork root

The current backend provider uses:

```text
/media/hdd/e2MDB/artwork/recordings/<source_key>/
```

Despite the folder name, this is currently also used for Live/EPG provider
artwork. The name is legacy/misleading and can be split later into cleaner
subfolders, for example:

```text
artwork/live_epg/<source_key>/
artwork/recordings/<recording_id>/
artwork/provider_assets/<provider>/<provider_id>/
```

