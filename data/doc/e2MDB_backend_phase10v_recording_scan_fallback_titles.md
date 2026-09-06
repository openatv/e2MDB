e2MDB Backend Phase 10v - Recording Scan Fallback and OpenATV Title Cleanup
=========================================================================

Problem
-------

A debug bundle from SF8008 showed that the media refresh did scan the configured
path successfully, but all six TS recordings were marked as scan errors.

The relevant diagnostics were:

- /etc/enigma2/e2mdb/paths.json had one active scan path:
  /media/hdd/movie
- scan paths count found six TS recordings.
- last_recording_scan.json contained six parse errors:
  native recording parser extension is not available: No module named '_e2mdb_recordingparser'
- provider enrichment searched titles that still contained the OpenATV recording
  filename prefix:
  YYYYMMDD HHMM - Service Name - Event Title

This made valid recordings fail after the backend-only scan path was introduced.

Changes
-------

1. The native TS recording parser is now optional.

If the parser or its native extension is unavailable, the daemon falls back to a
filename/path based scan item and records the parser problem as parse_warning,
not parse_error.

This keeps the scan usable on boxes where the native parser extension is not
installed yet.

2. OpenATV recording filename prefixes are stripped before provider lookup.

Example:

    20260406 0942 - SPORT1 - Hunde außer Kontrolle - Ein Coach für alle Felle S01E02 Der aggressive Collie.ts

becomes:

    Hunde außer Kontrolle - Ein Coach für alle Felle S01E02 Der aggressive Collie

The provider title for series is then derived from the cleaned title:

    Hunde außer Kontrolle - Ein Coach für alle Felle

3. Filename-only TS scan items are marked as partial instead of error when only
the optional native parser is missing.

4. Provider enrichment now counts "no provider match" separately from hard
provider errors.

5. The daemon refreshes the database schema before scan import and before
provider enrichment to avoid stale-schema failures such as:

    no such column: source_type

Result
------

A scan with only /media/hdd/movie active can still import TS recordings without
META/EIT/CUTS sidecars and without the native parser extension.

The scanner state should now show parse warnings rather than six hard scan
errors, and provider searches should use the real event title instead of the
OpenATV recording prefix.

