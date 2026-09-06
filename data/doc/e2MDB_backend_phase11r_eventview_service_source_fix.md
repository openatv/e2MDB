# e2MDB Backend Phase 11r - EventView service source crash fix

## Problem

Opening the simple e2MDB event information screen could still crash after the page scroll action fix with:

`AttributeError: 'E2MDBEventViewSimple' object has no attribute 'setService'`

`layoutFinished()` calls `setService()` and `setEvent()`, but the custom screen class did not provide these methods.

## Fix

- Added `E2MDBEventViewSimple.setService()`.
- Added `E2MDBEventViewSimple.setEvent()`.
- Added a small helper to normalize `ServiceReference` wrappers to the underlying Enigma2 service reference before updating the `ServiceEvent` source.
- Added a compatible `Service` source alias next to the existing `service` source.
- Errors during source updates are logged and no longer crash the GUI.

## Notes

This is a small hotfix on top of phase 11q. No backend schema, scan logic, provider logic or artwork logic was changed.
