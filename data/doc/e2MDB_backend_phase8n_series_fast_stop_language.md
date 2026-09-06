# e2MDB Backend Phase 8n

Fixes:

- MediaBrowser series/details/season endpoints no longer build the complete grouped browser list for every click.
- Series and season details use bounded SQL lookup based on browser_key/media_hash.
- Episode Play uses direct media_hash lookup before grouping, so playback commands are queued faster.
- Web season buttons render from the already loaded local inventory without a second API request when possible.
- Web playback stop restores the previously running Enigma2 service instead of leaving a black screen.
- GUI bridge polling interval reduced from 1000 ms to 250 ms.
- Backend provider language is normalized to short provider-compatible ISO-639-1 codes, e.g. de instead of de-DE. This avoids TVDB falling back to English.

Notes:

- A full metadata rebuild is required for existing English provider metadata to be replaced with German metadata.
- If existing rows already have provider_lookup_status done, run scan/provider refresh with only_missing false from the GUI blue button or clear the DB/cache for a clean rebuild.
