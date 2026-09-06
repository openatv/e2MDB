# e2MDB Backend Phase 11l - Progress text cleanup

Date: 2026-06-01

## Goal

The backend progress text shown in the Enigma2 GUI should be short and user-facing.
Technical implementation details such as `E2MDBScanner path mode and filename parser`
should not be shown in the normal progress area.

## Changes

- The backend now reports concise scan messages:
  - `Scanning TS recordings`
  - `Scanning media files`
- The GUI maps the `recording_scan` phase to `Media scan` instead of using a long
  action sentence as the header.
- German translations were shortened:
  - `Medienscan`
  - `TS-Aufnahmen scannen`
  - `Mediendateien scannen`
  - `Scandaten importieren`
  - `Providersuche vorbereiten`
- The total progress label is translated as `gesamt`.

## Notes

The technical scanner details remain available in backend diagnostics such as
`last_recording_scan.json`, but they are no longer displayed as long status text
in the normal GUI progress area.
