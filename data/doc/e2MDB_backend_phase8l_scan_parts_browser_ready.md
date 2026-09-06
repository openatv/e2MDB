# e2MDB Backend Phase 8l - scan parts and MediaBrowser ready filter

## Changes

- `scan_and_enrich` now reports one global progress value across three parts:
  - Part 1/3: media file scan and TS META/EIT/CUTS parsing
  - Part 2/3: SQLite import
  - Part 3/3: provider lookup and artwork handling
- The Enigma2 scanner screen displays the part number in the progress header/status.
- `e2mdb_media.browser_ready` was added.
- `browser_ready` is reset to `0` during scan import for touched items.
- `browser_ready` is set to `1` only after provider enrichment wrote a final result for that item.
- MediaBrowser list endpoints hide entries with `browser_ready != 1` by default.
- Debug calls can still include pending entries via `include_pending=1` or `browser list-all`.

## Test commands

```sh
/etc/init.d/e2mdbd restart
sleep 2

cd /usr/lib/enigma2/python/Plugins/Extensions/e2MDB
python3 e2mdbctl.py db status
python3 e2mdbctl.py scan-enrich start all
cat /tmp/e2mdb/status.json
```

Browser-ready DB check:

```sh
DB="/media/hdd/e2MDB/results.db"
sqlite3 -header -column "$DB" "select file_name,browser_ready,provider_lookup_status,metadata_title,artwork_poster_path from e2mdb_media limit 30;"
```

Normal browser list, ready entries only:

```sh
python3 e2mdbctl.py browser list 20
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=20' | python3 -m json.tool
```

Debug list, includes pending scan/import rows:

```sh
python3 e2mdbctl.py browser list-all 20
wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=20&include_pending=1' | python3 -m json.tool
```
