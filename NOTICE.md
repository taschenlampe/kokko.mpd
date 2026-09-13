# Origin / Attribution

`bin/mpd-bridge` is taken from the plugin **omajam** by Nathan Ollerenshaw (matjam),
file `bin/omajam-mpd`, MIT licence, Copyright (c) 2026 Nathan Ollerenshaw
(https://github.com/matjam/omajam).

Changed compared to the original:

* Docstring extended by this origin note.
* Cache directory `~/.cache/omajam` → `~/.cache/kokko-mpd`.
* Two commands added: `playlistdelete {name,pos}` and `playlistclear {name}` —
  removing a single track from a saved playlist, or emptying it (MPD knows these,
  the original never wired them up).
* The caller is this plugin's `BarWidget.qml` instead of the shell plugin service.

`Format.js` is taken from omajam as well (unchanged, MIT, same copyright holder).

Everything else (`BarWidget.qml`, `Panel.qml`, `manifest.json`) is original work.
