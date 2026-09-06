# e2MDB Entwicklerdokumentation

**Stand:** e2MDB v16.1 (interne Entwicklungsversion, nicht die Plugin-Version)
**Format:** Markdown / Markup
**Zielgruppe:** Plugin-Entwicklung, Provider-Integration, Skinning, WebIF/API und Debugging
**Vorgänger:** `e2MDB_developer_doku_v15.5_current.md` (beschreibt den Stand vor dem Backend-Daemon-Rewrite; bleibt als historischer Schnappschuss erhalten)

---

## 1. Zweck und Funktionsumfang

e2MDB ist ein optionales OpenATV-Plugin zur Anreicherung von Medien, Aufnahmen und Live-/EPG-Events mit Provider-Metadaten und Artwork.

Seit dem "Clean-Start Backend"-Umbau läuft die eigentliche Scan-/Provider-/Cache-Arbeit in einem **eigenständigen Daemon-Prozess** (`e2mdbd.py`), nicht mehr im Enigma2-GUI-Prozess. Die GUI (Enigma2-Plugin) zeigt Daten an, stößt Jobs an und spricht mit dem Daemon über einen Unix-Socket bzw. eine lokale HTTP-API.

Funktionsumfang:

- Scan lokaler Medienpfade (TS-Aufnahmen und andere Mediendateien)
- Film-, Serien-, Anime- und Manga-Erkennung
- Provider-Suche über mehrere Datenquellen (TMDb, TVDb, OMDb, TVmaze, Cinemeta, AniList, Kitsu; IMDB-Provider aktuell deaktiviert)
- Artwork-Download mit Dedup: Serien-/Staffel-Bilder werden pro Provider+ID einmal abgelegt, nicht pro Aufnahme
- lokale SQLite-Datenbank (`results.db`) für Aufnahmen, Provider-Treffer, Live-/EPG-Daten, Browser-Index und Personen
- lokaler Cache für Bilder (kein JSON-Metadaten-Cache mehr - Anzeige-Daten kommen aus SQLite)
- WebIF mit Editor und Media Browser (vom Daemon selbst ausgeliefert)
- Skin-Anbindung über `E2MDBEventInfo`
- optionale Live-/EPG-Metadaten für InfoBar, EventView, EPG und ChannelSelection
- Live-/EPG Queue mit Worker (im Daemon)
- Prefill für ausgewählte und bevorzugte Sender
- Cleanup und SQLite-Wartung (als Daemon-Jobs)
- Google Title Search Helper mit auswählbarer Zielsprache für temporäre Provider-Suchläufe

---

## 2. Architekturüberblick

```text
Enigma2 GUI-Prozess                          Backend-Daemon-Prozess (e2mdbd.py)
--------------------                          -----------------------------------
plugin.py / Bridges                           Unix-Socket (Command) + HTTP-API
  → config.plugins.e2mdb.*                      → JobManager
  → E2MDBBackendClient.py  ───────────────────→   → E2MDBBackendMetadataScanner
    (Unix-Socket-Client)                            (Datei-Scan, TS META/EIT/CUTS, Titel-Parser)
  → E2MDBSkin.py (liest SQLite direkt)            → BackendProviderEnricher
  → Screens/EventView/InfoBar/                      (Provider-Suche, Artwork-Download, Cast/Crew)
    ChannelSelection/EPGBridge                    → BackendDatabase (SQLite, results.db)
                                                   → Live/EPG Worker + Fetch Queue
                                                   → Twisted Web-Server (WebIF + JSON-API)
```

Wichtig: `E2MDBScanner.py` (alte GUI-Klasse `E2MDBScanner(E2MDBHelper)`) und `E2MDBDatabase.py` (`resultsdb`/`mediadb`) existieren weiterhin und werden von einigen GUI-Screens noch für Anzeige/Fallback-Zwecke genutzt (z.B. Cast/Crew-Personenindex, Browser-Index, EventView-Fallback-Lookup), aber der **produktive Scan- und Provider-Workflow läuft über den Daemon**, nicht mehr über `E2MDBScanner.title_scanner()`.

---

## 3. Wichtige Dateien und Module

```text
e2MDB/
├── __init__.py                         Plugin-Konfiguration, Logging, Globals
├── plugin.py                           Hauptscreen, Setup, Screens, Hooks, Scheduler-Trigger
├── setup.xml                           Setup-Menü
├── e2mdbd.py                           Backend-Daemon: JobManager, Unix-Socket, Twisted Web-API,
│                                        Live/EPG-Worker, Scheduler
├── e2mdbctl.py                         Standalone-CLI für den Daemon (Shell/Debug)
├── E2MDBBackendClient.py               Unix-Socket-Client (GUI-Seite spricht mit dem Daemon)
├── E2MDBBackendConfig.py               Enigma2-Config → settings.json Export, Default-JSON-Dateien
├── E2MDBBackendDatabase.py             Daemon-SQLite (results.db): Aufnahmen, Provider-Treffer,
│                                        Live/EPG, Cleanup-State
├── E2MDBBackendMetadataScanner.py      Datei-Scan, Pfadmodi, TS META/EIT/CUTS-Auswertung,
│                                        MediaNameParser-Anbindung (läuft nur im Daemon)
├── E2MDBBackendProvider.py             Provider-Suche/-Auswahl, Artwork-Download (Serien-Dedup),
│                                        Google-Übersetzungs-Fallback (läuft nur im Daemon)
├── E2MDBBackendNotify.py               GUI-Benachrichtigungen vom Daemon (Notify-Socket)
├── E2MDBBackendLiveBridge.py           Ad-hoc-Anstoß des Live/EPG-Workers aus der GUI
├── E2MDBRecordingParser.py             TS META/EIT/CUTS/TXT-Sidecar-Parser (Python, kein natives C mehr)
├── E2MDBImageDownloader.py             Experimentelle Twisted-only-Variante von
│                                        E2MDBHelper.image_download() (Agent/readBody statt requests)
├── E2MDBScanner.py                     Alte GUI-Scan-/Suchpipeline (E2MDBScanner-Klasse) -
│                                        noch für Anzeige-/Init-Zwecke genutzt, nicht mehr der
│                                        produktive Scan-Pfad
├── MediaNameParser.py                  Dateiname-/Pfadparser
├── E2MDBProviders.py                   GUI-seitige Provider-Orchestrierung (E2MDBProviders-Klasse,
│                                        Singleton `providers` - auch von E2MDBBackendProvider
│                                        importiert)
├── provider/                           Provider-Adapter (TMDB, TVDB, OMDB, TVMAZE, CINEMETA, ANIME,
│                                        KITSU, IMDB [deaktiviert], FanArt, FERNSEHSERIEN, WIKIMEDIA,
│                                        TVSPIELFILM, Consts.py)
├── E2MDBDatabase.py                    Legacy GUI-SQLite (`resultsdb`/`mediadb`): Browser-Index,
│                                        Personen, Live/EPG-Anzeige-Fallback
├── E2MDBHelper.py                      Cache-, Hash-, Datei- und Bild-Helfer (Mixin, u.a. noch von
│                                        E2MDBScanner, E2MDBLiveEPG, E2MDBEventSelection genutzt)
├── E2MDBSkin.py                        Live/EPG Skin-Sources, baut Anzeige-Dicts direkt aus SQLite
├── E2MDBTranslator.py                  Google Title Search Helper
├── E2MDBLiveEPG.py                     Live-/EPG Candidate und Normalisierung
├── E2MDBPriority.py                    Live/EPG Queue-Prioritäten
├── E2MDBPrefillManager.py              Prefill und Channel-Statistik
├── E2MDBPrefillConfig.py               manuelle Prefill-Senderauswahl
├── E2MDBCleanupManager.py              GUI-Bridge: stößt Daemon-Cleanup-/SQLite-Maintenance-Jobs an
├── E2MDBSchedulerTasks.py              OpenATV-Scheduler-Tasks, die Daemon-Jobs anstoßen
├── E2MDBComponentMeta.py               Source-Meta-Brücke
├── E2MDBInfoBarBridge.py               InfoBar-Metadaten
├── E2MDBEPGBridge.py                   EPGSelection / GraphicalEPG
├── E2MDBChannelSelectionBridge.py      ChannelSelection-Metadaten
├── E2MDBEventViewBridge.py             EventView-Auswahl
├── E2MDBEventViewEPG.py                e2MDB EventView für EPG
├── E2MDBEventViewSimple.py             e2MDB EventView für Medien/Aufnahmen
├── E2MDBServiceListIntegration.py      ServiceList InfoKey Integration
├── E2MDBServiceListPreview.py          ServiceList Preview-Logik
├── E2MDBServiceListIndices.py          ServiceList Hilfsindizes
├── E2MDBIgnoreConfig.py                Ignore-Pattern-Konfiguration
├── StubInfo.py                         Minimal-Stub für Event-Info-Objekte
├── init.d/e2mdbd                       Init-Skript für den Daemon
├── web/index.html                      WebIF Frontend (vom Daemon ausgeliefert)
└── locale/                             Übersetzungen

Components/
└── Converter/
    └── E2MDBEventInfo.py               Skin-Converter für Text und Pixmap
```

---

## 4. Globale Konfiguration

### 4.1 Enigma2-Seite (`config.plugins.e2mdb`)

Bleibt weitgehend wie in v15.5 beschrieben (siehe dort für die volle Tabelle: Basis, Live-/EPG, InfoBar/ChannelSelection, Prefill, Cleanup/Logging). Änderungen seit v15.5:

| Key | Default | Zweck |
|---|---:|---|
| `imdbactive` | `False` | **UI-Eintrag entfernt** (auskommentiert in `setup.xml`); Config-Attribut existiert weiter, IMDB-Provider ist überall im Code deaktiviert (`provider/IMDB.py` bleibt als Datei erhalten) |
| `cinemetaactive` | `False` | **neu**: Cinemeta (Stremio-Addon, `v3-cinemeta.strem.io`) als kostenloser Film-/Serien-Fallback ohne API-Key, nur englische Metadaten |

Diese Werte werden beim Sessionstart/Setup-Save nach `settings.json` exportiert (`E2MDBBackendConfig.build_settings_payload()`), damit der Daemon sie lesen kann.

### 4.2 Daemon-Seite (`/etc/enigma2/e2mdb/`)

| Datei | Zweck |
|---|---|
| `settings.json` | aus Enigma2-Config exportierte Laufzeit-Settings (Provider-Flags/Keys, Cache-Root, Webserver-Port, Live/EPG-Defaults, Cleanup-Defaults) |
| `paths.json` | Scan-Pfade mit Pfadmodus (`{"path": ..., "mode": 1-7, "recursive": true}`) - einzige Quelle für Scan-Pfade, kein Merge mehr mit `settings.scanner.recording_paths` |
| `scan_state.json` | letzter Scan-Diagnose-Stand |
| `provider_state.json` | letzter Provider-Anreicherungs-Stand |
| `api_keys.json` | persönliche API-Keys (nie in `/etc/enigma2/settings` oder `settings.json`) |
| `providers.json`, `webui.json`, `scanner.json`, `artwork.json` | weitere Default-Scaffold-Dateien |

Datengrößen, die mit der Bibliothek wachsen (`recordings.json` - kompletter letzter Scan-Katalog, `job_history.json` - Job-Verlauf), liegen **nicht** mehr unter `/etc/enigma2/e2mdb/`, sondern unter `<cache_root>/results/` (siehe §9) - direkt neben `results.db`, wo auch die Datengröße hingehört, nicht auf der (oft kleinen) Config-Partition.

`settings.json` enthält u.a.:

```json
{
  "provider": {
    "tmdb_enabled": true, "tmdb_api_key": "",
    "tvdb_enabled": true, "tvdb_api_key": "",
    "omdb_enabled": false, "omdb_api_key": "",
    "tvmaze_enabled": false,
    "cinemeta_enabled": false,
    "anime_enabled": false, "kitsu_enabled": false,
    "english_text_fallback": true,
    "translate_metadata_fallback": false
  },
  "cache": {"root": "/media/hdd/e2MDB"},
  "database": {"root": "/media/hdd/e2MDB", "journal_mode": "wal", ...},
  "webserver": {"enabled": true, "host": "0.0.0.0", "port": 6066},
  "live_epg": {"...": "..."},
  "cleanup": {"...": "..."}
}
```

`imdb_enabled`/`imdb_api_key` sind bewusst nicht mehr Teil der Settings-Payload (auskommentiert).

---

## 5. Provider-Schicht

### 5.1 Zwei Provider-Orchestrierungen, ein Singleton

```text
e2MDB/E2MDBProviders.py
```

Zentrale Klasse `E2MDBProviders`, Singleton `providers = E2MDBProviders()`. Wird sowohl von der alten GUI-Klasse `E2MDBScanner` **als auch** vom Daemon (`E2MDBBackendProvider.BackendProviderEnricher`, via `from E2MDBProviders import providers`) genutzt - es gibt nur eine Provider-Registry im Prozess.

Provider-Registry (aktueller Stand):

```python
providers_dict = {
    "tmdb": provider_tmdb,
    "tvdb": provider_tvdb,
    "tvmaze": provider_tvmaze,
    "cinemeta": provider_cinemeta,   # neu
    "anime": provider_anime,
    "kitsu": provider_kitsu,
    "omdb": provider_omdb,
    # "imdb" entfernt - provider/IMDB.py bleibt als Datei, aber unbenutzt
}
```

Default-Suchreihenfolge Serien:

```python
{"tvdb": True, "tmdb": True, "tvmaze": False, "cinemeta": False, "anime": False, "kitsu": False, "omdb": True}
```

Default-Suchreihenfolge Filme:

```python
{"tmdb": True, "cinemeta": False, "anime": False, "kitsu": False, "tvdb": True, "omdb": True}
```

`E2MDBBackendProvider.py` hat eigene `DEFAULT_SERIES_ORDER`/`DEFAULT_MOVIE_ORDER`-Konstanten mit denselben Werten, gesteuert über `settings.provider.*_enabled`.

### 5.2 Cinemeta (neu)

```text
e2MDB/provider/CINEMETA.py
```

- Kostenlos, kein API-Key (`requires_api_key = False`)
- Basis-URL `https://v3-cinemeta.strem.io`
- `series_id`/`movieId` sind immer die **IMDb-ID** (z.B. `tt1520211`)
- Suche: `/catalog/{movie|series}/top/search={query}.json`
- Details: `/meta/{movie|series}/{imdbId}.json`
- Kein separater Episode-Endpunkt: `get_episode_details()` lädt die komplette Serie erneut und sucht die Episode im `videos`-Array (per Season/Episode-Nummer oder über die zusammengesetzte ID `ttXXXXXXX:Staffel:Episode`)
- Liefert als Bonus Cross-Referenz-IDs (`tvdb_id`, `moviedb_id`) im Serien-Meta mit
- Nur englische Metadaten, keine Sprachauswahl

### 5.3 IMDB (deaktiviert)

`provider/IMDB.py` bleibt als Datei unverändert liegen, wird aber nirgends mehr importiert/registriert:

- `E2MDBProviders.py`: Import auskommentiert, aus `providers_dict`/`all_prov_ids`/Suchreihenfolgen entfernt
- `E2MDBBackendProvider.py`: aus `DEFAULT_SERIES_ORDER`/`DEFAULT_MOVIE_ORDER` und API-Key-Mapping entfernt
- `E2MDBScanner.py` (`init_providers`): aus `api_keys`/Suchreihenfolgen entfernt
- `e2mdbd.py` / `E2MDBBackendConfig.py`: `imdb_enabled` aus Default-Settings bzw. Settings-Export entfernt
- `setup.xml`: GUI-Checkbox als XML-Kommentar

Generische Provider-ID-Fallback-Listen (`("tvdb","tmdb","imdb",...)` in `E2MDBHelper.py`/`E2MDBBackendProvider.py`/`E2MDBDatabase.py`) sind **nicht** angefasst - das sind Cross-Reference-Schlüssel für IDs, die andere Provider liefern (z.B. TMDbs `imdb_id`), kein Aufruf des IMDB-Scrapers.

### 5.4 Restliche Provider-Eigenschaften

Siehe v15.5 §5.4 - TMDb/TVDb/OMDb/TVmaze/AniList/Kitsu/FanArt/TVSpielfilm/fernsehserien.de/Wikimedia unverändert.

---

## 6. Normalisierte Provider-Felder

Unverändert - siehe v15.5 §6 (`e2MDB/provider/Consts.py`, `Fields`-Klasse).

---

## 7. Backend-Daemon: Aufnahme-Scan und Provider-Anreicherung

Der produktive Scan-/Anreicherungs-Workflow läuft im Daemon, orchestriert von `JobManager` in `e2mdbd.py`.

### 7.1 Scan-Schritt: `E2MDBBackendMetadataScanner`

```text
e2MDB/E2MDBBackendMetadataScanner.py
```

Bis Phase 12g Teil von `E2MDBScanner.py`, seither eigene Datei (nur der Daemon importiert sie). Aufgaben:

- Scan-Pfade aus `paths.json` abgehen (`iter_media_files`/`collect_media_files`), `EXCLUDED_SCAN_DIRS` überspringen
- `.ts`/`.stream` vs. andere Video-Endungen unterscheiden (`is_ts_recording_file`) - steuert nur:
  - Titel-Bereinigung (`clean_openatv_recording_title` vs. `clean_title_from_filename`)
  - Parser-Pfad-Normalisierung für den `MediaNameParser` (`parser_path_for_recording`)
  - `source_type`-Spalte (`"recording"` vs. `"media_file"`) für Statistik/Filter
  - **nicht** die META/EIT/CUTS-Sidecar-Suche selbst - die läuft für jede erkannte Mediendatei gleich (`E2MDBRecordingParser.parse_recording()`), Sidecars existieren bei Nicht-TS-Dateien einfach faktisch nie
- Pfadmodi (`PATH_MODE_*`, unverändert seit v15.5 §7.2) bestimmen Medienart-Einschätzung
- `build_scan_item()` liefert das normalisierte Scan-Item, das die Provider-Anreicherung als Eingabe bekommt

### 7.2 Provider-Schritt: `BackendProviderEnricher`

```text
e2MDB/E2MDBBackendProvider.py
```

- `search_item(item)`: Kandidatentitel sammeln, `providers.gather_providers_info()` aufrufen, bestes Ergebnis wählen (`choose_best`, Titel-/Beschreibungs-Ratio wie im alten `get_match_ratio`)
- Episode-Anreicherung: Serien-Cast bleibt vom Serien-Level-Ergebnis, wird **nicht** mehr vom Episode-Lookup überschrieben (Fix: Provider liefern Gaststars der Episode unter demselben `"cast"`-Feldnamen wie den Haupt-Cast; der Episode-Merge lässt `"cast"` jetzt explizit aus)
- `download_artwork(item, best)`: lädt Artwork mit **Dedup**:
  - Film/episodeneigenes Standbild → `cache_root/<pic_type>/<hash[0]>/<hash>.<ext>`, gehasht aus dem Aufnahmepfad (`_primary_artwork_path`)
  - Serien-Cover/Backdrop/TitleLogo → `cache_root/series/<provider>/<series_id>/<pic_type>.<ext>`, **ein** Pfad pro Serie unabhängig von der Episodenzahl (`_secondary_artwork_path`/`_series_artwork_target`)
  - Staffel-Poster (sofern der Provider `seasons`-Daten liefert, z.B. TVDB via Cinemeta/TVDB) → `cache_root/seasons/<provider>/<series_id>/S<NN>/cover.<ext>`
  - `_download_if_missing()`: lädt nur, wenn die Zieldatei noch nicht existiert - das ist der eigentliche Dedup-Mechanismus
  - Vorher (bis Phase 12f): alles landete unter `artwork/recordings/<recording_id>/`, jede Episode lud Serien-Artwork erneut

### 7.3 Debug-Schalter `/tmp/e2MDB.flag`

Temporärer Debug-Schalter in `e2mdbd.py` (zum Entfernen markiert): wenn die Datei existiert, loggt der Scan/die Anreicherung pro Item zusätzlich Pfad+Modus, Parser-Ergebnis, Provider-Suchkandidaten und das rohe Provider-Ergebnis - ohne das eigentliche Scan-/Anreicherungsverhalten zu ändern.

### 7.4 Legacy-Pfad: `E2MDBScanner.py`

`class E2MDBScanner(E2MDBHelper)` mit `title_scanner()`/`get_search_results()`/etc. existiert weiterhin, wird aber im aktuellen Daemon-Workflow nicht mehr für den produktiven Scan aufgerufen. Bleibt relevant für:

- `init_providers()` (startet die gemeinsame `providers`-Registry mit GUI-Config-Werten)
- ggf. weiterhin referenzierte Hilfsfunktionen in GUI-Screens

---

## 8. Google Title Search Helper

Unverändert - siehe v15.5 §8.

---

## 9. Cache und Dateistruktur

Basis:

```text
<cachePath>/e2MDB/
```

Cache-Unterordner:

```text
cover/          Film-/Episode-Cover, gehasht aus dem Aufnahmepfad
backdrop/       Film-/Episode-Backdrop, gehasht aus dem Aufnahmepfad
titlelogo/      Film-/Episode-TitleLogo
image/          Episode-Standbild/Preview
series/<provider>/<series_id>/{cover,backdrop,titlelogo}.<ext>   Serien-Artwork (dedupliziert)
seasons/<provider>/<series_id>/S<NN>/cover.<ext>                 Staffel-Poster, sofern vom Provider geliefert
results/        recordings.json, job_history.json, results.db (siehe unten)
data/, index/, preview/, fanart/, fernsehserien/, wikimedia/, wikipedia/   wie v15.5
artwork/recordings/<recording-id>/provider_result.json   NUR bei aktivem debug_log - Debug-Dump des
                                                          rohen Provider-Ergebnisses, kein Artwork mehr
```

`recordings.json` (letzter Scan-Katalog) und `job_history.json` (Job-Verlauf) liegen seit Phase 12g/12h unter `<cache_root>/results/`, nicht mehr unter `/etc/enigma2/e2mdb/` - sie wachsen mit der Bibliotheksgröße und gehören daher zur Cache-/Datenpartition, nicht zur (oft kleinen) Config-Partition.

`artwork/recordings/<id>/provider_result.json` ist ein reiner Debug-Dump (voller roher Provider-Match) und wird nur geschrieben, wenn `settings.debug`/`debug_log`/`debug_json` aktiv ist (`debugLog` ist standardmäßig `1` = an). Das ist **nicht** dasselbe wie das alte, mittlerweile entfernte Artwork-Schema, das früher unter demselben Pfad lag.

Temporäre Dateien, Logs: unverändert, siehe v15.5 §9.

---

## 10. SQLite-Datenbank (`results.db`)

Anders als in v15.5 beschrieben gibt es **kein separates `media.db` mehr für den produktiven Pfad** - alles läuft über `results.db`, geschrieben von zwei Modulen auf dieselbe Datei:

- **`E2MDBBackendDatabase.py`** (Daemon): `e2mdb_media` (eigenes, größeres Schema), `e2mdb_recordings`, `e2mdb_provider_matches`, `e2mdb_provider_assets`, `e2mdb_epg_events`, `e2mdb_epg_event_asset_map`, `e2mdb_fetch_queue`, `e2mdb_backend_state`, `e2mdb_cleanup_state`
- **`E2MDBDatabase.py`** (Legacy/GUI, `resultsdb`): `e2mdb_browser_index`, `e2mdb_browser_series_seasons`, `e2mdb_browser_series_episodes`, `e2mdb_browser_index_people`, `e2mdb_people`, `e2mdb_media_people`, `e2mdb_provider_asset_people`, `e2mdb_channel_stats`, `e2mdb_meta`, eigene (kleinere) Version von `e2mdb_media`

`CREATE TABLE IF NOT EXISTS` migriert **nichts nachträglich** - wessen Schema zuerst auf einer Box angelegt wird, gewinnt für diese Tabelle dauerhaft. Für `e2mdb_recordings`/`e2mdb_media` betrifft das nur Boxen, auf denen die jeweils andere Seite die Tabelle zuerst je angelegt hat; im normalen Betrieb legt der Daemon `e2mdb_recordings` zuerst an.

### 10.1 `e2mdb_recordings` (Daemon, zentrale Aufnahme-Tabelle)

| Feld | Zweck |
|---|---|
| `recording_id` | Primary Key (Hash aus reduziertem Pfad) |
| `media_hash`, `path`, `folder`, `name`, `extension` | Datei-Identität |
| `title`, `description`, `extended_description` | Anzeige-Titel/-Beschreibung |
| `service_ref`, `recorded_at`, `duration_seconds`, `size_bytes`, `mtime` | Aufnahme-Metadaten |
| `search_text`, `search_text_norm` | Suchindex |
| `scan_status`, `parse_error`, `payload_json` | Scan-Diagnose |
| `source_type` | `"recording"` (.ts) oder `"media_file"` (sonst) |
| `path_mode`, `path_mode_label`, `media_family` | aus `paths.json`-Modus abgeleitet |
| `estimated_media_type`, `provider_media_type` | Scanner- bzw. Provider-Einschätzung |
| `provider_title`, `series_title`, `movie_title`, `season_no`, `episode_no` | Titel-/Serieninfo |
| `created_at`, `updated_at` | Zeitstempel |

Indizes u.a. auf `media_hash`, `path`, `title`, `path_mode`, `provider_media_type`, `search_text_norm`, `mtime`, `recorded_at`.

### 10.2 `e2mdb_provider_matches`

Speichert **alle** Kandidaten eines Provider-Laufs (nicht nur den besten Treffer): `media_hash`, `recording_id`, `provider`, `media_type`, `title`, `year`, `match_score`, `is_best`, `payload_json`, Zeitstempel.

### 10.3 `e2mdb_provider_assets` / `e2mdb_epg_event_asset_map` (Live/EPG)

Wiederverwendbare Provider-Assets für den Live/EPG-Pfad (nicht für normale Aufnahmen - dort läuft Dedup über deterministische Dateipfade, siehe §7.2). `e2mdb_media_asset_map` (analoges Mapping für normale Aufnahmen) existiert nur als nie beschriebene `CREATE TABLE`-Leiche im Legacy-Modul, wird nirgends befüllt.

### 10.4 Browser-Index, Personen, Channel-Stats

Unverändert von der Legacy-Seite gepflegt (`E2MDBDatabase.py`) - siehe v15.5 §10.5.

---

## 11. Live-/EPG-Datenmodell

Unverändert - siehe v15.5 §11. `E2MDBLiveEPG.py`/`E2MDBPriority.py` weiterhin GUI-seitig, die eigentliche Queue-Abarbeitung läuft im Daemon (`_run_live_epg_worker` in `e2mdbd.py`), nicht mehr in einem separaten `E2MDBEPGWorker.py` (existiert nicht mehr als eigene Datei).

---

## 12. Live-/EPG Worker

Läuft im Daemon (`e2mdbd.py`, `_run_live_epg_worker`/`LiveEPGAutoWorker`), nicht mehr als separates Modul. Ablauf inhaltlich wie v15.5 §12 beschrieben. `download_artwork()` wird von hier **und** vom Aufnahme-Scan-Pfad gemeinsam genutzt (§7.2) - Serien-Artwork, das ein Live/EPG-Treffer herunterlädt, wird auch von später gescannten Aufnahmen derselben Serie wiederverwendet und umgekehrt.

---

## 13. Bridges und Runtime-Metadaten

Unverändert - siehe v15.5 §13. Zusätzlich:

- `E2MDBBackendClient.py`: kapselt den Unix-Socket-Zugriff auf den Daemon für alle Bridges/Screens
- `E2MDBBackendNotify.py`: Daemon → GUI Notify-Socket (z.B. "Live-Event aktualisiert")
- `E2MDBSkin.py`: baut die Anzeige-Dicts für EventView/Skin-Sources direkt aus SQLite-Zeilen (`build_epg_skin_data`, `build_eventview_final_dict_from_db`) - **keine** JSON-Zwischendateien mehr

---

## 14. Prefill

Unverändert - siehe v15.5 §14.

---

## 15. Cleanup und SQLite-Wartung

`E2MDBCleanupManager.py` ist nur noch eine GUI-Bridge, die Daemon-Jobs (`cleanup/run`, `database/maintenance`) anstößt - die eigentliche Cleanup-/VACUUM-/REINDEX-Logik läuft im Daemon.

---

## 16. OpenATV Task-/Timer-Integration

Unverändert registriert in `plugin.py` (siehe v15.5 §16), die Task-Implementierungen (`E2MDBSchedulerTasks.py`, `E2MDBBackendJobSchedulerTask`) stoßen jetzt Daemon-Jobs über den Scheduler-Endpunkt an (`scheduler/run`), statt selbst zu scannen.

---

## 17. Backend-API (Daemon)

Der Daemon liefert **sowohl** einen Unix-Socket (Command-Protokoll, JSON-Zeilen, genutzt von `E2MDBBackendClient.py`) **als auch** einen Twisted-HTTP-Server unter dem konfigurierten `webserver.port` (Default `6066`).

### 17.1 Job-/Scan-Endpunkte

```text
/api/jobs/scan/start | /stop
/api/jobs/metadata/start
/api/jobs/scan-enrich/start
/api/jobs/current
/api/jobs/queue
/api/jobs/history
```

### 17.2 Scanner/Provider/Media-Status

```text
/api/scanner/state
/api/scanner/paths
/api/provider/state
/api/media/status
/api/refresh/status | /run
/api/database/status | /maintenance
```

### 17.3 Live/EPG

```text
/api/live/queue/status | /list | /reset-running | /retry-no-match | /clear
/api/live/result | /results | /duplicates | /dedupe
/api/live/artwork
/api/live/worker/status | /start
```

### 17.4 Cleanup / Cache

```text
/api/cleanup/status | /run
/api/cache/status | /cleanup
```

### 17.5 Scheduler

```text
/api/scheduler/status | /list | /e2gui | /reload | /run
```

### 17.6 Browser / Recordings / Artwork (WebIF-Frontend)

```text
/api/browser/list | /item | /series | /season | /status | /debug-artwork | /debug-performance
/api/recordings/list | /item
/api/artwork/file?path=<absolute-local-path>   -- nur aus erlaubten Cache-Roots, sonst 403
/api/results | /details | /settings | /settings-reload | /status
```

`ArtworkFileResource` liefert nur Dateien aus `settings.cache.root`, `settings.database.root`, `/media/hdd/e2MDB`, `/media/usb/e2MDB` aus - andere absolute Pfade werden mit 403 blockiert.

---

## 18. Skin-API

Unverändert - siehe v15.5 §18 (Converter, Bild-/Text-/Boolean-Tokens, Meta-Keys, Skin-Beispiele). Für EventView-Screens kommt der Meta-Dict-Aufbau jetzt über `E2MDBSkin.build_eventview_final_dict_from_db()` direkt aus SQLite, nicht mehr über JSON-Dateien.

---

## 19. Ignore-Listen

Unverändert - siehe v15.5 §19.

---

## 20. Logging

Unverändert - siehe v15.5 §20. Zusätzlich: `/tmp/e2MDB.flag` (siehe §7.3) für gezieltes Scan-/Provider-Debug-Logging, unabhängig vom `debugLog`-Level.

---

## 21. Debug- und Diagnose-Abfragen

Wie v15.5 §21, zusätzlich:

### 21.1 Scan-Ergebnis nach path_mode prüfen

```sh
sqlite3 <cache_root>/results.db "
SELECT path_mode, path_mode_label, media_family, estimated_media_type, COUNT(*)
FROM e2mdb_recordings
GROUP BY path_mode, path_mode_label, media_family, estimated_media_type;
"
```

### 21.2 Provider-Dedup-Ordner prüfen

```sh
find <cache_root>/series -maxdepth 3 -type d
find <cache_root>/seasons -maxdepth 4 -type d
```

Jede Serie sollte hier nur **einen** Cover/Backdrop/TitleLogo-Satz haben, unabhängig von der Episodenzahl.

---

## 22. Entwickler-Checkliste

Wie v15.5 §22, zusätzlich:

- Neue Provider: in `E2MDBProviders.py` **und** `E2MDBBackendProvider.py` **und** `E2MDBScanner.init_providers()` **und** `e2mdbd.py`/`E2MDBBackendConfig.py` Settings-Export **und** `__init__.py` Config-Attribut **und** `setup.xml` eintragen (siehe Cinemeta-Einbau als Vorlage)
- Neue Spalten in `e2mdb_recordings`/`e2mdb_media`: es gibt **keine** automatische Migration (`CREATE TABLE IF NOT EXISTS` ist ein No-Op auf bestehenden Tabellen) - auf betroffenen Boxen ggf. `results.db` neu anlegen lassen
- Artwork-Pfade: Serien-/Staffel-Level immer über `_series_artwork_target()`/`_season_artwork_path()`, nie direkt pro Aufnahme, sonst Dedup kaputt

---

## 23. Kurzreferenz

| Bereich | Modul |
|---|---|
| Config / Logging | `e2MDB/__init__.py` |
| Plugin UI / Hooks / Scheduler-Trigger | `e2MDB/plugin.py` |
| Setup UI | `e2MDB/setup.xml` |
| **Backend-Daemon** | `e2MDB/e2mdbd.py` |
| Daemon-CLI | `e2MDB/e2mdbctl.py` |
| Daemon-Client (GUI-Seite) | `e2MDB/E2MDBBackendClient.py` |
| Daemon-Config-Export | `e2MDB/E2MDBBackendConfig.py` |
| Daemon-SQLite | `e2MDB/E2MDBBackendDatabase.py` |
| Daemon-Scan | `e2MDB/E2MDBBackendMetadataScanner.py` |
| Daemon-Provider/Artwork | `e2MDB/E2MDBBackendProvider.py` |
| Daemon-Notify | `e2MDB/E2MDBBackendNotify.py` |
| TS-Sidecar-Parser | `e2MDB/E2MDBRecordingParser.py` |
| Legacy GUI-Scan | `e2MDB/E2MDBScanner.py` |
| Parser | `e2MDB/MediaNameParser.py` |
| Provider-Orchestrierung (Singleton) | `e2MDB/E2MDBProviders.py` |
| Provider-Felder | `e2MDB/provider/Consts.py` |
| Legacy GUI-SQLite (Browser/Personen) | `e2MDB/E2MDBDatabase.py` |
| Google Title Search | `e2MDB/E2MDBTranslator.py` |
| Live-/EPG Modell | `e2MDB/E2MDBLiveEPG.py` |
| Live-/EPG Skin-Sources | `e2MDB/E2MDBSkin.py` |
| Prefill | `e2MDB/E2MDBPrefillManager.py` |
| Cleanup-Bridge | `e2MDB/E2MDBCleanupManager.py` |
| Scheduler-Tasks | `e2MDB/E2MDBSchedulerTasks.py` |
| Source-Meta | `e2MDB/E2MDBComponentMeta.py` |
| InfoBar | `e2MDB/E2MDBInfoBarBridge.py` |
| EPG | `e2MDB/E2MDBEPGBridge.py` |
| ChannelSelection | `e2MDB/E2MDBChannelSelectionBridge.py` |
| EventView | `e2MDB/E2MDBEventViewBridge.py`, `E2MDBEventViewSimple.py`, `E2MDBEventViewEPG.py` |
| Skin-Converter | `Components/Converter/E2MDBEventInfo.py` |
