# e2MDB Live/EPG metadata extension

This document describes the current long-term test state of the Live/EPG metadata extension for e2MDB on OpenATV.

## Architecture decision

The extension uses one shared e2MDB database file, but Live/EPG data is stored in dedicated tables. Recording and media-file metadata remain separate from short-lived EPG/live metadata.

Core concepts:

- Recordings and media files remain long-lived.
- Live/EPG events are short-lived and retention-controlled.
- Provider results and assets can be reused by recordings, media files, EPG and live TV.
- Provider lookups never run directly in EPG/ChannelSelection list rendering.
- Queue/worker processing is controlled through the existing e2MDB provider logic.

## Title translation search fallback

The optional Google title translation setting is only a provider-search helper. e2MDB first searches providers with the original title and all normal title variants. If that returns no usable result, only the title is translated once with Google into the configured Google title translation target language and the provider search is retried with that temporary title.

The translated title is not written to SQLite, JSON metadata, provider assets, skin sources or cache files. There is no translation backfill task and no translated metadata database schema. The target language only controls this one temporary fallback search query.

## Implemented components

### Database

Additional Live/EPG tables are created in the shared e2MDB database:

- `e2mdb_epg_events`
- `e2mdb_fetch_queue`
- `e2mdb_provider_assets`
- `e2mdb_epg_event_asset_map`
- `e2mdb_channel_stats`
- `e2mdb_cleanup_state`

Manual prefill channel selection is stored outside `/etc/enigma2/settings`:

- `/etc/enigma2/e2mdb/prefill_services.json`

Prefill no-EPG cooldown state is stored in:

- `/etc/enigma2/e2mdb/prefill_state.json`

### EPG integration

GraphicalEPG/EPGSelection is hooked and now:

- detects selected EPG events,
- stores Live/EPG candidates in the DB,
- reads existing metadata immediately,
- queues missing metadata with bounded priority,
- exposes e2MDB skin sources.

### EventView integration

EventView is hooked and now:

- exposes e2MDB skin sources,
- shows cached cover/text metadata,
- can trigger ad-hoc lookup for the displayed event,
- updates the skin sources after the ad-hoc worker completes.

### ChannelSelection integration

ChannelSelection is hooked and now:

- reads the selected service,
- resolves the current event via existing sources/EPG cache,
- exposes e2MDB skin sources for the selected service/event,
- queues missing data with lower priority,
- does not start provider lookups while scrolling.

### InfoBar integration

InfoBar is hooked and now:

- exposes e2MDB skin sources,
- shows metadata for the current live event,
- can update immediately with delay `0`,
- clears stale metadata before updating when configured,
- queues missing metadata without blocking zapping.

### Worker

The Live/EPG worker processes `e2mdb_fetch_queue` entries and uses the existing e2MDB provider search. It updates event status, JSON paths, confidence and provider asset links.

Supported terminal states include:

- `done`
- `no_match`
- `ignored`
- `short_skipped`
- `ended_skipped`
- `failed`

### Prefill

Prefill can enqueue future EPG events for manually selected channels and preferred zap-history channels. The prefill horizon is configured in days (`Live/EPG prefill days`, range 1-7). For each selected/preferred channel, prefill walks the EPG forward event-by-event up to `Maximum events per prefill service`, while `Maximum prefill events` remains the global safety cap per run.

Scheduling is handled through the OpenATV task/timer menu:

- `e2MDB Live/EPG Prefill`

The internal automatic prefill timer and standby/night/idle mode selection are not used in the long-term test build. The OpenATV task/timer menu decides when the task runs.

Prefill uses `lookupEventTime()` step-by-step on the Enigma2 main loop. This avoids native crashes seen with bulk `lookupEvent()` calls and worker-thread EPG cache access. It does not start provider lookups directly; it only inserts/updates EPG events and fetch-queue rows. The normal Live/EPG worker processes those queued events afterwards.

### Cleanup

Cleanup removes expired Live/EPG DB rows, old queue entries and stale prefill-state data. Scheduling is handled through the OpenATV task/timer menu:

- `e2MDB Live/EPG Cleanup`
- `e2MDB SQLite Maintenance`

The internal automatic cleanup timer is not used in the long-term test build.

Primary EPG cache file cleanup is optional and disabled by default. Shared provider assets such as `series/`, `season/` and `index/` are not removed by Live/EPG cleanup. The cleanup reference checks also include `image_path` so horizontal fallback artwork from fernsehserien.de or Wikimedia/Wikipedia is not removed while it is still referenced.

SQLite maintenance can run after cleanup or as a separate task. `ANALYZE` refreshes query statistics, `VACUUM` shrinks the SQLite files after deletions, and `REINDEX` is optional and normally disabled. A weekly night task is recommended for VACUUM-heavy maintenance on slow boxes.

### Tools menu

In the e2MDB setup, the Menu key opens Live/EPG tools:

- Live/EPG worker queue
- Live/EPG cleanup status
- Prefill status / diagnostics
- Ignored EPG title patterns
- Ignored service name patterns

Green remains Save in the main setup.

## Skin sources

The following screen sources are available in InfoBar, GraphicalEPG, EventView and ChannelSelection detail screens:

- `e2mdb_title`
- `e2mdb_subtitle`
- `e2mdb_overview`
- `e2mdb_infoline`
- `e2mdb_status`
- `e2mdb_provider`
- `e2mdb_media_type`
- `e2mdb_genres`
- `e2mdb_runtime`
- `e2mdb_rating`
- `e2mdb_year`
- `e2mdb_source_key`
- `e2mdb_search_title`
- `e2mdb_json_path`
- `e2mdb_cover`
- `e2mdb_backdrop`
- `e2mdb_titlelogo`
- `e2mdb_image`

Use `E2MDBPixmap` for image sources:

```xml
<widget source="e2mdb_cover" render="E2MDBPixmap" position="850,215" size="140,200" alphatest="blend" scaleFlags="centerScaled" transparent="1" />
```

## Known limitation

Direct e2MDB images inside `serviceList` template entries were tested and are intentionally disabled for long-term testing. Native service list pixmap handling proved unstable on the test box. Keep normal `Picon` entries in `serviceList` templates and use the screen sources outside the list for preview panels.

## Recommended long-term test defaults

Suggested settings:

- Debug log: Off
- Enable Live/EPG metadata cache: Yes
- Enable InfoBar metadata: Yes
- Enable ChannelSelection metadata: Yes
- ServiceList preview mode: Backdrop preview
- Enable Live/EPG prefill: Yes, if selected channels are configured
- Use Google title translation as search fallback: Off by default; enable only when original titles regularly miss provider results
- Google title translation target language: Target language for the temporary fallback search query only
- SQLite cleanup VACUUM: Yes
- SQLite cleanup REINDEX: No

Worker timing, queue delays, ad-hoc behavior, cleanup intervals and other GUI
tuning details are fixed internal defaults now. They are intentionally not
exposed as hidden Enigma2 settings anymore.

Use the OpenATV task/timer menu for scheduled prefill and cleanup.

## Useful diagnostics

Queue summary:

```sh
sqlite3 /media/hdd/e2MDB/results.db "
SELECT state, reason, priority, COUNT(*)
FROM e2mdb_fetch_queue
GROUP BY state, reason, priority
ORDER BY priority DESC, state, reason;
"
```

Recent prefill queue entries:

```sh
sqlite3 /media/hdd/e2MDB/results.db "
SELECT q.state, q.priority, q.reason, q.title, e.service_name, e.status,
       datetime(q.begin_time, 'unixepoch', 'localtime') AS begin, q.attempts
FROM e2mdb_fetch_queue q
LEFT JOIN e2mdb_epg_events e ON e.source_key = q.source_key
WHERE q.reason LIKE 'prefill%'
ORDER BY q.updated_at DESC
LIMIT 30;
"
```

Recent Live/EPG events:

```sh
sqlite3 /media/hdd/e2MDB/results.db "
SELECT service_name, title, search_title, status,
       datetime(begin_time, 'unixepoch', 'localtime') AS begin,
       datetime(updated_at, 'unixepoch', 'localtime') AS updated
FROM e2mdb_epg_events
ORDER BY updated_at DESC
LIMIT 30;
"
```

Manual prefill services:

```sh
python3 - <<'PY'
import json
p='/etc/enigma2/e2mdb/prefill_services.json'
data=json.load(open(p))
print(len(data.get('services', [])))
PY
```

Prefill no-EPG state:

```sh
cat /etc/enigma2/e2mdb/prefill_state.json
```

## Current test status

Stable in long-term test scope:

- InfoBar metadata display
- GraphicalEPG metadata display
- EventView metadata display and ad-hoc lookup
- ChannelSelection detail metadata display
- Worker queue processing
- Manual prefill request
- Prefill via OpenATV task/timer menu
- Cleanup via OpenATV task/timer menu
- Worker queue diagnostics
- Prefill and cleanup diagnostics

Disabled/deferred:

- e2MDB images inside native `serviceList` entries
