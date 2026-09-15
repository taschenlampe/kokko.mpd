#!/usr/bin/env python3
"""Checks that need nothing but the files themselves.

    python3 tests/check_consistency.py

This is the half of the suite that can run anywhere -- including a CI container
with no Omarchy shell, no MPD and no Qt. It guards the seams where things go
wrong silently:

  1. the manifest is complete enough for the shell to load the widget,
  2. every setting the panel offers really exists in the manifest schema
     (a typo there is a setting that simply does nothing when clicked),
  3. the duplicated default in `barWidget.defaults` does not contradict the
     schema's `defaultValue`,
  4. no QML string uses a malformed `\\u` escape: JavaScript reads exactly four
     hex digits, so `"\\uF0456"` silently becomes the glyph plus a literal "6" --
     that bug already shipped an image where a play button belonged. Four digits
     are fine and sometimes the only sane way to write a character (a NUL
     separator in BarWidget's connection key); the count is what is checked.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "manifest.json")
PANEL = os.path.join(ROOT, "Panel.qml")
PLUGIN_DIR = os.path.basename(ROOT)
KINDS = ("bar-widget",)

FAIL = 0


def step(what):
    print("\n=== %s ===" % what)


def note(what):
    print("   %s" % what)


def bad(what):
    global FAIL
    FAIL = 1
    print("   FAIL: %s" % what)


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def schema_entries(man):
    """The settings schema lives under barWidget.schema."""
    bw = man.get("barWidget") or {}
    entries = bw.get("schema") or []
    return entries if isinstance(entries, list) else []


def panel_setting_keys():
    """Keys of the rows the panel's settings tab offers (actions have none)."""
    with open(PANEL, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"readonly property var settingRows: \{(.*?)\n  \}", src, re.S)
    if not m:
        bad("could not find settingRows in Panel.qml")
        return []
    block = m.group(1)
    keys = []
    for row in block.split("{ type:")[1:]:
        if 'kind: "action"' in row:
            continue
        km = re.search(r'key: "([^"]+)"', row)
        if km:
            keys.append(km.group(1))
    return keys


def main():
    step("manifest")
    try:
        man = load_manifest()
    except (OSError, ValueError) as exc:
        bad("manifest.json does not parse: %s" % exc)
        return 1
    note("id=%s  kinds=%s  version=%s" % (man.get("id"), man.get("kinds"), man.get("version")))

    if man.get("id") != PLUGIN_DIR:
        bad("id %r does not match the directory %r -- renaming the id breaks every install"
            % (man.get("id"), PLUGIN_DIR))
    kinds = man.get("kinds") or []
    if not any(k in kinds for k in KINDS):
        bad("kinds %s contains none of %s" % (kinds, list(KINDS)))
    ver = str(man.get("version") or "")
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        bad("version %r is not x.y.z" % ver)
    if man.get("schemaVersion") is None:
        bad("schemaVersion is missing")
    entry = (man.get("entryPoints") or {}).get("barWidget")
    if not entry:
        bad("entryPoints.barWidget is missing")
    elif not os.path.exists(os.path.join(ROOT, entry)):
        bad("entryPoints.barWidget points at %r, which does not exist" % entry)

    step("schema")
    entries = schema_entries(man)
    if not entries:
        bad("no barWidget.schema entries")
    keys = [e.get("key") for e in entries]
    for e in entries:
        for field in ("key", "type", "label", "defaultValue"):
            if field not in e:
                bad("schema entry %r has no %s" % (e.get("key"), field))
        if e.get("key") and not re.match(r"^[a-z][A-Za-z0-9]*$", e["key"]):
            bad("schema key %r is not camelCase" % e["key"])
    doppelt = sorted({k for k in keys if keys.count(k) > 1})
    if doppelt:
        bad("duplicate schema keys: %s" % ", ".join(doppelt))
    note("%d entries, %d keys" % (len(entries), len(set(keys))))

    step("panel offers only settings that exist")
    pkeys = panel_setting_keys()
    if not pkeys:
        bad("no setting keys found in the panel")
    note("panel offers %d: %s" % (len(pkeys), ", ".join(pkeys)))
    missing = [k for k in pkeys if k not in keys]
    if missing:
        bad("the panel offers %s, which the schema does not know" % ", ".join(missing))
    else:
        note("all of them are in the schema")

    step("defaults agree with the schema")
    defaults = (man.get("barWidget") or {}).get("defaults") or {}
    verglichen = 0
    for e in entries:
        k = e.get("key")
        if k in defaults:
            verglichen += 1
            if defaults[k] != e.get("defaultValue"):
                bad("defaults.%s = %r, but the schema says %r" % (k, defaults[k], e.get("defaultValue")))
    nur_schema = [k for k in keys if k not in defaults]
    note("%d keys in both and equal; %d only in the schema (%s)"
         % (verglichen, len(nur_schema), ", ".join(nur_schema) or "-"))

    step("house rule: \\u escapes must carry exactly four hex digits")
    escapes, malformed = [], []
    muster = re.compile(r"\\u([0-9A-Fa-f]*)")
    for name in sorted(os.listdir(ROOT)):
        if not name.endswith(".qml"):
            continue
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            for nr, line in enumerate(fh, 1):
                for m in muster.finditer(line):
                    ziffern = m.group(1)
                    if len(ziffern) == 4:
                        escapes.append("%s:%d" % (name, nr))
                    else:
                        malformed.append("%s:%d  \\u%s  (%d digits)" % (name, nr, ziffern[:6], len(ziffern)))
    if malformed:
        for spot in malformed[:6]:
            print("   %s" % spot)
        bad("%d malformed \\u escape(s) -- JavaScript reads four digits and turns the rest into text"
            % len(malformed))
    else:
        note("ok -- no malformed escape (%d well-formed: %s)" % (len(escapes), ", ".join(sorted(set(escapes))) or "-"))

    print("\n%s" % ("FAILED" if FAIL else "all green"))
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
