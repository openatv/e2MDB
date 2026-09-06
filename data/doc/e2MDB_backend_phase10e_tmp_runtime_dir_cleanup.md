# e2MDB backend phase10e - tmp runtime directory normalization

Date: 2026-05-31

## Problem

The backend runtime directory already uses the normalized lower-case path:

```text
/tmp/e2mdb
```

The legacy Enigma2 plugin globals still pointed temporary GUI data to:

```text
/var/volatile/tmp/e2MDB
```

On OpenATV this resolves into the volatile `/tmp` area and therefore creates an
additional `/tmp/e2MDB` directory. In the current backend architecture this
directory is not used by the daemon and can remain empty.

## Change

`e2MDB/__init__.py` now defines:

```python
TEMPDIR = "/tmp/e2mdb"
```

This makes GUI temporary data and backend runtime data use the same lower-case
runtime root. GUI cover previews still use a dedicated subdirectory:

```text
/tmp/e2mdb/covers
```

Backend files remain unchanged, for example:

```text
/tmp/e2mdb/status.json
/tmp/e2mdb/e2mdbd.sock
/tmp/e2mdb/prefill_request.json
```

## Result

A fresh start no longer creates the unused `/tmp/e2MDB` directory from e2MDB
plugin code. Existing empty directories can be removed manually or will disappear
automatically on reboot because `/tmp` is volatile.
