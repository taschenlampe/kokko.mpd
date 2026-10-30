# Queue mockups

Design proposals for the queue, **composited onto the real panel** rather than
drawn from scratch: the screenshot in `docs/panel-queue.png` keeps its header,
chips, transport and footer; only the list region is re-drawn. So the fonts
(JetBrainsMono Nerd Font), the palette and the row grid are the panel's own, and
what changes on screen is exactly the list.

The queue in the first three pictures is the one from the screenshot (two ADULT.
albums, `#130/147`, the playing track in the middle of the second one). The mixed
one uses real tracks from the library.

## The four

| file | idea | what it costs |
|---|---|---|
| `queue-1-said-once.png` | artist · album printed **once per run**, a thin rule in the gutter spans it | nothing — same rows, same heights, no new row type |
| `queue-2-mini-album.png` | an **album band**: name, artist, `tracks · total time`, then its tracks | one row per album (~33 px) |
| `queue-3-past-collapsed.png` | bands **plus** the played past: albums behind the playhead collapse to a single dim line, tracks above it dim | negative — a 147-entry queue gets shorter |
| `queue-4-mixed.png` | the same bands in a queue of **different artists** — runs of one stay plain rows | nothing; the list self-balances |

## The rule that keeps it from becoming noise

Group **consecutive runs**, not albums, and only from a run length of 2 (or 3).
A run of one keeps today's flat row with `artist · album` inline — which is what
`a` on a search hit produces, and the normal case for this player. `A B A` is two
groups for `A`; that is the truth about the queue and needs no special case.

A queue of albums ends up almost all bands, a shuffled queue almost none, and
both look like `queue-4-mixed.png` does in parts: bands and plain rows in the
same list — which is already how the search tab draws headers, groups and tracks.

## Visual language

- The band is **bold fg** with a hairline above, uppercase — the search tab's
  group row plus a rule. The accent stays what it is today: the playing row and
  its bar. Accent on every band would dilute the one thing that has to be seen
  at a glance.
- The band carries artist + `n · total`. Its tracks give up the second column
  entirely — that column is what the band replaced.
- Rows keep their existing metrics: 26 px + 1 px spacing, title 40 %, sub 44 %,
  duration at the right third, the two glyph buttons only on hover / on the
  playing row.

## Implementation notes

- `header` and `group` rows already exist and are already skipped by
  `isSelectable()`, `firstSelectable()` and `step()`; the delegate already draws
  `header` (dim caption) and `group` (bold accent title, sub, right count). A
  band is a `group` row with a rule, not a new list.
- The one real trap: `moveRow()` assumes **row index == MPD position** ("in the
  queue a row index is its MPD position"). With bands in the list that is false —
  move over `row.pos`, never over the delegate index.
- Queue rows already carry `pos`, `album`, `artist`, `albumartist`, `track`,
  `time`; nothing new has to travel from the bridge.

## Second round: the cover in the band

Prompted by a proposal that puts a mini cover and track numbers into the header.
Same base, same grid; the covers are the real ones, pulled through the bridge's
`art` query and therefore already in `~/.cache/kokko-mpd`.

| file | idea | verdict |
|---|---|---|
| `queue-5-inline-cover.png` | cover inline in the band, numbered tracks indented under it, year on the right | three left edges (cover 29, name 63, titles 98); the year says less than a count |
| `queue-6-split-gutter.png` | 30 px gutter: cover on the band row, track numbers under it, a rule as bracket, name and titles share one edge | the cleanest of the two — at the price of indenting every row by 30 px |
| `queue-7-cover-sizes.png` | the same band with a 16 / 20 / 24 / 30 px cover | 16 px is invisible, 20 px is a smudge, 24 px is the minimum, 30 px overflows the 26 px row |
| `queue-8-numbers.png` | band without a cover, track numbers in a narrow lead column | numbers are free information inside a run, but they cost a 4-character indent |

The strongest argument against the cover is already on screen: the panel's own
header shows the *playing* album at 127 px, 60 px above the list. A 24 px copy of
the same artwork under it is the weakest thing in both designs; for every other
album the thumbnail is a colour cue, not a cover.

Each distinct album costs one `art` query the first time it is seen (cached
afterwards, keyed by directory + album + albumartist — the same key a band would
group by).

## Third round: one design, a mixed queue

The recommended variant, on the same mixed queue as `queue-4`, plus a comparison
with the same queue under the plain band treatment.

| file | what it is |
|---|---|
| `queue-9-mixed-final.png` | bands, track numbers, played albums collapsed, past dimmed — the proposal |
| `queue-11-mixed-nested.png` | the same, but the band sits on the outer edge and its tracks are nested (one narrower indent, singles untouched) |
| `queue-10a-bands.png` | the same queue with bands only (`queue-4` treatment), for reference |
| `queue-10-compare.png` | `queue-10a` above, `queue-9` below — same queue, two treatments |

`queue-10-compare.png` is the argument: both panels hold the same queue. In the
lower one the played album collapsed to a single line, so the playhead sits four
rows higher and eight tracks after it are in the window instead of three. Same
window, more of what is coming.

What changes on screen, in one sentence per rule:

- a run of one stays a plain row with `artist · album` in the second column;
- a run of two or more gets a band: uppercase, bold `fg`, 1px rule above, `n · total`
  on the right;
- inside a band the second column is empty — the band already said it;
- the played part of the queue is dimmed, and albums entirely behind the playhead
  collapse to `› NAME  ·  n played · total`;
- numbers only inside a band (the gutter), singles keep the outer edge.

## Fourth round: search and the album view

The same language, applied to the two views that repeat the most.

`queue-12-search.png` — search, on the real panel (`docs/panel-suche.png` as the base):

- the three section labels (`Artists`, `Albums`, `Tracks — 34 hits`) go **dim,
  uppercase, letterspaced** with a rule above — the settings-tab header, not the
  accent. The accent stays what it is for the queue: the playing row.
- group rows stay as they are: bold `fg`, artist in the second column, count on
  the right. They already read as bands.
- the hits below them drop the repetition: `artist · album` is printed once per
  run of the same album, not on all 34 rows of Black Sabbath.

`queue-13-album.png` — one album, on the queue base with the breadcrumb added:

- rows are `number · title · duration` and nothing else; the album is the frame,
  so the second column has nothing left to say and the artist moves to the footer
  (`ADULT. · 10 tracks · 48:54`) where the entry count was;
- a multi-disc album gets a dim `DISC 2` line where the band would be — the same
  row type one level down;
- the playing track keeps the accent, the plate and the bar.

Caveats, so nobody builds on a lie: the chips in `queue-13` still show *Queue*
as the active tab (they come from the queue screenshot), and the breadcrumb is
drawn by hand — in the app it is `breadcrumb()`, so an album frame already puts
the album name up there.

## What the code says about these pictures

Two review passes over `Panel.qml` (read-only). The pictures stand; the notes
below are what a build has to get right. The first one was a bug that existed
until it was fixed: the album view is quiet now, the rest of this is still ahead.

### Search

- `rowSub(row)` (`Panel.qml:1109`) gets only the row. "Said once" needs the row
  before it — pass the index (or a flag set while building), but do not hang the
  flag on the row itself: the track rows in the Tracks section are the raw song
  objects from the bridge (`Panel.qml:821`).
- `matchNote()` (`841`) returns "" on purpose for a match on title, artist or
  album, *because* that value is already on the row (`834–840`). Suppress the
  album and an album match loses its only visible reason — the run rule has to
  leave that one alone.
- `groupHits()` groups by `album` alone (`793`, `813`). A run key must be
  album + artist; when the artist changes inside one album (compilation), the
  artist stays on the row.
- The right column of a group is `total`, MPD's track count (`1154–1162`), not
  the hit count — two different numbers that look alike.
- The section labels draw with `accent` (`2378`); dimming them needs its own
  flag, `settingsHeader` (`2363`) is settings-only.

### The album view

- An album opens as `mode: "find"` with `title: value + " — tracks"`
  (`1310–1313`), and `frameTitle` is that whole string (`144`). The suppression
  at `1135` compared exactly — so it **never fired**: the album name sat on every
  row of the album view, plus `genre` (`1136`). Three rows of noise per track,
  for a string compare. *Fixed:* the frame now carries `album`, the guard
  compares that, the genre is dropped in an album frame, and `case 17` builds
  its frame the way `activate()` does instead of by hand.
- The frame carries the album filter, not the artist (`1310–1313`); the footer's
  artist has to be derived from the rows. They do carry it: `albumartist` is in
  `SONG_FIELDS` (`bin/mpd-bridge:187–199`, the find path at `2309`).
- There is no total time anywhere: sum `row.time` and skip rows without it.
- `track` and `disc` are in the rows but deliberately never displayed (`1141–1142`)
  — the gutter and a `DISC 2` line are possible without touching the bridge.
- Untouched: the accent belongs to `isActiveRow` (`1178–1181`), which keys on the
  song id, not the row index; and the `find` filter stays as it is — filtering on
  `albumartist` or `disc` would silently drop albums with missing tags.
