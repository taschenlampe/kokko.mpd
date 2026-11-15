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

**The global search** (tab 2) asks MPD `search "(any contains 'term')"` — that is
every tag there is, in library order. Both halves of that answer have surprised
somebody: searching for the Thin Lizzy song *Southbound* returned seventeen hits,
sixteen of them Millie Jackson tracks whose records carry `Label: Southbound`
(the Stax imprint), and MPD's order put the one title match on the last of the
twenty-seven rows the panel draws. So the bridge ranks the hits by *where* the
term matched (`rank_search_hits`): `title`, then `artist`/`albumartist`, then
`album`/`name`, then `genre`/`composer`/`performer`/`date`, then
`label`/`comment`. Second, **where the term sits inside the value**: the whole
value, the start of a word in it, or the middle of a longer word — `search any` is
a substring match, so "abba" is found in "Sabbath", "Abbado" and "Jabba", and on
this library that made Black Sabbath (34 hits) the biggest group above ABBA (15,
the name that was typed). The place decides first, the tag only breaks the tie; a
row that matched only a tag the answer does not carry (a MusicBrainz id, a sort
name) is dropped — 40 of those 100 hits were nothing but UUID hex, and they turned
six artists into groups for a query they have no part in. The **file path** is the one
exception: MPD's `any contains` matches it too, and on this library that is the only way
"a-ha" is found at all — the artist tag spells it `a‐ha` (U+2010), the folder `a-ha`.
A path hit ranks below every tag (`FILE_RANK`) and says which folder it sits in
(`Folder: a-ha`). The sort is stable, so
hits of one strength keep MPD's order. A search answer therefore carries `label`
and `comment` (`SEARCH_FIELDS`; the browse lists still do not) and adds `match`
(the tag), `pos` (0 exact, 1 word start, 2 mid word) and `rank` (place x 10 + tag)
to every row, plus `inword` (the word the term sits in: "Sabbath" for
"S**abba**th"). The panel names the tag on any row whose match is not already
visible there — `Label: Southbound` — orders the artist and album groups by
their **strongest** hit, so the artist you searched for sits above the coincidence
whatever the hit counts say, and says so on the row where the reason is nowhere
else: a hit inside a longer word is named by its word (`inside “Sabbath”`), and a
group row names the tag it does not print (`Album artist contains “Abbado”` under
`Sergei Prokofiev`) — a title hit needs no line, that track is one section lower, and
a reason that repeats said once: eighty rows out of one folder name it on the first.

Two ideas for shortening the list were dropped after measuring them: ranking
mid-word hits out is arbitrary (it keeps "Abbado" and drops "Sabbath", both
accidents, and the boundary exists only in the code), and "show only exact hits
when an exact hit exists" leaves 2 of 494 hits for "love" — a term with two exact
matches and half the library behind it.

**How much `a` appends.** A group row is an artist or an album, and `a` appends
all of it with one `findadd`. The number beside the row used to be the hits that
produced it, so "Thin Lizzy 1 tracks" appended 137. It is now MPD's own `count`
with the same filter `findadd` takes, one command per group the panel draws (at
most thirty artists and thirty albums), asked as one `counts` query. The rows are
painted when the numbers are back, so no number changes under the pointer; a
filter the server refuses answers `null` and that row keeps saying how many hits
it stands for. The counts ride on their own channel (`counts`), and an answer to a
search that has been replaced is dropped like any other stale answer.

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

## When MPD stops answering

A broken internet-radio stream can wedge MPD so that it accepts connections on its
control port and then never sends its greeting — no CPU use, and
`systemctl --user is-active mpd` still says *active*. No MPD protocol message says so,
and the bridge's `idle` socket has no timeout by design, so the bridge probes the one
thing that has an answer: the banner. `HEALTH_INTERVAL`, `HEALTH_TIMEOUT` and
`HEALTH_FAILS` in `bin/mpd-bridge` are the whole policy (20 s, 3 s, two misses in a
row); the verdict goes out as a `health` event, and every surface asks before it
speaks — the bar, the hover card, the wallpaper card and the band stop presenting the
last title as current. The settings tab offers **Restart MPD** as the one action; the
plugin never restarts the daemon by itself.

How long a recovery takes is one number: a wedged MPD ignores SIGTERM, so
`systemctl --user restart mpd` waits out the unit's stop limit. systemd's default is
90 s; a drop-in of five seconds makes it five — which is what lets a watchdog outside
the plugin restart it in about a second:

    ~/.config/systemd/user/mpd.service.d/override.conf
    [Service]
    TimeoutStopSec=5

Without root, `kill -STOP $(systemctl --user show mpd -p MainPID --value)` freezes the
daemon into exactly that state, and `SIGCONT` (or a restart) releases it — the cheap
way to test the surfaces and the watchdog.

## Structure, command line, fine tuning

Everything else (server, port, password, label width, scroll behaviour, card
duration on hover) lives in the plugin settings or in `shell.json`; changes apply
without a restart.

**Covers** appear where they are seen: big in the band, small in the header, big in
the song info — not in every queue row (with 300 entries that would be 300 MPD
queries and 300 images). The bridge caches them under `~/.cache/kokko-mpd`.

**Spectrum** comes from **cava** (`bin/cava.conf`, 12 bars, 30 fps) and runs while music
plays *and* something shows the bars: the panel's band, the desktop card, or the bar's
play indicator. Because the bar and the card both show a spectrum while playing, cava
now runs whenever something plays — one small process (measured: about 3 % of one
core), one writer for all surfaces, no second cava per card.

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

**Favorites** are rows in MPD's saved playlist `favorites`, not a side file: every MPD
client sees the same stars, and the player can play the list without knowing what a
favorite is. The **widget** owns that set (`favSet`, `favoriteCurrent`) because it owns
the bridge — the panel, the two cards and the band all read it, and every write goes
through `toggleFavorite`, so the surfaces cannot drift apart. The set is asked for when
the connection comes up, once per track change (another client may have starred
something), when the hover card opens, and again 600 ms after a toggle: the mutation and
the query are two connections, and asking too early reads the playlist from before the
write. An album is starred as its filter (`favoritefilter`), because an album row carries
only the one track its cover came from.

The star is drawn where the playing track is named: on the **band** right behind the
title (on the thin `minimal` line as a fourth transport glyph — that line has no column
beside the title), on the **hover card** and on the **card on the wallpaper**. The start
screen's `Favorites` section shows track rows, newest first (the playlist appends, so the
last row is the most recent star); its heading is a door onto the whole list, and `enter`
plays the starred track rather than the album it came from (`l` opens that album).

**The start screen** is five sections and one row count, both switched in the settings
tab (9): New in the library (its two questions are one switch), Recently played,
Favorites, Random, Genres, and 1-6 rows for each (genres stay at two -- they are doors,
not a list). A section that is off is not *asked* either, which is where the speed comes
from: Random and Genres each cost a `list ... limit 3000`. Every switch off is a setting,
so the screen then carries one line pointing at tab 9 instead of standing empty; an empty
*library* still paints nothing, because that is information about the library.

**Settings** live in `~/.config/omarchy/shell.json` in the widget entry — host, port,
password, label format, the card and desktop-card options. The plugin's settings tab
writes them there too (`setBarWidget`), so there is only ever one writer.

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
omarchy-shell kokko.mpd favorite toggle       # star/unstar the playing track (on, off as well)
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
