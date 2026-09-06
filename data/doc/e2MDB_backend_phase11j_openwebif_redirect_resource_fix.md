# e2MDB Backend Phase 11j - OpenWebif Redirect Resource Fix

OpenWebif cannot register an external child with `child=None`. During OpenWebif root tree creation this makes Twisted fail in `putChild()` with:

```text
AttributeError: 'NoneType' object has no attribute 'server'
```

The e2MDB OpenWebif integration now registers a real Twisted resource under:

```text
/e2mdb
```

The resource redirects the browser to the backend web UI on port `8088` using the same host that was used to open OpenWebif:

```text
http://<box-host>:8088/
```

This keeps OpenWebif as a simple entry point only. The real e2MDB Web UI remains served by the backend daemon.
