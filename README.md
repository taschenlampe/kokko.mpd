# kokko.mpd

**Your MPD in the Omarchy bar.** See what's playing, click for the full player.

[![The player](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/panel-queue.png)](docs/panel-queue.png)

## What it is

A little bar widget for your music: cover + title always visible, a click opens the
full player — queue, search, your whole library, playlists. Mouse-first, keyboard if
you want it.

## Get it running

```
omarchy plugin add https://github.com/taschenlampe/kokko.mpd.git --enable
omarchy plugin enable kokko.mpd --section center
omarchy restart shell
```

That's it. You need a running MPD on `127.0.0.1:6600` (default, no password) —
nothing else. `cava` is optional, it just adds the little spectrum animation.

Open the panel any time with **`SUPER + CTRL + M`**.

<details>
<summary>Prefer a folder you control, or need to update/remove it?</summary>

```
git clone https://github.com/taschenlampe/kokko.mpd.git \
  ~/.config/omarchy/plugins/kokko.mpd
omarchy plugin enable kokko.mpd --section center
omarchy restart shell
```

The folder name must stay `kokko.mpd` — it's how `shell.json` and the CLI find it.

- Installed via Omarchy → update with `omarchy plugin update kokko.mpd`
- Cloned by hand → update with a plain `git pull` in the plugin folder
- Either way → remove with `omarchy plugin remove kokko.mpd`

</details>

## What you get

- **In the bar** — the current track scrolls by while it plays, a tiny live spectrum
runs along, left click = play/pause, middle click = next, scroll = volume.
- **On hover** — a card with cover, draggable progress, big transport buttons.
- **On the wallpaper** (optional) — the same card, sitting on your desktop.
- **The full panel** — queue, search, library, playlists, all in one view.
- **Search like on the web** — results grouped by artist/album as you type, one key
appends a track, album, or artist to the queue.
- **Quick cleanup** — clear a row, clear the queue, or keep only what's playing.
- **Track-change popup** — a brief card (and optional desktop notification) whenever
a new song starts.

<details>
<summary>See it — bar, queue, search, settings, wallpaper</summary>

**Bar and the hover card**

[![Bar and card](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/karte.png)](docs/karte.png)

**Queue** — the playing row stays easy to spot, `t` jumps straight to it.

[![Queue](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/panel-queue.png)](docs/panel-queue.png)

**Search** — grouped hits, `+` appends, `enter` plays.

[![Search](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/panel-suche.png)](docs/panel-suche.png)

**Settings** — everything you'd actually tweak, with a live preview.

[![Settings](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/einstellungen.png)](docs/einstellungen.png)

**A new track starts** — the brief card that shows up under the bar (it can also
send a desktop notification).

[![Card on track change](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/titelwechsel.png)](docs/titelwechsel.png)

**On the wallpaper** — it sits under your windows, on a free spot on the desktop.

[![Card on the wallpaper](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/desktop-card.png)](docs/desktop-card.png)

</details>

## Using it — the short way

**Add something to the queue in three moves:**

1. Press `/` and type (or open the search tab).
2. Press `+` next to a hit — appends the track, album, or artist.
3. Press `enter` instead — plays it right away.

That's really all you need. Everything below is for when you want more.

| Mouse on the bar | Effect |
|---|---|
| left click | play/pause |
| middle click | next track |
| scroll | volume (or seek/track — configurable) |
| hover | shows the card: cover, progress, buttons |

The panel itself opens with **`SUPER + CTRL + M`** — that is the binding this plugin
documents; if you want a different key, bind `omarchy-shell kokko.mpd panel` to your
own.

## Going further

<details>
<summary><strong>All keyboard shortcuts</strong></summary>

| Key | Effect |
|---|---|
| `1`…`8`, `tab` | queue · search · albums · artists · genres · files · playlists · settings |
| `t` | jump to the playing track, from any tab |
| `<` `>` | previous / next track |
| `/` | search — the current category only in albums/artists/genres, the filter in files/playlists, global elsewhere. Case never matters. |
| `j` `k`, `↑` `↓`, `pgup` `pgdn`, `g` `G` | move |
| `enter` | open or play |
| `a` / `A` | append the row / append everything in this list |
| `+` `-` · `,` `.` · `space` | volume · seek 5s · play/pause |
| `z` `R` `c` `v` | repeat · shuffle · consume · single (the four playlist switches) |
| `d` `D` `C` | delete row · clear queue · keep only what's playing |
| `J` `K` `x` | move a queue entry · shuffle the queue |
| `i` / `/` / `s` / `r` | song info · search · save queue · rename playlist |

**Good to know:**

- In search, `↓`/`↑` jump from the field to the first/last hit; `/` brings the field back.
- Digits switch tabs *only* when the search field is empty — otherwise they're search text.
- `esc` backs out step by step: song info → one level → panel.
- Saved playlists need MPD's `playlist_directory` set in `~/.config/mpd/mpd.conf`.

</details>

<details>
<summary><strong>All settings (panel tab 8)</strong></summary>

Click/`enter` toggles, `-`/`+` changes numbers, `enter` on the format row opens a
text field. No JSON editing needed for any of this.

| Setting | Effect |
|---|---|
| Format | `mpc`-style placeholders for the bar label, live preview |
| Show the card (hover) | the popup card when you point at the bar |
| Cover look | 7 styles for the player band — see below |
| Backdrop | how present the cover is behind the panel, 0 = off |
| Show the card (track change) | the brief popup on every new track |
| For how long | how long that popup stays |
| Notification | desktop notification bubble, independent of the popup |
| Show the card (wallpaper) | desktop widget on/off |
| Size | `card` (full) or `mini` (narrow) |
| Position | which screen corner |
| Layer | `desktop` (under windows) or `above` (over them) |
| Dim when paused | fades the wallpaper card while nothing plays |
| Update / Rescan | library maintenance — update after adding music, rescan after deleting or renaming |

**The 7 cover looks** — same data, seven pictures:

[![The seven cover looks](https://github.com/taschenlampe/kokko.mpd/raw/main/docs/cover-looks.png)](docs/cover-looks.png)

`classic` (default) · `sharp` (bigger cover, crisp backdrop) · `hero` (cover as full
background) · `anchor` (big cover, single control row) · `vinyl` (spinning disc) ·
`minimal` (no artwork, one thin line) · `split` (cover as a full-height column)

Connection details (server/port/password) and a few display options live in
`~/.config/omarchy/shell.json` or the CLI — see [docs/internals.md](docs/internals.md)
for every key. No restart needed.

</details>

## Requirements

- A running MPD on `127.0.0.1:6600` (both address and password changeable in settings)
- Nothing else — the bridge is pure Python standard library
- `cava` is optional, only needed for the spectrum animation

## If something looks wrong

- **Nothing happens at all** — is MPD running? `mpc status` in a terminal answers that
  in one line. The widget stays quiet instead of showing an error.
- **The widget vanished from the bar** — a QML syntax error does exactly that, without
  a word. `qmllint` in the plugin folder, or the shell log, says where.
- **The panel is empty but music plays** — the bridge could not reach MPD. Switch the
  server/port in the settings; a running player keeps playing through it.
- **No covers** — MPD needs to know its library: run *Update* in the settings once
  after adding music.

## More

- **[docs/internals.md](docs/internals.md)** — how it works under the hood: the bridge, cover picking, MPD quirks, CLI, Hyprland bindings.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — tests, the pre-commit hook, what not to change.
- Bugs, wishes and the roadmap live at **<https://git.m2control.de/bm/kokko.mpd>**.

## Origin

`bin/mpd-bridge` and `Format.js` are from [matjam/omajam](https://github.com/matjam/omajam)
(MIT, © 2026 Nathan Ollerenshaw) — see `NOTICE.md` for changes. Everything else
(`BarWidget.qml`, `Panel.qml`, `MiniPlayer.qml`, `Visualizer.qml`) is original.

MIT licensed.
