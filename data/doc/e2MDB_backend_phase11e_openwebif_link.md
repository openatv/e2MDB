# e2MDB Backend Phase 11e - OpenWebif Link to Backend Web UI

## Goal

The old e2MDB OpenWebif child no longer exposes a local Twisted resource tree from the Enigma2 plugin process.
The backend daemon now owns the web UI on port 8088.

OpenWebif should only show a small external link to the backend web UI.

## Implementation

The OpenWebif registration now lives directly in `plugin.py`:

```python
addExternalChild(("http://localhost:8088/", None, "e2MDB", __version__, True, ""))
```

This keeps Enigma2 lightweight:

- no old web API resources in the Enigma2 plugin process
- no DB/provider/browser work through the old OpenWebif child
- OpenWebif only acts as an entry point to the backend web UI

## Removed

`E2MDBWeb.py` was removed from the package because it represented the old OpenWebif-hosted API/web resource path.
The backend web assets remain in the package and are served by `e2mdbd`.
