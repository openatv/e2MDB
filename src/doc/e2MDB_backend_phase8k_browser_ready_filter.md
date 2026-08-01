# e2MDB Backend Phase 8k - MediaBrowser Ready-Only Filter

This phase changes the backend MediaBrowser visibility model.

The filesystem/media scan is phase 1 and imports raw media rows quickly. Those rows are not complete yet. Provider enrichment is phase 2 and fills title, metadata, artwork and provider state.

The MediaBrowser now hides rows whose provider enrichment is not completed yet. By default only rows with:

    provider_lookup_status = 'done'

are returned by the MediaBrowser list endpoints.

This prevents the Web UI and Enigma2 GUI from showing half-built cards without cover/backdrop while scan_and_enrich is still running.

## Visible MediaBrowser view

    python3 e2mdbctl.py browser list 20
    wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=20'
    wget -qO- 'http://127.0.0.1:8088/api/results?action=browser_list&limit=20&page=1'

The response contains:

    "visibility": "ready_only"
    "source": "sqlite-grouped-lazy-ready-only"

## Debug / include pending rows

For debugging only:

    python3 e2mdbctl.py browser list-all 20
    wget -qO- 'http://127.0.0.1:8088/api/browser/list?limit=20&include_pending=1'
    wget -qO- 'http://127.0.0.1:8088/api/results?action=browser_list&limit=20&page=1&include_pending=1'

The response contains:

    "visibility": "all"
    "source": "sqlite-grouped-lazy-all"

## Status counts

    python3 e2mdbctl.py browser status
    python3 e2mdbctl.py db status
    python3 e2mdbctl.py metadata state

Browser status now reports:

    total_visible
    total_raw
    hidden_pending
    provider_counts

This makes it clear why the MediaBrowser may temporarily show fewer cards while scan_and_enrich is still running.
