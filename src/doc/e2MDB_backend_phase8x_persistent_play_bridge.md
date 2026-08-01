# e2MDB Backend Phase 8x - Persistent Play/Stop GUI Bridge

This phase fixes web MediaBrowser playback for episode cards.

## Fixes

- Adds a persistent Enigma2 GUI command bridge started from sessionstart.
- Web playback no longer depends on the e2MDB scanner screen being open.
- The bridge polls `/tmp/e2mdb/gui_command.json` every 250 ms and executes `play`/`stop` inside the Enigma2 process.
- `season_details` now returns `media_hash` and `file_path` for every episode card.
- The web UI logs failed play requests to the browser console and keeps the user-visible error popup.

## Runtime flow

```text
Web MediaBrowser episode play
  -> e2mdbd /api/results?action=play&id=<media_hash>
  -> e2mdbd resolves media_hash to file_path in SQLite
  -> e2mdbd writes /tmp/e2mdb/gui_command.json
  -> persistent Enigma2 GUI bridge picks up the command
  -> session.nav.playService(eServiceReference(4097, 0, file_path))
```

## Test

Restart Enigma2 after installing this build because the persistent bridge is registered at sessionstart.

```sh
/etc/init.d/e2mdbd restart
init 4
sleep 3
init 3
```

Then hard reload the browser page and test episode Play/Stop.
