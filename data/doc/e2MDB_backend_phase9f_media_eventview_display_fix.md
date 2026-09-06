# e2MDB Backend Phase 9f - Media/EventView Display Metadata Fix

This phase restores metadata lookup for local media screens after moving scan/provider work to the daemon.

## Fixed

- The daemon now creates media ids with the v16 compatible hash: `md5(reduced_media_path)`.
- `E2MDBEventViewSimple` can fall back from hash lookup to file path lookup.
- Existing rows from earlier backend test builds can still be displayed if the file path matches.
- New scans will use the same hash that the v16 GUI screens expect.

## Why

The original GUI code uses `E2MDBHelper.get_reduced_org_hash()`. Early backend test phases used `sha1(abs_path)`, so provider data existed in SQLite but MediaView/EventView could not find it.

## Recommended after install

Restart daemon and GUI:

```sh
/etc/init.d/e2mdbd restart
init 4
sleep 3
init 3
```

For a clean test, run a full scan/provider refresh afterwards so all rows get v16-compatible hashes.
