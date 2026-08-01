# e2MDB Backend Phase 10q - Strict Landscape Artwork Separation

## Goal

Portrait poster/cover artwork must never be used as landscape preview artwork in Live/EPG, ServiceList, EventInfo converters or SimpleEventView.

## Changes

- Backend Live/EPG metadata now filters `metadata_backdrop_path` and `metadata_image_path` through a strict landscape-only selector.
- The Live/EPG artwork downloader does not store known poster/cover URLs as generic `image_path`.
- `E2MDBSkin.build_epg_skin_data()` filters landscape widgets so poster paths cannot leak into `backdrop`, `image` or `image_or_picon`.
- `E2MDBEventInfo` filters Backdrop/Image/Preview/ImageOrPicon converter paths and rejects known poster/cover paths there.
- `E2MDBServiceListPreview` filters ServiceList preview paths and keeps `metadata_cover_path` portrait-only.

## Intended mapping

- `metadata_cover_path`: portrait poster/cover only.
- `metadata_backdrop_path`: landscape backdrop/fanart only.
- `metadata_image_path`: landscape episode still/preview only.

If no known landscape artwork exists, landscape widgets stay empty or use their neutral default background. They must not fall back to a poster.
