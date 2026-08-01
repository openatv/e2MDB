# e2MDB Backend Phase 11h - Clean-Start Legacy Cleanup

## Ziel

Die Test-/Clean-Start-Phase benötigt keine Altlasten-Reparaturen. Code, der nur
für ZIP-overwrite Installationen, alte Datenbankschemata oder Debug-/Provenance-
Aufräumaktionen alter Testdaten gedacht war, wurde entfernt.

## Entfernt

- `cleanup_legacy_files()` aus `plugin.py`
- Sessionstart-Aufruf für Legacy-Datei-Cleanup
- manuelle Datenbank-Reparaturbefehle:
  - `e2mdbctl.py db repair-schema`
  - `e2mdbctl.py db cleanup-debug`
- API-Endpunkte:
  - `/api/database/repair-schema`
  - `/api/database/cleanup-debug`
- Socket-Kommandos:
  - `database_repair_schema`
  - `database_cleanup_debug_payloads`
- additive `ALTER TABLE`-Schema-Fixes aus der Backend-DB-Schicht
- additive `ALTER TABLE`-Schema-Fixes aus der GUI-/ResultsDB-Schicht
- alte Key-/Hash-Migrationslogik in der GUI-DB-Schicht

## Beibehalten

- Clean-Start Schema-Erzeugung per `CREATE TABLE IF NOT EXISTS`
- Diagnosebefehle:
  - `e2mdbctl.py db status`
  - `e2mdbctl.py db schema`
- SQLite-Wartung:
  - `e2mdbctl.py db maintenance [vacuum] [reindex]`
- Debug-JSON-Verhalten:
  - Debug an: Provider-JSON kann als Datei gespeichert werden
  - Debug aus: produktive DB bleibt ohne URL-/Provenance-Spalten

## Grundsatz

Neue Tests starten mit neuer DB. Wenn eine alte Test-DB oder alte Plugin-Dateien
im Zielsystem liegen, werden sie nicht mehr automatisch repariert. Die Box soll
für diese Phase sauber installiert werden.
