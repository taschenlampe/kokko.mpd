import QtQuick
import QtQuick.Effects
import qs.Commons
import qs.Ui

// The panel: queue, a local search, the library by albums/artists/genres, the
// music tree, and stored playlists -- plus transport, so nothing has to be
// done twice.
//
// The panel owns no MPD state. The bar widget (hostWidget) holds the
// connection; this asks it questions (`query(kind, args, channel, cb)`) and
// sends it commands (`bare`, `mutation`). What it does own is where the user
// is: a stack of frames, one per list, which is what makes "back" mean
// something and what the breadcrumb shows.
//
//   j k ↑ ↓      move            enter / l   open, or play it
//   1 … 7        tab             h ← bs      back one frame
//   /            search          a           append (folder: all of it)
//   i            song details    d D         remove / clear (queue)
//   s            queue to list   r           rename a playlist
//   x            shuffle queue   z r c v     repeat random consume single
//   space p      play/pause      + -         volume
//   esc          close, or leave the prompt / details
Panel {
  id: root
  moduleName: "kokko.mpd"
  manageIpc: false

  property var hostWidget: null
  property Item anchorItem: null

  readonly property var host: root.hostWidget
  readonly property bool up: !!host && host.connected === true

  // How present the blurred cover behind the panel is, 0..1 (0 = off); the widget
  // owns the setting.
  readonly property real backdropLevel: {
    if (root.host === null || root.host.backdrop === undefined) return 0.6
    return Math.max(0, Math.min(1, Number(root.host.backdrop) / 100))
  }

  // Which look the player band shows (chosen in the settings tab or the plugin
  // settings) and what follows from it for the cover behind the panel. The hero
  // and anchor looks carry the cover inside the band, so the panel stays plain.
  readonly property string look: {
    var v = root.host ? String(root.host.coverLook || "") : ""
    return v === "" ? "classic" : v
  }

  readonly property string backdropMode: root.look === "sharp" ? "sharp"
    : (root.look === "hero" || root.look === "anchor"
       || root.look === "minimal" || root.look === "split") ? "off"
    : "blur"

  readonly property color fg: Color.popups.text
  readonly property color bg: Color.popups.background
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)
  readonly property color selBg: Color.menu.selectedBackground
  readonly property color selFg: Color.menu.selectedText
  readonly property color rule: Qt.rgba(fg.r, fg.g, fg.b, 0.12)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ----------------------------------------------------------- where we are
  // Which root the stack hangs off (the chips and the tab keys), and one frame
  // per list: the last is what is on screen, the rest is the way back.
  // Reassigned rather than mutated, because that is what notifies.
  property string tab: "queue"
  property var stack: []
  property var rows: []
  property int sel: 0
  property string infoText: ""
  property bool loading: false

  // "" | "search" | "save" | "rename"
  property string promptMode: ""
  property string promptText: ""
  // What a prompt acts on, captured when it opens. The rename prompt is the reason:
  // it can sit open while the list reloads (a database event, the reload timer, a
  // reconnect), and every reload puts the selection back on the first row -- so
  // re-deriving the name when the field is submitted once renamed row 0 while the
  // footer still showed the name the user had opened.
  property string promptTarget: ""
  // Free text for the local filter (Dateien, Playlists): MPD has no filter for paths
  // or playlist names, so those two lists narrow themselves.
  property string filterText: ""
  // The unfiltered list of the current frame, so the filter can be undone.
  property var allRows: []
  // True when the field was opened with `/` -- the explicit "I want to type"
  // gesture. Only then do digits go into the term while the field is still empty
  // (see the number keys in handleKey).
  property bool promptExplicit: false
  // Where the selection should land once the next list arrives ("first"/"last"),
  // set when the user leaves the search field with ↓ or ↑.
  // Set while the panel is opening: the next queue load lands on the playing track
  // instead of on row one.
  property bool jumpToCurrent: false
  // Index the list should put in the middle. A plain positionViewAtIndex right
  // after a model change does nothing (the rows are not measured yet), so it is
  // done a moment later -- the list is ~20 rows, 120 ms is plenty.
  property int pendingCenter: -1
  property string pendingSelect: ""
  // Set while the pointer rests on a button that is only a glyph: the footer then
  // spells out what it does instead of the key hints.
  property string hoverHint: ""

  // Song details overlay: the row from the `songinfo` query, or null.
  property var detailRow: null
  property string detailTitle: ""
  property bool detailLoading: false

  readonly property var frame: stack.length > 0 ? stack[stack.length - 1] : null

  // Measured layout, published through `state`: the band slot's height and where
  // the list starts. Two looks whose bands differ by 22 px must put the list at the
  // same y in the settings tab -- a picture comparison is ambiguous, a number is not.
  readonly property real bandHeight: bandSlot.height
  readonly property real listY: list.y
  readonly property string frameMode: frame ? String(frame.mode || "") : ""
  readonly property string frameTitle: frame ? String(frame.title || "") : ""
  readonly property string promptLabel: promptMode === "save" ? "Save queue as:"
    : (promptMode === "rename" ? "Rename playlist:"
    : (promptMode === "format" ? "Label-Format:"
    : ((promptMode === "category" || promptMode === "filter")
       ? "filter in " + root.rootFrameFor(root.tab).title + ":" : "search:")))
  readonly property string promptPlaceholder: promptMode === "search"
    ? "tracks, artists, albums …"
    : (promptMode === "format" ? "[%artist% - ][%title%|%filename%]"
    : (promptMode === "category" ? "searches this category only"
    : (promptMode === "filter" ? "filters this list" : "type a name, enter confirms")))

  // Passing the frame in rather than reading `frame` inside this handler: QML
  // re-evaluates dependent bindings *after* the change signal, so `root.frame`
  // here is still the previous one -- which loaded the list the user had just
  // left.
  onStackChanged: root.loadFrame(root.stack[root.stack.length - 1])
  onUpChanged: if (root.up) root.loadFrame()

  // Set when the settings tab starts a library scan, so the confirmation names
  // what happened instead of firing on every scan another client happens to run.
  property bool scanRequested: false

  Connections {
    target: root.host
    function onConnectedChanged() { if (root.host && root.host.connected) root.loadFrame() }
    function onDatabaseRevisionChanged() {
      root.loadFrame()
      // A scan the panel started reports back here -- and the bridge only raises
      // this when the scan actually found something, so it is a real answer.
      if (root.scanRequested) { root.scanRequested = false; root.flash("music library updated") }
    }
    // The queue can change from anywhere (the bar, a bind, another client), so
    // re-read it when MPD says its length moved.
    function onQueueLengthChanged() { if (root.frameMode === "queue") reloadTimer.restart() }
    // MPD answers `findadd`/`searchadd` with a bare OK, so a filter that matches
    // nothing is silent there. The bridge turns that silence into an ack, and the
    // footer repeats it instead of leaving the optimistic "appended" standing.
    function onLastAckChanged() {
      if (root.host && String(root.host.lastAck || "") !== "") root.flash(String(root.host.lastAck))
    }
  }

  // ----------------------------------------------------------------- frames
  function rootFrameFor(tab) {
    if (tab === "queue") return { mode: "queue", title: "Queue" }
    if (tab === "search") return { mode: "search", title: "Search" }
    if (tab === "albums") return { mode: "list", tag: "album", filter: [], title: "Albums" }
    if (tab === "artists") return { mode: "list", tag: "artist", filter: [], title: "Artists" }
    if (tab === "genres") return { mode: "list", tag: "genre", filter: [], title: "Genres" }
    if (tab === "files") return { mode: "files", path: "", title: "Library" }
    if (tab === "settings") return { mode: "settings", title: "Settings" }
    return { mode: "playlists", title: "Playlists" }
  }

  function setTab(name, explicit) {
    root.note("setTab " + name + " (was " + root.tab + ", stack " + root.stack.length + ")")
    root.tab = String(name)
    root.detailRow = null
    root.sel = 0
    root.stack = [root.rootFrameFor(root.tab)]
    if (root.tab === "search") {
      root.openPrompt("search", root.promptText, false, explicit)
      if (root.promptText.trim() !== "") root.applySearch(root.promptText)
    } else {
      root.closePrompt()
    }
  }

  function pushFrame(nextFrame) {
    root.stack = root.stack.concat([nextFrame])
    root.sel = 0
    root.detailRow = null
  }

  function popFrame() {
    if (root.stack.length <= 1) return false
    root.stack = root.stack.slice(0, root.stack.length - 1)
    root.sel = 0
    root.detailRow = null
    return true
  }

  function breadcrumb() {
    var bits = []
    for (var i = 0; i < root.stack.length; i++) bits.push(String(root.stack[i].title || ""))
    return bits.join("  ›  ")
  }

  // ----------------------------------------------------------------- loading
  //
  // One generation per load: MPD answers asynchronously and the user can move
  // on (or the queue can change) before a reply lands, so a reply from an older
  // generation is dropped rather than painted over the frame that is showing.
  // Without this, rows and info came from different lists.
  property int loadGeneration: 0
  property int sentQueries: 0
  property int answeredLoads: 0
  property int staleAnswers: 0

  function loadFrame(which) {
    if (root.stack.length === 0) { root.stack = [root.rootFrameFor(root.tab)]; return }

    var f = (which !== undefined && which !== null) ? which : root.frame
    if (!f) return
    var mode = String(f.mode || "")

    // The settings tab needs no server: reachable even while MPD is down. The
    // generation goes up here too -- otherwise the answer to a query from the tab
    // the user just left lands afterwards and paints its rows over these.
    if (mode === "settings") {
      root.loadGeneration = root.loadGeneration + 1
      root.loading = false
      // Bound, not copied: a changed value should show in the row immediately.
      root.rows = Qt.binding(function() { return root.settingRows })
      root.sel = root.firstSelectable(0)
      root.setInfo("")
      return
    }

    if (!root.up) { root.rows = []; root.setInfo("no connection to MPD"); return }

    var gen = ++root.loadGeneration
    var term = String(f.term || "").trim()
    root.note("load frame=" + mode + " gen=" + gen + " tag=" + String(f.tag || "") + " term=" + term)

    if (mode === "search" && term === "") {
      // Same reason as the settings branch: drop anything still in flight.
      root.loadGeneration = root.loadGeneration + 1
      root.rows = []
      root.loading = false
      // No "type a term" line here: the field's placeholder and the empty list
      // already say it, and the footer keeps its hint.
      root.setInfo("")
      return
    }

    root.loading = true

    function answer(list, error) {
      if (gen !== root.loadGeneration) { root.staleAnswers++; return }
      root.answeredLoads++
      root.loading = false
      if (error !== "") { root.setInfo(error); return }
      // A search is grouped into artists and albums first, so the first thing on
      // screen is something to add wholesale rather than 1309 loose tracks.
      root.allRows = (mode === "search") ? root.groupHits(list) : (list || [])
      root.rows = root.allRows
      // A filter that is still set (Dateien/Playlists) applies to the list that just
      // arrived -- and then shows its own count instead of the frame's.
      if (root.filterText !== "") root.refreshFilteredRows()
      // Leaving the field with ↑ lands at the bottom of the list, with ↓ at the
      // top; the load itself only knows "first hit", so the wish rides along here.
      if (root.pendingSelect === "last") { root.sel = root.lastSelectable(); root.pendingSelect = "" }
      else {
        root.sel = root.firstSelectable(0)
        if (root.pendingSelect === "first") root.pendingSelect = ""
      }
      if (root.filterText === "") root.setInfo(root.infoFor(mode, f, list))

      // Opened on a long queue: put the selection on what is playing and scroll
      // there, so the list does not start somewhere the music is not.
      if (mode === "queue" && root.jumpToCurrent) {
        root.jumpToCurrent = false
        var here = root.currentIndex()
        if (here >= 0) {
          root.sel = here
          root.centerOn(here)
        }
      }

      // An artist (or genre) whose tracks carry no album tag has no album list to
      // show. Rather than leaving an empty frame -- a dead end right where the
      // user was looking for something to play -- fall back to the tracks.
      if (mode === "list" && root.rows.length === 0 && !f.search && (f.filter || []).length > 0) {
        var fallback = { mode: "find", title: String(f.title || "") + " — tracks",
                         sort: "track", filter: f.filter }
        root.stack = root.stack.slice(0, root.stack.length - 1).concat([fallback])
        return                      // the stack change loads the new frame
      }
    }

    root.sentQueries++
    if (mode === "queue") { host.query("queue", { limit: 2000 }, "list", answer); return }
    if (mode === "search") { host.query("search", { term: term, limit: 800 }, "list", answer); return }
    if (mode === "list") {
      host.query("list", { tag: String(f.tag || "album"), filter: f.filter || [],
                           search: String(f.search || ""), limit: 3000 }, "list", answer)
      return
    }
    if (mode === "find") {
      host.query("find", { filter: f.filter || [], sort: String(f.sort || ""), limit: 3000 }, "list", answer)
      return
    }
    if (mode === "files") {
      host.query("lsinfo", { path: String(f.path || ""), limit: 2000 }, "list", answer)
      return
    }
    if (mode === "playlists") { host.query("listplaylists", { limit: 500 }, "list", answer); return }
    if (mode === "plist") {
      host.query("playlist", { name: String(f.name || ""), limit: 3000 }, "list", answer)
      return
    }

    root.loading = false
    root.rows = []
    root.setInfo("unknown view: " + mode)
  }

  function infoFor(mode, f, list) {
    var n = (list || []).length
    if (mode === "queue") return n + " entries"
    if (mode === "search") return n === 0
      ? "no hits for “" + String(f.term || "") + "” — try fewer words"
      : n + (n >= 800 ? "+" : "") + " hits for “" + String(f.term || "") + "”"
    if (mode === "list") return n + " entries"
    if (mode === "find") return n + " tracks"
    if (mode === "files") return String(f.path || "") === "" ? "Library — " + n + " entries" : String(f.path) + " — " + n
    if (mode === "playlists") return n + " Playlists"
    if (mode === "plist") return n + " tracks"
    return n + " entries"
  }

  // ------------------------------------------------------- search grouping
  //
  // The flat hit list is what MPD answers; what a person wants from a search is
  // "that artist", "that album" -- something they can add in one go. So the
  // hits are tallied into artists and albums (most hits first), and the loose
  // songs come last.
  function groupHits(list) {
    var songs = list || []
    var rows = []
    if (songs.length === 0) return rows

    function tally(key) {
      var order = []
      var counts = ({})
      for (var i = 0; i < songs.length; i++) {
        var value = String(songs[i][key] || "")
        if (value === "") continue
        if (counts[value] === undefined) { counts[value] = 0; order.push(value) }
        counts[value] = counts[value] + 1
      }
      order.sort(function(a, b) {
        if (counts[b] !== counts[a]) return counts[b] - counts[a]
        return a.toLowerCase() < b.toLowerCase() ? -1 : 1
      })
      return { order: order, counts: counts }
    }

    var artists = tally("artist")
    if (artists.order.length > 0) {
      rows.push({ type: "header", title: "Artists" })
      for (var a = 0; a < artists.order.length && a < 30; a++)
        rows.push({ type: "group", kind: "artist", value: artists.order[a],
                    count: artists.counts[artists.order[a]] })
    }

    var albums = tally("album")
    if (albums.order.length > 0) {
      rows.push({ type: "header", title: "Albums" })
      for (var b = 0; b < albums.order.length && b < 30; b++) {
        var album = albums.order[b]
        var artist = ""
        for (var s = 0; s < songs.length; s++) {
          if (String(songs[s].album || "") === album && songs[s].artist) {
            artist = String(songs[s].artist)
            break
          }
        }
        rows.push({ type: "group", kind: "album", value: album, artist: artist,
                    count: albums.counts[album] })
      }
    }

    rows.push({ type: "header", title: "Tracks — " + songs.length
      + (songs.length >= 800 ? "+" : "") + " hits" })
    for (var t = 0; t < songs.length && t < 300; t++) rows.push(songs[t])
    return rows
  }

  function isSelectable(row) {
    return !!row && String(row.type || "") !== "header"
  }

  // The first rows as text, for `omarchy-shell kokko.mpd state` -- what the panel
  // is showing, without having to look at the screen.
  function peek(limit) {
    var count = Math.min(root.rows.length, Number(limit) || 8)
    var out = []
    for (var i = 0; i < count; i++) {
      var row = root.rows[i]
      out.push(String(row.type || "?") + "|" + root.rowTitle(row)
        + (row.count !== undefined ? " (" + row.count + ")" : ""))
    }
    return out
  }

  function firstSelectable(from) {
    for (var i = Math.max(0, from); i < root.rows.length; i++)
      if (root.isSelectable(root.rows[i])) return i
    return Math.max(0, root.rows.length - 1)
  }

  // Put a row in the middle of the list, once it can be measured.
  function centerOn(at) {
    if (at === undefined || at === null || at < 0) return
    root.pendingCenter = at
    centerTimer.restart()
  }

  // Where the music is, as an index into the rows at hand: the row carrying the
  // playing song's id. -1 when this list has nothing to do with the queue.
  function currentIndex() {
    if (!root.up || !root.host || !root.host.song) return -1
    var id = Number(root.host.song.id)
    for (var i = 0; i < root.rows.length; i++) {
      var row = root.rows[i]
      if (row && row.id !== undefined && Number(row.id) === id) return i
    }
    return -1
  }

  // t: go to the playing track. From another tab it switches to the queue first --
  // asking for the current track should always work.
  function gotoCurrent() {
    if (root.frameMode !== "queue") {
      root.jumpToCurrent = true
      root.setTab("queue")
      return
    }
    var at = root.currentIndex()
    if (at < 0) { root.flash("no playing track in this list"); return }
    root.sel = at
    root.centerOn(at)
    root.flash("playing track — #" + (at + 1) + "/" + root.rows.length)
  }

  // The list itself, for tests/inspection (`state.panel.visible`).
  readonly property var listView: list

  // Does the key hint fit on its line? `truncated` is QML's own answer, so this
  // needs no screenshot and no guessing at character widths.
  readonly property bool hintTruncated: hintText.truncated

  Timer {
    id: centerTimer
    interval: 120
    repeat: false
    onTriggered: {
      if (root.pendingCenter < 0) return
      list.positionViewAtIndex(root.pendingCenter, ListView.Center)
      root.pendingCenter = -1
    }
  }

  function lastSelectable() {
    for (var i = root.rows.length - 1; i >= 0; i--)
      if (root.isSelectable(root.rows[i])) return i
    return Math.max(0, root.rows.length - 1)
  }

  // A mutation that changes what a list would show: send it, then re-read the
  // frame shortly after so the list reflects MPD rather than what we hoped.
  function mutateAndReload(op, args) {
    host.mutation(op, args)
    reloadTimer.restart()
  }

  Timer {
    id: reloadTimer
    interval: 350
    repeat: false
    onTriggered: root.loadFrame()
  }

  function setInfo(text) { root.infoText = String(text || "") }

  function note(what) {
    if (root.host && root.host.debugProtocol) console.warn("kokko.mpd/panel: " + what)
  }

  // -------------------------------------------------------------- row fields
  function rowTitle(row) {
    if (!row) return ""
    if (row.type === "group" || row.type === "value") return String(row.value || "")
    if (row.type === "playlist") return String(row.playlist || "")
    if (row.type === "art") return String(row.path || "")
    if (row.title) return String(row.title)
    if (row.file) return host.basename(row.file)
    if (row.directory) return String(row.directory).split("/").pop()
    return String(row.value || row.playlist || "")
  }

  // ------------------------------------------------------------- settings
  //
  // The settings tab is a local list -- no MPD query behind it -- so the rows are
  // built here from what the widget reports. Writing goes through the widget,
  // which asks the shell (the owner of shell.json) to change the key, and the
  // shell pushes the new value back: one writer, live, no restart.
  readonly property var settingRows: {
    var h = root.host
    if (h === null) return []
    return [
      // Grouped by surface, in the order the README introduces them. The header
      // rows carry the context, which is why the rows underneath need only a short
      // title -- "Size" instead of "Card size (desktop)". Headers are section
      // labels: the selection steps over them (firstSelectable, step), and the
      // delegate draws them as a dim caption instead of a row.
      { type: "header", title: "In the bar" },
      { type: "setting", kind: "text", key: "format", title: "Format",
        value: String(h.format),
        hint: "mpc placeholders — enter to edit, preview below" },

      { type: "header", title: "On hover" },
      { type: "setting", kind: "bool", key: "hoverCard", title: "Show the card",
        value: h.hoverCard === true,
        hint: "hover the bar label — only while the panel is closed" },

      { type: "header", title: "In the player" },
      { type: "setting", kind: "enum", key: "coverLook", title: "Cover look",
        value: String(h.coverLook || "classic"),
        options: ["classic", "sharp", "hero", "anchor", "vinyl", "minimal", "split"],
        hint: "enter or -/+ cycles through — applies at once" },
      { type: "setting", kind: "int", key: "backdrop", title: "Backdrop",
        min: 0, max: 100, step: 10, value: Number(h.backdrop), suffix: " %",
        hint: "0 turns it off; higher = more present behind the lists" },

      { type: "header", title: "On a new track" },
      { type: "setting", kind: "bool", key: "osdOnChange", title: "Show the card",
        value: h.osdOnChange === true,
        hint: "flashes on every new track — switch it off here" },
      { type: "setting", kind: "int", key: "osdDuration", title: "For how long",
        min: 1000, max: 20000, step: 500, value: Number(h.osdDuration), suffix: " ms",
        hint: "stays that long after a new track — enter shows it now" },
      { type: "setting", kind: "bool", key: "notifyTrack", title: "Notification",
        value: h.notifyTrack === true,
        hint: "desktop bubble (app MPD) — independent of the card" },

      { type: "header", title: "On the wallpaper" },
      { type: "setting", kind: "bool", key: "desktopWidget", title: "Show the card",
        value: h.desktopWidget === true || String(h.desktopWidget) === "true" },
      { type: "setting", kind: "enum", key: "desktopSize", title: "Size",
        value: String(h.desktopSize || "card"),
        options: ["card", "mini"],
        hint: "enter or -/+ cycles through — applies at once" },
      { type: "setting", kind: "enum", key: "desktopCorner", title: "Position",
        value: String(h.desktopCorner || "bottom-right"),
        options: ["bottom-right", "bottom-left", "top-right", "top-left", "center"],
        hint: "enter or -/+ cycles through — applies at once" },
      { type: "setting", kind: "enum", key: "desktopLayer", title: "Layer",
        value: String(h.desktopLayer || "desktop"),
        options: ["desktop", "above"],
        hint: "desktop = under the windows, above = always visible" },
      { type: "setting", kind: "bool", key: "desktopDimOnPause", title: "Dim when paused",
        value: h.desktopDimOnPause === true || String(h.desktopDimOnPause) === "true" },

      { type: "header", title: "Music library" },
      { type: "setting", kind: "action", action: "update", title: "Update",
        hint: "reads new and changed files — the everyday one" },
      { type: "setting", kind: "action", action: "rescan", title: "Rescan",
        hint: "re-reads everything, drops removed files — slow on a NAS" },
    ]
  }

  // A value list ("enum" setting): -/+ walks it and wraps around, enter walks
  // forward. Writing goes the same way every other setting goes.
  // Library maintenance: MPD scans in the background, so the row starts it and
  // gets out of the way. The widget flashes what started and reports back when
  // the library really changed.
  function runLibraryAction(row) {
    if (!row || root.host === null) return
    var mode = String(row.action || "update") === "rescan" ? "rescan" : "update"
    root.scanRequested = true
    root.host.updateDatabase(mode, "")
    root.flash(mode === "rescan"
      ? "rescan started — re-reads everything, this can take a while"
      : "update started — MPD works through it in the background")
  }

  function stepEnum(row, delta) {
    var opts = row.options || []
    if (opts.length === 0) return
    var at = opts.indexOf(String(row.value))
    if (at < 0) at = 0
    root.writeSetting(row.key, opts[(at + delta + opts.length) % opts.length], row.title)
  }

  // One place that moves a value: numbers step inside their min/max, enum rows
  // walk their list. The keys (-/+), the steppers on the row and the row click
  // all go through here, so the three cannot drift apart.
  function stepSetting(row, delta) {
    if (!row || row.type !== "setting") return
    if (row.kind === "enum") { root.stepEnum(row, delta); return }
    if (row.kind !== "int") return
    var value = Number(row.value || 0)
    var next = value + Math.max(1, Number(row.step || 1)) * delta
    if (row.min !== undefined) next = Math.max(Number(row.min), next)
    if (row.max !== undefined) next = Math.min(Number(row.max), next)
    if (next === value) {
      root.note("setting " + row.key + " is at its limit")
      return
    }
    root.writeSetting(row.key, next, row.title)
  }

  function writeSetting(key, value, label) {
    if (root.host === null) return
    root.host.setSetting(key, value)
    var shown = (value === true) ? "on" : (value === false) ? "off" : String(value)
    root.flash(String(label || key) + ": " + shown)
    root.note("setting " + key + " = " + shown)
  }

  // What the pattern being typed would produce for the song that is playing.
  readonly property string formatPreview: {
    var pattern = root.promptText.trim()
    if (pattern === "") return "(empty)"
    var out = root.host !== null ? root.host.previewLabel(pattern) : ""
    return out === "" ? "(no playing track)" : out
  }

  function rowSub(row) {
    if (!row) return ""
    if (row.type === "setting") return String(row.hint || "")
    if (row.type === "group") return row.kind === "album" ? String(row.artist || "") : ""
    if (row.type === "value" || row.type === "playlist") return ""
    if (row.type === "directory") return "Folder"
    var bits = []
    if (row.artist) bits.push(String(row.artist))
    if (row.album && root.frameTitle !== String(row.album)) bits.push(String(row.album))
    if (row.genre && root.frameMode === "find") bits.push(String(row.genre))
    // No track number here: the list is already in track order and the number
    // usually leads the title anyway -- it was noise on every single row.
    return bits.join("  ·  ")
  }

  function rowRight(row) {
    if (!row) return ""
    if (row.type === "setting") {
      if (row.kind === "action") return "run"
      if (row.kind === "bool") return row.value === true ? "on" : "off"
      if (row.kind === "int") return String(row.value) + String(row.suffix || "")
      return String(row.value || "")
    }
    if (row.type === "group") return String(row.count || 0) + " tracks"
    if (row.time) return host.formatTime(row.time)
    if (row.type === "value" || row.type === "directory" || row.type === "playlist") return "›"
    return ""
  }

  function isActiveRow(row) {
    if (!row || !root.host || !row.id || !root.host.song) return false
    return Number(row.id) === Number(root.host.song.id)
  }

  function rowIsSong(row) {
    return !!row && (row.type === "file" || !!row.file)
  }

  // --------------------------------------------------------------- actions
  function activate() {
    var row = root.rows[root.sel]
    if (!row) return
    var mode = root.frameMode

    // Before the connection check: the settings tab works without MPD.
    if (mode === "settings") {
      // An action row: it carries no value and no steppers, it does something
      // when it is taken.
      if (row.kind === "action") { root.runLibraryAction(row); return }
      if (row.kind === "bool") {
        root.writeSetting(row.key, row.value !== true, row.title)
        // The hover card needs a closed panel (it would only be noise over the
        // full view), so the switch alone shows nothing -- say what to do.
        if (row.key === "hoverCard")
          root.flash("card " + (row.value !== true ? "on" : "off") + " — close the panel, then hover the label")
        // Switching the track-change card on shows it once: "on" should not be a
        // word the user has to take on faith.
        else if (row.key === "osdOnChange" && row.value !== true)
          root.host.showOsd(false)
      }
      else if (row.kind === "text") root.openPrompt("format", String(row.value || ""), true)
      else if (row.kind === "enum") root.stepEnum(row, 1)
      // A number you cannot try out is a number nobody understands: show the
      // card for exactly as long as it is set.
      else if (row.kind === "int" && row.key === "osdDuration") {
        root.host.showOsd(false)
        root.flash("Card on track change — " + (Number(row.value) / 1000).toFixed(1) + " s")
      }
      // Any other number: a click means "more of it", and the −/+ steppers on the
      // row go both ways. Before this, a click on `Cover backdrop` did nothing.
      else if (row.kind === "int") root.stepSetting(row, 1)
      return
    }
    if (!root.up) return

    if (mode === "queue") { if (row.id !== undefined) host.playId(row.id); return }
    if (mode === "playlists") {
      root.pushFrame({ mode: "plist", name: String(row.playlist || ""), title: String(row.playlist || "") })
      return
    }
    if (mode === "files") {
      if (row.type === "directory") {
        root.pushFrame({ mode: "files", path: String(row.directory || ""), title: String(row.directory || "").split("/").pop() })
        return
      }
      if (row.type === "playlist") { host.mutation("loadplaylist", { name: String(row.playlist || "") }); return }
    }
    if (row.type === "group") {
      // A search group: open the artist's albums or the album's tracks. What
      // appends the whole thing is the `+` on the row (or `a`).
      if (row.kind === "artist") {
        root.pushFrame({ mode: "list", tag: "album", title: String(row.value || ""),
                         filter: [["artist", String(row.value || "")]] })
        return
      }
      // An album found by search: go in through the artist's albums. Then one
      // step back out of the tracks lands on the artist's other albums -- which
      // is where somebody browsing an artist actually wants to be.
      var albumName = String(row.value || "")
      var byArtist = String(row.artist || "")
      if (byArtist !== "") {
        root.stack = root.stack.concat([
          { mode: "list", tag: "album", title: byArtist, filter: [["artist", byArtist]] },
          { mode: "find", title: albumName + " — tracks", sort: "track",
            filter: [["artist", byArtist], ["album", albumName]] }
        ])
        root.sel = 0
        root.detailRow = null
        return
      }
      root.pushFrame({ mode: "find", title: albumName + " — tracks", sort: "track",
                       filter: [["album", albumName]] })
      return
    }
    if (row.type === "value") {
      // A tag value: albums of that artist, albums in that genre, or the songs
      // of an album. The bridge wants filters as [tag, value] pairs, and the
      // filter grows as the stack does.
      var tag = String(root.frame.tag || "album")
      var value = String(row.value || "")
      var base = root.frame.filter || []
      if (tag === "album") {
        root.pushFrame({ mode: "find", title: value + " — tracks", sort: "track",
                         filter: base.concat([["album", value]]) })
        return
      }
      root.pushFrame({ mode: "list", tag: "album", title: value,
                       filter: base.concat([[tag, value]]) })
      return
    }
    if (rowIsSong(row) && row.file) host.addAndPlay(row.file)
  }

  // ------------------------------------------------------------ adding to the queue
  //
  // `a` on a row appends what that row stands for: a track, the whole album or
  // artist a search group represents, everything under a folder. `A` appends
  // everything the current list is. Both are single MPD commands (findadd /
  // searchadd) rather than one `add` per row, so adding an artist with 900 songs
  // is one round trip.
  function addRow() {
    root.addOne(root.rows[root.sel])
  }

  function addOne(row) {
    if (!row || !root.up) return
    var type = String(row.type || "")
    if (type === "header") return
    var what = ""

    if (type === "group") {
      if (row.kind === "artist") {
        host.mutation("findadd", { filter: [["artist", String(row.value || "")]] })
        what = "all tracks by " + String(row.value || "")
      } else {
        host.mutation("findadd", { filter: [["album", String(row.value || "")]] })
        what = "Album „" + String(row.value || "") + "”"
      }
    } else if (type === "value") {
      var tag = String(root.frame.tag || "")
      if (tag === "") { root.flash("this list cannot be appended as a filter"); return }
      host.mutation("findadd", { filter: (root.frame.filter || []).concat([[tag, String(row.value || "")]]) })
      what = String(row.value || "")
    } else if (type === "directory") {
      host.addUri(String(row.directory || ""))
      what = "Folder " + String(row.directory || "")
    } else if (type === "playlist") {
      host.mutation("loadplaylist", { name: String(row.playlist || "") })
      what = "Playlist " + String(row.playlist || "") + " (ersetzt die Queue)"
    } else if (row.file) {
      host.addUri(String(row.file))
      what = root.rowTitle(row)
    }

    if (what !== "") root.flash("appended: " + what)
  }

  function addAll() {
    if (!root.up) return
    var mode = root.frameMode

    if (mode === "search") {
      var term = String(root.frame.term || "").trim()
      if (term === "") return
      host.mutation("searchadd", { term: term })
      root.flash("all hits for “" + term + "” appended")
      return
    }
    if (mode === "find") {
      var filter = root.frame.filter || []
      if (filter.length === 0) { root.flash("nothing to append"); return }
      host.mutation("findadd", { filter: filter })
      root.flash("all tracks of this list appended")
      return
    }
    if (mode === "list") {
      // A scoped search frame: its rows *are* the matches, so "A" appends those --
      // one command in the same category, not a walk through every artist.
      var only = String(root.frame.search || "")
      if (only !== "") {
        host.mutation("searchadd", { term: only, tag: String(root.frame.tag || "album") })
        root.flash("all hits for “" + only + "” appended")
        return
      }
      var base = root.frame.filter || []
      if (base.length === 0) { root.flash("open an artist or album first, then A"); return }
      host.mutation("findadd", { filter: base })
      root.flash("everything under this selection appended")
      return
    }
    if (mode === "files") {
      var path = String(root.frame.path || "")
      if (path === "") { root.flash("open a folder first, then A"); return }
      host.addUri(path)
      root.flash("Folder " + path + " appended")
      return
    }
    if (mode === "plist") { root.flash("load a playlist: a on the list in the Playlists tab"); return }
    if (mode === "queue") { root.flash("in the queue, a appends single tracks"); return }
    root.flash("nothing to append here")
  }

  // A short confirmation in the footer: MPD answers `findadd` with a bare OK, and
  // "nothing happened" is the wrong reply to a keypress.
  property string flashText: ""

  function flash(text) {
    root.flashText = String(text)
    flashTimer.restart()
  }

  Timer {
    id: flashTimer
    interval: 3200
    repeat: false
    onTriggered: root.flashText = ""
  }

  // What the keys do right here, so nothing has to be remembered. `t` jumps to the
  // playing track from *every* view, so it is appended here instead of being
  // repeated in each list of keys -- but not while a field is open: there the
  // letters belong to the field, and `t` is just a letter.
  readonly property string hint: {
    if (root.promptMode !== "") return root.hintKeys
    // A filter that is still set says so -- otherwise "the list is short today"
    // looks like a bug.
    if (root.filterText !== "")
      return root.hintKeys + " · Filter: " + root.filterText + " · esc shows everything again"
    var keys = root.hintKeys
    // The two keys that are about the player rather than about this list travel
    // with every view.
    return keys === "" ? "" : keys + " · <> prev/next · t playing track"
  }

  // The keys of the current view, without the one key that is about the whole
  // player. See `hint` below.
  readonly property string hintKeys: {
    if (root.promptMode === "search")
      return (root.promptText === "" && !root.promptExplicit)
        ? "type to search · 1–8 switch tabs · ↓/↑ enters the list · / for digits · esc done"
        : "type to filter · ↓/↑ enters the list · enter plays the hit · ctrl+u clears · esc done"
    if (root.promptMode === "category")
      return "type to search in " + root.rootFrameFor(root.tab).title
        + " · ↓/↑ enters the list · enter shows them · esc back"
    if (root.promptMode === "filter")
      return "type to filter this list · ↓/↑ enters the list · ctrl+u clears · esc shows all"
    if (root.promptMode !== "") return "type · enter confirms · esc cancels"
    var mode = root.frameMode
    if (mode === "queue") return "enter plays · a appends · d removes · D clears · C keeps only the playing track"
    if (mode === "search") return "/ to type · enter opens · a appends · A all hits · h/esc back"
    if (mode === "list") return "enter goes in · a appends all of it · A appends the selection · h/esc back"
    if (mode === "find") return "enter plays · a appends · A whole list · h/esc back"
    if (mode === "files") return "enter opens/plays · a appends · A whole folder · ← back"
    if (mode === "playlists") return "enter opens · a loads · s saves the queue · r renames · d deletes"
    if (mode === "plist") return "enter plays · a appends · d removes the track · ← back"
    if (mode === "settings") return "enter/space toggles · -/+ change the value · 8 picks the tab · esc back"
    return ""
  }

  function removeRow() {
    var row = root.rows[root.sel]
    if (!row || !root.up) return
    if (root.frameMode === "queue") {
      if (row.id !== undefined) host.removeId(row.id)
      return
    }
    if (root.frameMode === "playlists") {
      mutateAndReload("rmplaylist", { name: String(row.playlist || "") })
      return
    }
    if (root.frameMode === "plist") {
      var name = String(root.frame.name || "")
      if (name === "" || row.file === undefined) return
      mutateAndReload("playlistdelete", { name: name, pos: Number(root.sel) })
      return
    }
  }

  function moveRow(delta) {
    var row = root.rows[root.sel]
    if (!row || !root.up || root.frameMode !== "queue") return
    var from = Number(row.pos)
    var to = from + delta
    if (isNaN(from) || to < 0 || to >= root.rows.length) return
    host.moveSong(from, to)
    // Bring the model in step instead of reloading: a reload puts the selection
    // back on the first row (the loader does that for every list), and the next J/K
    // would then move whatever row happens to sit under the cursor rather than the
    // one the user is walking. MPD has taken the command; this is only the picture,
    // and in the queue a row index is its MPD position.
    var rows = (root.rows || []).slice()
    if (rows[from] && rows[to] && from !== to) {
      var tausch = rows[from]
      rows[from] = rows[to]
      rows[to] = tausch
      rows[from].pos = from
      rows[to].pos = to
      root.rows = rows
      root.allRows = rows
    }
    root.sel = Math.max(0, Math.min(root.rows.length - 1, root.sel + delta))
    // The model was just replaced, so the view is rebuilt; without this the
    // selection can walk off the bottom while the delegates come back. Same call
    // `step()` makes for the same reason.
    list.positionViewAtIndex(root.sel, ListView.Contain)
  }

  function showDetails() {
    var row = root.rows[root.sel]
    if (!row || !root.up) return
    if (root.detailRow !== null) { root.detailRow = null; return }
    var uri = String(row.file || root.host.songFile || "")
    if (uri === "") return
    root.detailLoading = true
    root.detailTitle = root.rowTitle(row)
    host.query("songinfo", { file: uri }, "detail", function(list, error) {
      root.detailLoading = false
      if (error !== "") { root.setInfo(error); return }
      root.detailRow = list.length > 0 ? list[0] : null
    })
  }

  // ------------------------------------------------------------------ prompt
  function openPrompt(mode, initial, focus, explicit) {
    root.promptMode = String(mode)
    root.promptText = String(initial || "")
    root.promptExplicit = explicit === true
    if (focus) Qt.callLater(function() { promptFocusTimer.restart() })
  }

  // 1..8 -> tab name, so the number keys can be read in one place.
  function tabForNumber(value) {
    var order = ["queue", "search", "albums", "artists", "genres", "files", "playlists", "settings"]
    var index = Number(value) - 1
    return (index >= 0 && index < order.length) ? order[index] : ""
  }

  function closePrompt() {
    promptDebounce.stop()
    root.promptMode = ""
    root.promptText = ""
    root.promptTarget = ""
    if (root.filterText !== "") { root.filterText = ""; root.refreshFilteredRows() }
  }

  // Leave the field but keep the term: the results stay on screen, the keys go to
  // the list (`a`, enter, j/k), and `/` comes back with the term still in the
  // field. Without the flush, a pending debounce would land after the fact and
  // wipe the list.
  function leavePrompt() {
    promptDebounce.stop()
    if (root.promptMode === "search" && root.promptText.trim() !== "")
      root.applySearch(root.promptText)
    if (root.promptMode === "category")
      root.applyCategorySearch(root.promptText)
    root.promptMode = ""
  }

  // Live search: every keystroke re-runs the query after a short pause, and the
  // bridge drops the query a newer one supersedes on the same channel -- so
  // typing eight letters costs one MPD search, not eight.
  function searchWhileTyping() {
    if (root.promptMode === "filter") { root.applyLocalFilter(root.promptText); return }
    if (root.promptMode !== "search" && root.promptMode !== "category") return
    promptDebounce.restart()
  }

  function searchNow() {
    promptDebounce.stop()
    root.applySearch(root.promptText)
  }

  Timer {
    id: promptDebounce
    interval: 250
    repeat: false
    onTriggered: root.promptMode === "category"
      ? root.applyCategorySearch(root.promptText) : root.applySearch(root.promptText)
  }

  // If no list arrives (the term did not change, nothing was re-queried), the
  // wish must not linger and steer some later load.
  Timer {
    id: pendingSelectGuard
    interval: 1500
    repeat: false
    onTriggered: root.pendingSelect = ""
  }

  // One search frame, reused: the top frame is replaced while the user keeps
  // typing, so the way back does not fill up with one frame per keystroke.
  function applySearch(term) {
    var trimmed = String(term || "").trim()
    var nextFrame = { mode: "search", term: trimmed,
                      title: trimmed === "" ? "Search" : "Search: " + trimmed }
    var top = root.stack.length > 0 ? root.stack[root.stack.length - 1] : null
    if (top && String(top.mode) === "search") {
      var next = root.stack.slice(0, root.stack.length - 1)
      next.push(nextFrame)
      root.sel = 0
      root.detailRow = null
      root.stack = next
      return
    }
    root.pushFrame(nextFrame)
  }

  function topFrame() {
    return root.stack.length > 0 ? root.stack[root.stack.length - 1] : null
  }

  // The scoped search: "the albums whose name contains this". Same behaviour as the
  // global one -- the top frame is replaced while typing, so the way back does not
  // collect one frame per keystroke.
  function applyCategorySearch(term) {
    var top = root.topFrame()
    var tag = (top && String(top.mode) === "list") ? String(top.tag || "album") : "album"
    var trimmed = String(term || "").trim()
    var base = root.rootFrameFor(root.tab).title
    var nextFrame = { mode: "list", tag: tag, filter: [], search: trimmed,
                      title: trimmed === "" ? base : base + " · " + trimmed }
    if (top && String(top.mode) === "list" && top.search !== undefined) {
      root.sel = 0
      root.detailRow = null
      root.stack = root.stack.slice(0, root.stack.length - 1).concat([nextFrame])
      return
    }
    root.pushFrame(nextFrame)
  }

  // The local filter: keeps the loaded list and shows the matching rows. Simple
  // substring, case-insensitive, over title and subtitle -- what a person sees.
  function refreshFilteredRows() {
    var needle = root.filterText.trim().toLowerCase()
    if (needle === "") {
      root.rows = root.allRows
      root.setInfo(root.infoFor(root.frameMode, root.frame || {}, root.allRows))
      return
    }
    var out = []
    for (var i = 0; i < root.allRows.length; i++) {
      var row = root.allRows[i]
      if (String(row.type || "") === "header") { out.push(row); continue }
      var hay = (String(root.rowTitle(row)) + " " + String(root.rowSub(row))).toLowerCase()
      if (hay.indexOf(needle) !== -1) out.push(row)
    }
    root.rows = out
    root.sel = root.firstSelectable(0)
    root.setInfo(out.length + " of " + root.allRows.length)
  }

  function applyLocalFilter(term) {
    root.filterText = String(term || "")
    root.refreshFilteredRows()
  }

  // What `/` opens here: a scoped search in the library tabs, a plain filter where
  // MPD has nothing to filter (paths, playlist names), and the global search
  // everywhere else -- which is what `/` did before.
  function openPromptForFrame(explicit) {
    var top = root.topFrame()
    var mode = top ? String(top.mode || "") : ""
    if (mode === "list") {
      root.openPrompt("category", String(top.search || ""), true, explicit)
      return
    }
    if (mode === "files" || mode === "playlists") {
      root.openPrompt("filter", root.filterText, true, explicit)
      return
    }
    root.setTab("search", true)
  }

  function submitPrompt() {
    var text = root.promptText.trim()
    // Done typing: the scoped search keeps its result list, the filter keeps
    // filtering, and in both cases the field goes away. Enter in the *list* then
    // opens the row, exactly as in every other view.
    if (root.promptMode === "category" || root.promptMode === "filter") {
      root.promptMode = ""
      return
    }
    if (root.promptMode === "search") {
      if (text === "") return
      root.applySearch(text)
      // The field stays up: a correction costs nothing, esc leaves it.
      return
    }
    if (root.promptMode === "save") {
      if (text === "" || !root.up) return
      mutateAndReload("saveplaylist", { name: text })
      root.setInfo("Queue saved as “" + text + "”")
      root.closePrompt()
      return
    }
    if (root.promptMode === "rename") {
      var row = root.rows[root.sel]
      // The name from the moment the prompt opened -- not from the row that
      // happens to be selected now (a reload in between would have moved it).
      var from = root.promptTarget
      if (text === "" || from === "" || !root.up) { root.promptTarget = ""; return }
      mutateAndReload("renameplaylist", { name: from, to: text })
      root.setInfo("“" + from + "” is now “" + text + "”")
      root.closePrompt()
      return
    }
    if (root.promptMode === "format") {
      if (text === "") return
      var srow = root.rows[root.sel]
      root.writeSetting("format", text, srow ? srow.title : "Label format")
      root.closePrompt()
      return
    }
    root.closePrompt()
  }

  Timer {
    id: promptFocusTimer
    interval: 30
    repeat: false
    onTriggered: keyCatcher.forceActiveFocus()
  }

  // -------------------------------------------------------------------- keys
  function handleKey(event) {
    var key = event.key
    var text = String(event.text || "")
    var shift = (event.modifiers & Qt.ShiftModifier) !== 0
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0

    // The prompt owns the keyboard while it is up.
    if (root.promptMode !== "") {
      if (key === Qt.Key_Escape) { root.closePrompt(); event.accepted = true; return }
      if (key === Qt.Key_Tab) { root.cycleTab(shift ? -1 : 1); event.accepted = true; return }
      // ↓/↑ leave the field and take over the list: "done typing, now picking".
      // The term stays, so `/` brings the field back where it was, and everything
      // the list offers (a, enter, i, j/k) works from here on.
      if ((root.promptMode === "search" || root.promptMode === "category"
           || root.promptMode === "filter") && (key === Qt.Key_Down || key === Qt.Key_Up)) {
        var wasMode = root.promptMode
        var goLast = (key === Qt.Key_Up)
        var hadTerm = root.promptText.trim() !== ""
        root.leavePrompt()
        root.sel = goLast ? root.lastSelectable() : root.firstSelectable(0)
        // The re-run above answers later and resets the selection to the top hit;
        // the wish has to survive that.
        if (hadTerm && wasMode !== "filter") { root.pendingSelect = goLast ? "last" : "first"; pendingSelectGuard.restart() }
        event.accepted = true
        return
      }
      if (ctrl && text === "u") { root.promptText = ""; root.searchWhileTyping(); event.accepted = true; return }
      if (key === Qt.Key_Return || key === Qt.Key_Enter) {
        // Live search makes the old "run it once more" pointless: Enter takes the
        // row that is selected -- the top hit while the field is fresh. Playing a
        // track keeps the field (the next search is one key away); opening a group
        // leaves it, because from there on the keys belong to the new list.
        if (root.promptMode === "search") {
          var row = root.rows[root.sel]
          if (!rowIsSong(row)) root.leavePrompt()
          root.activate()
        } else {
          root.submitPrompt()
        }
        event.accepted = true
        return
      }
      if (key === Qt.Key_Backspace) {
        root.promptText = root.promptText.substring(0, Math.max(0, root.promptText.length - 1))
        root.searchWhileTyping()
        event.accepted = true
        return
      }
      // Numbers stay tab switches while the field is empty and was not asked for
      // with `/`: pressing 2 to peek at the search and then 3 to move on used to
      // end up as the search term "23". A term that begins with a digit goes
      // through `/` -- the explicit "I want to type" gesture.
      if (!root.promptExplicit && root.promptText === "" && text.length === 1
          && text >= "1" && text <= "7") {
        root.closePrompt()
        root.setTab(root.tabForNumber(text))
        event.accepted = true
        return
      }
      if (text.length === 1 && text >= " ") {
        // `/` is the gesture that opens the field, not a character. In an empty
        // field it means "I really do want to type -- digits included"; in a
        // filled one it stays a literal, so terms like "AC/DC" work.
        if (text === "/" && root.promptText === "") {
          root.promptExplicit = true
        } else {
          root.promptText += text
        }
        root.searchWhileTyping()
        event.accepted = true
      }
      return
    }

    // The details overlay owns it next.
    if (root.detailRow !== null) {
      if (key === Qt.Key_Escape || text === "i" || key === Qt.Key_Return || key === Qt.Key_Enter) {
        root.detailRow = null
        event.accepted = true
      }
      return
    }

    if (ctrl && text === "u") { root.step(-8); event.accepted = true; return }
    if (ctrl && text === "d") { root.step(8); event.accepted = true; return }

    if (key === Qt.Key_Escape) {
      // In the order of what is on top: the details overlay, then a set filter,
      // then one frame back, then closing the panel. Closing the whole panel from
      // three levels deep is not what somebody pressing `esc` means.
      if (root.detailRow !== null) { root.detailRow = null; event.accepted = true; return }
      if (root.filterText !== "") {
        root.filterText = ""
        root.refreshFilteredRows()
        event.accepted = true
        return
      }
      if (root.popFrame()) { event.accepted = true; return }
      root.filterText = ""
      root.setInfo("")
      host.close()
      event.accepted = true
      return
    }
    if (key === Qt.Key_Tab) { root.cycleTab(shift ? -1 : 1); event.accepted = true; return }
    if (text === "1" || key === Qt.Key_1) { root.setTab("queue"); event.accepted = true; return }
    if (text === "2" || key === Qt.Key_2) { root.setTab("search"); event.accepted = true; return }
    if (text === "3" || key === Qt.Key_3) { root.setTab("albums"); event.accepted = true; return }
    if (text === "4" || key === Qt.Key_4) { root.setTab("artists"); event.accepted = true; return }
    if (text === "5" || key === Qt.Key_5) { root.setTab("genres"); event.accepted = true; return }
    if (text === "6" || key === Qt.Key_6) { root.setTab("files"); event.accepted = true; return }
    if (text === "7" || key === Qt.Key_7) { root.setTab("playlists"); event.accepted = true; return }
    if (text === "8" || key === Qt.Key_8) { root.setTab("settings"); event.accepted = true; return }

    // Settings tab: -/+ step a number, space flips a switch. Before the global
    // volume/play bindings, which own those keys everywhere else.
    if (root.frameMode === "settings") {
      var srow = root.rows[root.sel]
      // One branch for both numeric kinds, through the same stepSetting() the
      // steppers on the row call. The sign arrives as text or as a key code (a
      // numpad sends the code), and this runs before the volume bindings -- so a
      // `-` on a settings row can never move the volume.
      var dir = (text === "-" || key === Qt.Key_Minus) ? -1
        : (text === "+" || text === "=" || key === Qt.Key_Plus || key === Qt.Key_Equal) ? 1 : 0
      if (dir !== 0 && srow && srow.type === "setting"
          && (srow.kind === "int" || srow.kind === "enum")) {
        root.stepSetting(srow, dir)
        event.accepted = true
        return
      }
      // Delegate to activate(): one place that knows what a row does, so extra
      // effects (the OSD preview, the "close the panel first" hint) cannot be
      // skipped by a key block that writes on its own.
      if (srow && (key === Qt.Key_Space || key === Qt.Key_Return || key === Qt.Key_Enter || text === "p")) {
        root.activate()
        event.accepted = true
        return
      }
    }

    if (key === Qt.Key_Slash) { root.openPromptForFrame(true); event.accepted = true; return }
    if (text === "i" && root.frameMode !== "playlists") { root.showDetails(); event.accepted = true; return }

    if (key === Qt.Key_Down || text === "j") { root.step(1); event.accepted = true; return }
    if (key === Qt.Key_Up || text === "k") { root.step(-1); event.accepted = true; return }
    if (key === Qt.Key_PageDown) { root.step(10); event.accepted = true; return }
    if (key === Qt.Key_PageUp) { root.step(-10); event.accepted = true; return }
    if (text === "t") { root.gotoCurrent(); event.accepted = true; return }
    // The ncmpcpp convention: > is the next track, < the previous one. (mpc's own
    // CLI spells them `next` and `prev`; the angle brackets are ncmpcpp's.) They
    // belong to the player, not to the list, so they work in every view.
    if (text === ">" || key === Qt.Key_Greater) {
      if (root.host) root.host.nextTrack()
      event.accepted = true
      return
    }
    if (text === "<" || key === Qt.Key_Less) {
      if (root.host) root.host.previousTrack()
      event.accepted = true
      return
    }
    if (text === "g") { root.sel = 0; root.centerOn(0); event.accepted = true; return }
    if (text === "G" || key === Qt.Key_End) {
      root.sel = Math.max(0, root.rows.length - 1)
      root.centerOn(root.sel)
      event.accepted = true
      return
    }

    if (key === Qt.Key_Return || key === Qt.Key_Enter || text === "l") { root.activate(); event.accepted = true; return }
    if (key === Qt.Key_Backspace || key === Qt.Key_Left || text === "h") {
      if (!root.popFrame() && text === "h") root.setTab("queue")
      event.accepted = true
      return
    }

    if (text === "a") { root.addRow(); event.accepted = true; return }
    if (text === "A") { root.addAll(); event.accepted = true; return }
    if (text === "d") { root.removeRow(); event.accepted = true; return }
    if (text === "D") { if (root.frameMode === "queue") host.clearQueue(); event.accepted = true; return }
    // Keep only what is playing: MPD's `crop`, the counterpart to clearing.
    if (text === "C") { if (root.frameMode === "queue") host.cropQueue(); event.accepted = true; return }
    if (text === "x") {
      // A shuffle reorders everything, so unlike a single move the model cannot be
      // patched in place. Reload -- and let the selection land on what is playing,
      // which after a shuffle is where the eye wants to be.
      if (root.frameMode === "queue") {
        root.jumpToCurrent = true
        mutateAndReload("shuffle", {})
      }
      // Accepted in every frame, as it always was: `x` is a queue key, and the
      // other tabs should not fall through to the keys below with it.
      event.accepted = true
      return
    }
    if (text === "J") { root.moveRow(1); event.accepted = true; return }
    if (text === "K") { root.moveRow(-1); event.accepted = true; return }
    if (text === "s" && root.frameMode !== "search") { root.openPrompt("save", "", true); event.accepted = true; return }
    if (text === "r" && root.frameMode === "playlists") {
      var row = root.rows[root.sel]
      root.promptTarget = row ? String(row.playlist || "") : ""
      root.openPrompt("rename", root.promptTarget, true)
      event.accepted = true
      return
    }
    if (key === Qt.Key_Space || text === "p") { host.toggleTrack(); event.accepted = true; return }
    if (text === "z") { host.toggleOption("repeat"); event.accepted = true; return }
    if (text === "R") { host.toggleOption("random"); event.accepted = true; return }
    if (text === "c") { host.toggleOption("consume"); event.accepted = true; return }
    if (text === "v") { host.toggleOption("single"); event.accepted = true; return }
    if (key === Qt.Key_Plus || text === "+") { host.nudgeVolume(5); event.accepted = true; return }
    if (key === Qt.Key_Minus || text === "-") { host.nudgeVolume(-5); event.accepted = true; return }
    if (key === Qt.Key_Comma) { host.bare("seek " + Math.max(0, Math.round(root.host.elapsed - 5))); event.accepted = true; return }
    if (key === Qt.Key_Period) { host.bare("seek " + Math.round(root.host.elapsed + 5)); event.accepted = true; return }
  }

  function step(delta) {
    if (root.rows.length === 0) return
    var at = root.sel
    var dir = delta > 0 ? 1 : -1
    for (var i = 0; i < Math.abs(delta); i++) {
      var next = at + dir
      // Section labels are not rows you can land on.
      while (next >= 0 && next < root.rows.length && !root.isSelectable(root.rows[next])) next += dir
      if (next < 0 || next >= root.rows.length) break
      at = next
    }
    root.sel = at
    list.positionViewAtIndex(root.sel, ListView.Contain)
  }

  function cycleTab(delta) {
    var order = ["queue", "search", "albums", "artists", "genres", "files", "playlists"]
    var at = order.indexOf(root.tab)
    root.setTab(order[(at + delta + order.length) % order.length])
  }

  // The band shows what is playing; the header thumbnail what is selected.
  readonly property string bandArt: root.host && root.host.hasSong ? root.host.artPath : ""

  // ------------------------------------------------------------------ window
  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget
    bar: root.bar
    open: root.hostWidget ? root.hostWidget.opened === true : false
    focusTarget: keyCatcher
    centerOnBar: true
    contentWidth: panel.fittedContentWidth(Style.space(900))
    contentHeight: panel.cappedContentHeight(Style.space(610))

    onOpenChanged: if (open) {
      // Opened on a long queue, the list would start at the top -- the one place
      // the playing track is not. The queue load picks this up and lands on it.
      root.jumpToCurrent = true
      if (root.stack.length === 0) root.setTab(root.tab)
      else root.loadFrame()
      Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) { root.handleKey(event) }

      // The panel's own floor. Up to now the opaque part came from the backdrop's
      // gradient -- so in the looks that carry the cover inside the band (hero,
      // anker) the panel had no floor at all and everything behind it showed
      // through. A plain rectangle, in the same colour the gradients end in, so the
      // blurred looks are unchanged and the flat ones are opaque.
      Rectangle {
        anchors.fill: parent
        color: root.bg
      }

      // ------------------------------------------ the cover behind the panel
      // Two treatments live in Backdrop.qml: the blurred cover (heute) and the
      // sharp, dimmed one (musify's trick). Which one shows, and whether any
      // shows at all, follows the look setting -- the hero and anchor looks
      // carry their own cover and leave the panel plain.
      Backdrop {
        id: backdrop
        anchors.fill: parent
        mode: root.backdropMode
        level: root.backdropLevel
        source: root.host ? root.host.artPath : ""
      }

      // ----------------------------------------------------------- header
      Item {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: Style.space(40)

        Row {
          anchors { left: parent.left; verticalCenter: parent.verticalCenter }
          spacing: Style.space(12)

          Text {
            text: "MPD"
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
            height: header.height
            verticalAlignment: Text.AlignVCenter
          }

          Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Text {
              text: root.breadcrumb()
              color: root.fg
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: Math.min(implicitWidth, Style.space(360))
            }

            // Only when it matters: an address and a version number are not worth
            // a line of their own, a connection that is not up is.
            Text {
              visible: !root.up
              text: root.host && root.host.lastError !== ""
                ? root.host.lastError : "verbinde …"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        Row {
          anchors { right: parent.right; verticalCenter: parent.verticalCenter }
          spacing: Style.space(8)

          Repeater {
            model: [
              { key: "queue", label: "1" },
              { key: "search", label: "2" },
              { key: "albums", label: "3" },
              { key: "artists", label: "4" },
              { key: "genres", label: "5" },
              { key: "files", label: "6" },
              { key: "playlists", label: "7" },
              { key: "settings", label: "8" }
            ]

            delegate: Item {
              required property var modelData
              implicitWidth: chipText.implicitWidth + Style.space(16)
              implicitHeight: Style.space(24)

              Rectangle {
                anchors.fill: parent
                radius: Style.cornerRadius
                color: root.tab === modelData.key ? root.selBg : "transparent"
                border.width: root.tab === modelData.key ? 0 : Math.max(1, Style.normalBorderWidth)
                border.color: root.line
              }

              Text {
                id: chipText
                anchors.centerIn: parent
                text: modelData.label
                color: root.tab === modelData.key ? root.selFg : root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setTab(modelData.key)
              }
            }
          }
        }
      }

      Rectangle {
        id: headerRule
        anchors { top: header.bottom; left: parent.left; right: parent.right }
        height: 1
        color: root.rule
      }

      // ---------------------------------------------------------- now playing
      // The band is its own file per look (Band*.qml). Values are bound in
      // wireBand(); the two things the band wants to say (a footer line, a hover
      // explanation) come back as signals.
      // The band carries its own height, and the looks differ: 74 px (classic),
      // 100 (sharp), 104 (hero), 126 (anchor). In the settings tab that pushed the
      // rows below it down or up on every look change -- and the pointer had to
      // follow the very value it was changing. There the band gets a slot as tall
      // as the tallest look, so the list never moves; the leftover room stays as
      // backdrop. Everywhere else each look keeps its own height.
      Item {
        id: bandSlot
        anchors { top: headerRule.bottom; topMargin: Style.space(7)
                  left: parent.left; right: parent.right }
        height: root.frameMode === "settings"
          ? Style.space(126)
          : (nowBand.item ? nowBand.item.implicitHeight : 0)

        Loader {
          id: nowBand
          anchors { top: parent.top; left: parent.left; right: parent.right }
          sourceComponent: root.bandComponent()

          onLoaded: root.wireBand(item)
        }
      }

      // ------------------------------------------------------------- list
      ListView {
        id: list
        anchors { top: bandSlot.bottom; topMargin: Style.space(6)
                  left: parent.left; right: parent.right
                  bottom: footer.top; bottomMargin: Style.space(6) }
        clip: true
        model: root.rows
        spacing: Style.space(1)

        delegate: Item {
          id: rowItem
          required property var modelData
          required property int index
          width: list.width
          height: rowItem.settingsHeader ? Style.space(29)
            : (rowItem.isHeader ? Style.space(22) : Style.space(26))

          readonly property string rowType: String(rowItem.modelData.type || "")
          readonly property bool isHeader: rowItem.rowType === "header"
          // A header in the settings tab is a heading over a group, not a divider
          // between result groups -- so it is drawn as a quiet label with a rule
          // above it, while the search tab keeps its accent labels.
          readonly property bool settingsHeader: rowItem.isHeader && root.frameMode === "settings"
          readonly property bool selected: index === root.sel && !rowItem.isHeader

          Rectangle {
            anchors.fill: parent
            color: rowItem.selected ? root.selBg : "transparent"
            radius: Style.cornerRadius
          }

          // The row that is playing right now. The colour + bold on the title
          // alone is easy to miss while scrolling a long queue, and it is the
          // same tone the keyboard selection uses -- so this bar is a second,
          // independent mark. Square on purpose: a one-sided edge should not be
          // rounded, and it has to stay visible when the row is also selected.
          Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: Math.max(2, Style.space(2))
            color: root.accent
            visible: !rowItem.isHeader && root.isActiveRow(rowItem.modelData)
          }

          // The rule between two groups in the settings tab. Only from the second
          // group on: above the first one a line would cut the list off from the
          // band, and there is nothing above it to separate from.
          Rectangle {
            id: groupRule
            visible: rowItem.settingsHeader && index > 0
            x: Style.space(8)
            y: Style.space(6)
            width: parent.width - Style.space(16)
            height: 1
            color: root.dim
            opacity: 0.35
          }

          // A section label: artists / albums / tracks.
          Text {
            visible: rowItem.isHeader
            anchors { left: parent.left; leftMargin: Style.space(8); verticalCenter: parent.verticalCenter }
            anchors.verticalCenterOffset: rowItem.settingsHeader && index > 0 ? Style.space(3) : 0
            text: rowItem.isHeader ? String(rowItem.modelData.title || "") : ""
            color: rowItem.settingsHeader ? root.dim : root.accent
            opacity: rowItem.settingsHeader ? 1 : 0.9
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: !rowItem.settingsHeader
            // Capitalisation is a display choice, not data: the row keeps "In the
            // bar" (so the README and the search tab stay untouched) and reads as
            // a heading here.
            font.capitalization: rowItem.settingsHeader ? Font.AllUppercase : Font.MixedCase
            font.letterSpacing: rowItem.settingsHeader ? 1.1 : 0
          }

          // The row's click target: declared before the `+` so the button keeps
          // its own clicks (a row-wide MouseArea after it would swallow them).
          MouseArea {
            anchors.fill: parent
            enabled: !rowItem.isHeader
            cursorShape: Qt.PointingHandCursor
            onClicked: function(mouse) {
              if (rowItem.isHeader) return
              root.sel = rowItem.index
              // In the settings tab a click means "change this", like any switch.
              if (root.frameMode === "settings") root.activate()
            }
            onDoubleClicked: if (!rowItem.isHeader) { root.sel = rowItem.index; root.activate() }
            onWheel: function(wheel) { root.step(wheel.angleDelta.y > 0 ? -3 : 3) }
          }

          Row {
            visible: !rowItem.isHeader
            anchors { left: parent.left; leftMargin: Style.space(8)
                      right: root.frameMode === "settings" ? stepMinus.left
                        : (trashButton.visible ? trashButton.left : addButton.left)
                      rightMargin: Style.space(8)
                      verticalCenter: parent.verticalCenter }
            spacing: Style.space(10)

            Text {
              text: root.rowTitle(rowItem.modelData)
              color: root.isActiveRow(rowItem.modelData) ? root.accent
                : (rowItem.selected ? root.selFg : root.fg)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: root.isActiveRow(rowItem.modelData) || rowItem.rowType === "group"
              elide: Text.ElideRight
              width: Math.max(Style.space(80), parent.width * 0.40)
            }

            Text {
              text: root.rowSub(rowItem.modelData)
              color: rowItem.selected ? root.selFg : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              width: Math.max(Style.space(60), parent.width * 0.44)
            }

            Text {
              text: root.rowRight(rowItem.modelData)
              color: rowItem.selected ? root.selFg : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // In the settings tab the row carries its own steppers: `−` and `+`, the
          // mouse half of the -/+ keys. Glyphs checked against the font (U+2212,
          // U+002B in JetBrainsMono Nerd Font), not guessed.
          Item {
            id: stepPlus
            visible: root.frameMode === "settings"
              && (rowItem.modelData.kind === "int" || rowItem.modelData.kind === "enum")
            anchors { right: parent.right; rightMargin: Style.space(5)
                      verticalCenter: parent.verticalCenter }
            width: Style.space(20)
            height: Style.space(18)

            Rectangle {
              anchors.fill: parent
              radius: Style.cornerRadius
              color: plusArea.containsMouse ? root.accent : "transparent"
              border.width: Math.max(1, Style.normalBorderWidth)
              border.color: rowItem.selected ? root.selFg : root.line
            }

            Text {
              anchors.centerIn: parent
              text: "+"
              color: plusArea.containsMouse ? root.bg : (rowItem.selected ? root.selFg : root.fg)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            MouseArea {
              id: plusArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) { root.sel = rowItem.index; root.stepSetting(rowItem.modelData, 1) }
            }
          }

          Item {
            id: stepMinus
            visible: stepPlus.visible
            anchors { right: stepPlus.left; rightMargin: Style.space(5)
                      verticalCenter: parent.verticalCenter }
            width: Style.space(20)
            height: Style.space(18)

            Rectangle {
              anchors.fill: parent
              radius: Style.cornerRadius
              color: minusArea.containsMouse ? root.accent : "transparent"
              border.width: Math.max(1, Style.normalBorderWidth)
              border.color: rowItem.selected ? root.selFg : root.line
            }

            Text {
              anchors.centerIn: parent
              text: "−"
              color: minusArea.containsMouse ? root.bg : (rowItem.selected ? root.selFg : root.fg)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            MouseArea {
              id: minusArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) { root.sel = rowItem.index; root.stepSetting(rowItem.modelData, -1) }
            }
          }

          // `+`: append what this row stands for — the track, the album, the
          // artist, the folder. The mouse half of `a`.
          Item {
            id: addButton
            // Not in the settings tab: appending a setting to the queue makes no
            // sense, and the button would only be a stray glyph there.
            visible: !rowItem.isHeader && root.frameMode !== "settings"
            anchors { right: parent.right; rightMargin: Style.space(5)
                      verticalCenter: parent.verticalCenter }
            width: Style.space(22)
            height: Style.space(18)

            Rectangle {
              anchors.fill: parent
              radius: Style.cornerRadius
              color: addArea.containsMouse ? root.accent : "transparent"
              border.width: Math.max(1, Style.normalBorderWidth)
              border.color: rowItem.selected ? root.selFg : root.line
            }

            Text {
              anchors.centerIn: parent
              text: "+"
              color: addArea.containsMouse ? root.bg : (rowItem.selected ? root.selFg : root.fg)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            MouseArea {
              id: addArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) { root.sel = rowItem.index; root.addOne(rowItem.modelData) }
            }
          }

          // The bin, where something can actually be thrown away: a queue entry or
          // a song inside a stored playlist. Glyph checked against the font
          // (U+F01B4 in JetBrainsMono Nerd Font), not guessed.
          Item {
            id: trashButton
            visible: !rowItem.isHeader
              && (root.frameMode === "queue" || root.frameMode === "plist")
            anchors { right: addButton.left; rightMargin: Style.space(6)
                      verticalCenter: parent.verticalCenter }
            width: Style.space(22)
            height: Style.space(18)

            Rectangle {
              anchors.fill: parent
              radius: Style.cornerRadius
              color: trashArea.containsMouse ? root.accent : "transparent"
              border.width: Math.max(1, Style.normalBorderWidth)
              border.color: rowItem.selected ? root.selFg : root.line
            }

            Text {
              anchors.centerIn: parent
              text: "󰆴"
              color: trashArea.containsMouse ? root.bg : (rowItem.selected ? root.selFg : root.fg)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            MouseArea {
              id: trashArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) { root.sel = rowItem.index; root.removeRow() }
            }
          }
        }
      }

      Text {
        anchors.centerIn: list
        visible: root.rows.length === 0
        // Constrained: an unconstrained centred line runs over the card's edge.
        width: list.width - Style.space(40)
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: {
          if (root.loading) return "loading …"
          if (!root.up) return "no connection to MPD"
          if (root.frameMode === "search" && String(root.frame.term || "").trim() === "") return "type — it searches while you type"
          if (root.frameMode === "queue") return "queue is empty — a appends the selected track"
          if (root.frameMode === "playlists") return "no saved playlists — s saves the queue"
          return root.infoText
        }
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      // ------------------------------------------------------- song details
      Item {
        id: details
        anchors.fill: list
        visible: root.detailRow !== null || root.detailLoading
        z: 10

        Rectangle {
          anchors.fill: parent
          color: Util.alpha(root.bg, 0.98)
          radius: Style.cornerRadius
          border.width: Math.max(1, Style.normalBorderWidth)
          border.color: root.line
        }

        Text {
          id: detailsTitle
          anchors { top: parent.top; left: parent.left; right: parent.right; margins: Style.space(10) }
          text: root.detailTitle
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
        }

        Text {
          anchors.centerIn: parent
          visible: root.detailLoading
          text: "loading …"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Flickable {
          anchors { top: detailsTitle.bottom; topMargin: Style.space(8)
                    left: parent.left; right: parent.right; bottom: parent.bottom
                    margins: Style.space(10) }
          visible: root.detailRow !== null
          contentWidth: width
          contentHeight: detailColumn.implicitHeight + Style.space(8)
          clip: true

          Column {
            id: detailColumn
            width: parent.width
            spacing: Style.space(1)

            Repeater {
              model: root.detailRow !== null ? root.detailPairs() : []

              delegate: Row {
                id: detailLine
                required property var modelData
                spacing: Style.space(8)

                Text {
                  text: modelData.label
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  width: Style.space(140)
                  elide: Text.ElideRight
                }

                Text {
                  text: modelData.value
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  width: detailColumn.width - Style.space(150)
                  wrapMode: Text.WrapAnywhere
                }
              }
            }
          }
        }

        Text {
          anchors { right: parent.right; bottom: parent.bottom; margins: Style.space(10) }
          text: "esc closes"
          color: root.faint
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      // ------------------------------------------------------------ footer
      Item {
        id: footer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Style.space(40)

        Rectangle {
          anchors { top: parent.top; left: parent.left; right: parent.right }
          height: 1
          color: root.rule
        }

        // One line for what is going on: the prompt while one is up, otherwise
        // what the list is and what the keys do right here -- so `a` and `A`
        // do not have to be remembered.
        Item {
          id: statusRow
          anchors { top: parent.top; topMargin: Style.space(7); left: parent.left; right: parent.right }
          height: Style.space(22)

          Row {
            id: promptRow
            anchors.fill: parent
            spacing: Style.space(8)
            visible: root.promptMode !== ""

            Text {
              id: promptLabelText
              text: root.promptLabel
              color: root.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              height: Style.space(22)
              verticalAlignment: Text.AlignVCenter
            }

            Rectangle {
              id: promptField
              // What is left between the label and the readout. A fixed width here
              // (row minus a constant) pushed the readout out of the card.
              width: Math.max(Style.space(120),
                promptRow.width - promptLabelText.width - promptInfoText.width
                - promptRow.spacing * 2 - Style.space(8))
              height: Style.space(22)
              color: "transparent"
              border.width: Math.max(1, Style.normalBorderWidth)
              border.color: root.accent
              radius: Style.cornerRadius

              Text {
                anchors { left: parent.left; leftMargin: Style.space(6); verticalCenter: parent.verticalCenter }
                // Constrained, or a long term spills over the field's border.
                width: parent.width - Style.space(12)
                text: root.promptText === "" ? root.promptPlaceholder : root.promptText
                color: root.promptText === "" ? root.faint : root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }
            }

            Text {
              id: promptInfoText
              // The hits when there are any; the keys otherwise. The hint line
              // below this row is hidden while a prompt is up, so the one place
              // it can appear is here.
              // While the label format is being edited this slot shows what the
              // pattern does to the current song.
              text: root.promptMode === "format"
                ? "→ " + root.formatPreview
                : (root.infoText !== "" ? root.infoText : root.hint)
              color: root.promptMode === "format" ? root.accent
                : (root.infoText !== "" ? root.dim : root.faint)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              height: Style.space(22)
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
              width: Math.min(implicitWidth, promptRow.width * 0.38)
            }
          }

          Row {
            anchors.fill: parent
            spacing: Style.space(10)
            visible: root.promptMode === ""

            Text {
              id: statusInfo
              text: root.flashText !== "" ? root.flashText : root.infoText
              color: root.flashText !== "" ? root.accent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              height: Style.space(22)
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
              width: Math.min(implicitWidth, statusRow.width * 0.42)
            }

            Text {
              id: hintText
              // The pointer explains a glyph button; otherwise the keys.
              text: root.hoverHint !== "" ? root.hoverHint : root.hint
              color: root.hoverHint !== "" ? root.accent : root.faint
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              height: Style.space(22)
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
              // Everything the info line does not need. It used to take a flat 58 %
              // whether the info needed it or not, which is why the end of the key
              // hints kept disappearing ("t playing track" among them).
              width: Math.max(Style.space(140), statusRow.width - statusInfo.width - Style.space(12))
            }
          }
        }

      }
    }
  }

  // Tags in a stable, readable order: what a person looks for first, the ids
  // and formats last.
  function detailPairs() {
    var row = root.detailRow
    if (!row) return []
    var order = ["artist", "albumartist", "title", "album", "track", "disc", "date",
                 "genre", "composer", "performer", "name", "time", "duration",
                 "file", "last-modified", "format", "added"]
    var pairs = []
    var seen = ({})
    for (var i = 0; i < order.length; i++) {
      var key = order[i]
      if (row[key] === undefined || row[key] === "") continue
      seen[key] = true
      pairs.push({ label: labelFor(key), value: String(row[key]) })
    }
    for (var key2 in row) {
      if (seen[key2] || key2 === "type") continue
      if (row[key2] === "" || row[key2] === undefined) continue
      pairs.push({ label: labelFor(key2), value: String(row[key2]) })
    }
    return pairs
  }

  // ---------------------------------------------------------------- the band
  //
  // Which band component to load. Everything unknown falls back to the classic
  // band, so a wrong value in the setting cannot leave the panel without a player.
  function bandComponent() {
    if (root.look === "sharp") return bandScharf
    if (root.look === "hero") return bandHero
    if (root.look === "anchor") return bandAnker
    if (root.look === "vinyl") return bandVinyl
    if (root.look === "minimal") return bandMinimal
    if (root.look === "split") return bandSplit
    return bandKlassisch
  }

  // The band gets its values as bindings -- a plain assignment would freeze at the
  // first song -- and talks back through its two signals.
  function wireBand(b) {
    if (!b) return
    b.host = Qt.binding(function() { return root.host })
    b.fontFamily = Qt.binding(function() { return root.fontFamily })
    b.vizBars = Qt.binding(function() { return root.host ? root.host.vizBars : [] })
    b.vizCount = Qt.binding(function() { return root.host ? root.host.vizCount : 12 })
    b.message.connect(function(text) { root.flash(String(text)) })
    b.hint.connect(function(text) { root.hoverHint = String(text) })
  }

  Component { id: bandKlassisch; BandKlassisch {} }
  Component { id: bandScharf; BandScharf {} }
  Component { id: bandHero; BandHero {} }
  Component { id: bandAnker; BandAnker {} }
  Component { id: bandVinyl; BandVinyl {} }
  Component { id: bandMinimal; BandMinimal {} }
  Component { id: bandSplit; BandSplit {} }

  function labelFor(key) {
    var names = {
      artist: "Artists", albumartist: "Album artist", title: "Title", album: "Album",
      track: "Track", disc: "Disc", date: "Datum", genre: "Genre", composer: "Komponist",
      performer: "Performer", name: "Name", time: "Length", duration: "Length (s)",
      file: "File", "last-modified": "Modified", format: "Format", added: "Added"
    }
    return names[key] !== undefined ? names[key] : key
  }
}
