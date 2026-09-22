#!/usr/bin/env node
// State regression for BarWidget.qml: cover cache after a failed fetch, the
// hover card's fade timer, and the width reserved for the cover thumbnails.
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

console.log("BarWidget.qml under test: " + target)
console.log("extracted verbatim:")
for (const key of Object.keys(pieces)) {
  const p = pieces[key]
  console.log("   " + p.what.padEnd(13) + " " + (p.first + "-" + p.last).padEnd(11)
    + " sha256:" + p.hash)
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

caseArtCache()
caseOsdTimers()
caseStripReserve()

console.log(failures === 0
  ? "all state checks passed"
  : failures + " of 3 state checks failed")
process.exit(failures === 0 ? 0 : 1)
