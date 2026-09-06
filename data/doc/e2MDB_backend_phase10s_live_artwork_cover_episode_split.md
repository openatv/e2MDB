# e2MDB Backend Phase 10s - Live/EPG Artwork Cover/Episode Split

Stand: 2026-05-31

## Problem

Nach der Backend-Umstellung konnte ein Live/EPG-Treffer zwar korrekt als `done`
gespeichert werden, aber das Artwork-Mapping war noch zu tolerant:

- generische Preview-/Still-Bilder wurden als `episode.jpg` geladen
- `episode.jpg` wurde zusätzlich als `poster_path` gespiegelt
- dadurch landete `episode.jpg` in `metadata_cover_path`

Beispiel:

```json
"metadata_backdrop_path": ".../backdrop.jpg",
"metadata_cover_path": ".../episode.jpg",
"metadata_image_path": ".../episode.jpg"
```

Das ist falsch. `metadata_cover_path` darf nur Portrait-Cover/Poster enthalten.
Episode-/Still-/Preview-Bilder gehören ausschließlich nach `metadata_image_path`.

## Änderung

`E2MDBBackendProvider.py`:

- Episode-Stills werden nicht mehr nach `poster_path` gespiegelt.
- `cover_url`/`poster_url` mit `cover_src/poster_src == episode` werden nicht mehr als Poster geladen.
- generische `preview_url`/`still_url` werden nur noch dann als `episode.jpg` geladen, wenn `image_src == episode` ist.
- normale Live/EPG-Preview-Bilder werden als `image.jpg` geladen.

`E2MDBBackendDatabase.py`:

- `metadata_cover_path` wird nur noch aus echten Cover-/Poster-Kandidaten gebildet.
- Kandidaten mit `cover_src/poster_src == episode` werden ausgeschlossen.
- `metadata_image_path` bleibt für Landscape-/Still-/Preview-/Episode-Bilder zuständig.

## Ergebnis

Korrekte Trennung:

```text
metadata_cover_path    = poster/cover/series_poster only
metadata_backdrop_path = backdrop/fanart/series_backdrop only
metadata_image_path    = image/preview/still/episode only
```

Bestehende falsche DB-Zeilen müssen neu verarbeitet oder bereinigt werden.
