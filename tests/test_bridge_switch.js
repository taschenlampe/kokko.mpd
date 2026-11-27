#!/usr/bin/env node
// The bridge switch: which file BarWidget.qml starts for `bridge` in shell.json.
//
// Method (as tests/test_barwidget_state.js): the two property bindings are
// extracted from the shipped source verbatim and evaluated under node with a
// stub `setting()` and a stub pluginDir -- QML is not needed to answer "which
// path does this binding produce".
//
// What it pins:
//   * no key at all -> the frozen bin/mpd-bridge ("legacy" is the default until
//     the cutover flips it),
//   * "next" -> bin/kokko-mpd-bridge, and the file that path names exists here,
//   * an unknown value -> legacy, never a third, non-existent mode,
//   * manifest.json carries the default, so shell.json gets the key written,
//     and it is NOT in the settings schema (no settings-tab row for a migration
//     switch).
//
// Usage:
//   node tests/test_bridge_switch.js [path/to/BarWidget.qml]
"use strict"

const fs = require("fs")
const path = require("path")

const root = path.join(__dirname, "..")
const target = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, "BarWidget.qml")
const src = fs.readFileSync(target, "utf8")

let failures = 0
function check(name, ok, detail) {
  if (ok) {
    console.log("   ok    " + name)
    return
  }
  failures++
  console.log("   FAIL  " + name + (detail ? " -- " + detail : ""))
}

// Take the text of `readonly property <type> <name>:` up to the next property
// or a blank-line block end, and strip the leading "if (...) {" wrapper style
// the file does not use -- one expression per binding here.
function binding(name) {
  const start = src.indexOf("readonly property string " + name + ":")
  if (start < 0) throw new Error("no binding for " + name)
  const from = src.indexOf(":", start) + 1
  const rest = src.slice(from)
  const end = rest.search(/\n\s*(readonly property|function|on[A-Z]|\/\/|\/\*)/)
  const text = rest.slice(0, end < 0 ? rest.length : end).trim().replace(/;$/, "")
  return text
}

const kindExpr = binding("bridgeKind")
const pathExpr = binding("bridgePath")
console.log("   bridgeKind:\n     " + kindExpr.replace(/\n\s*/g, " "))
console.log("   bridgePath:\n     " + pathExpr.replace(/\n\s*/g, " "))

function evaluate(expr, settings) {
  const fn = new Function(
    "__setting", "__pluginDir", "__kind",
    "return (" + expr
      .replace(/setting\(/g, "__setting(")
      .replace(/pluginDir/g, "__pluginDir")
      .replace(/bridgeKind/g, "__kind") + ")")
  const setting = (name, fallback) => {
    const value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }
  return fn(setting, "/home/x/.config/omarchy/plugins/kokko.mpd", arguments[2])
}

function kind(settings) {
  return evaluate(kindExpr, settings)
}
function bridgePath(settings) {
  const k = kind(settings)
  return evaluate(pathExpr, settings, k)
}

// --- the binding
check("no key -> legacy", kind({}) === "legacy", kind({}))
check("legacy -> bin/mpd-bridge", bridgePath({}) === "/home/x/.config/omarchy/plugins/kokko.mpd/bin/mpd-bridge", bridgePath({}))
check("next -> next", kind({ bridge: "next" }) === "next")
check("next -> bin/kokko-mpd-bridge",
  bridgePath({ bridge: "next" }) === "/home/x/.config/omarchy/plugins/kokko.mpd/bin/kokko-mpd-bridge",
  bridgePath({ bridge: "next" }))
check("explicit legacy stays legacy", bridgePath({ bridge: "legacy" }).endsWith("/bin/mpd-bridge"))
check("an unknown value is legacy, not a third mode",
  bridgePath({ bridge: "experimental" }).endsWith("/bin/mpd-bridge"))

// --- the two files are both there, and both start with python3
for (const rel of ["bin/mpd-bridge", "bin/kokko-mpd-bridge"]) {
  const file = path.join(root, rel)
  check(rel + " exists", fs.existsSync(file))
}
const command = src.match(/command:\s*\["python3",\s*root\.bridgePath\]/)
check("the Process runs `python3 <bridgePath>` (no shebang needed)", command !== null)

// --- manifest: the default exists, the settings tab gets no row for it
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"))
const bar = manifest.barWidget || {}
check("manifest default is legacy", bar.defaults && bar.defaults.bridge === "legacy",
  JSON.stringify(bar.defaults && bar.defaults.bridge))
const schemaKeys = (bar.schema || []).map((entry) => entry.key)
check("no settings-tab row for the switch", schemaKeys.indexOf("bridge") === -1)

// --- the restart path exists and does not go through the crash message
check("switch restarts the child", /function restartBridge\(\)/.test(src))
check("onBridgeKindChanged restarts", /onBridgeKindChanged:\s*Qt\.callLater\(restartBridge\)/.test(src))
check("a switch is not reported as a crash",
  /switchingBridge \? "bridge switched"/.test(src) && /if \(root\.switchingBridge\) return/.test(src))

if (failures) {
  console.log("\nFAILED (" + failures + ")")
  process.exit(1)
}
console.log("   all checks passed")
