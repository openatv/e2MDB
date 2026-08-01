# e2MDB Entwicklerdokumentation

**Stand:** e2MDB v15.5 aktueller Entwicklungsstand  
**Format:** Markdown / Markup  
**Zielgruppe:** Plugin-Entwicklung, Provider-Integration, Skinning, WebIF/API und Debugging

---

## 1. Zweck und Funktionsumfang

e2MDB ist ein optionales OpenATV-Plugin zur Anreicherung von Medien, Aufnahmen und Live-/EPG-Events mit Provider-Metadaten und Artwork.

Der aktuelle Entwicklungsstand umfasst:

- Scan lokaler Medienpfade
- Scan von Aufnahmen und externen Medien-Dateien
- Film-, Serien-, Anime- und Manga-Erkennung
- Provider-Suche über mehrere Datenquellen
- lokale SQLite-Datenbanken für Medien-, Ergebnis-, Personen-, Browser- und Live-/EPG-Daten
- lokaler Cache für JSON-Metadaten und Bilder
- WebIF mit Editor und Media Browser
- Skin-Anbindung über `E2MDBEventInfo`
- optionale Live-/EPG-Metadaten für InfoBar, EventView, EPG und ChannelSelection
- Live-/EPG Queue mit Worker
- Prefill für ausgewählte und bevorzugte Sender
- Cleanup und SQLite-Wartung
- Google Title Search Helper mit auswählbarer Zielsprache für temporäre Provider-Suchläufe

---

## 2. Architekturüberblick

e2MDB trennt die Hauptbereiche klar voneinander:

```text
Medien / Aufnahmen
  → Scanner
  → Parser
  → Provider
  → Bewertung / Finalisierung
  → JSON / Bilder / SQLite
  → WebIF / Skin / EventView

Live / EPG
  → Bridge
  → Candidate
  → SQLite Event
  → Fetch Queue
  → Worker
  → Provider / Scanner
  → Provider Asset
  → Source Meta
  → Skin / EventView / InfoBar / ChannelSelection
```

Die Anzeige arbeitet über vorhandene Metadaten. Provider-Suchen laufen über Scanner, Worker oder explizite WebIF/API-Aktionen.

---

## 3. Wichtige Dateien und Module

```text
e2MDB/
├── __init__.py                         Plugin-Konfiguration, Logging, Globals
├── plugin.py                           Hauptscreen, Setup, Screens, Hooks, Scheduler
├── setup.xml                           Setup-Menü
├── E2MDBScanner.py                     Medien-Scan und Provider-Suchpipeline
├── MediaNameParser.py                  Dateiname-/Pfadparser
├── E2MDBProviders.py                   Provider-Orchestrierung
├── E2MDBDatabase.py                    SQLite-Datenbanken und Live-/EPG Tabellen
├── E2MDBHelper.py                      Cache-, Hash-, Datei- und Bild-Helfer
├── E2MDBTranslator.py                  Google Title Search Helper
├── E2MDBWeb.py                         WebIF und JSON/API-Endpunkte
├── E2MDBLiveEPG.py                     Live-/EPG Candidate und Normalisierung
├── E2MDBEPGWorker.py                   Live-/EPG Fetch Queue Worker
├── E2MDBPrefillManager.py              Prefill und Channel-Statistik
├── E2MDBPrefillConfig.py               manuelle Prefill-Senderauswahl
├── E2MDBCleanupManager.py              Live-/EPG Cleanup und SQLite-Wartung
├── E2MDBComponentMeta.py               Source-Meta-Brücke
├── E2MDBInfoBarBridge.py               InfoBar-Metadaten
├── E2MDBEPGBridge.py                   EPGSelection / GraphicalEPG
├── E2MDBChannelSelectionBridge.py      ChannelSelection-Metadaten
├── E2MDBEventViewBridge.py             EventView-Auswahl
├── E2MDBEventViewEPG.py                e2MDB EventView für EPG
├── E2MDBEventViewSimple.py             e2MDB EventView für Medien
├── E2MDBServiceListIntegration.py      ServiceList InfoKey Integration
├── E2MDBServiceListPreview.py          ServiceList Preview-Logik
├── E2MDBServiceListIndices.py          ServiceList Hilfsindizes
├── E2MDBIgnoreConfig.py                Ignore-Pattern-Konfiguration
├── E2MDBPriority.py                    Queue-Prioritäten
├── provider/                           Provider-Adapter
├── web/index.html                      WebIF Frontend
└── locale/                             Übersetzungen

Components/
└── Converter/
    └── E2MDBEventInfo.py               Skin-Converter für Text und Pixmap
```

---

## 4. Globale Konfiguration

Die Konfiguration liegt unter:

```python
config.plugins.e2mdb
```

### 4.1 Basis

| Key | Typ | Default | Zweck |
|---|---:|---:|---|
| `enableDatabase` | `ConfigYesNo` | `False` | lokale e2MDB Datenbank-/Cache-Integration |
| `cachePath` | `ConfigText` | `/media/hdd/` | Basis für Cache, SQLite und generierte Dateien |
| `lang` | `ConfigSelection` | Box-Locale oder `en` | Provider-Suchsprache |
| `ignoreFolderNameListAction` | `NoSave(ConfigSelection)` | `open` | Editor für ignorierte Ordnernamen |

### 4.2 Provider

| Key | Default | Zweck |
|---|---:|---|
| `tmdbactive` | `True` | TMDb für Filme/Serien |
| `tmdbapikey` | leer | TMDb API-Key |
| `tvdbactive` | `True` | TVDb für Serien, Staffeln und Episoden |
| `tvdbapikey` | leer | TVDb API-Key |
| `omdbactive` | `False` | OMDb Fallback |
| `omdbapikey` | leer | OMDb API-Key |
| `imdbactive` | `False` | IMDb Fallback |
| `tvmazeactive` | `False` | TVmaze Serien-Fallback |
| `animeactive` | `False` | AniList Anime/Manga |
| `kitsuactive` | `False` | Kitsu Anime/Manga |
| `tvspielfilmactive` | `True` | TVSpielfilm für deutsche Live-/EPG-Suche |
| `fernsehserienactive` | `True` | fernsehserien.de Bild-Fallback für deutsches Live/EPG |
| `wikimediaactive` | `False` | Wikimedia/Wikipedia Bild-Fallback |
| `fanartactive` | `False` | FanArt.tv Artwork-Fallback |
| `fanartapikey` | leer | FanArt.tv API-Key |
| `fanartmode` | `missing` | `missing` oder `prefer` |

### 4.3 Google Title Search Helper

| Key | Typ | Default | Zweck |
|---|---:|---:|---|
| `translateTitleSearch` | `ConfigYesNo` | `False` | aktiviert Google als temporären Titel-Suchfallback |
| `translateTitleSearchLanguage` | `ConfigSelection` | Box-Locale oder `en` | Zielsprache für den temporären Such-Titel |

Die Sprachliste wird in `__init__.py` aus einer festen Sprachcode-Liste und `Components.International.international.LANGUAGE_DATA` aufgebaut. Die Auswahl ist identisch im Setup sichtbar.

### 4.4 Live-/EPG Basis

| Key | Default | Zweck |
|---|---:|---|
| `epgMetaEnabled` | `False` | Live-/EPG-Metadaten-Cache aktivieren |
| `epgRetentionDays` | `3` | Laufzeit gematchter Live-/EPG-Daten |
| `epgNoMatchRetentionHours` | `12` | Laufzeit von No-Match-Einträgen |
| `epgEventViewUseE2MDB` | `True` | e2MDB EventView für EPG-Events |
| `mediaEventViewUseE2MDB` | `True` | e2MDB EventView für Medien/Aufnahmen |

### 4.5 InfoBar und ChannelSelection

| Key | Default | Zweck |
|---|---:|---|
| `epgInfoBarEnabled` | `True` | Metadatenquellen in InfoBar/MoviePlayer |
| `epgChannelSelectionEnabled` | `True` | Metadaten in ChannelSelection |
| `epgServiceListPreviewMode` | `backdrop_preview` | bevorzugter Vorschau-Bildtyp |

Die früheren GUI-Tuning-Parameter für Queue-Status, Prioritäten, Delays, Ad-hoc-
Suche und Clear-before-update sind keine Config-Objekte mehr. Der Code nutzt die
bewährten Default-Werte direkt, damit im Setup und in `/etc/enigma2/settings`
keine versteckten Laufzeit-Schalter mehr existieren.

### 4.6 Worker

Der Live-/EPG-Worker wird nicht mehr über versteckte Enigma2-Config-Keys
gesteuert. Aktivierung, Intervall, Batch-Limits und Cleanup-Defaults werden über
die Backend-Settings-Payload aus festen Defaults erzeugt. Sichtbar steuerbar
bleibt nur, ob Live-/EPG-Metadaten grundsätzlich aktiv sind:

| Key | Default | Zweck |
|---|---:|---|
| `epgMetaEnabled` | `False` | Live-/EPG-Metadaten-Cache aktivieren |

Interne Worker-Defaults: Worker aktiv, 30 Sekunden Basisintervall, kurze Events
unter 15 Minuten überspringen, beendete Events nicht unnötig neu verarbeiten und
bei offenem EPG keine GUI-blockierenden Queue-/Worker-Aktionen starten.

### 4.7 Prefill und Channel-Statistik

| Key | Default | Zweck |
|---|---:|---|
| `epgPrefillEnabled` | `False` | Prefill aktivieren |
| `epgPrefillMode` | `standby` | `off`, `standby`, `night`, `idle` |
| `epgPrefillStartHour` | `5` | Startstunde für Night-Modus |
| `epgPrefillHorizonDays` | `1` | Zukunftstage |
| `epgPrefillMaxEvents` | `250` | globales Event-Limit |
| `epgPrefillMaxEventsPerService` | `50` | Limit je Sender |
| `epgUseZapHistory` | `True` | bevorzugte Sender aus Statistik |
| `epgZapHistoryTopN` | `10` | Anzahl Top-Sender |
| `epgPrefillIgnoreServiceNameListAction` | `open` | Editor für ignorierte Sendernamen |

Prefill-Intervall, Queue-Prioritäten, Idle-Boost, No-EPG-Cooldown, Slice-Delay
und Channel-Statistik-Erfassung sind feste interne Defaults und keine
versteckten Config-Elemente mehr.

### 4.8 Cleanup und Logging

| Key | Default | Zweck |
|---|---:|---|
| `epgCleanupSqliteVacuum` | `True` | VACUUM |
| `epgCleanupSqliteReindex` | `False` | REINDEX |
| `debugLog` | `1` | `0`, `1`, `2` |
| `logTarget` | `file` | `file`, `debuglog`, `both` |
| `logRotateSizeMb` | `5` | Logrotation in MB |

Cleanup-Aktivierung, Cleanup-Intervall, Queue-Retention, Event-Limits,
Prefill-State-Retention und SQLite-Maintenance sind feste Defaults. Sichtbar
steuerbar bleiben nur VACUUM/REINDEX und die globalen Log-Optionen.

---

## 5. Provider-Schicht

### 5.1 Zentrales Modul

```text
e2MDB/E2MDBProviders.py
```

Zentrale Klasse:

```python
class E2MDBProviders
```

Start der Provider:

```python
providers.start(language, api_keys, series_search_order, movie_search_order)
```

Provider-Registry:

```python
providers_dict = {
    "tmdb": provider_tmdb,
    "tvdb": provider_tvdb,
    "tvmaze": provider_tvmaze,
    "anime": provider_anime,
    "kitsu": provider_kitsu,
    "imdb": provider_imdb,
    "omdb": provider_omdb,
}
```

Artwork-Fallback:

```python
artwork_provider = provider_fanart
```

### 5.2 Provider-Suchreihenfolge

Default für Serien:

```python
{
    "tvdb": True,
    "tmdb": True,
    "tvmaze": False,
    "anime": False,
    "kitsu": False,
    "omdb": True,
    "imdb": False,
}
```

Default für Filme:

```python
{
    "tmdb": True,
    "imdb": False,
    "anime": False,
    "kitsu": False,
    "tvdb": True,
    "omdb": True,
}
```

### 5.3 Provider-Medientypen

`get_provider_media_types()` mappt interne Typen auf Provider-Endpunkte.

| Interner Typ | Provider-Ziel |
|---|---|
| `movie` | Film |
| `series` | Serie |
| `multi` | kombinierte Film-/Seriensuche bei TMDb |
| `anime` | Anime/Manga Provider und allgemeine Fallbacks |
| `anime_series` | Serienziel |
| `anime_movie` | Filmziel |
| `manga`, `manga_series`, `manga_movie` | Manga-Ziel bei AniList/Kitsu |

### 5.4 Provider-Eigenschaften

| Provider | Verwendung |
|---|---|
| TMDb | allgemeiner Film-/Serienprovider, mehrsprachig, unterstützt Multi-Suche |
| TVDb | Serien, Staffeln, Episoden, Serien-Artwork |
| OMDb | optionaler Fallback mit API-Key |
| IMDb | optionaler Fallback über GraphQL-Zugriff |
| TVmaze | Serien-Fallback |
| AniList | Anime/Manga |
| Kitsu | Anime/Manga |
| FanArt.tv | Artwork-Fallback nach erfolgreichem Match |
| TVSpielfilm | deutsche Live-/EPG-Suche |
| fernsehserien.de | deutscher Live-/EPG-Bild-Fallback |
| Wikimedia/Wikipedia | Bild-Fallback für Live-/EPG |

---

## 6. Normalisierte Provider-Felder

Konstanten liegen in:

```text
e2MDB/provider/Consts.py
```

Zentrale Feldnamen:

| Feld | Key |
|---|---|
| Provider | `provider` |
| Titel | `title` |
| Originaltitel | `original_title` |
| Jahr | `year` |
| IMDb-ID | `imdb_id` |
| Medientyp | `media_type` |
| Release | `released` |
| Altersfreigabe | `age_rating` |
| Genres | `genres` |
| Länder | `countries` |
| Beschreibung | `overview` |
| Laufzeit | `runtime` |
| Bewertung | `vote_average` |
| Stimmen | `vote_count` |
| Cover-URL | `cover_url` |
| Cover-Quelle | `cover_src` |
| Backdrop-URL | `backdrop_url` |
| Backdrop-Quelle | `backdrop_src` |
| TitleLogo-URL | `titlelogo_url` |
| TitleLogo-Quelle | `titlelogo_src` |
| Provider-IDs | `provider_ids` |
| Serien-ID | `series_id` |
| Staffelnummer | `season_no` |
| Staffelname | `season_name` |
| Episodennummer | `episode_no` |
| Episoden-ID | `episode_id` |
| Episodentitel | `episode_name` |
| Cast | `cast` |
| Crew | `crew` |
| Tagline | `tagline` |
| Originalsprache | `original_language` |

---

## 7. Medien- und Aufnahme-Scan

### 7.1 Scanner

```text
e2MDB/E2MDBScanner.py
```

Zentrale Klasse:

```python
class E2MDBScanner(E2MDBHelper)
```

Aufgaben:

- Medienpfade durchsuchen
- Dateinamen und Ordnerstruktur analysieren
- Medienart einschätzen
- Suchvarianten erzeugen
- Provider-Ergebnisse sammeln
- Treffer bewerten
- finale Metadaten erzeugen
- JSON, Bilder und SQLite aktualisieren
- Serien-, Staffel- und Episodendaten auflösen

### 7.2 Pfadmodi

| Konstante | Wert | Bedeutung |
|---|---:|---|
| `PATH_MODE_MOVIE` | `1` | Filme |
| `PATH_MODE_SERIES` | `2` | Serien |
| `PATH_MODE_MOVIE_SERIES` | `3` | Filme und Serien |
| `PATH_MODE_ANIME_SERIES` | `4` | Anime-Serien |
| `PATH_MODE_MANGA_SERIES` | `5` | Manga-Serien |
| `PATH_MODE_ANIME_MOVIE` | `6` | Anime-Filme |
| `PATH_MODE_MANGA_MOVIE` | `7` | Manga-Filme |

### 7.3 Parser

```text
e2MDB/MediaNameParser.py
```

Der Parser extrahiert:

- Titel
- Jahr
- Staffelnummer
- Episodennummer
- Episodentitel
- Serien-/Film-Hints aus Ordnern und Dateinamen
- Anime-/Manga-Hints über Pfadmodus und Ordnernamen

Erkannte Muster sind unter anderem:

```text
S01E02
1x02
Staffel 1
Season 1
(1997)
```

### 7.4 Medien-Suchpipeline

```text
org_path / org_title / EPG-Text / Pfadmodus
  ↓
MediaNameParser
  ↓
create_best_search()
  ↓
create_search_titles()
  ↓
append_search_variant()
  ↓
providers.gather_providers_info()
  ↓
createFinalDict()
  ↓
image_download()
  ↓
JSON / SQLite / Bilder
```

Zentrale Funktionen:

| Funktion | Zweck |
|---|---|
| `guess_category()` | Medienart anhand Titel/Pfad einschätzen |
| `create_best_search()` | besten Suchbegriff erzeugen |
| `divide_filename_infos()` | Titel/Beschreibung aus Dateinamen ableiten |
| `create_search_titles()` | Suchvarianten erzeugen |
| `normalize_provider_search_title()` | Provider-Suchtext bereinigen |
| `append_search_variant()` | Suchvarianten deduplizieren |
| `get_search_results()` | Provider-Suchpipeline |
| `createFinalDict()` | finalen Treffer bestimmen |
| `image_download()` | Bilder in Cache laden |

---

## 8. Google Title Search Helper

### 8.1 Modul

```text
e2MDB/E2MDBTranslator.py
```

Klasse:

```python
class E2MDBTitleTranslator
```

Öffentliche Funktion:

```python
translate_title_for_search(title, target_lang=None)
```

### 8.2 Zweck

Der Helper erzeugt einen zusätzlichen temporären Such-Titel für die Provider-Suche. Er wird eingesetzt, wenn die normale Suche mit Originaltitel und Suchvarianten keine Treffer liefert.

### 8.3 Zielsprache

Die Zielsprache kommt aus:

```python
config.plugins.e2mdb.translateTitleSearchLanguage.value
```

Der Sprachwert wird für Google normalisiert:

```python
"jv"      → "jw"
"he"      → "iw"
"zh_cn"   → "zh-CN"
"zh_tw"   → "zh-TW"
"zh_hans" → "zh-CN"
"zh_hant" → "zh-TW"
```

### 8.4 Ablauf

```text
normale Suchvarianten
  ↓
Provider-Suche
  ↓
bei leerem Ergebnis:
    Titel temporär übersetzen
    Provider-Suche mit übersetztem Such-Titel wiederholen
  ↓
Provider-Ergebnis normal finalisieren
```

Im Scanner:

```python
fallback_search_title = self.append_title_fallback_search_variant(
    fallback_variants,
    fallback_seen,
    search_title,
    last_year,
    org_path,
)
```

Temporäre Resultate bekommen für Debugging und Auswertung:

```python
result["_helper_search_title"] = provider_title
```

### 8.5 Google-Request

```text
https://translate.googleapis.com/translate_a/single
```

Parameter:

```text
client=gtx
sl=auto
tl=<target_lang>
dt=t
q=<title>
```

Runtime-Verhalten:

- Timeout: `8` Sekunden
- User-Agent aus `e2mdbglobals.USERAGENT`
- UTF-8-Decoding mit `replace`
- XSSI-Präfix wird entfernt
- Memory-Cache pro `(title, target_lang)`
- Lebensdauer des übersetzten Titels: aktueller Suchlauf / Prozess-Memory

---

## 9. Cache und Dateistruktur

Basis:

```text
<cachePath>/e2MDB/
```

Cache-Unterordner:

```text
data/
index/
series/
seasons/
backdrop/
cover/
titlelogo/
image/
preview/
fanart/
fernsehserien/
wikimedia/
wikipedia/
results/
```

Temporäre Dateien:

```text
/tmp/e2mdb
```

Logs:

```text
/home/root/logs/e2MDB.log
/home/root/logs/e2MDB-YYYYMMDD-HHMMSS.log.zip
```

---

## 10. SQLite-Datenbanken

### 10.1 `media.db`

Datei:

```text
<cachePath>/e2MDB/media.db
```

Tabelle:

```text
media
```

Felder:

| Feld | Typ | Zweck |
|---|---|---|
| `id` | INTEGER | Primary Key |
| `path` | TEXT UNIQUE | vollständiger Medienpfad |
| `name` | TEXT | Dateiname |
| `ref` | TEXT | Service-/Media-Referenz |
| `title` | TEXT | Titel |
| `short` | TEXT | Kurzbeschreibung |
| `extended` | TEXT | Langbeschreibung |
| `tags` | TEXT | Tags |
| `duration` | INTEGER | Dauer |
| `begin` | INTEGER | Startzeit |
| `size` | INTEGER | Dateigröße |

Index:

```text
idx_media_name ON media(name)
```

### 10.2 `results.db`

Datei:

```text
<cachePath>/e2MDB/results.db
```

Haupttabellen:

```text
e2mdb_media
e2mdb_results
e2mdb_people
e2mdb_media_people
e2mdb_provider_assets
e2mdb_media_asset_map
e2mdb_epg_events
e2mdb_epg_event_asset_map
e2mdb_epg_event_people
e2mdb_provider_asset_people
e2mdb_fetch_queue
e2mdb_channel_stats
e2mdb_cleanup_state
e2mdb_meta
e2mdb_browser_index
e2mdb_browser_series_seasons
e2mdb_browser_series_episodes
e2mdb_browser_index_people
```

### 10.3 `e2mdb_media`

| Feld | Zweck |
|---|---|
| `hash` | eindeutiger Medien-Hash |
| `file_path` | Ordner |
| `file_name` | Dateiname |
| `search_string` | Suchbegriff |
| `search_string_norm` | normalisierter Suchbegriff |
| `metadata_title` | Titel für Anzeige/WebIF |
| `metadata_subtitle` | Untertitel |
| `metadata_overview` | Beschreibung |
| `metadata_genres` | Genres |
| `metadata_provider` | Provider |
| `metadata_provider_ids` | Provider-ID-Mapping |
| `metadata_media_type` | Medientyp |
| `metadata_year` | Jahr |
| `metadata_runtime` | Laufzeit |
| `metadata_rating` | Bewertung |
| `metadata_vote_count` | Stimmen |
| `metadata_cover_path` | lokaler Cover-Pfad |
| `metadata_backdrop_path` | lokaler Backdrop-Pfad |
| `metadata_logo_path` | lokaler Logo-Pfad |
| `metadata_image_path` | lokaler Image-Pfad |
| `metadata_released` | Release |
| `metadata_countries` | Länder |
| `metadata_age_rating` | Altersfreigabe |
| `metadata_cast` | Cast |
| `metadata_crew` | Crew |
| `metadata_season_no` | Staffel |
| `metadata_episode_no` | Episode |

### 10.4 `e2mdb_results`

| Feld | Zweck |
|---|---|
| `media_id` | Referenz auf `e2mdb_media` |
| `provider` | Provider |
| `title` | Provider-Titel |
| `title_norm` | normalisierter Titel |
| `countries` | Länder |
| `released` | Release |
| `media_type` | Medientyp |
| `genres` | Genres |
| `overview` | Beschreibung |
| `vote_average` | Bewertung |
| `vote_count` | Stimmen |
| `cover_url` | Cover-URL |
| `backdrop_url` | Backdrop-URL |
| `provider_ids` | Provider-ID-Mapping |

### 10.5 Browser-Index

Tabellen:

```text
e2mdb_browser_index
e2mdb_browser_series_seasons
e2mdb_browser_series_episodes
e2mdb_browser_index_people
```

Zweck:

- schnelle WebIF-Listen
- Filter nach Medientyp, Jahr, Genre, Anfangsbuchstabe und Person
- Serienansicht mit Staffeln und Episoden
- Detaildaten für Browser-Items

---

## 11. Live-/EPG-Datenmodell

### 11.1 Candidate

Modul:

```text
e2MDB/E2MDBLiveEPG.py
```

Klasse:

```python
class E2MDBEPGCandidate
```

Felder:

| Feld | Zweck |
|---|---|
| `source_key` | stabiler Live-/EPG-Key |
| `source_type` | `epg` oder `live` |
| `service_ref` | Service-Referenz |
| `service_name` | Sendername |
| `event_id` | EPG Event-ID |
| `title` | Originaltitel |
| `search_title` | bereinigter Such-Titel |
| `short_desc` | Kurzbeschreibung |
| `extended_desc` | Langbeschreibung |
| `begin_time` | Startzeit |
| `duration` | Dauer |
| `event_end` | Endzeit |
| `virtual_path` | virtueller Scanner-Pfad |
| `expires_at` | Ablaufzeit |

### 11.2 Source-Key

Der `source_key` wird über Live-/EPG-Eigenschaften gebildet:

```text
source_type | service_ref | event_id | begin_time | normalized_title
```

### 11.3 Live-/EPG Tabellen

`e2mdb_epg_events` speichert kurzlebige Events.

| Feld | Zweck |
|---|---|
| `source_key` | eindeutiger Event-Key |
| `source_type` | `epg` / `live` |
| `service_ref` | Service-Referenz |
| `service_name` | Sendername |
| `event_id` | Event-ID |
| `title` | Originaltitel |
| `title_norm` | normalisierter Titel |
| `search_title` | bereinigter Such-Titel |
| `short_desc` | Kurzbeschreibung |
| `extended_desc` | Langbeschreibung |
| `begin_time` | Start |
| `duration` | Dauer |
| `event_end` | Ende |
| `virtual_path` | virtueller Pfad |
| `json_path` | JSON-Pfad |
| `status` | Status |
| `confidence` | Match-Qualität |
| `last_access` | letzter Zugriff |
| `expires_at` | Ablauf |
| `metadata_*` | Anzeige-Metadaten |

`e2mdb_provider_assets` speichert wiederverwendbare Provider-Assets.

| Feld | Zweck |
|---|---|
| `asset_key` | eindeutiger Asset-Key |
| `provider` | Provider |
| `provider_id` | Provider-ID |
| `media_type` | Medientyp |
| `title` | Titel |
| `original_title` | Originaltitel |
| `year` | Jahr |
| `json_path` | JSON |
| `cover_path` | Cover |
| `backdrop_path` | Backdrop |
| `logo_path` | TitleLogo |
| `image_path` | Preview/Stil |
| `episode_name` | Episodentitel |
| `tagline` | Tagline |
| `genres` | Genres |
| `overview` | Beschreibung |
| `expires_at` | Ablauf |

`e2mdb_fetch_queue` verwaltet Worker-Jobs.

| Feld | Zweck |
|---|---|
| `source_key` | Event-Key |
| `source_type` | Quelle |
| `service_ref` | Service-Referenz |
| `title` | Originaltitel |
| `search_title` | Such-Titel |
| `begin_time` | Start |
| `event_end` | Ende |
| `priority` | Priorität |
| `reason` | Herkunft |
| `state` | Queue-Status |
| `attempts` | Versuche |
| `not_before` | Retry-Zeitpunkt |
| `last_error` | Fehlertext |

---

## 12. Live-/EPG Worker

Modul:

```text
e2MDB/E2MDBEPGWorker.py
```

Der Worker verarbeitet Einträge aus `e2mdb_fetch_queue`.

Ablauf:

```text
pending Queue-Eintrag
  ↓
EPG Event laden
  ↓
Candidate rekonstruieren
  ↓
Skip-/Ignore-Regeln prüfen
  ↓
TVSpielfilm versuchen
  ↓
allgemeine Provider-Suche über E2MDBScanner
  ↓
fernsehserien.de / Wikimedia Bild-Fallback
  ↓
Metadaten und Bilder finalisieren
  ↓
Provider Asset schreiben
  ↓
Event mit Asset verknüpfen
  ↓
Queue-Status setzen
```

Statuswerte:

```text
pending
running
done
no_match
ignored
short_skipped
ended_skipped
failed
```

Queue-Prioritäten kommen aus:

```text
e2MDB/E2MDBPriority.py
```

---

## 13. Bridges und Runtime-Metadaten

### 13.1 Source-Meta

Zentrale Brücke:

```text
e2MDB/E2MDBComponentMeta.py
```

Die UI-Anbindung erfolgt über Source-Metadaten:

```python
source.setMeta(meta)
```

Skin-Converter lesen anschließend:

```python
source.getMeta(key)
```

### 13.2 InfoBar

```text
e2MDB/E2MDBInfoBarBridge.py
```

Aufgaben:

- aktuelles Live-Event erkennen
- Source-Meta für InfoBar setzen
- Queue-Eintrag für fehlende Metadaten erzeugen
- optional Ad-hoc-Lookup starten
- Watch-Time/Zap-Statistik bedienen

### 13.3 EPGSelection / GraphicalEPG

```text
e2MDB/E2MDBEPGBridge.py
```

Aufgaben:

- selektiertes EPG-Event erkennen
- Event in Live-/EPG Datenbank speichern
- vorhandene Metadaten lesen
- fehlende Metadaten queueen
- Source-Meta für Skin-Converter setzen

### 13.4 ChannelSelection

```text
e2MDB/E2MDBChannelSelectionBridge.py
```

Aufgaben:

- markierten Service auslesen
- aktuelles Event bestimmen
- Vorschau-Metadaten setzen
- fehlende Events mit ChannelSelection-Priorität queueen
- ServiceList-Hilfsindizes nutzen

### 13.5 EventView

```text
e2MDB/E2MDBEventViewBridge.py
e2MDB/E2MDBEventViewEPG.py
e2MDB/E2MDBEventViewSimple.py
```

Aufgaben:

- e2MDB EventView für EPG-Events
- e2MDB EventView für Medien/Aufnahmen
- Metadatenquellen für Text und Bilder
- Ad-hoc-Aktualisierung für EPG-Events

---

## 14. Prefill

Module:

```text
e2MDB/E2MDBPrefillManager.py
e2MDB/E2MDBPrefillConfig.py
```

Zweck:

- zukünftige EPG-Events für ausgewählte Sender vorbereiten
- bevorzugte Sender aus Zap-/Watch-Time berücksichtigen
- Queue-Einträge mit Prefill-Priorität anlegen
- No-EPG-Cooldown je Service verwalten

Persistente Dateien:

```text
/etc/enigma2/e2mdb_prefill_services.json
/etc/enigma2/e2mdb_prefill_state.json
/tmp/e2mdb_prefill_request.json
```

Prefill-Ablauf:

```text
manuelle Senderliste + bevorzugte Sender
  ↓
EPG Schritt für Schritt über lookupEventTime()
  ↓
E2MDBEPGCandidate
  ↓
e2mdb_epg_events
  ↓
e2mdb_fetch_queue
  ↓
Worker verarbeitet Provider-Suche
```

---

## 15. Cleanup und SQLite-Wartung

Modul:

```text
e2MDB/E2MDBCleanupManager.py
```

Cleanup bearbeitet Live-/EPG-Daten, Queue-Einträge, Prefill-State und optionale primäre Event-Cache-Dateien.

SQLite-Wartung:

```text
ANALYZE
VACUUM
REINDEX
```

Task-/Timer-Einträge:

```text
e2MDB Live/EPG Cleanup
e2MDB SQLite Maintenance
```

---

## 16. OpenATV Task-/Timer-Integration

In `plugin.py` werden folgende FunctionTimer registriert:

```python
addFunctionTimer(_("e2MDB Refresh"), _("Scan e2MDB media folders"), start_task, stop_task, True)
addFunctionTimer(_("e2MDB Live/EPG Prefill"), _("Prefill selected/preferred Live/EPG metadata"), start_prefill_task, stop_prefill_task, True)
addFunctionTimer(_("e2MDB Live/EPG Cleanup"), _("Remove expired Live/EPG metadata and queue entries"), start_cleanup_task, stop_cleanup_task, True)
addFunctionTimer(_("e2MDB SQLite Maintenance"), _("Optimize e2MDB database"), start_sqlite_maintenance_task, stop_sqlite_maintenance_task, True)
```

---

## 17. WebIF

Modul:

```text
e2MDB/E2MDBWeb.py
```

OpenWebif-Root:

```text
http://<box-ip>/e2mdb/
```

API-Root:

```text
/e2mdb/api/
```

Unterressourcen:

```text
/e2mdb/api/search
/e2mdb/api/details
/e2mdb/api/results
```

### 17.1 Search API

```text
GET /e2mdb/api/search?query=<title>&type=<multi|movie|series|anime|manga>&year=<year>
```

Aufgabe:

- Provider-Suche aus WebIF
- normalisierte Ergebnisliste liefern

### 17.2 Details API

```text
GET /e2mdb/api/details?provider=<provider>&id=<provider_id>&type=<media_type>
```

Aufgabe:

- Provider-Details für einen Treffer laden
- Detaildaten für Editor und Übernahme bereitstellen

### 17.3 Results API

```text
GET /e2mdb/api/results?action=<action>
```

Actions:

| Action | Zweck |
|---|---|
| `i18n` | WebIF-Übersetzungen |
| `list` | Scan-/Medienergebnisse listen |
| `get` | einzelnen Eintrag laden |
| `preview` | Vorschau/Alternativen |
| `rescan` | Einzel-Scan |
| `apply_result` | Provider-Treffer übernehmen |
| `rename` | Datei umbenennen |
| `set_images` | Bilder setzen |
| `image` | Bild ausliefern |
| `play` | Wiedergabe starten |
| `stop` | Wiedergabe stoppen |
| `browser_list` | Media-Browser Liste |
| `browser_item` | Browser-Detail |
| `series_details` | Serien-Details |
| `season_details` | Staffel-Details |
| `browser_status` | Browser-Index-Status |
| `rebuild_browser_cache` | Browser-Index neu aufbauen |

---

## 18. Skin-API

Converter:

```text
Components/Converter/E2MDBEventInfo.py
```

Nutzung:

```xml
<convert type="E2MDBEventInfo">Token</convert>
```

### 18.1 Bild-Tokens

```text
Cover
Backdrop
TitleLogo
Image
Preview
ImageOrPicon
```

### 18.2 Text-Tokens

```text
Title
Subtitle
Overview
Description
InfoLine
Status
Provider
MediaType
Genres
Runtime
Rating
Year
Cast
Crew
AdvDescription
AdvancedDescription
ADV_DESCRIPTION
```

### 18.3 Boolean-Tokens

```text
HasMetadata
HasCover
HasBackdrop
HasImage
```

### 18.4 Meta-Keys

| Meta-Key | Zweck |
|---|---|
| `source_key` | Live-/EPG-/Media-Key |
| `title` | Titel |
| `subtitle` | Untertitel |
| `overview` | Übersicht |
| `description` | Beschreibung |
| `infoline` | kompakte Infozeile |
| `status_text` | Status |
| `provider` | Provider |
| `media_type` | Medientyp |
| `genres` | Genres |
| `runtime` | Laufzeit |
| `rating` | Bewertung |
| `year` | Jahr |
| `cast_short` | Cast-Kurztext |
| `crew_short` | Crew-Kurztext |
| `cover_path` | Cover-Pfad |
| `backdrop_path` | Backdrop-Pfad |
| `titlelogo_path` | TitleLogo-Pfad |
| `image_path` | Preview/Stil |
| `image_or_picon_path` | Image/Picon-Pfad |
| `e2mdb_empty` | leerer UI-Zustand |
| `e2mdb_clear_reason` | Clear-Grund |

### 18.5 Skin-Beispiel: Cover

```xml
<widget source="Event" render="Pixmap"
        position="70,50" size="140,200"
        alphatest="blend"
        scaleFlags="centerScaled"
        backgroundColor="#000000"
        transparent="1"
        condition="config.plugins.e2mdb.epgMetaEnabled.value">
    <convert type="E2MDBEventInfo">Cover</convert>
</widget>
```

### 18.6 Skin-Beispiel: Backdrop

```xml
<widget source="Event" render="Pixmap"
        position="300,50" size="500,281"
        alphatest="blend"
        scaleFlags="centerScaled"
        backgroundColor="#000000"
        transparent="1"
        condition="config.plugins.e2mdb.epgMetaEnabled.value">
    <convert type="E2MDBEventInfo">Backdrop</convert>
</widget>
```

### 18.7 Skin-Beispiel: Text

```xml
<widget source="Event" render="Label"
        position="300,45" size="500,50"
        font="Regular;28"
        foregroundColor="#ffffff"
        backgroundColor="#000000"
        transparent="1"
        condition="config.plugins.e2mdb.epgMetaEnabled.value">
    <convert type="E2MDBEventInfo">Genres</convert>
</widget>
```

### 18.8 Skin-Beispiel: Erweiterte Beschreibung

```xml
<widget source="Event" render="Label"
        position="825,80" size="385,523"
        font="Regular;20"
        foregroundColor="#ffffff"
        backgroundColor="#000000"
        transparent="1"
        valign="top"
        condition="config.plugins.e2mdb.epgMetaEnabled.value">
    <convert type="E2MDBEventInfo">AdvDescription</convert>
</widget>
```

---

## 19. Ignore-Listen

Modul:

```text
e2MDB/E2MDBIgnoreConfig.py
```

Dateien:

```text
/etc/enigma2/e2mdb_ignore_epg_titles.json
/etc/enigma2/e2mdb_ignore_service_names.json
/etc/enigma2/e2mdb_ignore_folder_names.json
```

Verwendung:

- EPG-Titel beim Worker überspringen
- Sendernamen beim Prefill filtern
- generische Ordnernamen beim Parser ausblenden

---

## 20. Logging

Funktion:

```python
write_log(log_text1, log_text2="")
```

Ziel wird über `logTarget` bestimmt:

```text
file       → /home/root/logs/e2MDB.log
debuglog   → Enigma2 Debug Log
both       → beide Ziele
```

Log-Modi:

```text
0 / Off      → deaktiviert
1 / On       → normale Fehler- und Statusmeldungen
2 / Verbose  → ausführliche Diagnose
```

Logrotation:

```text
/home/root/logs/e2MDB-YYYYMMDD-HHMMSS.log.zip
```

Es werden die neuesten fünf Archive behalten.

---

## 21. Debug- und Diagnose-Abfragen

### 21.1 Queue-Zusammenfassung

```sh
sqlite3 /media/hdd/e2MDB/results.db "
SELECT state, reason, priority, COUNT(*)
FROM e2mdb_fetch_queue
GROUP BY state, reason, priority
ORDER BY priority DESC, state, reason;
"
```

### 21.2 Letzte Live-/EPG Events

```sh
sqlite3 /media/hdd/e2MDB/results.db "
SELECT service_name, title, search_title, status,
       datetime(begin_time, 'unixepoch', 'localtime') AS begin,
       datetime(updated_at, 'unixepoch', 'localtime') AS updated
FROM e2mdb_epg_events
ORDER BY updated_at DESC
LIMIT 30;
"
```

### 21.3 Prefill-State

```sh
cat /etc/enigma2/e2mdb_prefill_state.json
```

### 21.4 Manuelle Prefill-Sender

```sh
python3 - <<'PY'
import json
path = "/etc/enigma2/e2mdb_prefill_services.json"
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
print(len(data.get("services", [])))
PY
```

### 21.5 Google Title Search Helper

Bei aktivem Verbose-Log erscheint für erfolgreiche temporäre Titelübersetzungen:

```text
[E2MDBTitleTranslator] translated search title target=<lang> original='<title>' translated='<translated>'
```

---

## 22. Entwickler-Checkliste

Bei Änderungen prüfen:

- `__init__.py`: Config-Eintrag vorhanden
- `setup.xml`: Setup-Eintrag vorhanden
- `de.po` / `e2MDB.pot`: neue Texte vorhanden
- WebIF-i18n: neue WebIF-Texte ergänzt
- Provider: Ergebnisfelder über `Fields` normalisiert
- Scanner: Suchpfade und Pfadmodi berücksichtigt
- DB: neue Daten über passende Tabelle/Index abgebildet
- Live-/EPG: kurzlebige Daten mit `expires_at`
- Worker: Queue-Status und Retry-Logik gepflegt
- Cleanup: neue kurzlebige Daten erfasst
- Skin: neue Anzeige über `E2MDBEventInfo` oder Source-Meta
- Syntaxprüfung aller Python-Dateien
- XML-Prüfung für `setup.xml`
- ZIP-Test nach Erstellung

---

## 23. Kurzreferenz

| Bereich | Modul |
|---|---|
| Config / Logging | `e2MDB/__init__.py` |
| Plugin UI / Hooks / Scheduler | `e2MDB/plugin.py` |
| Setup UI | `e2MDB/setup.xml` |
| Medien-Scan | `e2MDB/E2MDBScanner.py` |
| Parser | `e2MDB/MediaNameParser.py` |
| Provider-Orchestrierung | `e2MDB/E2MDBProviders.py` |
| Provider-Felder | `e2MDB/provider/Consts.py` |
| SQLite | `e2MDB/E2MDBDatabase.py` |
| Google Title Search | `e2MDB/E2MDBTranslator.py` |
| WebIF/API | `e2MDB/E2MDBWeb.py` |
| Live-/EPG Modell | `e2MDB/E2MDBLiveEPG.py` |
| Live-/EPG Worker | `e2MDB/E2MDBEPGWorker.py` |
| Prefill | `e2MDB/E2MDBPrefillManager.py` |
| Cleanup | `e2MDB/E2MDBCleanupManager.py` |
| Source-Meta | `e2MDB/E2MDBComponentMeta.py` |
| InfoBar | `e2MDB/E2MDBInfoBarBridge.py` |
| EPG | `e2MDB/E2MDBEPGBridge.py` |
| ChannelSelection | `e2MDB/E2MDBChannelSelectionBridge.py` |
| EventView | `e2MDB/E2MDBEventViewBridge.py` |
| Skin-Converter | `Components/Converter/E2MDBEventInfo.py` |
