# The bridge contract

What a bridge executable must do so that `BarWidget.qml` can drive it. This file is
the specification the new bridge (`kokko_mpd/`) is written against, and the
contract tests in `tests/contract/` check it -- against the frozen `bin/mpd-bridge`
today, against the new bridge from phase 2 on:

```sh
python3 tests/contract/run.py                    # bin/mpd-bridge
python3 tests/contract/run.py --bridge <file>    # any other bridge executable
```

Where the old bridge breaks a rule written here, the test is marked
`legacy_differs` and reported as an *expected failure* for it; for any other bridge
it is an ordinary test. Those places are listed at the end.

## Process

- Started by the widget as `python3 <bridge-file>` (interpreter, not shebang -- a
  checkout without the executable bit must work). Standard library only.
- One JSON object per line on stdout, UTF-8. A title that cannot be encoded must not
  end the stream (old bridge: `errors="replace"`).
- stderr is free text; the widget logs every line via `console.warn`. Nothing on
  stderr is parsed.
- stdin EOF or `quit` → close every MPD connection and exit with code 0. SIGTERM (the
  shell's kill) must not leave child processes behind.
- A closed stdout (broken pipe) ends the bridge quietly, without a traceback.
- The bridge holds no state the widget depends on across a restart, apart from the
  cache directory (below). The widget restarts a dead bridge after 2.5 s and answers
  its own pending queries with `bridge exited`.

For the tests, the bridge file must also be loadable as a module and expose
`main() -> int` (`tests/contract/launch.py`). Tuning knobs come in as
`$KOKKO_MPD_TUNING` (JSON object); the old bridge gets them written onto its module
globals. Names: `HEALTH_INTERVAL`, `HEALTH_TIMEOUT`, `CMD_IDLE_RENEW`, `CMD_TIMEOUT`,
`MIN_ROUND_ALIVE`, `RADIO_API`, `RADIO_TIMEOUT`, `RADIO_GRACE`.

## Files

| Path | What |
|---|---|
| `$XDG_CACHE_HOME/kokko-mpd/` (default `~/.cache/kokko-mpd/`) | cover cache (`<20 hex>.<ext>`, written as `.part` + rename) and `recent.json` |
| `$XDG_CONFIG_HOME/mpd/mpd.conf`, `~/.mpdconf`, `/etc/mpd.conf` | read only, for `music_directory` (cover file fallback) when `musicRoot` is empty |

## Input (stdin)

One line each, `verb` or `verb SP rest`. **Anything malformed is ignored without an
answer**: unknown verbs, bad JSON, a JSON value that is not an object, a number that
does not parse, an unknown option name. Unknown keys inside a JSON payload are
ignored.

| Line | MPD | On a lost reply |
|---|---|---|
| `config {"host","port","password","musicRoot"}` | (re)connect, see below | -- |
| `toggle` | `status`, then `pause 1` (playing) / `pause 0` (paused) / `play` (stopped) | repeated |
| `play` · `pause` · `resume` · `stop` | `play` · `pause 1` · `pause 0` · `stop` | repeated |
| `next` · `prev` | `next` · `previous` | **repeated** (deliberate: a doubled skip beats a dead button) |
| `seek <seconds>` | `seekcur <s with 3 decimals>` | repeated |
| `volume <n>` | `setvol <int(n) clamped 0..100>` | repeated |
| `setopt <repeat\|random\|single\|consume> [v]` | `<name> <v or 0>` | repeated |
| `play_id <id>` | `playid <id>` | repeated |
| `update [path]` · `rescan [path]` | same, path as one argument | **not** repeated |
| `refresh` | re-read state, announce only if changed | -- |
| `cmd <json>` | one mutation, see below | never repeated |
| `query <json>` | one query, see below | -- |
| `quit` | shut down | -- |

Every transport line is followed by a state refresh straight away (the idle push
comes later and is then a no-op).

### `config`

- Empty `host` → `$MPD_HOST` (with its `password@host` spelling; a password given in
  `config` wins) and `$MPD_PORT` when `port` is missing or 0. Otherwise `127.0.0.1`.
- A `host` starting with `/` or `~` is a unix socket path, `@name` an abstract
  socket. `port` defaults to 6600.
- `musicRoot` is applied on **every** `config`, even when the server stays the same.
  Empty → read `music_directory` from `mpd.conf`; set and not a directory → the cover
  file fallback is off (no silent fallback to `mpd.conf`).
- Same target and password while connected → nothing happens (no reconnect).
- Otherwise: everything open is dropped (`disconnected` with
  `error: "settings changed"` if it was connected), then a fresh connect.
  Connections that come up for the old target after the change are never published.

### `cmd` ops (`{"op": ..., ...}`)

| op | fields | MPD |
|---|---|---|
| `playid` | `id` | `playid` |
| `playpos` | `pos` | `play <pos>` |
| `add` | `uri` | `add` |
| `addplay` | `uri` | `status`; `add`; `status`; `play <old length>` if something was added |
| `insert` | `uri` | `status`×2; `add`; `status`; `move <start>:<end> <current+1>` if that is earlier |
| `remove` | `id` | `deleteid` |
| `move` | `from`, `to` | `move` |
| `clear` · `shuffle` | -- | same |
| `crop` | -- | keep only the playing song: `delete <pos+1>:<len>` then `delete 0:<pos>`; nothing playing → `clear` |
| `findadd` · `findplay` | `filter` | `findadd <expr>`; `findplay` then `play <old length>`; nothing added → `ack` "nothing in the library matches that any more" |
| `searchadd` | `term`, optional `tag` | `searchadd (any contains 'term')` or `(tag =~ '(?i)<escaped>')`; nothing added → `ack` "nothing in the library matches “term”" |
| `favorite` | `uri`, `on` (default true) | `playlistadd favorites` unless present / `playlistdelete favorites <pos>` from the end |
| `favoritefilter` | `filter`, `on` | `find` (≤500 rows), then like `favorite` per song |
| `loadplaylist` · `saveplaylist` · `rmplaylist` | `name` | `load` · `save` · `rm` |
| `renameplaylist` | `name`, `to` | `rename` |
| `playlistadd` | `name`, `uri` | `playlistadd` |
| `playlistdelete` | `name`, `pos` | `playlistdelete` |
| `playlistclear` | `name` | `playlistclear` |

An unknown op, or a missing required field, sends nothing and causes no refresh.
After every executed op: state refresh. An MPD `ACK` → event `ack`, the connection
stays. A value containing CR, LF or NUL is refused before anything is sent (→ `ack`).

**Filters** (`filter` is a list of `[tag, value]`, `regex` a list of `[tag, pattern]`):
one argument, `(tag == 'value')`, several joined as `((a) AND (b))`, regex as
`(tag =~ 'pattern')`, `added_since` as `(added-since 'value')`. Inside the quotes
`\` and `'` are backslash-escaped, then the whole argument goes through the
protocol's `"…"` quoting. MPD < 0.21: positional `tag value …`; regex refused
("regexp filters need MPD 0.21 or newer"), `added-since` refused below 0.24.

### Queries (`{"id", "kind", "channel"?, ...}`)

Every query is answered by exactly **one** `result` event with its `id`, whatever
happens (see *Guarantees*). Common field `limit` (1..20000, default 20000); answers
that grow with the library are read in windows of 1000.

| kind | fields | rows |
|---|---|---|
| `queue` | -- | songs (`type:"file"`, with `id`, `pos`), `playlistinfo <range>` |
| `lsinfo` | `path` | `type` `directory`/`playlist`/`file`, sorted: folders, playlists, files, then name case-insensitively |
| `list` | `tag` (default album), `filter`, `search` | `{type:"value", value}`, no empty values, sorted case-insensitively; `search` → `(tag =~ '(?i)<re.escape(term)>')`, joined with the filter by AND; fallback to `contains` when MPD refuses the regex |
| `find` | `filter`, `regex`, `added_since`, `sort` | songs; no condition at all → `[]` without asking. `sort:"track"` (disc, missing disc = 1; track; file), `"date"` (ascending, file), `"added"` (descending) |
| `search` | `term` | songs with `label` and `comment`, ranked (below); empty term → `[]` |
| `counts` | `filters: [{tag, value}]` (≤120) | one number per filter (`count tag value`), `null` for a refused or malformed one |
| `songinfo` | `file` | the song with **every** tag MPD sends |
| `art` | `uri`, `album`, `albumartist` | `[{type:"art", path}]`, path `""` when there is no cover; no `uri` → `[]` |
| `listplaylists` | -- | `{type:"playlist", playlist, last-modified}`, sorted case-insensitively |
| `playlist` | `name` | songs of a stored playlist (ranges from 0.24 on) |
| `favorites` | -- | songs of `favorites` with `type:"favorite"` |
| `recent` | -- | from `recent.json`, newest first, `type:"recent"`, works without MPD |
| `radio_search` | `search`/`term`, `country`, `tag`, `limit` (≤200) | stations, see *Radio* |

Unknown kind → `error: "unknown query: <kind>"`.

**Song rows** carry only `type file id pos title artist albumartist album track
disc date genre composer performer name time duration last-modified added`
(lower-case keys; repeated tags joined with `", "`).

**Search ranking**: per row the best match decides: `match` (tag, or `file` for a
path-only hit), `pos` (0 whole value, 1 word start, 2 inside a word), `rank` =
`pos*10 + tagrank` (title 0; artist/albumartist 1; album/name 2;
genre/composer/performer/date 3; label/comment 4; file 4), `inword` (the word or
folder the term sits in). Stable sort by rank. A row that matched only a tag the
answer does not carry (a MusicBrainz id) is dropped.

**Channels**: a request with a non-empty `channel` that is still waiting when a newer
request on the same channel arrives is not run; it is answered with
`{rows: [], dropped: true}` and no `error`. No channel, or different channels: never
superseded. The request already running is not interrupted.

### Radio

`radio_search` asks `RADIO_API + /json/stations/search` with `name` (only if given),
`limit`, `hidebroken=true`, `order=votes`, `reverse=true`, `countrycode`, `tag`
(urlencoded) and a `User-Agent` naming kokko.mpd. Nothing to ask (no name, country
or tag) → `[]` without a request. Rows only for `lastcheckok == 1` and a plain
`http(s)` `url_resolved`; fields `name url_resolved codec bitrate country
countrycode lastcheckok votes tags homepage`, `bitrate`/`votes` as numbers. Errors
(HTTP status, not JSON, not a list, timeout) → `error`, never a `disconnected`.
It never touches MPD. The playing stream's logo is looked up via
`/json/stations/byurl` (favicon candidate chain) and announced as `art`.

## Output (stdout)

| event | fields | when |
|---|---|---|
| `connected` | `version`, `target` | command + idle connection are up |
| `disconnected` | `error`, optional `target`, `retryIn` | a connect failed (with `retryIn`) or a connection was lost/dropped |
| `state` | `status{}`, `song{}` | after connect, after every idle wake and command -- **only when different from the last one announced** (reset by a disconnect) |
| `art` | `uri`, `path`, `mime` | cover of the current song changed; `uri:""`, `path:""` when there is no song |
| `result` | `id`, `kind`, `channel`, `rows[]`, optional `error`, `truncated:true`, `dropped:true` | one per query |
| `database` | -- | MPD's `database` idle event |
| `health` | `ok`, `detail`, `target`, (`fails` when false) | the greeting probe changed its verdict |
| `ack` | `error` | an MPD `ACK` on a command/mutation, a refused value, a findadd/searchadd that added nothing |

`status` and `song` are MPD's own `status`/`currentsong` with lower-cased keys and
repeated keys joined by `", "`. The widget reads (among others) `state`, `elapsed`,
`duration`, `volume`, `repeat`, `random`, `single`, `consume`, `song`, `songid`,
`playlistlength`, `updating_db`, `bitrate`, `audio` and the song tags.

## Connections and timing

- **command** connection (timeout `CMD_TIMEOUT` 10 s) and **idle** connection (no
  timeout, TCP keepalive, `TCP_NODELAY`), both opened per round, the round
  announced only if the settings did not change meanwhile.
- idle subsystems: `player mixer options playlist update database`. Not
  `stored_playlist`: a star set by another client shows up at the next track change.
- reconnect backoff 1 s doubling to 15 s; reset by new settings and by a round that
  stayed up ≥ `MIN_ROUND_ALIVE` (5 s).
- the command connection is replaced before use once idle for `CMD_IDLE_RENEW` (45 s;
  MPD's `connection_timeout` is 60 s, and a write to a socket MPD closed succeeds).
- **query** connection opened on the first query (`binarylimit 262144`), two
  attempts per query (a stale socket is replaced quietly).
- **art**: own short-lived connection per cover (`binarylimit 262144`), order
  `albumart` → local file (`music_directory` / `musicRoot`, URI checked against the
  root with `realpath`) → `readpicture`; ≤ 12 MiB; a "no cover" is remembered until
  the next `database` event; cache keyed by album+albumartist+directory, 96 files.
- **health**: every `HEALTH_INTERVAL` (20 s) a separate connection waits
  `HEALTH_TIMEOUT` (3 s) for the greeting; `HEALTH_FAILS` (2) misses in a row →
  `health ok:false`, once; the next greeting → `ok:true`, once.

## Retry rules (the ones that protect the user's queue)

- A command whose write failed reached nothing → sent again on a fresh socket.
- A command whose reply was lost: repeated only if marked repeatable (table above);
  otherwise the connection is dropped and `disconnected.error` ends in
  `(sent, reply lost -- not repeated)`.
- The unit of retry is the single command, never the callback around it: a
  `findadd` inside `findplay` is sent once even if the `status` after it is retried.

## Guarantees the widget relies on

1. Every query gets exactly one `result` -- superseded, waiting during a reconnect or
   settings change, failed, or answered.
2. A `dropped` result is forgotten by the widget without calling back.
3. Nothing is announced as connected to a server the settings no longer name.
4. A mutation is never sent twice because of a lost reply.
5. Nothing is written to MPD that the widget did not ask for. (The repeat/consume
   rule -- `setopt consume 0` when both are on -- lives in the widget, not here.)

## Where the old bridge differs (`legacy_differs`)

| Test | Old behaviour | Rule |
|---|---|---|
| `Startup.test_nothing_is_dialled_before_the_first_config` | dials `127.0.0.1:6600` when it starts, before the widget's `config` arrives | connect only after the first `config` |
| `ServerHangsUp.test_the_query_in_flight_is_answered_when_the_settings_change` | a query running while the settings change never gets a `result` (guarantee 1) | answer it with an `error` or `dropped` |
