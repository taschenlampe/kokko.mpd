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
    timer: exprAt(src.mini, /running:(?=\s*mini\.open)/, "timer")
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
    progressVisible: propIn(src.card, "progressBox", "visible", "progressVisible")
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
function caseTexts() {
  const readmePath = path.join(root, "README.md")
  const panelPath = path.join(root, "Panel.qml")
  if (!fs.existsSync(readmePath) || !fs.existsSync(panelPath)) {
    report("5", "the prose points at the bridge and is honest about the restart", false,
      ["not found next to the surfaces: "
        + [readmePath, panelPath].filter(function (p) { return !fs.existsSync(p) }).join(", "),
       "expected: README.md and Panel.qml beside the three .qml files"])
    return
  }
  const readme = fs.readFileSync(readmePath, "utf8")
  const panel = fs.readFileSync(panelPath, "utf8")

  const hintM = /title: "Restart MPD",\s*\n\s*hint: "([^"]*)"/.exec(panel)
  const hint = hintM ? hintM[1] : null

  const bulletM = /- \*\*The bar says "MPD is not answering"\*\*([\s\S]*?)(?=\n- \*\*)/.exec(readme)
  const bullet = bulletM ? bulletM[1] : ""

  const hintOk = !!hint
    && /stop\s?limit/i.test(hint)
    && /\b90 s\b/.test(hint)
    && /\b5 s\b/.test(hint)
    && !/\b20 s\b|\b3 s\b|two misses|two failed/i.test(hint)
  const pointerOk = !/\b20 s\b/.test(bullet)
    && /HEALTH_INTERVAL|bin\/mpd-bridge/.test(bullet)
    && /band|hover card|wallpaper/i.test(bullet)
  const dropinOk = /\bTimeoutStopSec\b/.test(bullet)
    && /override\.conf/.test(bullet)
    && /\b90 s\b/.test(bullet)
    && /\b5 s\b/.test(bullet)

  report("5", "the prose points at the bridge and is honest about the restart",
    hintOk && pointerOk && dropinOk,
    [
      "Restart MPD hint  : " + (hint === null ? "not found" : "\"" + hint + "\""),
      "  names the unit's stop limit: " + (hint ? /stop\s?limit/i.test(hint) : false)
        + ", both durations (90 s / 5 s): "
        + (hint ? (/\b90 s\b/.test(hint) + " / " + /\b5 s\b/.test(hint)) : "n/a")
        + ", repeats no probe number: " + (hint ? !/\b20 s\b|\b3 s\b/.test(hint) : "n/a"),
      "README bullet     : " + (bulletM ? "found at the \"MPD is not answering\" entry"
        : "not found"),
      "  no \"20 s\" left: " + (bulletM ? !/\b20 s\b/.test(bullet) : false)
        + ", points at the bridge (HEALTH_INTERVAL/bin/mpd-bridge): "
        + (bulletM ? /HEALTH_INTERVAL|bin\/mpd-bridge/.test(bullet) : false)
        + ", names the other surfaces: " + (bulletM ? /band|hover card|wallpaper/i.test(bullet) : false),
      "  drop-in named (TimeoutStopSec in override.conf): "
        + (bulletM ? /\bTimeoutStopSec\b/.test(bullet) && /override\.conf/.test(bullet) : false),
      "expected: the numbers stay in the bridge comment, the prose points there,"
        + " and the restart says what the unit's stop limit does to it"
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

caseMiniPlayer()
caseDesktopCard()
caseBand()
caseDerived()
caseTexts()
caseAlbumRepeatsTitle()

console.log(failures === 0
  ? "all media-surface checks passed"
  : failures + " of " + total + " media-surface checks failed")
process.exit(failures === 0 ? 0 : 1)
