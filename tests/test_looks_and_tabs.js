#!/usr/bin/env node
// The two tables that must agree: the cover looks and the tab numbers.
//
// A look exists in four places -- the settings enum in manifest.json, the enum in
// the settings tab, a Band*.qml file, and one line of Panel.bandComponent(). A
// missing file or a forgotten line does not fail loudly: the look simply falls
// through to `classic` and looks wrong for nobody knows how long. Same for the
// digits: `1` is the queue by muscle memory, and a tab inserted in the middle
// renumbers every key after it (which is how `8` once stopped being the radio
// tab).
//
// What is checked, from the shipped sources:
//   * every look in the manifest enum has its Band file and its bandComponent line,
//   * every Component the lines name exists and instantiates that file,
//   * the settings tab's enum is the manifest's enum, in the same order,
//   * no Band file is orphaned (a file nothing can ever select),
//   * tabOrder has ten entries, no duplicate keys, `start` last,
//   * tabForNumber(i) picks tabOrder[i-1] and `0` reaches start,
//   * the chip digits the phosphor look draws are (index+1) % 10 -- so start is `0`,
//   * README's key table lists the same tabs in the same order.
//
// Usage:
//   node tests/test_looks_and_tabs.js
"use strict"

const fs = require("fs")
const path = require("path")

const root = path.join(__dirname, "..")
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8")
const panel = read("Panel.qml")
const manifest = JSON.parse(read("manifest.json"))
const readme = read("README.md")

let failures = 0
function check(name, ok, detail) {
  if (ok) {
    console.log("   ok    " + name)
    return
  }
  failures++
  console.log("   FAIL  " + name + (detail ? " -- " + detail : ""))
}

// ---------------------------------------------------------------- the looks

// look -> Band file. Written out, not derived: this table IS the mapping a
// person has to get right, and a test that guesses it cannot find a typo in it.
const FILES = {
  classic: "BandKlassisch.qml",
  sharp: "BandScharf.qml",
  hero: "BandHero.qml",
  anchor: "BandAnker.qml",
  vinyl: "BandVinyl.qml",
  minimal: "BandMinimal.qml",
  split: "BandSplit.qml",
  phosphor: "BandPhosphor.qml"
}

const schema = (manifest.barWidget.schema || []).find((e) => e.key === "coverLook")
const manifestLooks = schema ? schema.options.slice() : []
check("manifest has a coverLook enum", manifestLooks.length > 0)
check("the manifest enum lists every look this test knows",
  manifestLooks.slice().sort().join(",") === Object.keys(FILES).sort().join(","),
  manifestLooks.join(","))

// the settings tab's own enum: options: ["classic", ...] on the coverLook row
const tabRow = panel.match(/key: "coverLook"[\s\S]{0,400}?options: \[([^\]]+)\]/)
const tabLooks = tabRow ? tabRow[1].match(/"([a-z]+)"/g).map((s) => s.replace(/"/g, "")) : []
check("the settings tab offers the same looks, in the same order",
  tabLooks.join(",") === manifestLooks.join(","), tabLooks.join(","))

const component = panel.match(/function bandComponent\(\) \{([\s\S]*?)\n  \}/)
check("bandComponent() is where it was", component !== null)
const body = component ? component[1] : ""
const mapped = {}
for (const m of body.matchAll(/if \(root\.look === "([a-z]+)"\) return (\w+)/g)) mapped[m[1]] = m[2]
const fallback = body.match(/return (\w+)\s*$/)
const fallbackId = fallback ? fallback[1] : ""

for (const [look, file] of Object.entries(FILES)) {
  check("look " + look + " has a file", fs.existsSync(path.join(root, file)), file)
  if (look === "classic") {
    check("classic is the fallback in bandComponent()", fallbackId === "bandKlassisch", fallbackId)
    continue
  }
  check("look " + look + " is selected by bandComponent()", Boolean(mapped[look]), mapped[look])
}

const componentIds = {}
for (const m of panel.matchAll(/Component \{ id: (\w+); (\w+) \{\} \}/g)) componentIds[m[1]] = m[2]
for (const [look, id] of Object.entries(mapped)) {
  check("component " + id + " instantiates " + FILES[look],
    componentIds[id] === FILES[look].replace(/\.qml$/, ""), componentIds[id])
}
check("component bandKlassisch instantiates BandKlassisch",
  componentIds.bandKlassisch === "BandKlassisch", componentIds.bandKlassisch)

// No Band file without a look: one that exists and cannot be picked is dead code
// that will be edited by mistake sooner or later.
// BandChrome is the chassis every look is built on, not a look itself.
const onDisk = fs.readdirSync(root)
  .filter((n) => /^Band[A-Z].*\.qml$/.test(n) && n !== "BandChrome.qml")
for (const file of onDisk) {
  const used = Object.values(componentIds).indexOf(file.replace(/\.qml$/, "")) !== -1
  check("Band file " + file + " is reachable from bandComponent()", used)
}
check("one look per Band file",
  onDisk.length === Object.keys(FILES).length, onDisk.length + " files")

// ----------------------------------------------------------------- the tabs

const order = panel.match(/readonly property var tabOrder: \[([\s\S]*?)\n  \]/)
const tabs = order ? Array.from(order[1].matchAll(/\{ key: "([a-z]+)", label: "[^"]+" \}/g))
  .map((m) => m[1]) : []
check("tabOrder has ten tabs", tabs.length === 10, tabs.length + ": " + tabs.join(","))
check("no duplicate tab key", new Set(tabs).size === tabs.length)
check("start is the last tab (it is reached by 0)", tabs[tabs.length - 1] === "start", tabs[tabs.length - 1])
const expected = ["queue", "search", "albums", "artists", "genres", "files",
  "playlists", "radio", "settings", "start"]
check("the order is the documented one", tabs.join(",") === expected.join(","), tabs.join(","))

// tabForNumber(i) = tabOrder[i-1]; 0 is handled separately and must reach start
check("tabForNumber is one-based", /function tabForNumber\(value\) \{\s*var index = Number\(value\) - 1/.test(panel))
check("`0` reaches start", /if \(text === "0" \|\| key === Qt\.Key_0\) \{ root\.setTab\("start"\)/.test(panel))
// the digit that a chip shows for a tab: (index+1) % 10, so start shows 0
check("chip digits are (index+1) % 10", /String\(\(index \+ 1\) % 10\)/.test(panel))

// README's key table: the same ten names, in the same order
const keyLine = readme.split("\n").find((l) => l.indexOf("`1`…`9`, `0`, `tab`") !== -1)
check("README documents the digits", Boolean(keyLine))
if (keyLine) {
  const cell = keyLine.split("|")[2] || ""
  const names = cell.split("·").map((s) => s.trim())
  const translated = names.map((n) => n === "queue" ? "queue" : n === "search" ? "search"
    : n === "albums" ? "albums" : n === "artists" ? "artists" : n === "genres" ? "genres"
      : n === "files" ? "files" : n === "playlists" ? "playlists" : n === "radio" ? "radio"
        : n === "settings" ? "settings" : n === "start" ? "start" : "?" + n)
  check("README lists the same tabs in the same order",
    translated.join(",") === expected.join(","), translated.join(","))
}

// the settings tab is 9 and start is 0 -- said in prose in three places
check("README says the settings tab is 9", /settings tab \(9\)|panel tab 9/.test(readme))

if (failures) {
  console.log("\nFAILED (" + failures + ")")
  process.exit(1)
}
console.log("   all checks passed")
