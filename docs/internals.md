# How kokko.mpd works inside

Implementation notes: how the pieces fit together and why they are built this way.
None of it is needed to *use* the plugin — it is for contributors and the curious.
Using it: [README](../README.md). Tests: [CONTRIBUTING.md](../CONTRIBUTING.md).

## The settings tab

In this tab the band keeps a fixed height (the tallest look's), so cycling through
the looks never moves the rows under your pointer. Everywhere else each look keeps
its own height — there the look does not change while you watch it.

## Searching in a category

**Searching in a category.** In the library tabs, `/` does not search globally but
in *that* category: `list artist "(artist =~ '(?i)iam')"` — MPD does the filtering.
Two MPD quirks are in there: `contains` compares **case-sensitively** in the `list`
filter ("iam" found 5 artists, "IAM" was not among them), the regex operator `=~`
with `(?i)` finds both — hence the regex, with `re.escape` for special characters
and a fallback to `contains` if an MPD was built without regex. And MPD wants the
whole expression as **one** argument (otherwise it splits it at the spaces:
"Invalid unquoted character"). Two categories at once do not work: this MPD
combines filters with `AND` only, not with `OR` — which is exactly the "this
category only" idea. In the *global* search (tab 2) case does not matter anyway,
that is MPD's own search. Files and playlists have no filter in MPD (paths and
playlist names are not tags); there the field filters the loaded list on the spot,
the info line says "4 of 19", and `esc` shows everything again. On MPD 0.20 (NAS)
that becomes an exact match instead of a partial one.

**Cover files.** Over `albumart`, MPD only hands out image files whose names it
knows — in MPD 0.24 that is `cover.*`. A `folder.jpg` next to it is ignored
(measured: `albumart` answers "No file exists" for `folder.jpg`, `album.jpg` or
`Album Art.jpg`; the same bytes give a result as soon as a `cover.jpg` exists).
That is why the bridge searches the music directory itself (path from MPD's
`mpd.conf`, `music_directory`) — by patterns, not by a fixed name list:

| Rank | Matches | Example |
| --- | --- | --- |
| 1 | `cover`, `front`, `folder`, `album`, `album art`, `albumart`, `artwork` (exact) | `folder.jpg` |
| 2 | "front" + "cover/art" anywhere | `Danzig - Danzig - Front Cover.jpg` |
| 3 | "cover", "artwork" or "album art" anywhere | `AlbumArt_{0F838ADF-…}_Large.jpg` |
| 4 | `case`, `scan`, `cd`, `thumb` (exact) | — |

Within a rank the **bigger** file wins (usually the less cropped scan). Names that
usually show the wrong side — `back`, `inside`, `inlay`, `booklet`, `small`, `disc`,
`cd`, `thumb` — are sorted to the end: an album with only a back cover scan shows
that one, but a front always wins. Allowed extensions: `.jpg .jpeg .png .webp .gif
.bmp`. Embedded images come through `readpicture` unchanged; a cover file beats
them, because it is usually the bigger one — the same order MPD itself chooses.
Important: the files have to be readable for the user the bridge runs as (usually
no problem with a library on a NAS).

## Structure, command line, fine tuning

Everything else (server, port, password, label width, scroll behaviour, card
duration on hover) lives in the plugin settings or in `shell.json`; changes apply
without a restart.

**Covers** appear where they are seen: big in the band, small in the header, big in
the song info — not in every queue row (with 300 entries that would be 300 MPD
queries and 300 images). The bridge caches them under `~/.cache/kokko-mpd`.

**Spectrum** comes from **cava** (`bin/cava.conf`, 12 bars, 30 fps) and runs only
while music plays *and* the panel is open — unseen it would be work for nobody.

**The bridge** (`bin/mpd-bridge`, Python, stdlib only) holds the MPD connections
and talks to the widget in one JSON line per direction; state arrives by MPD
`idle` push, not by polling. It is a **child process of the widget**, not a shell
service — under a third-party bar (`charlieras262.floating-bar`) a widget cannot
reach its own service. The price: one bridge per monitor.

**The card** is a layer surface of its own with an input mask only over the card
(the rest stays click-through) and is created only while it is visible. No
`PopupWindow`: a Quickshell popup on a layer surface makes screen recording hang in
this compositor.

**Appending** is always *one* MPD command (`findadd`/`searchadd`), not `add` per
track — an artist with 900 tracks costs one query. Every action reports in the
footer.

**Settings** live in `~/.config/omarchy/shell.json` in the widget entry:
**host, port, password, format, maxWidth, overflow, showStateIcon, showArt, whenIdle, wheelAction, hoverCard, backdrop, osdOnChange, osdHover, osdDuration, notifyTrack, coverLook, desktopWidget, desktopSize, desktopCorner, desktopLayer, desktopDimOnPause**.

**From the command line:**

```bash
omarchy-shell kokko.mpd state                 # JSON: connection, label, panel, card
omarchy-shell -q kokko.mpd toggle             # play/pause (next, prev, stop as well)
omarchy-shell -q kokko.mpd volume +5          # sign = nudge, number = set
omarchy-shell -q kokko.mpd option random      # repeat, random, single, consume
omarchy-shell kokko.mpd panel                 # panel on/off
omarchy-shell kokko.mpd tab artists           # set the tab
omarchy-shell kokko.mpd find "kate bush"      # run a search
omarchy-shell kokko.mpd key j                 # simulate a key press
omarchy-shell kokko.mpd hover on              # show the card without a mouse (screenshots/tests)
omarchy-shell kokko.mpd debug on              # protocol to the shell log
```

**Hyprland** (`~/.config/hypr/bindings.lua`):

```lua
o.bind("SUPER + CTRL + M", "MPD player", "omarchy-shell kokko.mpd panel")
o.bind("XF86AudioPlay", "Play/pause", "omarchy-shell -q kokko.mpd toggle", { locked = true })
o.bind("XF86AudioNext", "Next track", "omarchy-shell -q kokko.mpd next", { locked = true })
o.bind("XF86AudioPrev", "Previous track", "omarchy-shell -q kokko.mpd prev", { locked = true })
```

</details>
