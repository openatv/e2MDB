# e2MDB Backend Phase 11q - EventView scroll action crash fix

## Problem

Opening the simple e2MDB event information screen could crash with:

`AttributeError: 'E2MDBEventViewSimple' object has no attribute 'pageUp'`

The action map registered `pageUp` and `pageDown`, but the screen class did not provide these methods.

## Fix

- Added `E2MDBEventViewSimple.pageUp()`.
- Added `E2MDBEventViewSimple.pageDown()`.
- Both methods forward to the existing `ScrollLabel` description widget.
- Errors are caught and written to the e2MDB log instead of crashing the GUI.

## Notes

This is a small hotfix on top of phase 11p. No backend schema or scan logic was changed.
