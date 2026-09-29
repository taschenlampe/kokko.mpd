#!/usr/bin/env node
/*
 * Panel state regression: the prompt/filter/tab state machine of Panel.qml.
 *
 * Why this shape: the state that breaks lives in Panel.qml, and qmllint only
 * checks that the file parses -- it cannot press a key. So the functions that
 * carry the state are cut out of Panel.qml byte for byte (bracket matching, the
 * same way the independent verification did it: extract -> run with node) and
 * executed here against a small model of the QML semantics they rely on.
 *
 *     node tests/test_panel_state.js
 *     PANEL_QML=/tmp/panel_before.qml node tests/test_panel_state.js   # other revision
 *
 * MODELLED, not measured -- everything else is production code:
 *   1. `root.stack = [...]` runs onStackChanged synchronously. The handler is
 *      extracted from Panel.qml (onStackChanged), the synchronicity is the
 *      model's; QML does exactly that.
 *   2. Qt.binding(fn) marks a property as bound, and a later plain assignment
 *      destroys that binding (QML semantics).
 *   3. Timers: restart() arms, stop() cancels, fire() runs the timer's
 *      onTriggered, taken verbatim from Panel.qml.
 *   4. host.query/mutation/setSetting and the other widget methods only record
 *      what the panel asks for. No bridge, no MPD, no socket.
 *   5. The key events handed to the extracted handleKey are shaped here (key
 *      code + text); the routing inside handleKey is the production one.
 *   6. settingRows is a list the test owns; in QML it is a readonly property and
 *      re-evaluated on read.
 *   7. The row delegate: `rowType`, `isHeader` and `selected` are taken verbatim
 *      from Panel.qml and evaluated once per row with the ListView's modelData and
 *      index -- the same three properties the mark is drawn from. Nothing about
 *      the selection is re-written here.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const PANEL = process.env.PANEL_QML
  ? path.resolve(process.env.PANEL_QML)
  : path.join(__dirname, "..", "Panel.qml");
const SRC = fs.readFileSync(PANEL, "utf8");

// --------------------------------------------------------------- extraction
// Verbatim: the text between the opening and the matching closing brace, with
// strings and line comments skipped while counting.

function braceEnd(text, open) {
  let depth = 0;
  let i = open;
  let quote = null;
  while (i < text.length) {
    const ch = text[i];
    if (quote !== null) {
      if (ch === "\\") { i += 2; continue; }
      if (ch === quote) quote = null;
    } else if (ch === "\"" || ch === "'") {
      quote = ch;
    } else if (ch === "/" && text.slice(i, i + 2) === "//") {
      const nl = text.indexOf("\n", i);
      i = nl < 0 ? text.length : nl;
      continue;
    } else if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) return i;
    }
    i++;
  }
  throw new Error("unbalanced braces");
}

function lineOf(index) {
  return SRC.slice(0, index).split("\n").length;
}

function grabFunction(name) {
  const m = new RegExp("^  function " + name + "\\(", "m").exec(SRC);
  if (!m) throw new Error("Panel.qml has no function " + name);
  const open = SRC.indexOf("{", m.index);
  const end = braceEnd(SRC, open);
  return { text: SRC.slice(m.index, end + 1), from: lineOf(m.index), to: lineOf(end) };
}

// The `onTriggered:` handler of a Timer, verbatim (the property lines above it
// are dropped, the body is used as it stands).
function grabTimerHandler(id) {
  const at = SRC.indexOf("id: " + id);
  if (at < 0) throw new Error("Panel.qml has no timer " + id);
  const decl = SRC.lastIndexOf("Timer {", at);
  if (decl < 0) throw new Error("no Timer declaration before " + id);
  const open = SRC.indexOf("{", decl + "Timer".length);
  const end = braceEnd(SRC, open);
  const block = SRC.slice(open + 1, end);
  const h = block.indexOf("onTriggered:");
  if (h < 0) throw new Error("timer " + id + " has no onTriggered");
  return {
    text: block.slice(h + "onTriggered:".length).trim(),
    from: lineOf(decl),
    to: lineOf(end)
  };
}

// A one-line handler of the root item, e.g. `onStackChanged: root.loadFrame(...)`.
function grabRootHandler(name) {
  const m = new RegExp("^  " + name + ": (.+)$", "m").exec(SRC);
  if (!m) throw new Error("Panel.qml has no " + name);
  return m[1].trim();
}

// One `readonly property <type> <name>: <expression>` binding out of the row
// delegate, verbatim. The expression may wrap onto the following line (Panel.qml
// breaks it where it would get long), so it is run on while the line so far ends
// with an operator or the next line opens with one.
function grabRowBinding(name) {
  const m = new RegExp("^[ \\t]+readonly property (?:bool|string) " + name + ": (.+)$", "m").exec(SRC);
  if (!m) throw new Error("Panel.qml has no row binding " + name);
  let text = m[1].trim();
  const rest = SRC.slice(m.index + m[0].length).split("\n");
  for (let i = 1; i < rest.length; i++) {
    const line = rest[i].trim();
    if (line === "") break;
    const continues = /^(&&|\|\||\?|:|\.|\+)/.test(line) || /(&&|\|\||\?|\+|\()$/.test(text);
    if (!continues) break;
    text += " " + line;
  }
  return text;
}

const FUNCTIONS = [
  "rootFrameFor", "tabForNumber", "setTab", "pushFrame", "popFrame", "topFrame", "loadFrame",
  "infoFor", "groupHits", "isSelectable", "firstSelectable", "lastSelectable",
  "rowIsSong", "activate", "addRow", "addOne", "addAll", "openPrompt",
  "closePrompt", "leavePrompt", "clearLocalFilter", "filterableFrame",
  "searchWhileTyping", "searchNow", "applySearch",
  "applyCategorySearch", "refreshFilteredRows", "applyLocalFilter",
  "openPromptForFrame", "submitPrompt", "rowTitle", "rowSub", "rowRight", "mutateAndReload",
  "handleKey",
  // The station directory: its own frames, its own rows, and the two helpers the
  // stream display hangs on.
  "isStream", "radioFrame", "radioRowsFor", "radioCountries", "radioGenres",
  "dedupeStations", "stationTitle", "stationSub", "applyRadioSearch",
  "stationRow", "stationDetail", "streamPlaying", "openRadioLevel", "showDetails",
  "detailPairs", "labelFor"
];

const MISSING = [];
const EXTRACTED = FUNCTIONS.map(function (name) {
  try {
    return grabFunction(name);
  } catch (e) {
    // A function a given revision does not have (a fix may add one). The model
    // then simply has no such call -- fine as long as nothing that is present
    // calls it.
    MISSING.push(name);
    return { text: "", from: 0, to: 0 };
  }
});
const STACK_HANDLER = grabRootHandler("onStackChanged");
const DEBOUNCE_HANDLER = grabTimerHandler("promptDebounce");
// The row delegate's own bindings, verbatim (see grabRowBinding). The mark the
// list draws is `selected`; `rowType`/`isHeader` are the two it reads.
const ROW_TYPE = grabRowBinding("rowType");
const ROW_IS_HEADER = grabRowBinding("isHeader");
const ROW_SELECTED = grabRowBinding("selected");

const BUILD = new Function(
  "root", "host", "Qt", "settingRows", "timers", "promptDebounce",
  "promptFocusTimer", "pendingSelectGuard", "reloadTimer",
  EXTRACTED.map(function (f) { return f.text; }).filter(Boolean).join("\n\n")
    + "\nreturn { " + FUNCTIONS.filter(function (n) { return MISSING.indexOf(n) < 0; })
        .map(function (n) { return n + ": " + n; }).join(", ") + " };"
);

function sha(text) {
  return crypto.createHash("sha256").update(text).digest("hex").slice(0, 12);
}

// --------------------------------------------------------------- tiny asserts
let checks = 0;
let failures = 0;

function group(title) {
  console.log("\n=== " + title + " ===");
}

function check(label, ok, detail) {
  checks++;
  if (!ok) failures++;
  console.log("  " + (ok ? "ok   " : "FAIL ") + label
    + (detail !== undefined && detail !== "" ? "   [" + detail + "]" : ""));
}

// --------------------------------------------------------------- panel model
function QtStub() {
  const keys = ["Escape", "Tab", "Down", "Up", "Return", "Enter", "Backspace",
    "Slash", "Space", "Plus", "Minus", "Equal", "Comma", "Period", "Greater",
    "Less", "End", "Left", "PageUp", "PageDown"];
  const Qt = {
    ShiftModifier: 0x02000000,
    ControlModifier: 0x04000000,
    binding: function (fn) { return { __binding: true, fn: fn }; },
    callLater: function (fn) { Qt.__later.push(fn); },
    rgba: function () { return {}; },
    __later: []
  };
  keys.forEach(function (k, i) { Qt["Key_" + k] = 1000 + i; });
  for (let d = 0; d <= 9; d++) Qt["Key_" + d] = 2000 + d;
  return Qt;
}

function makePanel(opts) {
  opts = opts || {};
  const queries = [];
  const mutations = [];
  const flashes = [];
  const infos = [];
  const calls = [];

  // MODELLED: model 2 in the header.
  let rowsValue = [];
  let rowsBound = false;

  const settingRows = opts.settingRows || [
    { type: "header", title: "In the bar" },
    { type: "setting", kind: "bool", key: "hoverCard", title: "Show the card", value: true },
    { type: "header", title: "In the player" },
    { type: "setting", kind: "int", key: "backdrop", title: "Backdrop", value: 60 }
  ];

  const Qt = QtStub();

  const root = {
    tab: "queue",
    sel: 0,
    infoText: "",
    loading: false,
    promptMode: "",
    promptText: "",
    promptTarget: "",
    promptExplicit: false,
    promptDebounceMode: "",
    filterText: "",
    allRows: [],
    detailRow: null,
    jumpToCurrent: false,
    skipCarry: false,
    scanRequested: false,
    pendingSelect: "",
    pendingCenter: -1,
    loadGeneration: 0,
    sentQueries: 0,
    answeredLoads: 0,
    staleAnswers: 0,
    settingRows: settingRows,
    note: function () {},
    flash: function (t) { flashes.push(String(t)); },
    setInfo: function (t) { infos.push(String(t)); root.infoText = String(t || ""); },
    writeSetting: function () {},
    stepEnum: function () {},
    stepSetting: function () {},
    runLibraryAction: function () {},
    showDetails: function () {},
    removeRow: function () {},
    moveRow: function () {},
    step: function () {},
    centerOn: function () {},
    gotoCurrent: function () {},
    currentIndex: function () { return -1; }
  };

  Object.defineProperty(root, "rows", {
    get: function () { return rowsValue; },
    set: function (v) {
      if (v !== null && typeof v === "object" && v.__binding === true) {
        rowsBound = true;
        rowsValue = v.fn();
        return;
      }
      rowsBound = false;
      rowsValue = v;
    }
  });
  Object.defineProperty(root, "rowsBoundToSettingRows", {
    get: function () { return rowsBound; }
  });

  let stackValue = [];
  const onStackChanged = new Function("root", STACK_HANDLER);
  Object.defineProperty(root, "stack", {
    get: function () { return stackValue; },
    set: function (v) {
      stackValue = v;
      onStackChanged(root);            // MODELLED: synchronous, as in QML
    }
  });
  Object.defineProperty(root, "frame", {
    get: function () { return stackValue.length > 0 ? stackValue[stackValue.length - 1] : null; }
  });
  Object.defineProperty(root, "frameMode", {
    get: function () { return root.frame ? String(root.frame.mode || "") : ""; }
  });
  Object.defineProperty(root, "frameTitle", {
    get: function () { return root.frame ? String(root.frame.title || "") : ""; }
  });
  // Panel.qml: readonly property bool up: !!host && host.connected === true
  Object.defineProperty(root, "up", {
    get: function () { return host.connected === true; }
  });

  const host = {
    connected: true,
    song: {},
    songFile: "",
    format: "%artist% - %title%",
    hoverCard: true,
    coverLook: "classic",
    elapsed: 0,
    query: function (kind, args, channel, cb) {
      queries.push({ kind: kind, args: args, channel: channel });
      if (cb) host.__pending = cb;
    },
    mutation: function (op, args) { mutations.push({ op: op, args: args }); },
    addUri: function (uri) { mutations.push({ op: "add", args: { uri: uri } }); },
    addAndPlay: function (uri) { mutations.push({ op: "addplay", args: { uri: uri } }); },
    basename: function (p) { return String(p).split("/").pop(); },
    formatTime: function (t) { return String(t); },
    previewLabel: function () { return ""; },
    showOsd: function () {},
    setSetting: function () {},
    updateDatabase: function () {},
    close: function () {},
    clearQueue: function () {},
    cropQueue: function () {},
    toggleTrack: function () {},
    toggleOption: function () {},
    nudgeVolume: function () {},
    bare: function () {},
    nextTrack: function () {},
    previousTrack: function () {}
  };
  root.host = host;

  const timers = {};
  ["promptDebounce", "promptFocusTimer", "pendingSelectGuard", "reloadTimer",
   "flashTimer", "skipTimer", "centerTimer"].forEach(function (id) {
    timers[id] = {
      id: id, running: false,
      restart: function () { timers[id].running = true; },
      stop: function () { timers[id].running = false; }
    };
  });

  const panel = BUILD(root, host, Qt, settingRows, timers, timers.promptDebounce,
                      timers.promptFocusTimer, timers.pendingSelectGuard,
                      timers.reloadTimer);
  Object.keys(panel).forEach(function (k) { root[k] = panel[k]; });

  // Record what the panel asks for, without changing what it does.
  const realSearch = root.applySearch;
  const realCategory = root.applyCategorySearch;
  root.applySearch = function (t) {
    calls.push("applySearch(" + t + ")");
    return realSearch.call(root, t);
  };
  root.applyCategorySearch = function (t) {
    calls.push("applyCategorySearch(" + t + ")");
    return realCategory.call(root, t);
  };

  // MODELLED (header note 3): the timer body is Panel.qml's, armed/cancelled by
  // the model.
  const timerHandlers = {
    promptDebounce: new Function("root", "promptDebounce", "promptFocusTimer",
                                 DEBOUNCE_HANDLER.text)
  };

  function event(key, text) {
    return {
      key: key, text: text, modifiers: 0, accepted: false
    };
  }

  // MODELLED (header note 7): the row delegate is asked the way the ListView asks
  // it -- one delegate per row, with `modelData` and `index`, its three bindings
  // taken verbatim from Panel.qml and re-evaluated on read like QML bindings are.
  const rowTypeExpr = new Function("root", "rowItem", "return (" + ROW_TYPE + ");");
  const isHeaderExpr = new Function("root", "rowItem", "return (" + ROW_IS_HEADER + ");");
  const selectedExpr = new Function("root", "rowItem", "index",
                                    "return (" + ROW_SELECTED + ");");

  function rowItemAt(modelData, index) {
    const rowItem = { modelData: modelData, index: index };
    Object.defineProperty(rowItem, "rowType", {
      get: function () { return rowTypeExpr(root, rowItem); }
    });
    Object.defineProperty(rowItem, "isHeader", {
      get: function () { return isHeaderExpr(root, rowItem); }
    });
    Object.defineProperty(rowItem, "selected", {
      get: function () { return selectedExpr(root, rowItem, index); }
    });
    return rowItem;
  }

  const SHAPE = { "/": "Slash", " ": "Space", "+": "Plus", "-": "Minus", "=": "Equal" };

  return {
    root: root, host: host, Qt: Qt, timers: timers, settingRows: settingRows,
    queries: queries, mutations: mutations, flashes: flashes, infos: infos,
    calls: calls,
    key: function (keyCode, text) {
      const e = event(keyCode, text === undefined ? "" : text);
      root.handleKey(e);
      return e;
    },
    press: function (ch) {
      const code = SHAPE[ch] !== undefined ? Qt["Key_" + SHAPE[ch]] : 0;
      return this.key(code, ch);
    },
    type: function (str) {
      for (let i = 0; i < str.length; i++) this.press(str[i]);
    },
    enter: function () { return this.key(Qt.Key_Return, ""); },
    escape: function () { return this.key(Qt.Key_Escape, ""); },
    fire: function (id) {
      const t = timers[id];
      if (!t || !t.running) return false;
      t.running = false;
      timerHandlers[id](root, timers.promptDebounce, timers.promptFocusTimer);
      return true;
    },
    answer: function (list, error) {
      const cb = host.__pending;
      host.__pending = null;
      if (!cb) throw new Error("nothing was asked");
      cb(list || [], error === undefined ? "" : error);
    },
    callsReset: function () { calls.length = 0; },
    rowItem: function (index) { return rowItemAt(root.rows[index], index); },
    marked: function (index) { return rowItemAt(root.rows[index], index).selected === true; },
    // Every row that wears the mark. In QML one per delegate; here all of them.
    markedRows: function () {
      const out = [];
      root.rows.forEach(function (row, i) {
        if (rowItemAt(row, i).selected === true) out.push(i);
      });
      return out;
    },
    rowsTitles: function () {
      return root.rows.map(function (r) { return root.rowTitle(r); });
    },
    frames: function () {
      return root.stack.map(function (f) {
        return String(f.mode || "") + (f.tag ? "/" + f.tag : "")
          + (f.search !== undefined ? "[search=" + f.search + "]" : "")
          + " filter=" + JSON.stringify(f.filter || []);
      });
    }
  };
}

// --------------------------------------------------------------- the cases
group("case 4: Enter before the 250 ms make the category search global");
{
  const P = makePanel();
  P.key(0, "3");                                   // the `3` key: the albums tab
  check("the albums tab is loaded", P.root.tab === "albums", P.root.tab);
  P.press("/");                                    // `/`: the scoped field
  check("`/` opens the category prompt", P.root.promptMode === "category", P.root.promptMode);
  P.type("iam");
  check("typing arms the 250 ms timer", P.timers.promptDebounce.running === true);
  P.callsReset();
  P.enter();                                       // Enter, well inside those 250 ms
  check("the field is closed", P.root.promptMode === "", JSON.stringify(P.root.promptMode));
  check("no global search ran", P.calls.filter(function (c) {
    return c.indexOf("applySearch") === 0; }).length === 0, P.calls.join(", "));
  check("the scoped search ran for the mode it was started in",
        P.calls.filter(function (c) { return c === "applyCategorySearch(iam)"; }).length === 1,
        P.calls.join(", "));
  check("the pending timer was dealt with", P.fire("promptDebounce") === false);
  check("the frame is a scoped list, not a global search frame",
        P.root.frameMode === "list" && P.root.frame.tag === "album"
          && P.root.frame.search === "iam",
        P.frames()[P.frames().length - 1]);

  // The same, one step further: the timer must never be re-judged against a mode
  // that changed in the meantime -- it is either run for its own mode or dropped.
  const Q = makePanel();
  Q.key(0, "3");
  Q.press("/");
  Q.type("iam");
  check("timer armed again", Q.timers.promptDebounce.running === true);
  Q.root.promptMode = "";        // MODELLED: some other path clears the mode
  Q.callsReset();
  const fired = Q.fire("promptDebounce");
  check("a stale armed timer is dropped instead of re-judged",
        fired === true && Q.calls.length === 0, Q.calls.join(", "));

  // Controls: the ordinary paths keep working.
  const R = makePanel();
  R.key(0, "3");
  R.press("/");
  R.type("iam");
  R.callsReset();
  R.fire("promptDebounce");      // 250 ms pass, nobody presses Enter
  check("waiting the 250 ms still runs the scoped search",
        R.calls.join(", ") === "applyCategorySearch(iam)"
          && R.root.frameMode === "list", R.calls.join(", "));

  const S = makePanel();
  S.key(0, "3");
  S.press("/");
  S.enter();                     // Enter with an empty scoped field
  check("Enter on an empty scoped field adds no frame",
        S.frames().length === 1 && S.calls.length === 0, S.frames().join(" | "));
}

group("case 5: a local filter must not overwrite the settings list");
{
  const LISTING = [
    { type: "directory", directory: "Rock" },
    { type: "file", file: "Rock/01.flac", artist: "Alice", album: "Rock" },
    { type: "file", file: "Jazz/02.mp3", artist: "Bob", album: "Jazz" }
  ];
  function onFilesTab() {
    const P = makePanel();
    P.key(0, "6");                       // the `6` key: the files tab
    P.answer(LISTING);                   // the bridge answers the lsinfo query
    return P;
  }

  const P = onFilesTab();
  check("the files tab is loaded with its list", P.root.rows.length === 3
        && P.root.frameMode === "files", P.rowsTitles().join(", "));
  P.press("/");
  check("`/` opens the local filter", P.root.promptMode === "filter", P.root.promptMode);
  P.type("flac");
  check("typing narrows the loaded list",
        P.root.filterText === "flac" && P.root.rows.length === 1,
        P.rowsTitles().join(", "));
  P.enter();
  check("Enter closes the field and keeps the filter",
        P.root.promptMode === "" && P.root.filterText === "flac", P.root.filterText);

  P.key(0, "9");                         // the `9` key: the settings tab
  check("the settings tab is loaded", P.root.frameMode === "settings", P.root.frameMode);
  check("its rows are the settings rows",
        P.rowsTitles().join(", ") === "In the bar, Show the card, In the player, Backdrop",
        P.rowsTitles().join(", "));
  check("rows are bound to settingRows, not replaced by the old list",
        P.root.rowsBoundToSettingRows === true, String(P.root.rowsBoundToSettingRows));
  check("the filter of the old view is gone",
        P.root.filterText === "", JSON.stringify(P.root.filterText));

  // The two halves of the fix, apart from each other: cleaning up a prompt may
  // not hand the view that is showing now the rows of the view before.
  const Q = makePanel();
  Q.key(0, "9");
  const before = Q.rowsTitles().join(", ");
  Q.root.filterText = "flac";            // MODELLED: a filter left over from files
  Q.root.closePrompt();
  check("a cleanup does not rebind the rows of the current view",
        Q.rowsTitles().join(", ") === before && Q.root.rowsBoundToSettingRows === true,
        Q.rowsTitles().join(", "));

  // Control: without a filter the settings tab always worked.
  const R = onFilesTab();
  R.key(0, "9");
  check("control: no filter, same result",
        R.root.frameMode === "settings" && R.root.rowsBoundToSettingRows === true,
        R.rowsTitles().join(", "));
}

group("case 6: a scoped search keeps the narrowing it was started in");
{
  const ALBUMS = [{ type: "value", value: "Kiss & Swallow" },
                  { type: "value", value: "The Alternative" }];
  function insideAnArtist() {
    const P = makePanel();
    P.key(0, "4");                          // the `4` key: the artists tab
    P.answer([{ type: "value", value: "IamX" }]);
    P.root.sel = 0;
    P.root.activate();                      // open the artist
    P.answer(ALBUMS);                       // the artist's albums
    return P;
  }

  const P = insideAnArtist();
  check("the artist's albums are the frame at hand",
        P.frames()[1] === "list/album filter=[[\"artist\",\"IamX\"]]", P.frames().join(" | "));
  P.press("/");
  check("`/` opens the scoped field on top of it", P.root.promptMode === "category",
        P.root.promptMode);
  P.type("grea");
  P.fire("promptDebounce");                 // 250 ms: the delayed search runs
  const top = P.root.frame;
  check("the search frame keeps the artist",
        JSON.stringify(top.filter) === "[[\"artist\",\"IamX\"]]", JSON.stringify(top.filter));
  check("it is still a scoped search in the album category",
        top.mode === "list" && top.tag === "album" && top.search === "grea",
        JSON.stringify({ mode: top.mode, tag: top.tag, search: top.search }));

  P.queries.length = 0;
  P.root.loadFrame();
  const asked = P.queries[0];
  check("the query carries the narrowing and the term together",
        asked.kind === "list" && JSON.stringify(asked.args.filter) === "[[\"artist\",\"IamX\"]]"
          && asked.args.search === "grea", JSON.stringify(asked.args));

  // One more keystroke replaces the frame in place; the narrowing has to survive
  // that as well.
  P.type("t");
  P.fire("promptDebounce");
  check("typing on keeps it",
        JSON.stringify(P.root.frame.filter) === "[[\"artist\",\"IamX\"]]"
          && P.root.frame.search === "great", JSON.stringify(P.root.frame.filter));

  P.mutations.length = 0;
  P.root.addAll();
  check("appending the rows stays inside the artist",
        P.mutations.length === 1 && P.mutations[0].op === "findadd"
          && JSON.stringify(P.mutations[0].args.filter) === "[[\"artist\",\"IamX\"]]",
        JSON.stringify(P.mutations[0]));

  // Control: from the root Albums tab there is no narrowing, and the term alone is
  // the whole scope -- that is what searchadd with a tag is for.
  const Q = makePanel();
  Q.key(0, "3");
  Q.press("/");
  Q.type("grea");
  Q.fire("promptDebounce");
  check("control: the root category has no filter to carry",
        JSON.stringify(Q.root.frame.filter) === "[]", JSON.stringify(Q.root.frame.filter));
  Q.mutations.length = 0;
  Q.root.addAll();
  check("control: appending there is still a scoped search",
        Q.mutations[0] && Q.mutations[0].op === "searchadd"
          && Q.mutations[0].args.term === "grea" && Q.mutations[0].args.tag === "album",
        JSON.stringify(Q.mutations[0]));

  // Control: a genre opened from the Genres tab is the same mechanism.
  const R = makePanel();
  R.key(0, "5");
  R.answer([{ type: "value", value: "Ambient" }]);
  R.root.sel = 0;
  R.root.activate();
  R.answer([{ type: "value", value: "Selected Works" }]);
  R.press("/");
  R.type("work");
  R.fire("promptDebounce");
  check("control: a genre is carried the same way",
        JSON.stringify(R.root.frame.filter) === "[[\"genre\",\"Ambient\"]]"
          && R.root.frame.search === "work", JSON.stringify(R.root.frame.filter));
}

group("case 7: a compilation album opens with all of its tracks");
{
  // MODELLED: how a filter selects songs. The bridge builds `(tag == 'value')`
  // clauses from these pairs (bin/mpd-bridge:1236) or passes `tag value` on MPD
  // < 0.21 (1240-1242); the matcher below is the reading of that, not its run.
  function matches(filter, song) {
    var out = true;
    (filter || []).forEach(function (pair) {
      if (String(song[pair[0]] || "") !== String(pair[1])) out = false;
    });
    return out;
  }
  function setOf(filter, songs) {
    return songs.filter(function (s) { return matches(filter, s); })
      .map(function (s) { return s.file; }).join(", ");
  }

  const SONGS = [
    { type: "file", file: "c/01.mp3", artist: "Alice", album: "Best Of", title: "One" },
    { type: "file", file: "c/02.mp3", artist: "Bob", album: "Best Of", title: "Two" },
    { type: "file", file: "c/03.mp3", artist: "Carol", album: "Best Of", title: "Three" },
    { type: "file", file: "s/01.mp3", artist: "Alice", album: "Solo", title: "Only" }
  ];

  function grouped(P) {
    P.root.tab = "search";
    P.root.stack = [{ mode: "search", term: "bo", title: "Search: bo" }];
    P.root.rows = P.root.groupHits(SONGS);
    return P.root.rows;
  }

  const P = makePanel();
  const ROWS = grouped(P);
  const bestOf = ROWS.filter(function (r) { return r.kind === "album" && r.value === "Best Of"; })[0];
  const solo = ROWS.filter(function (r) { return r.kind === "album" && r.value === "Solo"; })[0];
  check("the compilation row names no single artist", bestOf.artist === "",
        JSON.stringify(bestOf));
  check("the single-artist row keeps its artist", solo.artist === "Alice", JSON.stringify(solo));

  P.root.sel = ROWS.indexOf(bestOf);
  P.root.activate();
  const opened = P.root.frame;
  check("opening the compilation reaches every track of the album",
        setOf(opened.filter, SONGS) === "c/01.mp3, c/02.mp3, c/03.mp3",
        JSON.stringify(opened.filter) + " -> " + setOf(opened.filter, SONGS));

  P.mutations.length = 0;
  P.root.addOne(bestOf);
  const appended = P.mutations[0].args.filter;
  check("opening and appending the same row agree",
        setOf(appended, SONGS) === setOf(opened.filter, SONGS),
        JSON.stringify(appended) + " -> " + setOf(appended, SONGS));

  // The single-artist album has to behave exactly as before: in through the
  // artist (that is where the other albums of that artist sit), and on to the
  // album's tracks.
  const Q = makePanel();
  const ROWS2 = grouped(Q);
  const soloRow = ROWS2.filter(function (r) { return r.kind === "album" && r.value === "Solo"; })[0];
  Q.root.sel = ROWS2.indexOf(soloRow);
  Q.root.activate();
  check("a single-artist album still opens through its artist",
        Q.frames().slice(1).join(" | ")
          === "list/album filter=[[\"artist\",\"Alice\"]] | find filter=[[\"artist\",\"Alice\"],[\"album\",\"Solo\"]]",
        Q.frames().slice(1).join(" | "));
  check("and reaches exactly that album's tracks",
        setOf(Q.root.frame.filter, SONGS) === "s/01.mp3", setOf(Q.root.frame.filter, SONGS));
  Q.mutations.length = 0;
  Q.root.addOne(soloRow);
  check("appending it reaches the same tracks",
        setOf(Q.mutations[0].args.filter, SONGS) === "s/01.mp3",
        setOf(Q.mutations[0].args.filter, SONGS));

  // Control: an album whose tracks carry no artist tag at all keeps working.
  const N = makePanel();
  const untagged = [{ type: "file", file: "u/01.mp3", album: "Untagged" },
                    { type: "file", file: "u/02.mp3", album: "Untagged" }];
  const row = N.root.groupHits(untagged).filter(function (r) { return r.kind === "album"; })[0];
  N.root.tab = "search";
  N.root.stack = [{ mode: "search", term: "untag", title: "Search: untag" }];
  N.root.rows = [row];
  N.root.sel = 0;
  N.root.activate();
  check("control: an album without any artist tag is unchanged",
        JSON.stringify(N.root.frame.filter) === "[[\"album\",\"Untagged\"]]",
        JSON.stringify(N.root.frame.filter));
}

group("case 8: the mark only shows while the list really has the keys");
{
  // The user's report: `/`, then "queen" -- the hits arrive and the first one is
  // marked although the keys are still in the field, where `+`, `a` and `A` are
  // letters. The mark may only be drawn for the state the keys actually follow:
  // while a prompt is up the field owns them (handleKey), so no row is marked --
  // whatever `sel` happens to be (MODEL: the row delegate's `selected` binding is
  // Panel.qml's, asked per row through rowItemAt).
  const HITS = [
    { type: "file", file: "q/01.mp3", artist: "Queen", album: "A Night at the Opera",
      title: "Bohemian Rhapsody" },
    { type: "file", file: "q/02.mp3", artist: "Queen", album: "News of the World",
      title: "We Will Rock You" }
  ];

  // `/` is not the only way in: `2` opens the search tab with its field up.
  function typing() {
    const P = makePanel();
    P.key(0, "2");                   // the `2` key: the search tab
    P.type("queen");
    P.fire("promptDebounce");        // 250 ms: the hits are queried
    P.answer(HITS);                  // and they arrive while the field is up
    return P;
  }

  const P = typing();
  check("the field is up with the term in it",
        P.root.promptMode === "search" && P.root.promptText === "queen",
        P.root.promptMode + " / " + P.root.promptText);
  check("the hits are on screen and sel sits on the first of them",
        P.root.rows.length === 8 && P.root.sel === P.root.firstSelectable(0),
        P.rowsTitles().join(", ") + "  sel=" + P.root.sel);

  // (a) prompt open, term typed, sel = 0-ish: no row wears the mark.
  check("(a) no row is marked while the field owns the keys",
        P.markedRows().length === 0, "marked: " + JSON.stringify(P.markedRows()));
  check("(a) not even the row sel points at", P.marked(P.root.sel) === false,
        "sel=" + P.root.sel + " -> marked=" + P.marked(P.root.sel));

  // The keys really are in the field: `+` lands in the term instead of acting.
  const F = typing();
  F.mutations.length = 0;
  F.press("+");
  check("control: in the field `+` is text, not an action",
        F.root.promptText === "queen+" && F.mutations.length === 0,
        F.root.promptText + " / " + JSON.stringify(F.mutations));

  // (b) ↓ hands the keys to the list (Panel.qml's own jump out of the field):
  // now, and only now, the mark appears -- on the first hit.
  P.key(P.Qt.Key_Down, "");
  check("↓ took the keys out of the field", P.root.promptMode === "",
        JSON.stringify(P.root.promptMode));
  P.answer(HITS);
  check("(b) the first hit wears the mark once the list has the keys",
        P.markedRows().length === 1 && P.marked(P.root.sel) === true
          && P.root.sel === P.root.firstSelectable(0),
        "marked: " + JSON.stringify(P.markedRows()) + "  sel=" + P.root.sel + "  ("
          + P.rowsTitles()[P.root.sel] + ")");
  // The action on that row is the one it always was -- the fix is the drawing.
  P.mutations.length = 0;
  P.press("a");
  check("control: `a` appends what the marked row stands for",
        P.mutations.length === 1 && P.mutations[0].op === "findadd"
          && JSON.stringify(P.mutations[0].args.filter) === "[[\"artist\",\"Queen\"]]",
        JSON.stringify(P.mutations[0]));

  // (c) the field comes back (`/`, with the term still in it) -> the mark goes
  // again. The check runs after the query that `/` starts has answered, so it is
  // the reload landing under an open field that is being judged, not an empty list.
  P.press("/");
  check("`/` brings the field back with the term", P.root.promptMode === "search"
        && P.root.promptText === "queen", P.root.promptMode + " / " + P.root.promptText);
  P.answer(HITS);
  check("(c) no row is marked again while the field is back",
        P.markedRows().length === 0,
        "marked: " + JSON.stringify(P.markedRows()) + "  sel=" + P.root.sel);

  // The other direction of the same rule: esc in the field closes it, the keys go
  // to the list, and the mark is drawn again.
  P.escape();
  check("control: esc closes the field and the mark is back",
        P.root.promptMode === "" && P.markedRows().length === 1
          && P.marked(P.root.sel) === true,
        "marked: " + JSON.stringify(P.markedRows()));

  // The scoped search (Alben/Kuenstler/Genres) obeys the same rule.
  const Q = makePanel();
  Q.key(0, "3");                     // the albums tab
  Q.answer([{ type: "value", value: "Kiss & Swallow" }, { type: "value", value: "The Alternative" }]);
  Q.press("/");
  Q.type("kiss");
  Q.fire("promptDebounce");
  Q.answer([{ type: "value", value: "Kiss & Swallow" }]);
  check("control: the scoped field is open on a narrowed list",
        Q.root.promptMode === "category" && Q.root.rows.length === 1
          && Q.root.sel === 0, Q.rowsTitles().join(", "));
  check("the scoped list is unmarked while the field is up",
        Q.markedRows().length === 0, "marked: " + JSON.stringify(Q.markedRows()));
  Q.key(Q.Qt.Key_Down, "");
  Q.answer([{ type: "value", value: "Kiss & Swallow" }]);
  check("and marked again after ↓",
        Q.root.promptMode === "" && Q.markedRows().length === 1,
        "marked: " + JSON.stringify(Q.markedRows()));

  // The local filter of Dateien/Playlists is the third kind of field.
  const R = makePanel();
  R.key(0, "6");                     // the files tab
  R.answer([{ type: "directory", directory: "Rock" },
            { type: "file", file: "Rock/01.flac", artist: "Alice", album: "Rock" },
            { type: "file", file: "Jazz/02.mp3", artist: "Bob", album: "Jazz" }]);
  R.press("/");
  R.type("flac");
  check("control: the local filter narrowed the loaded list",
        R.root.promptMode === "filter" && R.root.rows.length === 1,
        R.rowsTitles().join(", "));
  check("the filtered list is unmarked while the field is up",
        R.markedRows().length === 0, "marked: " + JSON.stringify(R.markedRows()));
  R.key(R.Qt.Key_Down, "");
  check("and marked again after ↓",
        R.root.promptMode === "" && R.markedRows().length === 1 && R.marked(R.root.sel),
        "marked: " + JSON.stringify(R.markedRows()));

  // Control: a tab without a prompt is untouched -- there the mark is the
  // selection, and it is always legitimate.
  const S = makePanel();
  S.key(0, "1");                     // the queue tab
  S.answer([{ type: "file", file: "a/01.mp3", id: 7, title: "One" },
            { type: "file", file: "a/02.mp3", id: 8, title: "Two" }]);
  check("control: with no prompt the loaded list keeps its mark",
        S.root.promptMode === "" && S.root.sel === 0 && S.markedRows().join(",") === "0",
        "marked: " + JSON.stringify(S.markedRows()));
}

group("case 9: the ninth tab is reachable from an open, empty search field");
{
  // The hint promises "1-9 switch tabs" and the settings hint says "9 picks the
  // tab" (both read from Panel.qml), and tabForNumber maps the nine numbers --
  // but the number shortcut once stopped at 7. With a field open and empty,
  // `9` was typed into it: the settings tab could not be reached from the search
  // tab at all, and the field showed a term nobody typed.
  const P = makePanel();
  P.key(0, "2");                       // the `2` key: the search tab, field up
  check("the search field is open and empty",
        P.root.promptMode === "search" && P.root.promptText === ""
          && P.root.promptExplicit === false,
        P.root.promptMode + " / " + JSON.stringify(P.root.promptText)
          + " explicit=" + String(P.root.promptExplicit));
  P.key(0, "9");
  check("`9` switches to the settings tab",
        P.root.tab === "settings" && P.root.frameMode === "settings",
        "tab=" + P.root.tab + " frame=" + P.root.frameMode);
  check("... and the field did not take the digit", P.root.promptText === "",
        JSON.stringify(P.root.promptText));

  // tabForNumber and the shortcut have to agree on the range -- one of them
  // knowing eight tabs while the other stops at seven is exactly the bug.
  check("every number tabForNumber knows is a tab the key opens",
        [1, 2, 3, 4, 5, 6, 7, 8, 9].every(function (n) {
          const Q = makePanel();
          Q.key(0, String(n));
          return Q.root.tab === Q.root.tabForNumber(String(n));
        }), [1, 2, 3, 4, 5, 6, 7, 8, 9].map(function (n) {
          const Q = makePanel();
          Q.key(0, String(n));
          return n + ":" + Q.root.tab;
        }).join(", "));

  // The other half of the rule is untouched: `/` says "I really do want to type",
  // and in that field a digit stays a digit -- the 9 included.
  const Q = makePanel();
  Q.key(0, "2");
  Q.press("/");                        // the explicit gesture
  check("`/` marks the field explicit",
        Q.root.promptExplicit === true && Q.root.promptText === "",
        String(Q.root.promptExplicit));
  Q.key(0, "9");
  check("with an explicit field `9` is text, not a tab switch",
        Q.root.promptText === "9" && Q.root.tab === "search",
        JSON.stringify(Q.root.promptText) + " tab=" + Q.root.tab);

  // Control: with no field open the `9` always worked, and still does.
  const R = makePanel();
  R.key(0, "9");
  check("control: `9` with no field open picks the settings tab",
        R.root.tab === "settings" && R.root.frameMode === "settings", R.root.tab);
}

// The station directory arrives with its own functions. Against a source that
// does not have them -- the unfixed revision -- the five cases below report what
// is missing and stand down instead of dying on the first call, so the run still
// names the lines that fail. That report is the counter-proof: it shows the
// cases test the change, not the harness.
const RADIO_FNS = ["isStream", "radioFrame", "radioRowsFor", "radioCountries",
                   "radioGenres", "dedupeStations", "stationTitle", "stationSub",
                   "applyRadioSearch", "stationDetail", "streamPlaying",
                   "openRadioLevel"];
const RADIO_MISSING = (function () {
  const probe = makePanel();
  return RADIO_FNS.filter(function (n) { return typeof probe.root[n] !== "function" });
})();
function radioCase(title, run) {
  if (RADIO_MISSING.length > 0) {
    check(title + " -- the radio functions are in this source", false,
      "missing: " + RADIO_MISSING.join(", "));
    return;
  }
  run();
}

// The bug the radio cases did not see: the list draws a row by its `type` (the
// delegate's `rowType`, and rowTitle/rowSub/rowRight all switch on it), and the
// station directory's answer carries no such field. Handed to the list as it
// arrived -- which is what the loading branch did -- every station became a
// blank row while the count read "50 stations" over it. So the guard is not
// "dedupeStations returns something" but "every row a radio query puts into the
// list is typed", and it is run on every way a station can land in `rows`: the
// browse lists, a country, a genre and the free text search.
function untypedRows(rows) {
  return (rows || []).filter(function (r) {
    return String((r && r.type) || "") === "";
  });
}
// What a person saw: rows the list holds but draws with nothing in them.
function blankRows(P, rows) {
  return (rows || []).filter(function (r) {
    return P.root.rowTitle(r) === "" && P.root.rowSub(r) === ""
      && P.root.rowRight(r) === "";
  });
}
function typesOf(rows) {
  return (rows || []).map(function (r) { return String((r && r.type) || "(untyped)") });
}

function case10RadioTab() {
  // The radio tab is the eighth tab: `8` picks it, tabForNumber knows it, and
  // the header chips carry it -- the keyboard and the mouse have to agree on the
  // range, which is what case 9 already had to fix once.
  const P = makePanel();
  check("tabForNumber knows nine tabs, the eighth radio and the ninth settings",
        P.root.tabForNumber("8") === "radio" && P.root.tabForNumber("9") === "settings",
        "8 -> " + P.root.tabForNumber("8") + ", 9 -> " + P.root.tabForNumber("9"));

  P.key(0, "8");
  check("`8` opens the radio tab", P.root.tab === "radio", P.root.tab);
  check("the browse root is up", P.root.frameMode === "radio", P.root.frameMode);
  const titles = P.rowsTitles();
  check("it offers a country list, a genre list and a station search",
        titles.indexOf("By country") >= 0 && titles.indexOf("By genre") >= 0
          && titles.indexOf("Search stations") >= 0, titles.join(", "));
  check("a browse list asks the server nothing", P.queries.length === 0,
        JSON.stringify(P.queries));
  // And every row of it is typed: the list draws a row by its `type`, so an
  // untyped browse row would be a blank line here just as the stations were.
  check("every row of the browse root carries a type",
        P.root.rows.length === 3 && untypedRows(P.root.rows).length === 0,
        typesOf(P.root.rows).join(", "));

  check("every number tabForNumber knows is a tab the key opens",
        [1, 2, 3, 4, 5, 6, 7, 8, 9].every(function (n) {
          const Q = makePanel();
          Q.key(0, String(n));
          return Q.root.tab === Q.root.tabForNumber(String(n));
        }), [1, 2, 3, 4, 5, 6, 7, 8, 9].map(function (n) {
          const Q = makePanel();
          Q.key(0, String(n));
          return n + ":" + Q.root.tab;
        }).join(", "));

  // The chips are the mouse way in; a tab the keyboard has and the header does
  // not is a tab half the users cannot reach.
  check("the header chips carry the eighth tab (the mouse way in)",
        /\{ key: "radio", label: "8" \}/.test(SRC), "chip row in Panel.qml");

  // Control: with an empty search field the digit switches tabs instead of being
  // typed into it -- the rule case 9 established, now with the eighth digit.
  const Q = makePanel();
  Q.key(0, "2");
  Q.key(0, "8");
  check("control: `8` from an open, empty search field switches tabs",
        Q.root.tab === "radio" && Q.root.promptText === "",
        Q.root.tab + " / " + JSON.stringify(Q.root.promptText));
}
group("case 10: the eighth tab is the station directory");
radioCase("the eighth tab is the station directory", case10RadioTab);

// The swap, nailed down: the eighth tab is the station directory, the ninth the
// settings list. Eight and nine are the only two digits that ever moved, so the
// check names them pair by pair -- an edit that turns the two back, or renumbers
// one and not the other, fails here instead of quietly in the panel.
group("the tab digits: 8 is the station directory, 9 the settings");
{
  const P = makePanel();
  check("tabForNumber maps 8 to radio and 9 to settings",
        P.root.tabForNumber("8") === "radio" && P.root.tabForNumber("9") === "settings",
        "8 -> " + P.root.tabForNumber("8") + ", 9 -> " + P.root.tabForNumber("9"));

  const EIGHT = makePanel();
  EIGHT.key(0, "8");
  check("`8` opens the station directory",
        EIGHT.root.tab === "radio" && EIGHT.root.frameMode === "radio",
        "tab=" + EIGHT.root.tab + " frame=" + EIGHT.root.frameMode);

  const NINE = makePanel();
  NINE.key(0, "9");
  check("`9` opens the settings",
        NINE.root.tab === "settings" && NINE.root.frameMode === "settings",
        "tab=" + NINE.root.tab + " frame=" + NINE.root.frameMode);

  // The key code, not just the text: a numpad or a layout that hands the digit
  // over as a code has to land on the same tab.
  const CODE8 = makePanel();
  CODE8.key(CODE8.Qt.Key_8, "");
  check("the key code 8 opens the station directory too",
        CODE8.root.tab === "radio", CODE8.root.tab);

  const CODE9 = makePanel();
  CODE9.key(CODE9.Qt.Key_9, "");
  check("the key code 9 opens the settings too",
        CODE9.root.tab === "settings", CODE9.root.tab);

  // The header chips are the mouse way in. They carry the two digits in the same
  // order the keys do: 8 (radio) before 9 (settings), right after the library.
  const chip8 = SRC.indexOf('{ key: "radio", label: "8" }');
  const chip9 = SRC.indexOf('{ key: "settings", label: "9" }');
  check("the chips carry radio=8 and settings=9, radio first",
        chip8 >= 0 && chip9 >= 0 && chip8 < chip9,
        "radio chip at " + chip8 + ", settings chip at " + chip9 + " (Panel.qml)");
}

function case11DedupeStations() {
  // The measured case: the directory returns the same station twice, once per
  // relay URL. Two rows that play the same programme are noise, not choice.
  const STATIONS = [
    { name: "SWISS GROOVE", country: "Switzerland", countrycode: "CH",
      url_resolved: "http://relay1.example/stream", codec: "MP3", bitrate: 128,
      votes: 341, lastcheckok: 1, tags: "funk,soul" },
    { name: "SWISS GROOVE", country: "Switzerland", countrycode: "CH",
      url_resolved: "http://relay2.example/stream", codec: "MP3", bitrate: 320,
      votes: 341, lastcheckok: 1, tags: "funk,soul" },
    { name: "Jazz Radio", country: "France", countrycode: "FR",
      url_resolved: "http://jazz.example/live", codec: "AAC", bitrate: 192,
      votes: 900, lastcheckok: 1, tags: "jazz" },
    { name: "groove salad", country: "The United States Of America", countrycode: "US",
      url_resolved: "http://gs.example/aac", codec: "AAC", bitrate: 128,
      votes: 5000, lastcheckok: 1, tags: "ambient" },
    { name: "Groove Salad", country: "The United States Of America", countrycode: "US",
      url_resolved: "http://gs.example/relay2", codec: "AAC", bitrate: 64,
      votes: 3, lastcheckok: 1, tags: "ambient" }
  ];
  const P = makePanel();
  const out = P.root.dedupeStations(STATIONS);

  check("the two Swiss Groove relays are one row",
        out.filter(function (r) { return /swiss groove/i.test(r.name) }).length === 1,
        out.map(function (r) { return r.name }).join(", "));
  check("... and the two Groove Salad spellings are one row as well",
        out.filter(function (r) { return /groove salad/i.test(r.name) }).length === 1,
        out.map(function (r) { return r.name }).join(", "));
  check("five entries become three stations", out.length === 3,
        out.map(function (r) { return r.name }).join(", "));

  const gs = out.filter(function (r) { return /groove salad/i.test(r.name) })[0];
  check("the surviving row is the one with the votes",
        gs.votes === 5000 && gs.url_resolved === "http://gs.example/aac",
        JSON.stringify(gs));
  const single = out.filter(function (r) { return /swiss groove/i.test(r.name) })[0];
  check("the alternatives are counted, not listed", single.streams === 2,
        "swiss groove streams=" + single.streams);
  check("a station the directory lists once says nothing about alternatives",
        out.filter(function (r) { return /jazz radio/i.test(r.name) })[0].streams === 1,
        "jazz radio streams="
          + out.filter(function (r) { return /jazz radio/i.test(r.name) })[0].streams);
  check("every surviving row is playable",
        out.every(function (r) { return String(r.url_resolved).indexOf("http") === 0 }),
        out.map(function (r) { return r.url_resolved }).join(", "));

  // Two stations without a name are not the same station.
  const nameless = [
    { name: "", country: "Germany", url_resolved: "http://a.example/1", votes: 1 },
    { name: "", country: "Germany", url_resolved: "http://b.example/2", votes: 2 }
  ];
  check("two stations without a name stay two rows",
        P.root.dedupeStations(nameless).length === 2,
        P.root.dedupeStations(nameless).length + " row(s)");
  check("an empty answer stays empty", P.root.dedupeStations([]).length === 0,
        String(P.root.dedupeStations([]).length));

  // ... and what it hands over are rows the list can draw. This is the class of
  // bug case 11 could not see before: it checked the merge, not the shape. The
  // directory's answer has no `type`, so rows that came straight out of it were
  // drawn blank under a correct count (the reported "50 stations", empty list).
  check("every row it returns is a typed station row, not the raw answer",
        untypedRows(out).length === 0, typesOf(out).join(", "));
  check("... and each one is drawn with the station in it, not blank",
        blankRows(P, out).length === 0,
        out.map(function (r) { return JSON.stringify(P.root.rowTitle(r)) }).join(", "));
  check("a nameless station's row is typed too",
        untypedRows(P.root.dedupeStations(nameless)).length === 0,
        typesOf(P.root.dedupeStations(nameless)).join(", "));
}
group("case 11: one station, however many relays the directory lists");
radioCase("one station, however many relays the directory lists", case11DedupeStations);

function case12BrowseDirectory() {
  const STATIONS = [
    { name: "Deutschlandfunk", country: "Germany", countrycode: "DE",
      url_resolved: "http://dlf.example/live", codec: "MP3", bitrate: 128,
      votes: 700, lastcheckok: 1, tags: "news" },
    { name: "laut.fm lofi", country: "Germany", countrycode: "DE",
      url_resolved: "http://lofi.example/stream", codec: "MP3", bitrate: 128,
      votes: 5100, lastcheckok: 1, tags: "lofi" }
  ];

  // `8` -> "By country" -> Germany -> its stations. The same browser as the
  // library: enter goes in, h comes back out.
  const P = makePanel();
  P.key(0, "8");
  P.root.sel = P.rowsTitles().indexOf("By country");
  P.root.activate();
  check("`By country` opens a country list", P.root.frameMode === "radioCountries",
        P.root.frameMode);
  check("the country rows carry the two-letter code the search needs",
        P.root.rows.length > 0 && P.root.rows.every(function (r) {
          return String(r.code || "").length === 2;
        }), JSON.stringify(P.root.rows.slice(0, 3)));
  check("... and every country row is typed (the list draws by type)",
        untypedRows(P.root.rows).length === 0,
        typesOf(P.root.rows.slice(0, 3)).join(", ") + " ... "
          + P.root.rows.length + " rows");
  check("a country row shows the country, not the code",
        P.root.rowTitle(P.root.rows[0]) === "Argentina"
          && P.root.rowTitle(P.root.rows[0]) !== P.root.rows[0].code,
        P.root.rowTitle(P.root.rows[0]));

  let de = -1;
  P.root.rows.forEach(function (r, i) { if (r.code === "DE") de = i; });
  check("Germany is in the list", de >= 0, "index " + de);
  P.root.sel = de;
  P.root.activate();
  check("picking one opens its stations", P.root.frameMode === "radioStations",
        P.root.frameMode);
  const asked = P.queries[P.queries.length - 1];
  check("the question is a radio_search with the country and no text",
        asked.kind === "radio_search" && asked.channel === "radio"
          && asked.args.country === "DE" && asked.args.search === ""
          && asked.args.tag === "",
        JSON.stringify(asked));

  P.answer(STATIONS);
  check("the answer becomes the station list", P.root.rows.length === 2,
        P.rowsTitles().join(", "));
  check("the frame says how many stations it found", /2 stations/.test(P.root.infoText),
        P.root.infoText);
  // The count and the list have to be the same story: the reported bug was a
  // correct "50 stations" over rows the list could not draw. `rows` and
  // `allRows` are the two lists the delegate draws from.
  check("every station row the country answer put in the list is typed",
        untypedRows(P.root.rows).length === 0 && untypedRows(P.root.allRows).length === 0,
        typesOf(P.root.rows).join(", "));
  check("... so the list shows the stations, not blank rows",
        blankRows(P, P.root.rows).length === 0
          && P.rowsTitles().join(", ") === "Deutschlandfunk, laut.fm lofi",
        P.root.rows.map(function (r) {
          return JSON.stringify(P.root.rowTitle(r)) + " / "
            + JSON.stringify(P.root.rowSub(r));
        }).join("   "));
  P.press("h");
  check("h goes back to the countries", P.root.frameMode === "radioCountries",
        P.root.frameMode);

  // The genre path, from the same root.
  const Q = makePanel();
  Q.key(0, "8");
  Q.root.sel = Q.rowsTitles().indexOf("By genre");
  Q.root.activate();
  check("`By genre` opens a genre list", Q.root.frameMode === "radioGenres",
        Q.root.frameMode);
  const jazz = Q.rowsTitles().indexOf("jazz");
  check("jazz is in the genre list", jazz >= 0, Q.rowsTitles().slice(0, 8).join(", "));
  Q.root.sel = jazz;
  Q.root.activate();
  const genreAsk = Q.queries[Q.queries.length - 1];
  check("a genre narrows the same query by tag",
        genreAsk.kind === "radio_search" && genreAsk.args.tag === "jazz",
        JSON.stringify(genreAsk.args));
  // The genre's stations are the same path and must come out as the same rows.
  Q.answer(STATIONS);
  check("the genre's stations land as typed rows as well",
        Q.root.rows.length === 2 && untypedRows(Q.root.rows).length === 0
          && Q.rowsTitles().join(", ") === "Deutschlandfunk, laut.fm lofi",
        typesOf(Q.root.rows).join(", ") + " | " + Q.rowsTitles().join(", "));

  // The free text search: `/` in the radio tab is a station search, and it runs
  // while typing like the other two fields.
  const R = makePanel();
  R.key(0, "8");
  R.press("/");
  check("`/` opens a station search field", R.root.promptMode === "radio",
        R.root.promptMode);
  R.type("laut.fm");
  check("typing arms the delayed search", R.timers.promptDebounce.running === true);
  R.fire("promptDebounce");
  const textAsk = R.queries[R.queries.length - 1];
  check("the term goes out as the search text",
        textAsk.kind === "radio_search" && textAsk.args.search === "laut.fm",
        JSON.stringify(textAsk.args));
  R.answer([STATIONS[1]]);
  check("the hits land in a station list under the browse root",
        R.root.frameMode === "radioStations" && R.root.rows.length === 1
          && R.frames().length === 2, R.frames().join(" | "));
  // The free text search is the third way into the directory and the third way a
  // station reaches the list -- the same guard applies to it.
  check("a search hit is a typed station row too",
        untypedRows(R.root.rows).length === 0
          && R.root.rowTitle(R.root.rows[0]) === "laut.fm lofi",
        typesOf(R.root.rows).join(", ") + " | "
          + JSON.stringify(R.root.rowTitle(R.root.rows[0])));
  check("a station search asks no MPD question",
        R.queries.every(function (q) { return q.kind === "radio_search"; }),
        JSON.stringify(R.queries.map(function (q) { return q.kind; })));

  // `+` on a browse row means what `+` means everywhere -- take this row -- and
  // on a country or a genre that is the level behind it, not a queue full of live
  // streams. The button is not a dead glyph there.
  const T = makePanel();
  T.key(0, "8");
  T.root.sel = T.rowsTitles().indexOf("By genre");
  T.root.addRow();
  check("`+` on a browse row opens the level instead of filling the queue",
        T.root.frameMode === "radioGenres" && T.mutations.length === 0,
        T.root.frameMode + " mutations=" + JSON.stringify(T.mutations));

  // Browsing and searching never touch the queue -- nothing plays by itself.
  check("no station was appended or played while browsing",
        P.mutations.length === 0 && Q.mutations.length === 0 && R.mutations.length === 0,
        JSON.stringify(P.mutations.concat(Q.mutations, R.mutations)));

  // The directory is not MPD: the list is readable with the player down, and the
  // tab does not claim otherwise.
  const S = makePanel();
  S.host.connected = false;
  S.key(0, "8");
  S.root.sel = S.rowsTitles().indexOf("By country");
  S.root.activate();
  S.root.sel = S.root.rows.map(function (r) { return r.code }).indexOf("DE");
  S.root.activate();
  check("a station list is readable while MPD is down",
        S.root.frameMode === "radioStations"
          && S.queries[S.queries.length - 1].kind === "radio_search",
        S.root.frameMode);
  S.answer(STATIONS);
  check("... and it shows the stations it got",
        S.root.rows.length === 2 && !/no connection/.test(S.root.infoText),
        S.root.infoText);
}
group("case 12: browsing the directory, level by level");
radioCase("browsing the directory, level by level", case12BrowseDirectory);

function case13StationRow() {
  const STATION = { type: "radioStation", name: "Groove Salad [SomaFM]",
                    url_resolved: "https://ice5.somafm.com/groovesalad-128-aac",
                    url: "https://ice5.somafm.com/groovesalad-128-aac",
                    codec: "AAC", bitrate: 128, country: "The United States Of America",
                    countrycode: "US", votes: 5000, streams: 2, tags: "ambient" };
  const P = makePanel();
  P.root.tab = "radio";
  P.root.stack = [{ mode: "radioStations", title: "Radio" }];
  P.root.rows = [STATION];
  P.root.sel = 0;

  check("the row is the station name", P.root.rowTitle(STATION) === "Groove Salad [SomaFM]",
        P.root.rowTitle(STATION));
  check("the URL is nowhere in it",
        P.root.rowTitle(STATION).indexOf("http") < 0
          && P.root.rowSub(STATION).indexOf("http") < 0,
        P.root.rowTitle(STATION) + " | " + P.root.rowSub(STATION));
  check("the second line carries bitrate, codec, country and the relay count",
        P.root.rowSub(STATION) === "128 kbps  ·  AAC  ·  The United States Of America  ·  2 streams",
        P.root.rowSub(STATION));
  check("the right column names what the row has instead",
        P.root.rowRight(STATION) === "5000 votes", P.root.rowRight(STATION));

  // `a` appends the stream URL -- one `add`, and the queue keeps playing.
  P.mutations.length = 0;
  P.root.addRow();
  check("`a` appends the stream URL",
        P.mutations.length === 1 && P.mutations[0].op === "add"
          && P.mutations[0].args.uri === STATION.url_resolved,
        JSON.stringify(P.mutations[0]));
  check("... and appending does not touch what is playing",
        P.mutations.filter(function (m) { return m.op === "playid" || m.op === "addplay" }).length === 0,
        JSON.stringify(P.mutations));

  // Enter on the row plays it: `add` and then `play`, exactly like a library row.
  P.mutations.length = 0;
  P.root.activate();
  check("enter adds the station and plays it",
        P.mutations.length === 1 && P.mutations[0].op === "addplay"
          && P.mutations[0].args.uri === STATION.url_resolved,
        JSON.stringify(P.mutations[0]));

  // `A` would append a whole library selection; there is no such thing here.
  P.mutations.length = 0;
  P.root.addAll();
  check("`A` on a station list appends nothing by itself",
        P.mutations.length === 0 && P.flashes.length > 0,
        JSON.stringify(P.mutations) + " flashes=" + JSON.stringify(P.flashes));

  // The station pane is local: a station is in nobody's library, so there is
  // nothing for MPD to look up and the URL is not the thing to show.
  const Q = makePanel();
  Q.root.tab = "radio";
  Q.root.stack = [{ mode: "radioStations", title: "Radio" }];
  Q.root.rows = [STATION];
  Q.root.sel = 0;
  Q.queries.length = 0;
  Q.root.showDetails();
  check("`i` on a station asks nobody and shows what the row has",
        Q.queries.length === 0 && Q.root.detailRow !== null
          && Q.root.detailTitle === "Groove Salad [SomaFM]",
        JSON.stringify(Q.queries) + " title=" + Q.root.detailTitle);
  const fields = Q.root.detailPairs().map(function (p) { return p.label + "=" + p.value });
  check("the pane names the station and its stream",
        fields.indexOf("Name=Groove Salad [SomaFM]") >= 0
          && fields.some(function (f) { return f.indexOf("ice5.somafm.com") >= 0 }),
        fields.join(", "));
}
group("case 13: a station row shows the station, and appends rather than plays");
radioCase("a station row shows the station, and appends rather than plays", case13StationRow);

function case14StreamDisplay() {
  // What MPD really answers for a stream (measured): `file` is the URL, `Name`
  // is the station, `Title` is the running track, and there is no artist, no
  // album and no length (`time` arrives as "0.000").
  const STREAM = { type: "file", file: "https://ice5.somafm.com/groovesalad-128-aac",
                   name: "Groove Salad [SomaFM]", title: "Sine - The Return",
                   time: "0.000" };
  const FILE = { type: "file", file: "Music/01.mp3", artist: "Alice", album: "Solo",
                 title: "One", time: "212" };
  const P = makePanel();

  check("a stream is recognised by its file, not by a tag",
        P.root.isStream(STREAM) === true && P.root.isStream(FILE) === false,
        String(P.root.isStream(STREAM)) + " / " + String(P.root.isStream(FILE)));
  check("the queue row is the station", P.root.rowTitle(STREAM) === "Groove Salad [SomaFM]",
        P.root.rowTitle(STREAM));
  check("the second line is what is on the station",
        P.root.rowSub(STREAM) === "Sine - The Return", P.root.rowSub(STREAM));
  check("a stream has no clock: the row keeps the time column empty",
        P.root.rowRight(STREAM) === "", JSON.stringify(P.root.rowRight(STREAM)));
  check("control: an ordinary file row is unchanged",
        P.root.rowTitle(FILE) === "One" && P.root.rowSub(FILE) === "Alice  ·  Solo"
          && P.root.rowRight(FILE) === "212", [P.root.rowTitle(FILE), P.root.rowSub(FILE),
          P.root.rowRight(FILE)].join(" | "));

  // Without ICY metadata the stream still has its name, and never the URL.
  const BARE = { type: "file", file: "http://jazz.example:8000/live", name: "Jazz Radio" };
  check("a stream without ICY metadata still shows its name",
        P.root.rowTitle(BARE) === "Jazz Radio", P.root.rowTitle(BARE));
  check("... and its second line stays empty instead of the URL",
        P.root.rowSub(BARE) === "", JSON.stringify(P.root.rowSub(BARE)));

  // Seeking a live stream is meaningless: the keys go quiet while one plays.
  const Q = makePanel();
  const bares = [];
  Q.host.bare = function (command) { bares.push(String(command)) };
  Q.host.elapsed = 42;
  Q.host.isStream = true;
  Q.key(Q.Qt.Key_Comma, ",");
  Q.key(Q.Qt.Key_Period, ".");
  check("`,` and `.` send no seek while a stream plays", bares.length === 0,
        JSON.stringify(bares));
  Q.host.isStream = false;
  Q.key(Q.Qt.Key_Comma, ",");
  check("control: on a file the same key still seeks",
        bares.length === 1 && bares[0] === "seek 37", JSON.stringify(bares));
}
group("case 14: a stream is named, not addressed");
radioCase("a stream is named, not addressed", case14StreamDisplay);

group("language: the panel's strings are English");
{
  // A source scan, not an extraction: the panel's string literals with the
  // comments removed -- the same scope the review's language sweep used. German is
  // romanised in this project (there is not a single umlaut in the whole file), so
  // the search is for word stems and for the German opening quote U+201E.
  const code = SRC.split("\n").map(function (ln) {
    const at = ln.indexOf("//");
    return at < 0 ? ln : ln.slice(0, at);
  }).join("\n");
  const literals = [];
  const re = /"((?:[^"\\]|\\.)*)"/g;
  let m;
  while ((m = re.exec(code)) !== null) literals.push(m[1]);

  const stems = ["ersetz", "verbind", "warte", "beendet", "loesch", "waehl", "oeffn",
                 "abbrech", "schliess", "umbenenn", "hinzufueg", "kuenstler",
                 "sammlung", "einstellung", "wiedergabe", "lautstaerke", "zufall"];
  const german = [];
  literals.forEach(function (l) {
    const low = l.toLowerCase();
    stems.forEach(function (s) {
      if (low.indexOf(s) >= 0) german.push(s + " in " + JSON.stringify(l));
    });
  });
  check("no German word stem in a string literal", german.length === 0, german.join("; "));
  check("the German opening quote U+201E is gone from the file",
        SRC.indexOf("\u201e") < 0,
        String(SRC.split("\u201e").length - 1) + " occurrence(s)");
  check("no umlaut or sharp s anywhere in the file",
        !/[\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc\u00df]/.test(SRC));
  check("the three spots read English now",
        literals.indexOf(" (replaces the queue)") >= 0
          && literals.indexOf("connecting \u2026") >= 0
          && literals.indexOf("Album \u201c") >= 0,
        "album flash quote, playlist flash, connection line");
}

// --------------------------------------------------------------- report
console.log("\nPanel.qml: " + PANEL + "  sha256:" + sha(SRC));
EXTRACTED.forEach(function (f) {
  if (f.text === "") return;
  console.log("  extracted " + f.from + "-" + f.to + "  sha256:" + sha(f.text)
    + "  " + f.text.split("(")[0].replace("function ", ""));
});
if (MISSING.length > 0)
  console.log("  not in this revision: " + MISSING.join(", "));
console.log("  onStackChanged handler: " + JSON.stringify(STACK_HANDLER));
console.log("  promptDebounce onTriggered: " + DEBOUNCE_HANDLER.text);
console.log("  row selected binding: " + JSON.stringify(ROW_SELECTED));
console.log("\n" + (checks - failures) + "/" + checks + " checks passed");
process.exit(failures === 0 ? 0 : 1);
