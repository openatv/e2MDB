# e2MDB Backend Phase 9e - Live/EPG Display Cache

This phase keeps the v16 Live/EPG producers and the Enigma2 display path intact.

The daemon Live/EPG worker now writes provider results not only to the backend media cache, but also to the v16 display cache tables used by the Enigma2 GUI:

- `e2mdb_epg_events`
- `e2mdb_provider_assets`
- `e2mdb_epg_event_asset_map`

This is important because the GUI/skin code reads Live-TV and EPG metadata from `e2mdb_epg_events`. Writing only `e2mdb_media` was not enough for live/ad-hoc display updates.

## New API endpoints

```text
/api/live/result?source_key=<source_key>
/api/live/results?limit=50&q=<query>
```

## New CLI commands

```sh
python3 e2mdbctl.py live-result <source_key>
python3 e2mdbctl.py live-results 50
python3 e2mdbctl.py live-results 50 Tatort
```

## Result flow

```text
InfoBar/EventView/ChannelSelection
  -> e2mdb_fetch_queue
  -> e2mdbd Live/EPG worker
  -> provider/artwork lookup
  -> e2mdb_epg_events metadata columns
  -> e2mdb_provider_assets + link map
  -> Enigma2 GUI reads the v16 display cache
```

The daemon still keeps `source_type = live_epg` rows out of the MediaBrowser by forcing `browser_ready = 0` for those transient cache entries.

## Test

```sh
/etc/init.d/e2mdbd restart

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py live-queue status
python3 e2mdbctl.py live-worker start 5
python3 e2mdbctl.py live-results 20
```

For one source key:

```sh
python3 e2mdbctl.py live-result '<source_key>'
```
