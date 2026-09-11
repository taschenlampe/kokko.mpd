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
  // True when the field was opened with `/` -- the explicit "I want to type"
  // gesture. Only then do digits go into the term while the field is still empty
  // (see the number keys in handleKey).
  property bool promptExplicit: false
  // Where the selection should land once the next list arrives ("first"/"last"),
  // set when the user leaves the search field with ↓ or ↑.
  property string pendingSelect: ""
  // Set while the pointer rests on a button that is only a glyph: the footer then
  // spells out what it does instead of the key hints.
  property string hoverHint: ""

  // Song details overlay: the row from the `songinfo` query, or null.
  property var detailRow: null
  property string detailTitle: ""
  property bool detailLoading: false

  readonly property var frame: stack.length > 0 ? stack[stack.length - 1] : null
  readonly property string frameMode: frame ? String(frame.mode || "") : ""
  readonly property string frameTitle: frame ? String(frame.title || "") : ""
  readonly property string promptLabel: promptMode === "save" ? "Queue speichern als:"
    : (promptMode === "rename" ? "Playlist umbenennen:"
    : (promptMode === "format" ? "Label-Format:" : "suchen:"))
  readonly property string promptPlaceholder: promptMode === "search"
    ? "Titel, Künstler, Album …"
    : (promptMode === "format" ? "[%artist% - ][%title%|%filename%]" : "Name eintippen, Enter bestätigt")

  // Passing the frame in rather than reading `frame` inside this handler: QML
  // re-evaluates dependent bindings *after* the change signal, so `root.frame`
  // here is still the previous one -- which loaded the list the user had just
  // left.
  onStackChanged: root.loadFrame(root.stack[root.stack.length - 1])
  onUpChanged: if (root.up) root.loadFrame()

  Connections {
    target: root.host
    function onConnectedChanged() { if (root.host && root.host.connected) root.loadFrame() }
    function onDatabaseRevisionChanged() { root.loadFrame() }
    // The queue can change from anywhere (the bar, a bind, another client), so
    // re-read it when MPD says its length moved.
    function onQueueLengthChanged() { if (root.frameMode === "queue") reloadTimer.restart() }
    // MPD answers `findadd`/`searchadd` with a bare OK, so a filter that matches
    // nothing is silent there. The bridge turns that silence into an ack, and the
    // footer repeats it instead of leaving the optimistic "angehängt" standing.
    function onLastAckChanged() {
      if (root.host && String(root.host.lastAck || "") !== "") root.flash(String(root.host.lastAck))
    }
  }

  // ----------------------------------------------------------------- frames
  function rootFrameFor(tab) {
    if (tab === "queue") return { mode: "queue", title: "Queue" }
    if (tab === "search") return { mode: "search", title: "Suche" }
    if (tab === "albums") return { mode: "list", tag: "album", filter: [], title: "Alben" }
    if (tab === "artists") return { mode: "list", tag: "artist", filter: [], title: "Künstler" }
    if (tab === "genres") return { mode: "list", tag: "genre", filter: [], title: "Genres" }
    if (tab === "files") return { mode: "files", path: "", title: "Bibliothek" }
    if (tab === "settings") return { mode: "settings", title: "Einstellungen" }
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

    if (!root.up) { root.rows = []; root.setInfo("keine Verbindung zu MPD"); return }

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
      root.rows = (mode === "search") ? root.groupHits(list) : (list || [])
      // Leaving the field with ↑ lands at the bottom of the list, with ↓ at the
      // top; the load itself only knows "first hit", so the wish rides along here.
      if (root.pendingSelect === "last") { root.sel = root.lastSelectable(); root.pendingSelect = "" }
      else {
        root.sel = root.firstSelectable(0)
        if (root.pendingSelect === "first") root.pendingSelect = ""
      }
      root.setInfo(root.infoFor(mode, f, list))

      // An artist (or genre) whose tracks carry no album tag has no album list to
      // show. Rather than leaving an empty frame -- a dead end right where the
      // user was looking for something to play -- fall back to the tracks.
      if (mode === "list" && root.rows.length === 0 && (f.filter || []).length > 0) {
        var fallback = { mode: "find", title: String(f.title || "") + " — Titel",
                         sort: "track", filter: f.filter }
        root.stack = root.stack.slice(0, root.stack.length - 1).concat([fallback])
        return                      // the stack change loads the new frame
      }
    }

    root.sentQueries++
    if (mode === "queue") { host.query("queue", { limit: 2000 }, "list", answer); return }
    if (mode === "search") { host.query("search", { term: term, limit: 800 }, "list", answer); return }
    if (mode === "list") {
      host.query("list", { tag: String(f.tag || "album"), filter: f.filter || [], limit: 3000 }, "list", answer)
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
    root.setInfo("unbekannte Ansicht: " + mode)
  }

  function infoFor(mode, f, list) {
    var n = (list || []).length
    if (mode === "queue") return n + " Einträge"
    if (mode === "search") return n + (n >= 800 ? "+" : "") + " Treffer für „" + String(f.term || "") + "“"
    if (mode === "list") return n + " Einträge"
    if (mode === "find") return n + " Titel"
    if (mode === "files") return String(f.path || "") === "" ? "Bibliothek — " + n + " Einträge" : String(f.path) + " — " + n
    if (mode === "playlists") return n + " Playlists"
    if (mode === "plist") return n + " Titel"
    return n + " Einträge"
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
      rows.push({ type: "header", title: "Künstler" })
      for (var a = 0; a < artists.order.length && a < 30; a++)
        rows.push({ type: "group", kind: "artist", value: artists.order[a],
                    count: artists.counts[artists.order[a]] })
    }

    var albums = tally("album")
    if (albums.order.length > 0) {
      rows.push({ type: "header", title: "Alben" })
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

    rows.push({ type: "header", title: "Titel — " + songs.length
      + (songs.length >= 800 ? "+" : "") + " Treffer" })
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
      { type: "setting", kind: "bool", key: "hoverCard", title: "Karte beim Überfahren",
        value: h.hoverCard === true,
        hint: "Cover, Fortschritt und die großen Bedienknöpfe unter der Leiste" },
      { type: "setting", kind: "int", key: "backdrop", title: "Cover-Hintergrund",
        min: 0, max: 100, step: 10, value: Number(h.backdrop), suffix: " %",
        hint: "0 schaltet ihn aus; höher = präsenter hinter Queue und Suche" },
      { type: "setting", kind: "text", key: "format", title: "Label-Format",
        value: String(h.format),
        hint: "mpc-Platzhalter — enter zum Bearbeiten, Vorschau unten" },
      { type: "setting", kind: "int", key: "osdDuration", title: "Karte sichtbar",
        min: 1000, max: 20000, step: 500, value: Number(h.osdDuration), suffix: " ms",
        hint: "wie lange die Karte bei Titelwechsel stehen bleibt" },
      { type: "setting", kind: "bool", key: "notifyTrack", title: "Benachrichtigung bei Titelwechsel",
        value: h.notifyTrack === true,
        hint: "Desktop-Hinweis mit Cover" }
    ]
  }

  function writeSetting(key, value, label) {
    if (root.host === null) return
    root.host.setSetting(key, value)
    var shown = (value === true) ? "an" : (value === false) ? "aus" : String(value)
    root.flash(String(label || key) + ": " + shown)
    root.note("setting " + key + " = " + shown)
  }

  // What the pattern being typed would produce for the song that is playing.
  readonly property string formatPreview: {
    var pattern = root.promptText.trim()
    if (pattern === "") return "(leer)"
    var out = root.host !== null ? root.host.previewLabel(pattern) : ""
    return out === "" ? "(kein laufender Titel)" : out
  }

  function rowSub(row) {
    if (!row) return ""
    if (row.type === "setting") return String(row.hint || "")
    if (row.type === "group") return row.kind === "album" ? String(row.artist || "") : ""
    if (row.type === "value" || row.type === "playlist") return ""
    if (row.type === "directory") return "Ordner"
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
      if (row.kind === "bool") return row.value === true ? "an" : "aus"
      if (row.kind === "int") return String(row.value) + String(row.suffix || "")
      return String(row.value || "")
    }
    if (row.type === "group") return String(row.count || 0) + " Titel"
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
      if (row.kind === "bool") root.writeSetting(row.key, row.value !== true, row.title)
      else if (row.kind === "text") root.openPrompt("format", String(row.value || ""), true)
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
          { mode: "find", title: albumName + " — Titel", sort: "track",
            filter: [["artist", byArtist], ["album", albumName]] }
        ])
        root.sel = 0
        root.detailRow = null
        return
      }
      root.pushFrame({ mode: "find", title: albumName + " — Titel", sort: "track",
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
        root.pushFrame({ mode: "find", title: value + " — Titel", sort: "track",
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
        what = "alle Titel von " + String(row.value || "")
      } else {
        host.mutation("findadd", { filter: [["album", String(row.value || "")]] })
        what = "Album „" + String(row.value || "") + "“"
      }
    } else if (type === "value") {
      var tag = String(root.frame.tag || "")
      if (tag === "") { root.flash("diese Liste lässt sich nicht als Filter anhängen"); return }
      host.mutation("findadd", { filter: (root.frame.filter || []).concat([[tag, String(row.value || "")]]) })
      what = String(row.value || "")
    } else if (type === "directory") {
      host.addUri(String(row.directory || ""))
      what = "Ordner " + String(row.directory || "")
    } else if (type === "playlist") {
      host.mutation("loadplaylist", { name: String(row.playlist || "") })
      what = "Playlist " + String(row.playlist || "") + " (ersetzt die Queue)"
    } else if (row.file) {
      host.addUri(String(row.file))
      what = root.rowTitle(row)
    }

    if (what !== "") root.flash("angehängt: " + what)
  }

  function addAll() {
    if (!root.up) return
    var mode = root.frameMode

    if (mode === "search") {
      var term = String(root.frame.term || "").trim()
      if (term === "") return
      host.mutation("searchadd", { term: term })
      root.flash("alle Treffer für „" + term + "“ angehängt")
      return
    }
    if (mode === "find") {
      var filter = root.frame.filter || []
      if (filter.length === 0) { root.flash("nichts anzuhängen"); return }
      host.mutation("findadd", { filter: filter })
      root.flash("alle Titel dieser Liste angehängt")
      return
    }
    if (mode === "list") {
      var base = root.frame.filter || []
      if (base.length === 0) { root.flash("erst Künstler oder Album öffnen, dann A"); return }
      host.mutation("findadd", { filter: base })
      root.flash("alles unter dieser Auswahl angehängt")
      return
    }
    if (mode === "files") {
      var path = String(root.frame.path || "")
      if (path === "") { root.flash("erst in einen Ordner gehen, dann A"); return }
      host.addUri(path)
      root.flash("Ordner " + path + " angehängt")
      return
    }
    if (mode === "plist") { root.flash("Playlist laden: a auf der Liste im Playlists-Tab"); return }
    if (mode === "queue") { root.flash("in der Queue hängt a einzelne Titel an"); return }
    root.flash("hier gibt es nichts anzuhängen")
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

  // What the keys do right here, so nothing has to be remembered.
  readonly property string hint: {
    if (root.promptMode === "search")
      return (root.promptText === "" && !root.promptExplicit)
        ? "tippen sucht · 1–8 wechseln den Tab · ↓/↑ geht in die Liste · / für Ziffern · esc fertig"
        : "tippen filtert · ↓/↑ geht in die Liste · enter spielt den Treffer · ctrl+u leeren · esc fertig"
    if (root.promptMode !== "") return "tippen · enter bestätigen · esc abbrechen"
    var mode = root.frameMode
    if (mode === "queue") return "enter spielen · a anhängen · d entfernen · D leeren · C nur Laufendes behalten · J/K verschieben · x mischen"
    if (mode === "search") return "/ tippen · enter öffnen · a anhängen · A alle Treffer · h/esc zurück"
    if (mode === "list") return "enter hinein · a alles davon anhängen · A Auswahl anhängen · h/esc zurück"
    if (mode === "find") return "enter spielen · a anhängen · A ganze Liste · h/esc zurück"
    if (mode === "files") return "enter hinein/abspielen · a anhängen · A ganzer Ordner · ← zurück"
    if (mode === "playlists") return "enter öffnen · a laden · s Queue speichern · r umbenennen · d löschen"
    if (mode === "plist") return "enter spielen · a anhängen · d Titel entfernen · ← zurück"
    if (mode === "settings") return "enter/space schalten um · -/+ ändern die Zahl · 8 wählt den Tab · esc zurück"
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
    root.sel = Math.max(0, Math.min(root.rows.length - 1, root.sel + delta))
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
  }

  // Leave the field but keep the term: the results stay on screen, the keys go to
  // the list (`a`, enter, j/k), and `/` comes back with the term still in the
  // field. Without the flush, a pending debounce would land after the fact and
  // wipe the list.
  function leavePrompt() {
    promptDebounce.stop()
    if (root.promptMode === "search" && root.promptText.trim() !== "")
      root.applySearch(root.promptText)
    root.promptMode = ""
  }

  // Live search: every keystroke re-runs the query after a short pause, and the
  // bridge drops the query a newer one supersedes on the same channel -- so
  // typing eight letters costs one MPD search, not eight.
  function searchWhileTyping() {
    if (root.promptMode !== "search") return
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
    onTriggered: root.applySearch(root.promptText)
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
                      title: trimmed === "" ? "Suche" : "Suche: " + trimmed }
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

  function submitPrompt() {
    var text = root.promptText.trim()
    if (root.promptMode === "search") {
      if (text === "") return
      root.applySearch(text)
      // The field stays up: a correction costs nothing, esc leaves it.
      return
    }
    if (root.promptMode === "save") {
      if (text === "" || !root.up) return
      mutateAndReload("saveplaylist", { name: text })
      root.setInfo("Queue gespeichert als „" + text + "“")
      root.closePrompt()
      return
    }
    if (root.promptMode === "rename") {
      var row = root.rows[root.sel]
      var from = row ? String(row.playlist || "") : ""
      if (text === "" || from === "" || !root.up) return
      mutateAndReload("renameplaylist", { name: from, to: text })
      root.setInfo("„" + from + "“ heißt jetzt „" + text + "“")
      root.closePrompt()
      return
    }
    if (root.promptMode === "format") {
      if (text === "") return
      var srow = root.rows[root.sel]
      root.writeSetting("format", text, srow ? srow.title : "Label-Format")
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
      if (root.promptMode === "search" && (key === Qt.Key_Down || key === Qt.Key_Up)) {
        var goLast = (key === Qt.Key_Up)
        var hadTerm = root.promptText.trim() !== ""
        root.leavePrompt()
        root.sel = goLast ? root.lastSelectable() : root.firstSelectable(0)
        // The re-run above answers later and resets the selection to the top hit;
        // the wish has to survive that.
        if (hadTerm) { root.pendingSelect = goLast ? "last" : "first"; pendingSelectGuard.restart() }
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
      // In the order of what is on top: the details overlay, then one frame back,
      // then closing the panel. Closing the whole panel from three levels deep
      // is not what somebody pressing `esc` means.
      if (root.detailRow !== null) { root.detailRow = null; event.accepted = true; return }
      if (root.popFrame()) { event.accepted = true; return }
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
      if (srow && srow.kind === "int" && (text === "-" || text === "+" || text === "=")) {
        var step = Number(srow.step || 5)
        var next = Number(srow.value || 0) + ((text === "-") ? -step : step)
        next = Math.max(Number(srow.min || 0), Math.min(Number(srow.max || 100), next))
        root.writeSetting(srow.key, next, srow.title)
        event.accepted = true
        return
      }
      if (srow && srow.kind === "bool"
          && (key === Qt.Key_Space || key === Qt.Key_Return || key === Qt.Key_Enter || text === "p")) {
        root.writeSetting(srow.key, srow.value !== true, srow.title)
        event.accepted = true
        return
      }
    }

    if (key === Qt.Key_Slash) { root.setTab("search", true); event.accepted = true; return }
    if (text === "i" && root.frameMode !== "playlists") { root.showDetails(); event.accepted = true; return }

    if (key === Qt.Key_Down || text === "j") { root.step(1); event.accepted = true; return }
    if (key === Qt.Key_Up || text === "k") { root.step(-1); event.accepted = true; return }
    if (key === Qt.Key_PageDown) { root.step(10); event.accepted = true; return }
    if (key === Qt.Key_PageUp) { root.step(-10); event.accepted = true; return }
    if (text === "g") { root.sel = 0; event.accepted = true; return }
    if (text === "G" || key === Qt.Key_End) { root.sel = Math.max(0, root.rows.length - 1); event.accepted = true; return }

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
    if (text === "x") { if (root.frameMode === "queue") host.shuffleQueue(); event.accepted = true; return }
    if (text === "J") { root.moveRow(1); event.accepted = true; return }
    if (text === "K") { root.moveRow(-1); event.accepted = true; return }
    if (text === "s" && root.frameMode !== "search") { root.openPrompt("save", "", true); event.accepted = true; return }
    if (text === "r" && root.frameMode === "playlists") {
      var row = root.rows[root.sel]
      root.openPrompt("rename", row ? String(row.playlist || "") : "", true)
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
      if (root.stack.length === 0) root.setTab(root.tab)
      else root.loadFrame()
      Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) { root.handleKey(event) }

      // ------------------------------------------------ the cover, blurred
      //
      // Behind everything: the now-playing cover, blurred, faded into the panel
      // colour and, from the lower half down, gone -- that is what keeps the rows
      // readable. How loud it is comes from one setting (`backdrop`), because the
      // three levers pull the same way: opacity up, blur down and saturation up
      // together make a cover read as "more cover". Turning one of them alone
      // either leaves it washed out (only opacity) or turns it into confetti
      // (only blur).
      Item {
        id: backdrop
        anchors.fill: parent
        visible: root.backdropLevel > 0
                 && root.host !== null && root.host.artPath !== ""

        Image {
          id: backdropSource
          anchors.fill: parent
          source: root.host ? root.host.artPath : ""
          sourceSize.width: 1200
          sourceSize.height: 800
          fillMode: Image.PreserveAspectCrop
          asynchronous: true
          visible: false        // MultiEffect draws it; showing it too would double it
        }

        MultiEffect {
          anchors.fill: backdrop
          source: backdropSource
          autoPaddingEnabled: false
          blurEnabled: backdropSource.status === Image.Ready
          blur: 1.0
          blurMax: 96
          // 0 -> soft and barely there, 1 -> shapes stay recognisable.
          blurMultiplier: 1.5 - 1.1 * root.backdropLevel
          saturation: 0.5 * root.backdropLevel
          brightness: 0.03 * root.backdropLevel
          opacity: 0.18 + 0.62 * root.backdropLevel
        }

        Rectangle {
          anchors.fill: parent
          gradient: Gradient {
            // The fade down starts lower the bolder the backdrop is, so more of
            // the cover survives above the list.
            GradientStop { position: 0.0; color: Util.alpha(root.bg, 0.36 - 0.26 * root.backdropLevel) }
            GradientStop { position: 0.40; color: Util.alpha(root.bg, 0.86 - 0.26 * root.backdropLevel) }
            GradientStop { position: 0.66 + 0.12 * root.backdropLevel; color: root.bg }
            GradientStop { position: 1.0; color: root.bg }
          }
        }
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
      // Cover, what is playing, and the controls -- so pausing does not need a
      // trip to the bar.
      Item {
        id: nowBand
        anchors { top: headerRule.bottom; topMargin: Style.space(7)
                  left: parent.left; right: parent.right }
        height: root.host && root.host.hasSong ? Style.space(74) : 0
        visible: height > 0

        Rectangle {
          anchors.fill: parent
          color: Util.alpha(root.fg, 0.05)
          radius: Style.cornerRadius
        }

        Rectangle {
          id: bandCover
          anchors { left: parent.left; leftMargin: Style.space(8); verticalCenter: parent.verticalCenter }
          width: Style.space(58)
          height: width
          radius: Style.cornerRadius
          color: Util.alpha(root.fg, 0.06)
          border.width: Math.max(1, Style.normalBorderWidth)
          border.color: root.line
          clip: true

          Image {
            id: bandCoverImage
            anchors.fill: parent
            source: root.bandArt
            sourceSize.width: 160
            sourceSize.height: 160
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            visible: status === Image.Ready
          }

          Text {
            anchors.centerIn: parent
            visible: bandCoverImage.status !== Image.Ready
            text: root.host && root.host.isPlaying ? "󰏤" : "󰐊"
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.displayLarge
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (root.host) root.host.toggleTrack()
          }
        }

        Column {
          id: bandText
          anchors { left: bandCover.right; leftMargin: Style.space(12)
                    right: bandViz.left; rightMargin: Style.space(12)
                    verticalCenter: parent.verticalCenter }
          spacing: Style.space(3)

          Text {
            width: parent.width
            text: root.host && root.host.hasSong
              ? (String(root.host.song.title || "") || root.host.basename(root.host.song.file))
              : ""
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            text: {
              if (!root.host || !root.host.hasSong) return ""
              var bits = []
              if (root.host.song.artist) bits.push(String(root.host.song.artist))
              if (root.host.song.album) bits.push(String(root.host.song.album))
              if (root.host.queueLength > 0) bits.push("#" + (root.host.queuePosition + 1) + "/" + root.host.queueLength)
              return bits.join("  ·  ")
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          // Progress: times beside the line, click on the line to seek there.
          Item {
            id: bandProgress
            width: parent.width
            height: Style.space(16)

            readonly property real fraction: (root.host && root.host.duration > 0)
              ? Math.max(0, Math.min(1, root.host.elapsed / root.host.duration)) : 0

            Text {
              id: bandElapsed
              anchors { left: parent.left; verticalCenter: parent.verticalCenter }
              text: root.host && root.host.hasSong ? root.host.formatTime(root.host.elapsed) : ""
              color: root.faint
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              id: bandDuration
              anchors { right: parent.right; verticalCenter: parent.verticalCenter }
              text: (root.host && root.host.hasSong && root.host.duration > 0)
                ? root.host.formatTime(root.host.duration) : ""
              color: root.faint
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Rectangle {
              id: bandBar
              anchors { left: bandElapsed.right; leftMargin: Style.space(8)
                        right: bandDuration.left; rightMargin: Style.space(8)
                        verticalCenter: parent.verticalCenter }
              height: Style.space(4)
              radius: height / 2
              color: root.line

              Rectangle {
                width: parent.width * bandProgress.fraction
                height: parent.height
                radius: parent.radius
                color: root.accent
              }
            }

            MouseArea {
              anchors { left: bandBar.left; right: bandBar.right
                        top: parent.top; bottom: parent.bottom }
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) {
                if (!root.host || !root.host.hasSong || root.host.duration <= 0) return
                root.host.bare("seek " + Math.round((mouse.x / width) * root.host.duration))
              }
            }
          }
        }

        // cava, live: the bars sit between the text and the buttons.
        Visualizer {
          id: bandViz
          anchors { right: bandButtons.left; rightMargin: Style.space(14)
                    verticalCenter: parent.verticalCenter }
          width: Style.space(150)
          height: Style.space(30)
          visible: root.host !== null && root.host.queueLength > 0
          levels: root.host ? root.host.vizBars : []
          count: root.host ? root.host.vizCount : 12
        }

        Row {
          id: bandButtons
          anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
          spacing: Style.space(16)
          // Explicit height: the children say `height: parent.height`, and a Row
          // whose height comes from its children would resolve that to 0 -- which
          // is exactly how these buttons disappeared.
          height: Style.space(30)

          Text {
            text: "󰒮"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: if (root.host) root.host.previousTrack() }
          }

          Text {
            text: root.host && root.host.isPlaying ? "󰏤" : "󰐊"
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: if (root.host) root.host.toggleTrack() }
          }

          Text {
            text: "󰒭"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: if (root.host) root.host.nextTrack() }
          }

          // The same two playback options the hover card offers, in the same
          // colours: accent while on, dim while off. The footer used to print
          // them as text; the buttons say it better.
          Text {
            text: root.host && root.host.randomOn ? "󰒝" : "󰒞"
            color: root.host && root.host.randomOn ? root.accent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                if (!root.host) return
                var on = !root.host.randomOn
                root.host.toggleOption("random")
                root.flash(on ? "Zufall an" : "Zufall aus")
              }
            }
          }

          Text {
            text: root.host && root.host.repeatOn
              ? (root.host.singleMode !== "0" ? "󰑘" : "󰑖") : "󰑗"
            color: root.host && root.host.repeatOn ? root.accent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.subtitle
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                if (!root.host) return
                var on = !root.host.repeatOn
                root.host.toggleOption("repeat")
                root.flash(on ? "Wiederholen an" : "Wiederholen aus")
              }
            }
          }

          // Queue: icons instead of the words "löschen"/"nur dieses" -- two
          // glyphs that are distinct from the per-row bin, with the full wording
          // in the footer while the pointer rests on them (and in the queue hint
          // as `D leeren` / `C nur Laufendes behalten` anyway).
          Item {
            width: Style.space(26)
            height: parent.height

            Text {
              anchors.centerIn: parent
              text: "󰗩"                     // delete_sweep: everything out
              color: clearArea.containsMouse ? root.accent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
            }

            MouseArea {
              id: clearArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onEntered: root.hoverHint = "Queue leeren — alle Titel entfernen (D)"
              onExited: root.hoverHint = ""
              onClicked: {
                if (!root.host) return
                root.host.clearQueue()
                root.flash("Queue geleert")
              }
            }
          }

          Item {
            width: Style.space(26)
            height: parent.height

            Text {
              anchors.centerIn: parent
              text: "󰆐"                     // content_cut: cut the rest away
              color: keepArea.containsMouse ? root.accent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
            }

            MouseArea {
              id: keepArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onEntered: root.hoverHint = "nur das Laufende behalten — alles andere aus der Queue (C)"
              onExited: root.hoverHint = ""
              onClicked: {
                if (!root.host) return
                root.host.cropQueue()
                root.flash("alles außer dem laufenden Titel entfernt")
              }
            }
          }
        }
      }

      // ------------------------------------------------------------- list
      ListView {
        id: list
        anchors { top: nowBand.bottom; topMargin: Style.space(6)
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
          height: rowItem.isHeader ? Style.space(22) : Style.space(26)

          readonly property string rowType: String(rowItem.modelData.type || "")
          readonly property bool isHeader: rowItem.rowType === "header"
          readonly property bool selected: index === root.sel && !rowItem.isHeader

          Rectangle {
            anchors.fill: parent
            color: rowItem.selected ? root.selBg : "transparent"
            radius: Style.cornerRadius
          }

          // A section label: Künstler / Alben / Titel.
          Text {
            visible: rowItem.isHeader
            anchors { left: parent.left; leftMargin: Style.space(8); verticalCenter: parent.verticalCenter }
            text: rowItem.isHeader ? String(rowItem.modelData.title || "") : ""
            color: root.accent
            opacity: 0.9
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
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
                      right: trashButton.visible ? trashButton.left : addButton.left
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
          if (root.loading) return "lade …"
          if (!root.up) return "keine Verbindung zu MPD"
          if (root.frameMode === "search" && String(root.frame.term || "").trim() === "") return "tippen — gesucht wird, während du schreibst"
          if (root.frameMode === "queue") return "Queue ist leer — a hängt den markierten Titel an"
          if (root.frameMode === "playlists") return "keine gespeicherten Playlists — s speichert die Queue"
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
          text: "lade …"
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
          text: "esc schließt"
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
              // The pointer explains a glyph button; otherwise the keys.
              text: root.hoverHint !== "" ? root.hoverHint : root.hint
              color: root.hoverHint !== "" ? root.accent : root.faint
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              height: Style.space(22)
              verticalAlignment: Text.AlignVCenter
              elide: Text.ElideRight
              width: Math.max(Style.space(80), statusRow.width - Math.min(statusRow.width * 0.42, statusRow.width) - Style.space(12))
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

  function labelFor(key) {
    var names = {
      artist: "Künstler", albumartist: "Album-Künstler", title: "Titel", album: "Album",
      track: "Track", disc: "Disc", date: "Datum", genre: "Genre", composer: "Komponist",
      performer: "Performer", name: "Name", time: "Länge", duration: "Länge (s)",
      file: "Datei", "last-modified": "Geändert", format: "Format", added: "Hinzugefügt"
    }
    return names[key] !== undefined ? names[key] : key
  }
}
