#!/usr/bin/env node
// The three media surfaces and the "connected, but not answering" state.
//
// The bar widget owns the verdict: BarWidget.qml answers `stale` (connected and
// the greeting probe has failed -- see HEALTH_INTERVAL in the bridge). The
// surfaces around it are siblings, not copies of it: the hover card
// (MiniPlayer.qml) sees the widget as `service`, the card on the wallpaper
// (DesktopCard.qml) and the playback band (BandChrome.qml) see it as `host`.
// They derive the state from it -- this suite checks that they do, and that
// each of them stops presenting the last title, the last clock and the last
// position as if they were current while the daemon is wedged.
//
// Method (same as tests/test_barwidget_state.js): every binding under test is
// pulled out of the shipped source verbatim by brace / expression matching and
// then run under node with a small model of the widget. Each piece prints its
// source line range and a hash of the extracted body, so a silent edit of the
// code under test shows up here instead of passing quietly. Against the
// unfixed sources the cases fail on the *value* (the title is still the song,
// the clock still runs) -- that is what makes this suite the proof that the
// fix is what makes it pass, not a tautology over property names.
//
// Measured control values (elapsed 37 s, duration 341 s, queue 3/7):
//   title  "Dayvan Cowboy"   artist "Boards of Canada"
//   meta   "Boards of Canada  ·  Music Has the Right to Children  ·  #3/7"
//   clock  "0:37" / "5:41"
//
// Usage:
//   node tests/test_media_surfaces.js                     # the repo's files
//   node tests/test_media_surfaces.js /tmp/stale-orig     # a copy (3 .qml + README + Panel)
//   node tests/test_media_surfaces.js Mini.qml Card.qml Band.qml
"use strict"

const fs = require("fs")
const path = require("path")
const crypto = require("crypto")

// --- what is under test -----------------------------------------------------
const args = process.argv.slice(2)
let root, miniFile, cardFile, bandFile
if (args.length === 0) {
  root = path.join(__dirname, "..")
  miniFile = path.join(root, "MiniPlayer.qml")
  cardFile = path.join(root, "DesktopCard.qml")
  bandFile = path.join(root, "BandChrome.qml")
} else if (args.length === 1) {
  root = path.resolve(args[0])
  miniFile = path.join(root, "MiniPlayer.qml")
  cardFile = path.join(root, "DesktopCard.qml")
  bandFile = path.join(root, "BandChrome.qml")
} else if (args.length === 3) {
  miniFile = path.resolve(args[0])
  cardFile = path.resolve(args[1])
  bandFile = path.resolve(args[2])
  root = path.dirname(miniFile)
} else {
  console.error("usage: node tests/test_media_surfaces.js [dir | 3 .qml paths]")
  process.exit(2)
}

const src = {
  mini: fs.readFileSync(miniFile, "utf8"),
  card: fs.readFileSync(cardFile, "utf8"),
  band: fs.readFileSync(bandFile, "utf8")
}

// The widget itself (its surfaces live here: the OSD, the wallpaper card) and
// the label's format language. Read lazily so a copy that holds only the three
// sibling surfaces still runs every case that does not need them.
function readBeside(name) {
  try { return fs.readFileSync(path.join(root, name), "utf8") } catch (e) { return "" }
}
const barSrc = readBeside("BarWidget.qml")
const formatSrc = readBeside("Format.js")

// --- verbatim extraction ----------------------------------------------------
function matchBraces(text, open) {
  let depth = 0
  let i = open
  let inStr = null
  while (i < text.length) {
    const ch = text[i]
    if (inStr) {
      if (ch === "\\") { i += 2; continue }
      if (ch === inStr) inStr = null
    } else if (ch === "\"" || ch === "'") {
      inStr = ch
    } else if (ch === "/" && text[i + 1] === "/") {
      i = text.indexOf("\n", i)
      if (i < 0) break
      continue
    } else if (ch === "{") {
      depth++
    } else if (ch === "}") {
      depth--
      if (depth === 0) return i
    }
    i++
  }
  throw new Error("unbalanced braces at offset " + open)
}

function lineOf(text, idx) { return text.slice(0, idx).split("\n").length }

function mkPiece(text, start, end, what) {
  const body = text.slice(start, end)
  return {
    what: what,
    body: body,
    first: lineOf(text, start),
    last: lineOf(text, end),
    hash: crypto.createHash("sha256").update(body).digest("hex").slice(0, 12)
  }
}

// The expression that starts at (or just after) an offset: consumed until the
// line ends at bracket depth 0 and the next line does not continue it with an
// operator. This is what makes the multi-line ternaries readable as one string.
const CONTINUE = "?:|&.,+("
function readExpr(text, from, what) {
  if (from === null || from === undefined || from < 0) return null
  let i = from
  while (text[i] === " " || text[i] === "\t") i++
  const start = i
  let depth = 0
  let inStr = null
  while (i < text.length) {
    const ch = text[i]
    if (inStr) {
      if (ch === "\\") { i += 2; continue }
      if (ch === inStr) inStr = null
      i++
      continue
    }
    if (ch === "\"" || ch === "'") { inStr = ch; i++; continue }
    if (ch === "/" && text[i + 1] === "/") {
      i = text.indexOf("\n", i)
      if (i < 0) break
      continue
    }
    if (ch === "{" || ch === "(" || ch === "[") depth++
    else if (ch === "}" || ch === ")" || ch === "]") depth--
    if (ch === "\n" && depth <= 0) {
      let j = i + 1
      while (j < text.length && (text[j] === " " || text[j] === "\t")) j++
      const tail = text.slice(start, i).trimEnd()
      const last = tail[tail.length - 1] || ""
      const next = text[j] || ""
      // An empty tail is an expression that never started; nothing to continue.
      if (last === "" || (CONTINUE.indexOf(next) < 0 && CONTINUE.indexOf(last) < 0)) break
    }
    i++
  }
  return mkPiece(text, start, i, what)
}

// `name: <expression>` -- anchored on the property name, the id or a comment
// line that stays in place, so the piece is found in the fixed and in the
// unfixed source alike.
function exprAt(text, re, what) {
  const m = re.exec(text)
  if (!m) return null
  return readExpr(text, m.index + m[0].length, what)
}

// `name: { ... }` -- the block after the anchor, braces matched.
function blockAt(text, re, what) {
  const m = re.exec(text)
  if (!m) return null
  const open = text.indexOf("{", m.index)
  if (open < 0) return null
  return mkPiece(text, open, matchBraces(text, open) + 1, what)
}

// A whole declaration: from the anchor (the `function` keyword) through its
// closing brace. `blockAt` starts at the brace and would leave the signature
// behind, which turns the body into a block that runs where it stands.
function declAt(text, re, what) {
  const m = re.exec(text)
  if (!m) return null
  const open = text.indexOf("{", m.index)
  if (open < 0) return null
  return mkPiece(text, m.index, matchBraces(text, open) + 1, what)
}

// The block whose opening `{` stands before a match -- the item that encloses
// the anchored line. This is how an *anonymous* item (a MouseArea with only
// `acceptedButtons: ...`) is pulled out: there is no id to name it by.
function enclosingBlock(text, re, what) {
  const m = re.exec(text)
  if (!m) return null
  const open = text.lastIndexOf("{", m.index)
  if (open < 0) return null
  return mkPiece(text, open, matchBraces(text, open) + 1, what)
}

// `id: name` -- the same, anchored on the id instead: the one stable name of a
// hover area. In the unfixed source the id does not exist and the piece is
// absent, which is what makes the check fail there.
function blockAtId(text, idName, what) {
  return enclosingBlock(text, new RegExp("id:\\s*" + idName + "\\b"), what)
}

// An expression that sits right after `prop:` inside the item with `id: name`.
// Anchored on the id, which is stable across the two versions.
function propIn(text, idName, prop, what) {
  const m = new RegExp("id:\\s*" + idName + "\\b").exec(text)
  if (!m) return null
  const v = new RegExp("\n\\s*" + prop + ":").exec(text.slice(m.index))
  if (!v) return null
  return readExpr(text, m.index + v.index + v[0].length, what)
}

const P = {
  mini: {
    stale: exprAt(src.mini, /^  readonly property bool stale:/m, "stale"),
    hasTrack: exprAt(src.mini, /^  readonly property bool hasTrack:/m, "hasTrack"),
    playing: exprAt(src.mini, /^  readonly property bool playing:/m, "playing"),
    streaming: exprAt(src.mini, /^  readonly property bool streaming:/m, "streaming"),
    seekable: exprAt(src.mini, /^  readonly property bool seekable:/m, "seekable"),
    title: exprAt(src.mini,
      /\/\/ The station's name for a stream, the title for a file \(BarWidget\.songTitle\)\.\n\s*text:/, "title"),
    meta: blockAt(src.mini, /^        text: \{$/m, "meta"),
    // Lookahead anchors: the anchor must stop at the colon, otherwise it eats
    // the expression it is supposed to hand over.
    clock: exprAt(src.mini, /text:(?=\s*mini\.fmt\(mini\.playPos\))/, "clock"),
    clockVisible: exprAt(src.mini, /\n\s*visible:(?=\s*!mini\.streaming)/, "clockVisible"),
    progressVisible: propIn(src.mini, "bar", "visible", "progressVisible"),
    timer: exprAt(src.mini, /running:(?=\s*mini\.open)/, "timer"),
    // The star: `id: star` is stable, and the two properties read the widget's
    // own set (BarWidget.favoriteCurrent) instead of keeping a copy.
    starOn: exprAt(src.mini, /\n      readonly property bool on:(?=\s*!!mini\.service)/, "starOn"),
    starVisible: propIn(src.mini, "star", "visible", "starVisible"),
    starClick: exprAt(src.mini,
      /onClicked:(?=\s*if \(mini\.service\) mini\.service\.toggleFavorite)/, "starClick")
  },
  card: {
    stale: exprAt(src.card, /^  readonly property bool stale:/m, "stale"),
    streaming: exprAt(src.card, /^  readonly property bool streaming:/m, "streaming"),
    title: blockAt(src.card, /^  readonly property string title:/m, "title"),
    artist: exprAt(src.card, /^  readonly property string artist:/m, "artist"),
    coverPath: exprAt(src.card, /^  readonly property string coverPath:/m, "coverPath"),
    seekable: exprAt(src.card, /^  readonly property bool seekable:/m, "seekable"),
    elapsed: propIn(src.card, "elapsedText", "text", "elapsed"),
    duration: propIn(src.card, "durationText", "text", "duration"),
    progressVisible: propIn(src.card, "progressBox", "visible", "progressVisible"),
    // The star sits with the title (not in the transport row, which stays five
    // playback verbs) and asks the widget for the state, exactly like the card.
    starOn: exprAt(src.card, /\n          readonly property bool on:(?=\s*!!card\.host)/, "starOn"),
    starVisible: propIn(src.card, "star", "visible", "starVisible"),
    starClick: exprAt(src.card,
      /onClicked:(?=\s*if \(card\.host\) card\.host\.toggleFavorite)/, "starClick")
  },
  band: {
    stale: exprAt(src.band, /^  readonly property bool stale:/m, "stale"),
    hasSong: exprAt(src.band, /^  readonly property bool hasSong:/m, "hasSong"),
    streaming: exprAt(src.band, /^  readonly property bool streaming:/m, "streaming"),
    art: exprAt(src.band, /^  readonly property string art:/m, "art"),
    seekable: exprAt(src.band, /^  readonly property bool seekable:/m, "seekable"),
    title: blockAt(src.band, /^  readonly property string title:/m, "title"),
    meta: blockAt(src.band, /^  readonly property string meta:/m, "meta"),
    elapsed: propIn(src.band, "elapsed", "text", "elapsed"),
    duration: propIn(src.band, "duration", "text", "duration"),
    progressVisible: propIn(src.band, "progress", "visible", "progressVisible"),
    rotation: exprAt(src.band, /paused:(?=\s*!\(band\.cover === "disc")/, "rotationPaused")
  }
}

console.log("media surfaces under test:")
console.log("   hover card   " + miniFile)
console.log("   desktop card " + cardFile)
console.log("   band         " + bandFile)
console.log("extracted verbatim:")
for (const key of ["mini", "card", "band"]) {
  for (const name of Object.keys(P[key])) {
    const p = P[key][name]
    console.log("   " + (key + "." + name).padEnd(18) + " "
      + (p ? (p.first + "-" + p.last).padEnd(11) + " sha256:" + p.hash
           : "absent"))
  }
}
console.log()

// --- the model of the widget ------------------------------------------------
// One host per run, so no state leaks between checks. Values are the measured
// control: elapsed 37 s of 341 s, queue 3/7, a file with artist and album.
function host(opts) {
  const o = opts || {}
  const song = o.song || {
    file: "Music/Boards of Canada/Dayvan.mp3",
    artist: "Boards of Canada",
    album: "Music Has the Right to Children",
    title: "Dayvan Cowboy"
  }
  return {
    connected: true,
    mpdHealthy: o.stale !== true,
    stale: o.stale === true,
    hasSong: o.hasSong !== false,
    isPlaying: o.isPlaying !== false,
    isStream: o.isStream === true,
    duration: o.duration === undefined ? 341 : o.duration,
    elapsed: o.elapsed === undefined ? 37 : o.elapsed,
    artPath: o.artPath === undefined ? "/tmp/cover.jpg" : o.artPath,
    songFile: song.file,
    song: song,
    queueLength: o.queueLength === undefined ? 7 : o.queueLength,
    queuePosition: o.queuePosition === undefined ? 2 : o.queuePosition,
    songTitle: function () { return o.songTitle === undefined ? "Dayvan Cowboy" : o.songTitle },
    songMeta: function () { return o.songMeta || "" },
    seekable: function () { return o.seekable === undefined ? true : o.seekable },
    basename: function (f) { return String(f || "").split("/").pop() },
    formatTime: function (sec) {
      const s = Math.max(0, Math.floor(Number(sec) || 0))
      const m = Math.floor(s / 60)
      const r = s % 60
      return m + ":" + (r < 10 ? "0" : "") + r
    }
  }
}

function evalPiece(piece, kind, names, values, label) {
  if (!piece) return "<absent:" + label + ">"
  try {
    const f = kind === "block"
      ? new Function(names.join(","), piece.body)
      : new Function(names.join(","), "return (" + piece.body + ")")
    return f.apply(null, values)
  } catch (e) {
    return "<error:" + label + ": " + e.message + ">"
  }
}

// The hover card: the widget is its `service`, the expressions say `mini.*`.
function miniView(h) {
  const names = ["mini", "service"]
  const mini = { service: h }
  const ev = function (piece, kind, label) { return evalPiece(piece, kind, names, [mini, h], label) }
  mini.stale = ev(P.mini.stale, "expr", "stale")
  mini.hasTrack = ev(P.mini.hasTrack, "expr", "hasTrack")
  mini.playing = ev(P.mini.playing, "expr", "playing")
  mini.streaming = ev(P.mini.streaming, "expr", "streaming")
  mini.seekable = ev(P.mini.seekable, "expr", "seekable")
  mini.durNow = h && h.duration > 0 ? h.duration : 0
  mini.playPos = h ? h.elapsed : 0
  mini.fmt = h ? h.formatTime : function (s) { return String(s) }
  // The card's own state at rest: open, the pointer on it, no drag in flight.
  mini.open = true
  mini.hovered = true
  mini.dragging = false
  mini.dragFrac = -1
  mini.title = ev(P.mini.title, "expr", "title")
  mini.meta = ev(P.mini.meta, "block", "meta")
  mini.clockText = ev(P.mini.clock, "expr", "clockText")
  mini.clockVisible = ev(P.mini.clockVisible, "expr", "clockVisible")
  mini.progressVisible = ev(P.mini.progressVisible, "expr", "progressVisible")
  mini.timer = ev(P.mini.timer, "expr", "timer")
  return mini
}

// The card on the wallpaper: the widget is its `host`, the expressions say `card.*`.
function cardView(h) {
  const streaming = h ? h.isStream === true : false
  const names = ["card", "host", "streaming"]
  const card = { host: h, streaming: streaming }
  const ev = function (piece, kind, label) {
    return evalPiece(piece, kind, names, [card, h, streaming], label)
  }
  card.stale = ev(P.card.stale, "expr", "stale")
  card.duration = h ? (Number(h.duration) || 0) : 0
  card.seekable = ev(P.card.seekable, "expr", "seekable")
  card.title = ev(P.card.title, "block", "title")
  card.artist = ev(P.card.artist, "expr", "artist")
  card.coverPath = ev(P.card.coverPath, "expr", "coverPath")
  card.elapsed = ev(P.card.elapsed, "expr", "elapsed")
  card.durationText = ev(P.card.duration, "expr", "durationText")
  card.progressVisible = ev(P.card.progressVisible, "expr", "progressVisible")
  return card
}

// The band: the widget is its `host`, the expressions say `band.*` -- and the
// three that read the root's own `hasSong` get it in scope too, the way QML
// resolves a bare name against the root object. The look is the disc, the one
// whose pause state carries the claim "this is spinning".
function bandView(h) {
  const names = ["band", "host", "hasSong"]
  const band = { host: h, cover: "disc", oneLine: false }
  const ev = function (piece, kind, label) {
    return evalPiece(piece, kind, names, [band, h, band.hasSong], label)
  }
  band.stale = ev(P.band.stale, "expr", "stale")
  band.hasSong = ev(P.band.hasSong, "expr", "hasSong")
  band.streaming = ev(P.band.streaming, "expr", "streaming")
  band.title = ev(P.band.title, "block", "title")
  band.meta = ev(P.band.meta, "block", "meta")
  band.art = ev(P.band.art, "expr", "art")
  band.seekable = ev(P.band.seekable, "expr", "seekable")
  band.elapsed = ev(P.band.elapsed, "expr", "elapsed")
  band.duration = ev(P.band.duration, "expr", "duration")
  band.progressVisible = ev(P.band.progressVisible, "expr", "progressVisible")
  band.rotationPaused = ev(P.band.rotation, "expr", "rotationPaused")
  return band
}

let failures = 0
let total = 0
function report(id, title, ok, detail) {
  total++
  if (!ok) failures++
  console.log("[" + (ok ? "PASS" : "FAIL") + "] " + id + " " + title)
  detail.forEach(function (line) { console.log("        " + line) })
  console.log()
}

const SAYS = "MPD is not answering"
const META = "Boards of Canada  ·  Music Has the Right to Children  ·  #3/7"

// --- 1: the hover card says what the connection is doing --------------------
function caseMiniPlayer() {
  const answers = miniView(host({ stale: false }))
  const wedged = miniView(host({ stale: true }))

  report("1", "the hover card shows the status, not the last title",
    answers.stale === false && wedged.stale === true
      && wedged.title === SAYS && answers.title === "Dayvan Cowboy"
      && wedged.meta === "" && answers.meta === META
      && wedged.clockVisible === false && answers.clockVisible === true
      && wedged.progressVisible === false && answers.progressVisible === true
      && wedged.timer === false && answers.timer === true
      // the surface itself stays: it exists to be read
      && wedged.hasTrack === true && answers.hasTrack === true,
    [
      "answering: stale=" + answers.stale + " title=\"" + answers.title + "\" meta=\""
        + answers.meta + "\"",
      "wedged:    stale=" + wedged.stale + " title=\"" + wedged.title + "\" meta=\""
        + wedged.meta + "\"",
      "clock drawn  answering/wedged: " + answers.clockVisible + " / " + wedged.clockVisible
        + "   progress drawn: " + answers.progressVisible + " / " + wedged.progressVisible,
      "clock still ticking (the 250 ms timer): " + answers.timer + " / " + wedged.timer,
      "the card is shown in both states: hasTrack " + answers.hasTrack + " / " + wedged.hasTrack,
      "expected: \"" + SAYS + "\" and no meta line while wedged, the title untouched"
        + " otherwise, and the card stays up to carry the line"
    ])
}

// --- 2: the card on the wallpaper ------------------------------------------
function caseDesktopCard() {
  const answers = cardView(host({ stale: false }))
  const wedged = cardView(host({ stale: true }))

  report("2", "the card on the wallpaper drops the clock and the position",
    answers.stale === false && wedged.stale === true
      && wedged.title === SAYS && answers.title === "Dayvan Cowboy"
      && wedged.artist === "" && answers.artist === "Boards of Canada"
      && wedged.elapsed === "" && answers.elapsed === "0:37"
      && wedged.durationText === "" && answers.durationText === "5:41"
      && wedged.progressVisible === false && answers.progressVisible === true
      && wedged.coverPath === "/tmp/cover.jpg",
    [
      "answering: title=\"" + answers.title + "\" artist=\"" + answers.artist + "\"",
      "wedged:    title=\"" + wedged.title + "\" artist=\"" + wedged.artist + "\"",
      "clock  answering/wedged: \"" + answers.elapsed + "\" / \"" + answers.durationText
        + "\"  ->  \"" + wedged.elapsed + "\" / \"" + wedged.durationText + "\"",
      "progress row drawn answering/wedged: " + answers.progressVisible + " / "
        + wedged.progressVisible,
      "cover kept while wedged: \"" + wedged.coverPath + "\" (a memory, not a claim)",
      "expected: the status line instead of the title, no artist line, and no clock"
        + " or progress bar that would claim a position"
    ])
}

// --- 3: the playback band ---------------------------------------------------
function caseBand() {
  const answers = bandView(host({ stale: false }))
  const wedged = bandView(host({ stale: true }))

  report("3", "the band stops the timeline, the seam and the platter",
    answers.stale === false && wedged.stale === true
      && wedged.title === SAYS && answers.title === "Dayvan Cowboy"
      && wedged.meta === "" && answers.meta === META
      && wedged.seekable === false && answers.seekable === true
      && wedged.progressVisible === false && answers.progressVisible === true
      && wedged.elapsed === "" && answers.elapsed === "0:37"
      && wedged.duration === "" && answers.duration === "5:41"
      && wedged.rotationPaused === true && answers.rotationPaused === false
      // the band and its cover stay -- they are the memory, not the claim
      && wedged.art === "/tmp/cover.jpg" && wedged.hasSong === true,
    [
      "answering: title=\"" + answers.title + "\" meta=\"" + answers.meta + "\"",
      "wedged:    title=\"" + wedged.title + "\" meta=\"" + wedged.meta + "\"",
      "seekable answering/wedged: " + answers.seekable + " / " + wedged.seekable
        + "   progress drawn: " + answers.progressVisible + " / " + wedged.progressVisible,
      "clock  answering/wedged: \"" + answers.elapsed + "\" / \"" + answers.duration
        + "\"  ->  \"" + wedged.elapsed + "\" / \"" + wedged.duration + "\"",
      "disc paused answering/wedged: " + answers.rotationPaused + " / " + wedged.rotationPaused,
      "band still shown with its cover while wedged: hasSong " + wedged.hasSong
        + ", art \"" + wedged.art + "\"",
      "expected: no seek, no progress, no clock and a stopped platter while wedged"
        + " -- and the band itself untouched"
    ])
}

// --- 4: the three surfaces derive `stale`, they do not re-invent it ---------
function caseDerived() {
  const specs = [
    { label: "MiniPlayer.qml", key: "mini", prop: "service", view: miniView },
    { label: "DesktopCard.qml", key: "card", prop: "host", view: cardView },
    { label: "BandChrome.qml", key: "band", prop: "host", view: bandView }
  ]
  const lines = []
  let ok = true
  for (const spec of specs) {
    const piece = P[spec.key].stale
    if (!piece) {
      ok = false
      lines.push(spec.label + ": no `stale` binding at all -- the surface cannot know")
      continue
    }
    const fromWidget = new RegExp(spec.prop + "\\.stale").test(piece.body)
    const invented = /mpdHealthy|healthDetail|HEALTH_|probe/i.test(piece.body)
    const vNone = spec.view(null).stale
    const vNo = spec.view(host({ stale: false })).stale
    const vYes = spec.view(host({ stale: true })).stale
    if (!(fromWidget && !invented && vNone === false && vNo === false && vYes === true)) ok = false
    lines.push(spec.label + " lines " + piece.first + "-" + piece.last + ": " + piece.body)
    lines.push("    derived from " + spec.prop + ".stale: " + fromWidget
      + ", re-invented from the health report: " + invented
      + ", answers " + spec.prop + " null/false/true -> " + vNone + "/" + vNo + "/" + vYes)
  }
  lines.push("expected: one line per surface, derived from the widget's own verdict"
    + " (BarWidget.stale) -- never from the probe numbers or the health detail again")
  report("4", "the three surfaces derive the state from the widget", ok, lines)
}

// --- 5: the two texts -------------------------------------------------------
// The probe rule (interval, timeout, misses) lives in one place: the comment
// above HEALTH_INTERVAL in bin/mpd-bridge. Prose points at it instead of
// repeating the numbers -- and the restart action says how long the unit's stop
// limit can leave it looking idle.
//
// The prose has two homes: the README keeps the short version and hands the depth
// to docs/internals.md, and that file is where the numbers, the surfaces and the
// drop-in have to stay. Both halves are checked, so the detail cannot go missing
// unnoticed -- it may only move, together with the pointer that leads there.
function caseTexts() {
  const readmePath = path.join(root, "README.md")
  const panelPath = path.join(root, "Panel.qml")
  const docsPath = path.join(root, "docs", "internals.md")
  const wanted = [readmePath, panelPath, docsPath]
  if (!wanted.every(function (p) { return fs.existsSync(p) })) {
    report("5", "the prose points at the bridge and is honest about the restart", false,
      ["not found next to the surfaces: "
        + wanted.filter(function (p) { return !fs.existsSync(p) }).join(", "),
       "expected: README.md, Panel.qml and docs/internals.md beside the three .qml files"])
    return
  }
  const readme = fs.readFileSync(readmePath, "utf8")
  const panel = fs.readFileSync(panelPath, "utf8")
  const docs = fs.readFileSync(docsPath, "utf8")

  const hintM = /title: "Restart MPD",\s*\n\s*hint: "([^"]*)"/.exec(panel)
  const hint = hintM ? hintM[1] : null

  const bulletM = /- \*\*The bar says "MPD is not answering"\*\*([\s\S]*?)(?=\n- \*\*)/.exec(readme)
  const bullet = bulletM ? bulletM[1] : ""

  const hintOk = !!hint
    && /stop\s?limit/i.test(hint)
    && /\b90 s\b/.test(hint)
    && /\b5 s\b/.test(hint)
    && !/\b20 s\b|\b3 s\b|two misses|two failed/i.test(hint)
  // The README stays short: no probe numbers, and a pointer to the file that
  // carries them. Writing the numbers back in here is what this forbids.
  const readmeLink = /docs\/internals\.md/.test(bullet)
  const pointerOk = !/\b20 s\b/.test(bullet) && readmeLink
  // ... and that file has to be the honest one: it names the bridge constant the
  // numbers live in, the surfaces that stop pretending, and the drop-in with both
  // durations -- spelled either way, it is the facts that count.
  const bridgeOk = /HEALTH_INTERVAL|bin\/mpd-bridge/.test(docs)
  const surfacesOk = /band|hover card|wallpaper/i.test(docs)
  const dropinOk = /\bTimeoutStopSec\b/.test(docs)
    && /override\.conf/.test(docs)
    && (/\b90 s\b|90 seconds|ninety seconds/i.test(docs))
    && (/\b5 s\b|five seconds/i.test(docs))

  report("5", "the prose points at the bridge and is honest about the restart",
    hintOk && pointerOk && bridgeOk && surfacesOk && dropinOk,
    [
      "Restart MPD hint  : " + (hint === null ? "not found" : "\"" + hint + "\""),
      "  names the unit's stop limit: " + (hint ? /stop\s?limit/i.test(hint) : false)
        + ", both durations (90 s / 5 s): "
        + (hint ? (/\b90 s\b/.test(hint) + " / " + /\b5 s\b/.test(hint)) : "n/a")
        + ", repeats no probe number: " + (hint ? !/\b20 s\b|\b3 s\b/.test(hint) : "n/a"),
      "README bullet     : " + (bulletM ? "found at the \"MPD is not answering\" entry"
        : "not found"),
      "  no \"20 s\" left: " + (bulletM ? !/\b20 s\b/.test(bullet) : false)
        + ", hands the depth over (docs/internals.md): " + (bulletM ? readmeLink : false),
      "docs/internals.md : names the bridge (HEALTH_INTERVAL/bin/mpd-bridge): " + bridgeOk
        + ", names the surfaces (band/hover card/wallpaper): " + surfacesOk,
      "  drop-in named (TimeoutStopSec in override.conf, 90 s and 5 s): " + dropinOk,
      "expected: the numbers stay in the bridge comment, the README points at the file"
        + " that carries them (docs/internals.md), that file is honest about the restart,"
        + " and the restart action says what the unit's stop limit does to it"
    ])
}

// --- 6: the album stands in the player even when it repeats the title -------
// The decision this case pins down: the hover card and the band name the album
// on their second line whenever a track carries one -- a single whose album tag
// is its own name included. The old rule hid the album while it equalled the
// title to avoid a repetition; the repetition is wanted there now. The wallpaper
// card (DesktopCard.qml) is deliberately not asked here: it stays minimal and
// carries no album line at all. The controls are the other half: a track with no
// album tag must not grow one, and the value is the album, not an invention.
function caseAlbumRepeatsTitle() {
  const single = { file: "Music/Dopplereffekt/Athanatos.flac", artist: "Dopplereffekt",
                   album: "Athanatos", title: "Athanatos" }
  const untagged = { file: "Music/Dopplereffekt/Untitled.flac", artist: "Dopplereffekt",
                     title: "Athanatos" }
  // The band takes its title from the widget (BarWidget.songTitle), and the
  // widget takes it from the same tags the card reads -- so a single with
  // album == title is one where songTitle() answers with the album's word too.
  const mini = miniView(host({ song: single, songTitle: "Athanatos" }))
  const miniBare = miniView(host({ song: untagged, songTitle: "Athanatos" }))
  const band = bandView(host({ song: single, songTitle: "Athanatos" }))
  const bandBare = bandView(host({ song: untagged, songTitle: "Athanatos" }))

  const wants = "Dopplereffekt  ·  Athanatos  ·  #3/7"
  const bare = "Dopplereffekt  ·  #3/7"

  report("6", "the album stands in the player even when it equals the title",
    mini.meta === wants && band.meta === wants
      && miniBare.meta === bare && bandBare.meta === bare,
    [
      "hover card, album == title : \"" + mini.meta + "\"",
      "band,       album == title : \"" + band.meta + "\"",
      "hover card, no album tag   : \"" + miniBare.meta + "\"",
      "band,       no album tag   : \"" + bandBare.meta + "\"",
      "expected: \"" + wants + "\" whenever the album tag is there (even as the"
        + " title), and \"" + bare + "\" when it is not -- never an invented album",
      "the wallpaper card is not asked: it stays minimal (DesktopCard.qml)"
    ])
}

// --- 7: the transport buttons answer the pointer on both surfaces -----------
// The flat controls of the band and of the hover card used to be bare Text
// items whose only pointer answer was a colour swap to the accent -- and on both
// surfaces that is easy to miss, because the accent and the popup foreground sit
// close together in the dark themes: side by side on the running desktop the two
// states differ by a few percent of hue, and the pointer was the only real
// feedback. The answer now lives in TransportButton.qml: a plate in the accent
// under the glyph (16 %, 22 % while pressed), faded in over 120 ms, as big as
// the button rather than as big as the glyph, so the aim point grew with it.
// Both surfaces build every flat control from it, and the band keeps naming the
// click in its footer hint. The pieces are read from the component and *run* in
// both pointer states -- a source without it (a fixed colour, no plate) fails on
// the value, not merely on a property name.
function caseTransportHover() {
  const buttonFile = path.join(root, "TransportButton.qml")
  let component = ""
  try { component = fs.readFileSync(buttonFile, "utf8") } catch (e) { component = "" }

  const surfaces = [
    { label: "BandChrome.qml", text: src.band, hint: true },
    { label: "MiniPlayer.qml", text: src.mini, hint: false }
  ]
  const targets = [
    { call: "previousTrack", hint: "Previous track" },
    { call: "nextTrack", hint: "Next track" }
  ]
  const lines = []
  let ok = component !== ""

  // Every `TransportButton { ... }` block of a surface, braces matched.
  function buttonBlocks(text) {
    const out = []
    const re = /TransportButton\s*\{/g
    let m
    while ((m = re.exec(text)) !== null) {
      const open = text.indexOf("{", m.index)
      out.push(mkPiece(text, open, matchBraces(text, open) + 1, "transportButton"))
    }
    return out
  }

  // The component's own answer: the plate under the glyph, and a glyph colour
  // that moves between the two pointer states.
  const plateOpacity = exprAt(component, /\n\s*opacity:(?=\s*button\.hot)/, "plateOpacity")
  const plateColor = exprAt(component, /\n\s*color:(?=\s*Util\.alpha\(button\.activeColor)/, "plateColor")
  const glyphColor = exprAt(component, /\n\s*color:(?=\s*!button\.enabled)/, "glyphColor")
  const hoverOn = /hoverEnabled\s*:\s*true/.test(component)

  function evalWith(piece, hot, enabled, on) {
    const button = { hot: hot, enabled: enabled, on: on, glyphColor: "fg", activeColor: "accent" }
    const Qt = { darker: function (c) { return c + "-dim" } }
    return evalPiece(piece, "expr", ["button", "Qt"], [button, Qt], piece ? piece.what : "absent")
  }
  const opOff = evalWith(plateOpacity, false, true, false)
  const opOn = evalWith(plateOpacity, true, true, false)
  const colOff = evalWith(glyphColor, false, true, false)
  const colOn = evalWith(glyphColor, true, true, false)
  const moves = function (off, on) {
    return !/^</.test(String(off)) && !/^</.test(String(on)) && String(off) !== String(on)
  }
  const plateAnswers = !!plateOpacity && !!plateColor && moves(opOff, opOn)
  const glyphAnswers = !!glyphColor && moves(colOff, colOn)

  lines.push("TransportButton.qml:")
  lines.push("    plate opacity " + (plateOpacity ? "line " + plateOpacity.first
    + " sha256:" + plateOpacity.hash + "  " + JSON.stringify(plateOpacity.body.trim())
    : "absent") + "   off/on -> " + JSON.stringify(opOff) + " / " + JSON.stringify(opOn))
  lines.push("    plate colour  " + (plateColor ? "line " + plateColor.first
    + " sha256:" + plateColor.hash + "  " + JSON.stringify(plateColor.body.trim())
    : "absent"))
  lines.push("    glyph colour  " + (glyphColor ? "line " + glyphColor.first
    + " sha256:" + glyphColor.hash + "  " + JSON.stringify(glyphColor.body.trim())
    : "absent") + "   off/on -> " + JSON.stringify(colOff) + " / " + JSON.stringify(colOn))
  lines.push("    hoverEnabled: " + hoverOn)

  for (const s of surfaces) {
    const blocks = buttonBlocks(s.text)
    lines.push("    " + s.label + ": " + blocks.length + " TransportButton(s)")
    for (const t of targets) {
      const hit = blocks.find(function (b) { return new RegExp("\\b" + t.call + "\\s*\\(").test(b.body) })
      const hint = hit && /onEntered\s*:\s*band\.hint\s*\(\s*"([^"]*)"\s*\)/.exec(hit.body)
      const namesTarget = !s.hint || (!!hint && hint[1].indexOf(t.hint) >= 0)
      if (!hit || !namesTarget) ok = false
      lines.push("        " + t.call + ": " + (hit ? "lines " + hit.first + "-" + hit.last
        + " sha256:" + hit.hash : "absent")
        + (s.hint ? "   hint: " + JSON.stringify(hint ? hint[1] : null) : ""))
    }
  }

  if (!plateAnswers || !glyphAnswers || !hoverOn) ok = false
  lines.push("expected: a plate in the accent under the glyph whose opacity follows the")
  lines.push("pointer (0 / 1) and a glyph colour that moves between the two states; both")
  lines.push("surfaces build prev/next from that component, and the band names the click")
  lines.push("in its footer hint")
  report("7", "the transport buttons answer the pointer on both surfaces", ok, lines)
}

// --- 8: the hover card keeps its own pointer, not the click area's ----------
// Tinting prev/next made those two areas `hoverEnabled`, and a child that takes
// the pointer makes its *sibling* click area report `containsMouse: false` --
// the widget then read the card as left and closed it 280 ms later. The card's
// hover state has to come from a HoverHandler on the card itself (it counts the
// pointer anywhere on the card, children included), and the click area has to
// stop deciding it in onEntered/onExited.
function caseCardHoverOwnership() {
  const handler = blockAt(src.mini, /HoverHandler\s*\{/, "cardHover")
  const setsHover = !!handler
    && /mini\.hovered\s*=\s*(?:[A-Za-z_]\w*\s*\.\s*)?hovered\b/.test(handler.body)

  // The click area: the one MouseArea that takes every button.
  const click = enclosingBlock(src.mini, /acceptedButtons\s*:\s*Qt\.AllButtons/, "clickArea")
  const stillSets = !!click && /mini\.hovered/.test(click.body)
  const handlerInClick = !!click && /HoverHandler/.test(click.body)

  const ok = !!handler && setsHover && !!click && !stillSets && !handlerInClick

  report("8", "the card's hover state comes from the card, not the click area",
    ok,
    [
      "HoverHandler " + (handler ? "lines " + handler.first + "-" + handler.last
        + " sha256:" + handler.hash : "absent")
        + ", id: " + (handler ? /id:\s*cardHover\b/.test(handler.body) : "n/a"),
      "    body: " + (handler ? JSON.stringify(handler.body.replace(/\s+/g, " ").trim())
        : "absent")
        + "   sets mini.hovered from its own `hovered`: " + setsHover,
      "click area  " + (click ? "lines " + click.first + "-" + click.last
        + " sha256:" + click.hash : "absent")
        + ", still sets mini.hovered in onEntered/onExited: " + stillSets
        + ", HoverHandler nested in it: " + handlerInClick,
      "expected: one HoverHandler on the card whose `hovered` drives mini.hovered, and a"
        + " click area that no longer touches the hover state -- that is exactly what the"
        + " sibling transport areas broke"
    ])
}

// --- 9: the card hangs from the bar strip, not from the bar's window --------
// The bar's layer surface spans the whole screen ("Keep the bar surface
// full-size so drags survive empty workspaces", Omarchy e2d618ac), so the bar
// *window* is as tall as the screen. A card positioned at `anchorWindow.height`
// therefore lands at y = screen height + gap -- one screen below the bar: the
// surface is mapped, the buttons are mapped, and nobody sees them (measured on
// the running desktop: window 960, strip 26, card drawn at y=967, surface
// mapped 1536x1097). The edge to hang from is the anchor item's own bottom edge
// inside the bar window, which is what the musify card measures as well.
function caseCardAnchoredToStrip() {
  const piece = exprAt(src.mini, /readonly property real barH:/, "barH")
  const strip = { height: 26, mapToItem: function () { return { x: 0, y: 0 } } }
  const win = { height: 960, width: 1536 }
  const barH = evalPiece(piece, "expr", ["anchorItem", "anchorWindow"], [strip, win], "barH")
  const fromWindow = /barH:[\s\S]{0,120}?anchorWindow\.height/.test(src.mini)
  const ok = piece !== null && barH === 26 && !fromWindow

  report("9", "the card hangs from the bar's strip, not from its full-screen window",
    ok,
    [
      "barH " + (piece ? "line " + piece.first + " sha256:" + piece.hash : "absent")
        + "  " + (piece ? JSON.stringify(piece.body.replace(/\s+/g, " ").trim()) : ""),
      "    evaluated with a 26 px strip in a 960 px bar window -> " + JSON.stringify(barH)
        + "   (the screen height would be 960)",
      "    the expression still reads anchorWindow.height: " + fromWindow,
      "expected: the strip's bottom edge (26), so the card starts just under the bar"
        + " -- a card at 960 sits a whole screen below it"
    ])
}

// --- 10: the star on the two cards -----------------------------------------
// Favourites are rows in MPD's `favorites` playlist, and the widget owns that set
// (BarWidget.favoriteCurrent, asked in the panel test as well): the panel, the
// hover card and the card on the wallpaper read the same star, so a card keeping
// its own copy would disagree with the panel the moment one of them toggled. Both
// cards draw one star for the track that is playing, take the state from the
// widget and hand the click back to it. Not drawn while the daemon is wedged --
// the title on the card is a memory then, and a star for it would be a write to a
// player that is not answering.
function caseCardStar() {
  function favHost(opts) {
    const o = opts || {}
    const h = host(o)
    h.favoriteCurrent = o.favorite === true
    h.toggleCalls = 0
    h.toggleFavorite = function () { h.toggleCalls++; return !h.favoriteCurrent }
    return h
  }
  function miniOf(h) {
    const mini = { service: h, hasTrack: h.hasSong === true, stale: h.stale === true }
    const ev = function (piece, kind) {
      return evalPiece(piece, kind || "expr", ["mini", "service"], [mini, h], "mini")
    }
    return { on: ev(P.mini.starOn), visible: ev(P.mini.starVisible),
             click: function () { return ev(P.mini.starClick, "block") } }
  }
  function cardOf(h) {
    const card = { host: h, stale: h.stale === true }
    const ev = function (piece, kind) {
      return evalPiece(piece, kind || "expr", ["card", "host", "streaming"],
                       [card, h, h.isStream === true], "card")
    }
    return { on: ev(P.card.starOn), visible: ev(P.card.starVisible),
             click: function () { return ev(P.card.starClick, "block") } }
  }

  const miniOff = miniOf(favHost({}))
  const miniOn = miniOf(favHost({ favorite: true }))
  const miniWedged = miniOf(favHost({ favorite: true, stale: true }))
  const miniEmpty = miniOf(favHost({ favorite: true, hasSong: false }))
  const cardOff = cardOf(favHost({}))
  const cardOn = cardOf(favHost({ favorite: true }))
  const cardWedged = cardOf(favHost({ favorite: true, stale: true }))
  const cardEmpty = cardOf(favHost({ favorite: true, hasSong: false }))

  const miniClickHost = favHost({ favorite: true })
  miniOf(miniClickHost).click()
  const cardClickHost = favHost({})
  cardOf(cardClickHost).click()

  const reads = [/favoriteCurrent/.test((P.mini.starOn || {}).body || ""),
                 /favoriteCurrent/.test((P.card.starOn || {}).body || "")]
  const ok = miniOff.on === false && miniOn.on === true
    && miniOff.visible === true && miniWedged.visible === false && miniEmpty.visible === false
    && cardOff.on === false && cardOn.on === true
    && cardOff.visible === true && cardWedged.visible === false && cardEmpty.visible === false
    && miniClickHost.toggleCalls === 1 && cardClickHost.toggleCalls === 1
    && reads[0] && reads[1]

  report("10", "the cards carry the star of what is playing",
    ok,
    [
      "hover card  on: not starred -> " + JSON.stringify(miniOff.on) + ", starred -> "
        + JSON.stringify(miniOn.on),
      "              drawn: playing " + miniOff.visible + ", wedged " + miniWedged.visible
        + ", nothing playing " + miniEmpty.visible,
      "wallpaper   on: not starred -> " + JSON.stringify(cardOff.on) + ", starred -> "
        + JSON.stringify(cardOn.on),
      "              drawn: playing " + cardOff.visible + ", wedged " + cardWedged.visible
        + ", nothing playing " + cardEmpty.visible,
      "a click goes to the widget: hover card " + miniClickHost.toggleCalls
        + " toggleFavorite, wallpaper " + cardClickHost.toggleCalls,
      "the state is the widget's own favoriteCurrent: " + reads[0] + " / " + reads[1]
        + " (no copy of the playlist in either card)",
      "expected: filled when the playing uri is in `favorites`, dim when it is not,"
        + " one write per click, and no star while nothing plays or MPD is not answering"
    ])
}

// --- 11: the star in the band -----------------------------------------------
// The band is the third surface with the star, and the only one with two
// placements by design: on the title line for every look that has a column
// (docs/mockups/fav-7 -- attached reads as part of the name), and as a fourth
// transport glyph on the thin line, which has no column beside the title. The
// star itself is StarButton.qml: it owns no state, it asks the widget
// (BarWidget.favoriteCurrent) and hands the click back through `toggleStar`.
function caseBandStar() {
  const starFile = path.join(root, "StarButton.qml")
  let starSrc = ""
  try { starSrc = fs.readFileSync(starFile, "utf8") } catch (e) { starSrc = "" }

  const onPiece = exprAt(starSrc, /readonly property bool on:/, "starOn")
  const onSet = evalPiece(onPiece, "expr", ["host"], [{ favoriteCurrent: true }], "starOn")
  const onUnset = evalPiece(onPiece, "expr", ["host"], [{ favoriteCurrent: false }], "starOn")
  const onNoHost = evalPiece(onPiece, "expr", ["host"], [null], "starOn")
  const starClicks = /star\.clicked\(\)/.test(starSrc)

  // The two placements: mutually exclusive, and each one is gated on a track
  // being there while the daemon answers.
  const titleVis = exprAt(src.band, /visible:(?=\s*!band\.oneLine && band\.hasSong)/, "titleVis")
  const rowVis = exprAt(src.band, /visible:(?=\s*band\.oneLine && band\.hasSong)/, "rowVis")
  function bandState(oneLine, hasSong, stale) {
    return { oneLine: oneLine, hasSong: hasSong, stale: stale }
  }
  const titleOn = evalPiece(titleVis, "expr", ["band"], [bandState(false, true, false)], "titleVis")
  const titleWedged = evalPiece(titleVis, "expr", ["band"], [bandState(false, true, true)], "titleVis")
  const titleSilent = evalPiece(titleVis, "expr", ["band"], [bandState(false, false, false)], "titleVis")
  const rowOn = evalPiece(rowVis, "expr", ["band"], [bandState(true, true, false)], "rowVis")
  const rowFat = evalPiece(rowVis, "expr", ["band"], [bandState(false, true, false)], "rowVis")

  // `toggleStar` is the one write the band sends: through the widget, with the
  // footer line said in the same word the rest of the panel uses.
  const toggle = blockAt(src.band, /function toggleStar\s*\(\s*\)/, "toggleStar")
  const stub = { calls: 0, said: "", host: { toggleFavorite: function () { stub.calls++; return true } },
                 message: function (t) { stub.said = String(t) }, hint: function () {} }
  evalPiece(toggle, "block", ["band"], [stub], "toggleStar")

  const ok = starSrc !== "" && onSet === true && onUnset === false && onNoHost === false
    && starClicks
    && titleOn === true && titleWedged === false && titleSilent === false
    && rowOn === true && rowFat === false
    && stub.calls === 1 && stub.said === "in favorites"

  report("11", "the band's star sits on the title, or in the transport on the thin line",
    ok,
    [
      "StarButton.qml on: set " + JSON.stringify(onSet) + ", unset " + JSON.stringify(onUnset)
        + ", no host " + JSON.stringify(onNoHost) + "   click calls star.clicked(): " + starClicks,
      "title line   drawn: playing " + titleOn + ", wedged " + titleWedged
        + ", nothing playing " + titleSilent,
      "thin line    drawn: thin look " + rowOn + ", other looks " + rowFat
        + "   (the two placements exclude each other)",
      "toggleStar   toggleFavorite called: " + stub.calls + ", footer said: \"" + stub.said + "\"",
      "expected: filled only for the playing uri that is in `favorites`, two placements that"
        + " never show at once, one write through the widget, and no star while nothing plays"
    ])
}

// --- 12: the wallpaper card exists only while the setting is on -------------
// `visible: root.desktopWidget` left the PanelWindow mapped in a hidden state,
// and a mapped layer surface that never draws is enough to block screencopy --
// grim hangs until timeout -- and the orphan surface survives a shell restart.
// The OSD and the hover card above already create their window through a Loader;
// the wallpaper card has to do the same. This case asserts the presence rule (the
// boolean that drives `active`), not a window: off means no window is built.
function caseDesktopCardPresence() {
  if (!barSrc) {
    report("12", "the wallpaper card is created, not switched invisible", false,
      ["BarWidget.qml not found beside the surfaces -- nothing to check"])
    return
  }
  const m = /Variants\s*\{/.exec(barSrc)
  let block = null
  if (m) {
    const open = barSrc.indexOf("{", m.index)
    block = mkPiece(barSrc, open, matchBraces(barSrc, open) + 1, "desktopVariants")
  }
  const presence = blockAt(barSrc, /^  readonly property bool desktopWidget:/m, "desktopWidget")
  const active = block ? exprAt(block.body, /\n\s*active:/, "desktopActive") : null
  const stillVisible = block ? /\bvisible:\s*root\.desktopWidget/.test(block.body) : false
  const loader = block ? /Loader\s*\{/.test(block.body) : false
  const source = block ? /sourceComponent:\s*\w+/.test(block.body) : false

  function presenceFor(v) {
    if (!presence) return "<absent>"
    try {
      const f = new Function("setting", "return (function () " + presence.body + ")()")
      return f(function (key, fallback) { return v === undefined ? fallback : v })
    } catch (e) {
      return "<error:" + e.message + ">"
    }
  }
  function activeFor(v) {
    if (!active) return "<absent>"
    return evalPiece(active, "expr", ["root"], [{ desktopWidget: v }], "desktopActive")
  }
  const offRule = presenceFor(false)
  const onRule = presenceFor(true)
  const offActive = activeFor(false)
  const onActive = activeFor(true)
  const driven = !!active && /desktopWidget/.test(active.body)
  const ok = !!block && loader && source && driven && !stillVisible
    && offRule === false && onRule === true
    && offActive === false && onActive === true

  report("12", "the wallpaper card is created, not switched invisible", ok, [
    "Variants block " + (block ? "lines " + block.first + "-" + block.last
      + " sha256:" + block.hash : "absent"),
    "  delegate is a Loader: " + loader + "   sourceComponent set: " + source,
    "  window still switched with `visible: root.desktopWidget`: " + stillVisible,
    "setting `desktopWidget` off/on -> " + JSON.stringify(offRule) + " / " + JSON.stringify(onRule),
    "Loader `active:` " + (active ? "line " + active.first + " sha256:" + active.hash
      + "  " + JSON.stringify(active.body.trim()) : "absent")
      + "   off/on -> " + JSON.stringify(offActive) + " / " + JSON.stringify(onActive),
    "expected: a Loader whose `active` is the setting's boolean, so off builds no"
      + " window at all -- not a mapped window with `visible: false`"
  ])
}

// --- 13: a favourites answer that was already in flight cannot undo a toggle --
// A query sent before a local write can land after it. Assigning its `favSet`
// unconditionally restored the playlist from before the write, so the star the
// user just set flipped back for the ~600 ms until the timer's reload arrived.
// Every local write bumps an epoch; a favourites answer carries the epoch it was
// asked under and is dropped when a newer local write has happened since. The
// control is the other half: an answer with the current epoch still wins.
function caseFavoritesEpoch() {
  if (!barSrc) {
    report("13", "an in-flight favourites answer cannot undo a toggle", false,
      ["BarWidget.qml not found beside the surfaces -- nothing to check"])
    return
  }
  const load = declAt(barSrc, /^  function loadFavorites\(/m, "loadFavorites")
  const toggle = declAt(barSrc, /^  function toggleFavorite\(/m, "toggleFavorite")
  if (!load || !toggle) {
    report("13", "an in-flight favourites answer cannot undo a toggle", false,
      ["not found in BarWidget.qml: " + (!load ? "loadFavorites" : "toggleFavorite")])
    return
  }
  const build = new Function("root", "favTimer",
    // In the widget these are the root's properties; the extracted functions use
    // them as bare names, the way QML resolves an id.
    "var connected = root.connected\n"
    + load.body + "\n\n" + toggle.body + "\n\n"
    + "return { loadFavorites: loadFavorites, toggleFavorite: toggleFavorite }")
  const uri = "Music/Boards of Canada/Dayvan.mp3"

  function widget() {
    const pending = []
    const root = {
      connected: true, songFile: uri, favSet: {}, favEpoch: 0,
      isFavorite: function (key) { return root.favSet[key] === true },
      mutation: function () {},
      query: function (kind, args, channel, cb) { pending.push({ kind: kind, cb: cb }) }
    }
    return { root: root, pending: pending,
             w: build(root, { restart: function () {} }) }
  }

  // The race: ask, toggle, then deliver the answer asked before the toggle.
  const a = widget()
  a.w.loadFavorites()
  const asked = a.pending.length
  a.w.toggleFavorite()
  const afterToggle = a.root.favSet[uri] === true
  const epochAfterWrite = a.root.favEpoch
  if (a.pending[0]) a.pending[0].cb([], "")
  const afterOldAnswer = a.root.favSet[uri] === true

  // The control: a fresh load after the write is the current answer and applies.
  a.w.loadFavorites()
  if (a.pending[1]) a.pending[1].cb([], "")
  const afterNewAnswer = a.root.favSet[uri] === true

  // And an answer asked after the write can star the track again.
  const b = widget()
  b.w.toggleFavorite()
  b.root.favSet = {}
  b.root.favEpoch++          // a later local write, so the old demand is moot
  b.w.loadFavorites()
  if (b.pending[0]) b.pending[0].cb([{ file: uri }], "")
  const starredByNewAnswer = b.root.favSet[uri] === true

  const readsEpoch = /favEpoch/.test(load.body) && /favEpoch/.test(toggle.body)
  const ok = asked === 1 && afterToggle === true && epochAfterWrite > 0
    && afterOldAnswer === true && afterNewAnswer === false
    && starredByNewAnswer === true && readsEpoch

  report("13", "an in-flight favourites answer cannot undo a toggle", ok, [
    "loadFavorites " + (load ? "lines " + load.first + "-" + load.last
      + " sha256:" + load.hash : "absent")
      + "   reads the epoch: " + (load ? /favEpoch/.test(load.body) : false),
    "toggleFavorite  " + (toggle ? "lines " + toggle.first + "-" + toggle.last
      + " sha256:" + toggle.hash : "absent")
      + "   bumps the epoch: " + (toggle ? /favEpoch/.test(toggle.body) : false),
    "asked, then toggled: star on " + afterToggle + ", epoch " + epochAfterWrite,
    "  old answer delivered -> star still on: " + afterOldAnswer + " (want true)",
    "  new answer delivered -> star now off: " + !afterNewAnswer + " (the newer answer wins)",
    "  an answer asked after a write can still star: " + starredByNewAnswer,
    "expected: the epoch is bumped on every local write, an answer carrying an older"
      + " epoch is dropped, and an answer carrying the current one still applies"
  ])
}

// --- 14: the hover card hangs from whichever edge the bar is on ------------
// `barPosition` was declared and read nowhere: the card always sat under the top
// edge, so with `bar.position: "bottom"` it was drawn below the screen. The
// position expression is run for both edges. A top bar keeps the card exactly
// where it was: y = strip bottom + gap, surface anchored to the top. A bottom bar
// anchors the surface to the bottom and hangs the card one gap above the strip's
// top edge. The internals are untouched: the progress line stays above the
// transport in both cases.
function caseCardBarPosition() {
  const yPiece = propIn(src.mini, "card", "y", "cardY")
  const heightPiece = exprAt(src.mini, /^  implicitHeight:/m, "surfaceHeight")
  const bottomPiece = exprAt(src.mini, /^  readonly property bool barAtBottom:/m, "barAtBottom")
  const gap = 7, stripH = 26, cardH = 122, screenH = 960
  const stripTop = screenH - stripH

  if (!yPiece || !heightPiece) {
    report("14", "the hover card hangs from whichever edge the bar is on", false,
      ["not found in MiniPlayer.qml: " + (!yPiece ? "the card's `y:`" : "the surface height")])
    return
  }

  function evalAt(piece, bottom) {
    try {
      const mini = { barAtBottom: bottom, barH: stripH, barY: stripTop, gap: gap }
      const card = { height: cardH }
      const Style = { space: function (n) { return n } }
      const screen = { height: screenH }
      // The surface height expression writes `barH`/`gap`/`card` as bare names
      // (they are ids/properties in the card's own scope), the y expression names
      // its `mini.` owner -- hand the evaluator both.
      const f = new Function("mini", "Style", "card", "screen", "barH", "gap",
        "barAtBottom", "barY", "return (" + piece.body + ")")
      return f(mini, Style, card, screen, stripH, gap, bottom, stripTop)
    } catch (e) {
      return "<error:" + e.message + ">"
    }
  }
  function bottomRule() {
    if (!bottomPiece) return "<absent>"
    try {
      const f = new Function("barPosition", "return (" + bottomPiece.body + ")")
      return { top: f("top"), bottom: f("bottom") }
    } catch (e) {
      return { top: "<error:" + e.message + ">", bottom: "<error:" + e.message + ">" }
    }
  }
  const rule = bottomRule()
  const topY = evalAt(yPiece, false)
  const bottomY = evalAt(yPiece, true)
  const topH = evalAt(heightPiece, false)
  const bottomH = evalAt(heightPiece, true)

  // Top bar: the card starts just under the strip's bottom edge.
  const topAbsolute = topY
  // Bottom bar: the surface is anchored to the screen's bottom, so the card's
  // absolute y is screen height - surface height + its local y.
  const bottomAnchored = /bottom:\s*(?:mini\.)?barAtBottom/.test(src.mini)
    && /top:\s*!(?:mini\.)?barAtBottom/.test(src.mini)
  const bottomAbsolute = bottomAnchored ? screenH - bottomH + bottomY : bottomY
  const bottomCardBottom = bottomAbsolute + cardH

  const topOk = topY === stripH + gap && topH === stripH + gap + cardH + 8
  // Bottom: the card hangs one gap above the strip's top edge.
  const bottomOk = bottomY === 8 && bottomCardBottom === stripTop - gap
  const ruleOk = bottomPiece !== null && rule.top === false && rule.bottom === true
  const internalsUntouched = /id: controls/.test(src.mini)

  report("14", "the hover card hangs from whichever edge the bar is on",
    topOk && bottomOk && ruleOk && bottomAnchored && internalsUntouched,
    [
      "card `y:` " + (yPiece ? "line " + yPiece.first + " sha256:" + yPiece.hash
        + "  " + JSON.stringify(yPiece.body.trim()) : "absent"),
      "surface height " + (heightPiece ? "line " + heightPiece.first
        + " sha256:" + heightPiece.hash : "absent"),
      "barAtBottom " + (bottomPiece ? "line " + bottomPiece.first + " sha256:" + bottomPiece.hash
        + "  " + JSON.stringify(bottomPiece.body.trim()) : "absent")
        + "   bar top/bottom -> " + JSON.stringify(rule.top) + " / " + JSON.stringify(rule.bottom),
      "top bar    (" + stripH + " px strip, " + screenH + " px screen): y " + topY
        + ", height " + topH + ", card starts at " + topAbsolute
        + " (want " + (stripH + gap) + " = strip bottom + gap)",
      "bottom bar: local y " + bottomY + ", height " + bottomH
        + ", surface anchored bottom: " + bottomAnchored,
      "  card absolute top " + bottomAbsolute + ", bottom " + bottomCardBottom
        + " (want " + (stripTop - gap) + " = strip top - gap); it is above the strip: "
        + (bottomCardBottom <= stripTop),
      "expected: top bar unchanged (y = barH + gap, top-anchored surface), bottom bar"
        + " hanging above the strip from its top edge -- never drawn off-screen"
    ])
}

// --- 15: the cover-path map is bounded like the cover cache ------------------
// Every `art` event added one entry to `artMap` and never removed one, while the
// fetch cache next to it is deliberately capped at 64. A long session with
// streams grew the map without bound, and it is copied on every insert. Drive
// N+ inserts through the shipped event handler: the map has to stay at the cap
// and the newest entry has to survive.
function caseArtMapCap() {
  if (!barSrc) {
    report("15", "the cover-path map stays bounded", false,
      ["BarWidget.qml not found beside the surfaces -- nothing to check"])
    return
  }
  const block = blockAt(barSrc, /if \(name === "art"\) \{/, "artEvent")
  if (!block) {
    report("15", "the cover-path map stays bounded", false,
      ["not found in BarWidget.qml: the `art` event handler"])
    return
  }
  const run = new Function("event", block.body)
  // The extracted block is the body of `if (name === "art")` and ends in a bare
  // `return`; it reads and writes `artMap` as a free name. In a non-strict
  // Function body that is the global object -- the same way the widget's own
  // scope resolves it -- so hand the map over through it.
  let map = {}
  function insert(uri, path) {
    global.artMap = map
    run({ uri: uri, path: path })
    map = global.artMap
  }

  const N = 70
  for (let i = 0; i < N; i++) insert("stream/" + i, "/cover/" + i)
  const size = Object.keys(map).length
  const newest = map["stream/" + (N - 1)] === "/cover/" + (N - 1)
  const oldestGone = map["stream/0"] === undefined

  // Re-seeing an entry that is already there must not grow the map either.
  insert("stream/" + (N - 1), "/cover/" + (N - 1))
  const sizeAgain = Object.keys(map).length

  // An entry that was evicted comes back as the newest one and pushes the
  // oldest surviving entry out.
  insert("stream/10", "/cover/10")
  const sizeRevived = Object.keys(map).length
  const revivedNewest = map["stream/10"] === "/cover/10"

  const cap = 64
  const ok = size === cap && newest && oldestGone && sizeAgain === cap
    && sizeRevived === cap && revivedNewest

  report("15", "the cover-path map stays bounded", ok, [
    "art event " + (block ? "lines " + block.first + "-" + block.last
      + " sha256:" + block.hash : "absent"),
    N + " inserts -> " + size + " entries (want " + cap + "), newest \"stream/"
      + (N - 1) + "\" present: " + newest + ", oldest \"stream/0\" gone: " + oldestGone,
    "the same entry again -> " + sizeAgain + " entries",
    "an evicted entry re-inserted -> " + sizeRevived + " entries, it is the newest: "
      + revivedNewest,
    "expected: at most " + cap + " paths, the most recent ones kept -- the same bound"
      + " the fetch cache already has, so a session with streams cannot grow forever"
  ])
}

// --- 16: the OSD title asks the widget, like every other surface -------------
// The OSD built its own first line from `song.title` (and a URL piece as the
// fallback), so a stream showed its ICY track or `groovesalad-128-mp3`, and with
// a wedged daemon it still presented the last title as current while the bar,
// the hover card and the wallpaper said "MPD is not answering". The title now
// comes from the same helpers as everywhere else and honours `stale`.
function caseOsdTitle() {
  if (!barSrc) {
    report("16", "the OSD title asks the widget, like every other surface", false,
      ["BarWidget.qml not found beside the surfaces -- nothing to check"])
    return
  }
  const at = barSrc.indexOf("id: osdComponent")
  const end = barSrc.indexOf("IpcHandler", at)
  const osd = at >= 0 ? barSrc.slice(at, end > at ? end : barSrc.length) : ""
  const colorAt = osd.indexOf("color: Color.popups.text")
  const textAt = colorAt >= 0 ? osd.lastIndexOf("text:", colorAt) : -1
  const piece = textAt >= 0 ? readExpr(osd, textAt + "text:".length, "osdTitle") : null
  if (!piece) {
    report("16", "the OSD title asks the widget, like every other surface", false,
      ["not found in BarWidget.qml: the OSD title's `text:`"])
    return
  }

  function view(stale, song, songTitleValue) {
    const root = {
      stale: stale,
      song: song,
      songFile: song.file || "",
      songTitle: function () { return songTitleValue },
      basename: function (f) { return String(f || "").split("/").pop().replace(/\.[^.]+$/, "") }
    }
    return evalPiece(piece, "expr", ["root"], [root], "osdTitle")
  }

  const streamSong = { file: "https://ice5.somafm.com/groovesalad-128-mp3",
                       name: "Groove Salad [SomaFM]", title: "Sine - The Return" }
  const fileSong = { file: "Music/Boards of Canada/Dayvan.mp3", artist: "Boards of Canada",
                     album: "Music Has the Right to Children", title: "Dayvan Cowboy" }
  const stale = view(true, fileSong, "Dayvan Cowboy")
  const stream = view(false, streamSong, "Groove Salad [SomaFM]")
  const file = view(false, fileSong, "Dayvan Cowboy")
  const empty = view(false, {}, "")

  const asksWidget = /songTitle/.test(piece.body) && /stale/.test(piece.body)
  const ok = stale === "MPD is not answering"
    && stream === "Groove Salad [SomaFM]"
    && stream.indexOf("Sine - The Return") < 0
    && stream.indexOf("groovesalad-128-mp3") < 0
    && file === "Dayvan Cowboy"
    && empty === "—"
    && asksWidget

  report("16", "the OSD title asks the widget, like every other surface", ok, [
    "OSD title " + (piece ? "line " + (piece.first + (at >= 0
      ? barSrc.slice(0, at).split("\n").length - 1 : 0)) + " sha256:" + piece.hash
      + "  " + JSON.stringify(piece.body.trim()) : "absent"),
    "  reads songTitle()/stale: " + asksWidget,
    "wedged daemon -> " + JSON.stringify(stale) + " (want \"" + SAYS + "\")",
    "stream        -> " + JSON.stringify(stream)
      + " (want the station name, never the ICY title or the URL remnant)",
    "file          -> " + JSON.stringify(file),
    "nothing       -> " + JSON.stringify(empty),
    "expected: the shared helpers and the stale flag decide this line, exactly as"
      + " the bar label does -- not a private copy of the song title"
  ])
}

// --- 17: the format language reads only the values it was given -------------
// `_value` did `values[name]`, so `%constructor%` printed
// "function Object() { [native code] }" and `%__proto__%` printed
// "[object Object]": the prototype leaked into the label. Only own properties
// are tags now; everything else is empty, and a real tag still renders.
function caseFormatOwnProperties() {
  if (!formatSrc) {
    report("17", "the format language reads only its own values", false,
      ["Format.js not found beside the surfaces -- nothing to check"])
    return
  }
  let Format = null
  try {
    const source = formatSrc.replace(/^\s*\.pragma library\s*$/m, "")
    Format = new Function(source
      + "\nreturn { render: render, parse: parse, _value: _value }")()
  } catch (e) {
    report("17", "the format language reads only its own values", false,
      ["Format.js did not evaluate: " + e.message])
    return
  }
  const values = { artist: "Boards of Canada", title: "Dayvan Cowboy" }
  // A null-prototype map for the results: `rendered["__proto__"] = …` on a plain
  // object would set the prototype instead of an entry, hiding the very leak this
  // case is about.
  const rendered = Object.create(null)
  for (const tag of ["constructor", "__proto__", "hasOwnProperty", "toString",
                     "valueOf", "artist", "title"]) {
    rendered[tag] = Format.render("%" + tag + "%", values)
  }
  const empty = ["constructor", "__proto__", "hasOwnProperty", "toString", "valueOf"]
  const leaked = empty.filter(function (tag) { return rendered[tag] !== "" })
  const ownTagWorks = rendered.artist === "Boards of Canada"
    && rendered.title === "Dayvan Cowboy"
  const direct = Format._value("constructor", values) === ""
    && Format._value("__proto__", values) === ""
    && Format._value("artist", values) === "Boards of Canada"
  // A tag that is genuinely present but empty is still "not resolved": the
  // bracket rule must keep dropping `[%album% - ]` for it.
  const bracketed = Format.render("[%constructor% - ]%artist%", values)

  const ok = leaked.length === 0 && ownTagWorks && direct
    && bracketed === "Boards of Canada"

  report("17", "the format language reads only its own values", ok, [
    "prototype names rendered: " + empty.map(function (tag) {
      return "%" + tag + "% -> " + JSON.stringify(rendered[tag])
    }).join(", "),
    "  anything leaked: " + (leaked.length ? leaked.join(", ") : "no"),
    "own tags still render: %artist% -> " + JSON.stringify(rendered.artist)
      + ", %title% -> " + JSON.stringify(rendered.title),
    "_value direct: constructor -> " + JSON.stringify(Format._value("constructor", values))
      + ", __proto__ -> " + JSON.stringify(Format._value("__proto__", values))
      + ", artist -> " + JSON.stringify(Format._value("artist", values)),
    "[%constructor% - ]%artist% -> " + JSON.stringify(bracketed)
      + " (the unknown tag is empty, as a missing tag always was)",
    "expected: only own properties of `values` are tags -- Object.prototype is not"
      + " part of the format language"
  ])
}

caseMiniPlayer()
caseDesktopCard()
caseBand()
caseDerived()
caseTexts()
caseAlbumRepeatsTitle()
caseTransportHover()
caseCardHoverOwnership()
caseCardAnchoredToStrip()
caseCardStar()
caseBandStar()
caseDesktopCardPresence()
caseFavoritesEpoch()
caseCardBarPosition()
caseArtMapCap()
caseOsdTitle()
caseFormatOwnProperties()

console.log(failures === 0
  ? "all media-surface checks passed"
  : failures + " of " + total + " media-surface checks failed")
process.exit(failures === 0 ? 0 : 1)
