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
console.log("\n" + (checks - failures) + "/" + checks + " checks passed");
process.exit(failures === 0 ? 0 : 1);
