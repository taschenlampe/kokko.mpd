#!/usr/bin/env node
// State regression for BarWidget.qml: cover cache after a failed fetch, the
// hover card's fade timer, the width reserved for the cover thumbnails, and the
// width the strip keeps when nothing plays.
//
// Method (same as the independent verification): every function under test is
// extracted from BarWidget.qml verbatim with brace matching and then run under
// node with a small model of the QML environment. Each piece prints its source
// line range and a hash of the extracted body, so a silent edit of the code
// under test shows up here instead of passing quietly.
//
// Modelled, not real QML -- everything else is the shipped source:
//   * osdVisible / osdOn are properties of the widget root. The extracted code
//     assigns them as bare names, which in a Function-constructor body (sloppy
//     mode) is the global object -- the same way the verification harness ran it.
//   * the timers osdHide (interval = root.osdDuration, 3000 ms) and osdFade
//     (220 ms, the literal from the source) offer QML stop()/restart()
//     semantics: both single shot, stop() cancels a pending firing, restart()
//     cancels the pending firing and arms a new one.
//   * Style.space(n) returns n (fontScale 1.0), barSize 26, maxWidth 160,
//     stateIndicator.implicitWidth 20 -- the numbers the verification report
//     measured from the live configuration.
//   * bindings are read eagerly here. In QML stripReserve re-evaluates when
//     showArt or artPath changes; this test reads it again at exactly those
//     points, which is the whole question (does the cover arriving change the
//     reserved width?).
//   * for case 11, `info.implicitWidth` is the content row (20 px when only the
//     state glyph is left) and `stripReserve` carries the value the reserve
//     block above produced -- the two numbers the width rule picks between. The
//     live configuration measured 196 px of reserve against 20 px of content.
//
// Usage:
//   node tests/test_barwidget_state.js                       # the repo's file
//   node tests/test_barwidget_state.js /path/to/BarWidget.qml  # another copy
"use strict"

const fs = require("fs")
const path = require("path")
const crypto = require("crypto")

const target = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(__dirname, "..", "BarWidget.qml")
const src = fs.readFileSync(target, "utf8")

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

function grab(re, what, blockOnly) {
  const m = re.exec(src)
  if (!m) throw new Error("not found in " + target + ": " + what)
  const start = m.index
  const open = src.indexOf("{", start)
  const end = matchBraces(src, open)
  const from = blockOnly ? open : start
  const body = src.slice(from, end + 1)
  return {
    what: what,
    body: body,
    first: src.slice(0, from).split("\n").length,
    last: src.slice(0, end).split("\n").length,
    hash: crypto.createHash("sha256").update(body).digest("hex").slice(0, 12)
  }
}

const pieces = {
  artFor: grab(/^  function artFor\(/m, "artFor"),
  showOsd: grab(/^  function showOsd\(/m, "showOsd"),
  hideOsd: grab(/^  function hideOsd\(/m, "hideOsd"),
  stripReserve: grab(/^  readonly property real stripReserve:/m, "stripReserve", true)
}

// The width rule for the no-title case is case 11's own subject, so it is grabbed
// on its own: against a source without it -- the unfixed one -- the case has to
// *report* that absence instead of dying before the first check runs, which is
// what makes this suite the proof that the fix is what makes it pass.
let stripActual = null
try {
  stripActual = grab(/^  readonly property real stripActual:/m, "stripActual", true)
} catch (e) {
  // Reported by case 11 as a note; the case itself reads the source's own width
  // expression, so it fails on the number even on a source without this property.
}

console.log("BarWidget.qml under test: " + target)
console.log("extracted verbatim:")
for (const key of Object.keys(pieces)) {
  const p = pieces[key]
  console.log("   " + p.what.padEnd(13) + " " + (p.first + "-" + p.last).padEnd(11)
    + " sha256:" + p.hash)
}
if (stripActual) {
  console.log("   " + stripActual.what.padEnd(13) + " " + (stripActual.first + "-" + stripActual.last).padEnd(11)
    + " sha256:" + stripActual.hash)
} else {
  console.log("   " + "stripActual".padEnd(13) + " absent -- no width rule for the no-title case")
}
console.log()

// One factory per run, so the widget's own state cannot leak between checks.
const makeWidget = new Function("root",
  pieces.artFor.body + "\n\n" + pieces.showOsd.body + "\n\n" + pieces.hideOsd.body
  + "\nreturn { artFor: artFor, showOsd: showOsd, hideOsd: hideOsd }")
const makeReserve = new Function("return (function () " + pieces.stripReserve.body + ")")

let failures = 0
function report(id, title, ok, detail) {
  if (!ok) failures++
  console.log("[" + (ok ? "PASS" : "FAIL") + "] " + id + " " + title)
  detail.forEach(function (line) { console.log("        " + line) })
  console.log()
}

// --- 8: a failed cover fetch must not be cached as "no cover" ---------------
function caseArtCache() {
  const calls = []
  let mode = "error"
  const root = {
    artCache: {}, artCacheCount: 0, debugProtocol: false,
    query: function (kind, args, channel, cb) {
      calls.push(args.uri)
      if (mode === "error") return cb([], "connection lost")
      if (mode === "none") return cb([], "")
      return cb([{ path: "/tmp/cover.jpg" }], "")
    }
  }
  const w = makeWidget(root)
  const got = []

  w.artFor("Song/01.mp3", "Album", "Artist", function (p) { got.push(p) })
  const cachedAfterError = Object.prototype.hasOwnProperty.call(root.artCache, "Song/01.mp3")

  mode = "ok"
  const before = calls.length
  w.artFor("Song/01.mp3", "Album", "Artist", function (p) { got.push(p) })
  const retried = calls.length - before

  // Control: a confirmed "no cover" (empty answer, no error) may still be cached.
  const root2 = {
    artCache: {}, artCacheCount: 0, debugProtocol: false,
    query: function (kind, args, channel, cb) { calls.push("none:" + args.uri); return cb([], "") }
  }
  const w2 = makeWidget(root2)
  const got2 = []
  w2.artFor("NoCover/01.mp3", "", "", function (p) { got2.push(p) })
  const noneCached = root2.artCache["NoCover/01.mp3"] === ""
  const before2 = calls.length
  w2.artFor("NoCover/01.mp3", "", "", function (p) { got2.push(p) })
  const noneHits = calls.length - before2

  report("8", "a failed cover fetch is not cached as an answer", 
    !cachedAfterError && retried === 1 && got[0] === "" && got[1] === "/tmp/cover.jpg"
      && noneCached && noneHits === 0 && got2[0] === "" && got2[1] === "",
    [
      "fetch fails        -> callback \"" + got[0] + "\", cache entry for the title: "
        + (cachedAfterError ? "yes (empty path)" : "none"),
      "same title, bridge back -> " + retried + " new backend quer(y|ies), callback \""
        + got[1] + "\"",
      "control, confirmed no cover -> cached: " + noneCached + ", second call: "
        + noneHits + " new queries, callback \"" + got2[1] + "\"",
      "expected: no cache entry and 1 new query after the error; the confirmed"
        + " no cover still answers from the cache"
    ])
}

// --- 9: a card shown again during the fade must not be hidden by it ---------
function caseOsdTimers() {
  let now = 0
  const pending = []
  const handlers = {}

  function timer(name, interval) {
    const t = {
      name: name, interval: interval,
      stop: function () {
        for (let i = pending.length - 1; i >= 0; i--) if (pending[i].name === name) pending.splice(i, 1)
      },
      restart: function () {
        t.stop()
        pending.push({ name: name, at: now + interval, fire: function () { handlers[name]() } })
      }
    }
    return t
  }

  global.osdVisible = false
  global.osdOn = false
  global.osdHide = timer("osdHide", 3000)   // root.osdDuration, as measured
  global.osdFade = timer("osdFade", 220)    // the literal in the source
  const root = { debugProtocol: false, hovering: true, artPath: "/tmp/cover.jpg" }
  const w = makeWidget(root)
  handlers.osdHide = function () { w.hideOsd() }
  handlers.osdFade = function () { global.osdVisible = false }

  const trace = []
  function step(ms) {
    now += ms
    while (true) {
      const due = pending.filter(function (p) { return p.at <= now })
        .sort(function (a, b) { return a.at - b.at })
      if (due.length === 0) break
      const t = due[0]
      pending.splice(pending.indexOf(t), 1)
      t.fire()
    }
  }

  // Pointer leaves the label and returns 100 ms later, inside the 220 ms fade.
  root.hovering = true
  w.showOsd(true)
  trace.push("t=" + now + " showOsd(true)          visible=" + global.osdVisible + " on=" + global.osdOn)
  root.hovering = false
  w.hideOsd()
  step(100)
  trace.push("t=" + now + " hideOsd() then +100 ms  visible=" + global.osdVisible + " on=" + global.osdOn)
  root.hovering = true
  w.showOsd(true)
  trace.push("t=" + now + " showOsd(true)          visible=" + global.osdVisible + " on=" + global.osdOn)
  step(125)
  trace.push("t=" + now + " osdFade would fire      visible=" + global.osdVisible + " on=" + global.osdOn)
  const stillUp = global.osdVisible === true && global.osdOn === true

  // Control: a hide without a re-open must still take the card down.
  global.osdVisible = false
  global.osdOn = false
  pending.length = 0
  now = 0
  root.hovering = true
  w.showOsd(true)
  root.hovering = false
  w.hideOsd()
  step(220)
  const faded = global.osdVisible === false && global.osdOn === false

  report("9", "a card re-opened during the fade survives it",
    stillUp && faded,
    trace.concat([
      "expected: the card is still up (visible=true, on=true) after the fade's",
      "220 ms, because showOsd() stops the pending hide; control: a hide that is",
      "not undone still ends with visible=false, on=false -> " + faded
    ]))
}

// --- 10: the reserved width must not depend on the cover arriving -----------
function caseStripReserve() {
  global.Style = { space: function (n) { return n } }
  global.barSize = 26
  global.maxWidth = 160
  global.showStateIcon = true
  global.stateIndicator = { implicitWidth: 20 }
  const reserve = makeReserve()

  global.showArt = true
  global.artPath = ""
  const withoutCover = reserve()
  global.artPath = "/tmp/cover.jpg"
  const withCover = reserve()
  const delta = withCover - withoutCover

  // Control: showArt still buys the slot, measured against showArt off.
  global.showArt = false
  global.artPath = ""
  const off = reserve()
  const slot = withoutCover - off

  report("10", "the reserved width is keyed to the setting, not to the cover",
    delta === 0 && slot === global.barSize + global.Style.space(6),
    [
      "showArt on,  no cover yet : " + withoutCover + " px",
      "showArt on,  cover arrived: " + withCover + " px   (delta " + delta + " px)",
      "showArt off               : " + off + " px   (slot " + slot + " px)",
      "expected: delta 0 -- the strip must not move when the image lands; and",
      "showArt still reserves barSize + space(6) = 26 + 6 px"
    ])
}

// --- 11: with no title the strip drops the label reserve ---------------------
// Reported symptom: stopped, the widget showed only the glyph but kept the
// reserve -- stripWidth 196, contentRight 108, rightGap 88, i.e. 88 px of nothing
// on *both* sides of the glyph, because the content row is centred in the box.
//
// Read from the shipped source, not from a property name: the width expression of
// the `nowPlaying` item and the offset the hover card is anchored on are lifted
// out as expressions, so the case runs against a source with or without a width
// property of its own -- and against the unfixed one it fails on the number, not
// on a missing name.
function caseIdleWidth() {
  // The configuration the report measured: label max 160, state glyph 20, no
  // cover slot -- so the reserve comes out at 196 px.
  global.Style = { space: function (n) { return n } }
  global.barSize = 26
  global.maxWidth = 160
  global.showStateIcon = true
  global.showArt = false
  global.artPath = ""
  global.stateIndicator = { implicitWidth: 20 }

  // The whole width expression of the `nowPlaying` item, ternary included, so the
  // vertical branch is the source's own and not the test's model of it.
  const widthM = /^      implicitWidth: (root\.vertical \? root\.barSize : .+?)\s*$/m.exec(src)
  const anchorM = /return root\.mapToItem\(null, root\.width, 0\)\.x - (.+?)\s*\/\s*2\s*$/m.exec(src)
  if (!widthM || !anchorM) {
    report("11", "with no title the strip is only as wide as its content", false, [
      "not found in " + target + ": " + (widthM ? "the card's anchor offset" : "the strip's width expression"),
      "expected: the `nowPlaying` item's implicitWidth and the hover card's",
      "cardCenterX offset, which this case reads out of the source"
    ])
    return
  }
  const evalWidth = new Function("root", "return (" + widthM[1] + ")")
  const evalAnchor = new Function("root", "return (" + anchorM[1] + ")")

  const reserve = makeReserve()
  // What the source under test answers for the actual width: the model is
  // `stripActual` where it exists, an unbound name (undefined) where it does not.
  const actualRule = stripActual
    ? (new Function("return (function () " + stripActual.body + ")"))()
    : null

  const content = 20        // measured: the state glyph is all that is left

  // One snapshot of the widget in a given state, the way QML would resolve it.
  function state(hasSongValue, verticalValue, contentWidth) {
    global.vertical = verticalValue
    global.hasSong = hasSongValue
    global.info = { implicitWidth: contentWidth }
    const reserved = reserve()      // the settings as set right now
    global.stripReserve = reserved  // in QML this is the root property
    const root = {
      vertical: verticalValue, barSize: global.barSize, stripReserve: reserved,
      stripActual: actualRule ? actualRule() : undefined
    }
    return { width: evalWidth(root), anchor: evalAnchor(root), reserve: reserved }
  }

  const idle = state(false, false, content)          // stopped / disconnected
  const playing = state(true, false, content)        // playing
  const otherTitle = state(true, false, 148)         // same player, other title
  global.maxWidth = 200
  const roomier = state(true, false, content)        // settings changed
  const roomierIdle = state(false, false, content)
  global.maxWidth = 160
  const upright = state(true, true, content)         // vertical bar
  const uprightIdle = state(false, true, content)

  const emptyPerSide = (idle.reserve - content) / 2

  report("11", "with no title the strip is only as wide as its content",
    idle.reserve === 196
      && playing.width === idle.reserve && otherTitle.width === playing.width
      && roomier.width === roomier.reserve && roomier.reserve === 236
      && idle.width === content && roomierIdle.width === content
      && upright.width === global.barSize && uprightIdle.width === global.barSize
      // The hover card is anchored on the same number the strip is wide: half of
      // the actual width, never half of the reserve.
      && playing.anchor === playing.width && idle.anchor === idle.width,
    [
      "stripReserve from the settings           : " + idle.reserve + " px",
      "with a title (content 20 / 148 px)       : " + playing.width + " / " + otherTitle.width + " px",
      "settings changed (label max 200 -> 236)  : " + roomier.width + " px",
      "no title (stopped, content 20 px)        : " + idle.width + " px",
      "  the reserve would be " + idle.reserve + " px -- " + emptyPerSide + " px of nothing",
      "  on each side, the measured 88 px",
      "vertical bar, with / without a title     : " + upright.width + " / " + uprightIdle.width + " px",
      "card anchor offset, with / without title : " + playing.anchor + " / " + idle.anchor + " px",
      "expected: 196 px while a title is there, exactly the content width without"
    ].concat(actualRule ? [] : [
      "note: this source has no `stripActual` -- the width expression is read",
      "directly, and it answers " + idle.width + " px with no title"
    ]))
}

caseArtCache()
caseOsdTimers()
caseStripReserve()
caseIdleWidth()

console.log(failures === 0
  ? "all state checks passed"
  : failures + " of 4 state checks failed")
process.exit(failures === 0 ? 0 : 1)
