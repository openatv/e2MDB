# e2MDB Backend Phase 10w - Recording parser remains mandatory

Clean-start correction after phase 10v.

The native `_e2mdb_recordingparser` extension is not treated as optional.
It is part of the plugin build and must be installed on the box. If it is
missing, `.ts` recording scans must fail with a clear error instead of creating
partial fallback entries.

Kept from phase 10v:

- OpenATV recording filename prefix cleanup before provider search.
- Provider title cleanup for names like `YYYYMMDD HHMM - Channel - Title.ts`.
- Series episode extraction from cleaned filenames.
- SQLite schema refresh before scan import/enrichment.

Reverted from phase 10v:

- No filename-only fallback when `_e2mdb_recordingparser` is missing.
- Parser import errors are hard errors again.
- Individual parser exceptions are scan errors, not partial successful scans.
