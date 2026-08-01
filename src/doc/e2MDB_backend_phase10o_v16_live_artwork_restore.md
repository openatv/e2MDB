# e2MDB Backend Phase 10o - v16 Live/EPG Artwork Restore

Stand: 2026-05-31

## Ziel

Die Backend-Umstellung darf die funktionierende v16-ServiceList-Bildlogik nicht verlieren.
Die ServiceList braucht Landscape-Bilder. Portrait-Cover bleiben Cover, dürfen aber nicht als
ServiceList-Preview missbraucht werden.

## Problem

Nach der Worker-Entfernung lieferte der Backend-Live/EPG-Worker zwar Provider-Treffer, aber bei
TVDB wurde häufig nur `metadata_cover_path` gefüllt. `metadata_backdrop_path` und
`metadata_image_path` blieben leer. Dadurch hatte die ServiceList kein Landscape-Bild.

## Änderungen

- TVDB-Artwork-Erkennung erweitert:
  - `artwork` und `artworks` werden nicht mehr nur über URL-Substring ausgewertet.
  - Type-/Name-/Slug-Felder und Bilddimensionen werden zur Klassifikation genutzt.
  - Landscape wird als `backdrop`, Episode-Still als `image`, Portrait als `cover` erkannt.
  - alter v16-URL-Fallback bleibt erhalten.

- BackendProviderEnricher erweitert:
  - FanArt.tv Fill-up wird wie in der v16-Pipeline wieder nach dem Provider-Match angewendet.
  - Live/EPG bekommt bei fehlendem horizontalem Bild wieder Fernsehserien/Wikimedia-Fallback.
  - `image_url` wird separat als Landscape-/Preview-Bild geladen und nicht mehr als Poster
    gespeichert.
  - `backdrop_src` wird nicht mehr fälschlich als URL behandelt.

- Live/EPG DB-Mapping korrigiert:
  - `metadata_cover_path` bleibt Portrait/Poster.
  - `metadata_image_path` nimmt nur echte Preview-/Still-/Landscape-Bilder.
  - `metadata_backdrop_path` bevorzugt Backdrop/FanArt/Series-Backdrop.

- Queue-Kontext erweitert:
  - `short_desc` und `extended_desc` werden in `e2mdb_fetch_queue` gespeichert.
  - Der Backend-Worker bekommt dadurch wieder mehr Kontext für Live/EPG-Fallbackprovider.

## Wichtig

Die ServiceList bleibt read-only und nutzt weiterhin keine Portrait-Cover als Preview.
Der richtige Fix ist, dass das Backend wieder Landscape-Felder befüllt.
