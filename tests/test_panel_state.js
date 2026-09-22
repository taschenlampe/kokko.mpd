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
  "rootFrameFor", "setTab", "pushFrame", "popFrame", "topFrame", "loadFrame",
  "infoFor", "groupHits", "isSelectable", "firstSelectable", "lastSelectable",
  "rowIsSong", "activate", "addRow", "addOne", "addAll", "openPrompt",
  "closePrompt", "leavePrompt", "clearLocalFilter", "filterableFrame",
  "searchWhileTyping", "searchNow", "applySearch",
  "applyCategorySearch", "refreshFilteredRows", "applyLocalFilter",
  "openPromptForFrame", "submitPrompt", "rowTitle", "rowSub", "mutateAndReload",
  "handleKey"
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

  P.key(0, "8");                         // the `8` key: the settings tab
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
  Q.key(0, "8");
  const before = Q.rowsTitles().join(", ");
  Q.root.filterText = "flac";            // MODELLED: a filter left over from files
  Q.root.closePrompt();
  check("a cleanup does not rebind the rows of the current view",
        Q.rowsTitles().join(", ") === before && Q.root.rowsBoundToSettingRows === true,
        Q.rowsTitles().join(", "));

  // Control: without a filter the settings tab always worked.
  const R = onFilesTab();
  R.key(0, "8");
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
