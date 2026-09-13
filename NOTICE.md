# Origin / Attribution

`bin/mpd-bridge` is taken from the plugin **omajam** by Nathan Ollerenshaw (matjam),
file `bin/omajam-mpd`, MIT licence, Copyright (c) 2026 Nathan Ollerenshaw
(https://github.com/matjam/omajam).

Changed compared to the original:

* Docstring um diesen Herkunftshinweis ergänzt.
* Cache-Verzeichnis `~/.cache/omajam` → `~/.cache/kokko-mpd`.
* Zwei Kommandos ergänzt: `playlistdelete {name,pos}` und `playlistclear {name}` —
  einen einzelnen Titel aus einer gespeicherten Playlist entfernen bzw. sie leeren
  (MPD kennt die dafür, das Original hatte sie nicht angebunden).
* Aufrufer ist dieses Plugins `BarWidget.qml` statt des Shell-Plugin-Service.

`Format.js` ist ebenfalls aus omajam übernommen (unverändert, MIT, gleicher Rechteinhaber).

Alles andere (`BarWidget.qml`, `Panel.qml`, `manifest.json`) ist eigenständig.
