# e2MDB backend phase 2 - native recording parser

## Scope

This phase adds a standalone native parser for Enigma2 recording sidecar files.
The daemon does not import `enigma` and does not use `eServiceCenter`,
`eServiceReference` or `iServiceInformation`.

The parser is built as a Python C extension:

```text
e2MDB/native/e2mdb_recordingparser.c
```

Python glue:

```text
e2MDB/E2MDBRecordingParser.py
```

Daemon integration:

```text
e2MDB/e2mdbd.py
```

## Parsed files

For a recording path like:

```text
/media/hdd/movie/example.ts
```

The native parser reads:

```text
/media/hdd/movie/example.ts.meta
/media/hdd/movie/example.eit
/media/hdd/movie/example.ts.cuts
/media/hdd/movie/example.txt
```

This follows the Enigma2 recording sidecar model used by the PVR service code.

## Output

`parse_recording(path)` returns a dictionary with:

```text
path
exists
meta
 eit
cuts
txt
```

The daemon maps the parsed result into a scan item with:

```text
title
description
extended_description
service_ref
meta
eit
cuts
txt
```

## No Python parser fallback

There is intentionally no legacy scanner fallback and no Python META/EIT/CUTS
fallback in the daemon path. If the native extension is missing, the daemon scan
job fails with a clear error.

This keeps the clean-start architecture strict:

- daemon owns recording scan
- native parser owns sidecar parsing
- Enigma2 only provides GUI and live context

## Build

The root `setup.py` now defines this extension module:

```text
Extensions.e2MDB._e2mdb_recordingparser
```

It is built from:

```text
e2MDB/native/e2mdb_recordingparser.c
```

The ZIP contains the C source, not an architecture-specific `.so` file. The
extension must be built by the image/plugin build environment for the target CPU.
