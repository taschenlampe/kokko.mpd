# Herkunft / Attribution

`bin/mpd-bridge` ist eine Übernahme aus dem Plugin **omajam** von Nathan Ollerenshaw (matjam),
Datei `bin/omajam-mpd`, MIT-Lizenz, Copyright (c) 2026 Nathan Ollerenshaw
(https://github.com/matjam/omajam).

Geändert gegenüber dem Original:

* Docstring um diesen Herkunftshinweis ergänzt.
* Cache-Verzeichnis `~/.cache/omajam` → `~/.cache/kokko-mpd`.
* Zwei Kommandos ergänzt: `playlistdelete {name,pos}` und `playlistclear {name}` —
  einen einzelnen Titel aus einer gespeicherten Playlist entfernen bzw. sie leeren
  (MPD kennt die dafür, das Original hatte sie nicht angebunden).
* Aufrufer ist dieses Plugins `BarWidget.qml` statt des Shell-Plugin-Service.

`Format.js` ist ebenfalls aus omajam übernommen (unverändert, MIT, gleicher Rechteinhaber).

Alles andere (`BarWidget.qml`, `Panel.qml`, `manifest.json`) ist eigenständig.
