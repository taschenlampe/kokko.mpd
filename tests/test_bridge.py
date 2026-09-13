#!/usr/bin/env python3
"""Unit tests for the pure parts of bin/mpd-bridge -- no MPD, no shell, no deps.

    python3 tests/test_bridge.py      (or: tests/run.sh)

Stdlib only on purpose: the plugin must be checkable on a machine that has
nothing installed. The bridge is imported by path because it carries no `.py`
suffix (it is a copy of the upstream script, see NOTICE.md).
"""
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bin", "mpd-bridge")

FAILS = []


def load_bridge():
    loader = importlib.machinery.SourceFileLoader("bridge_under_test", BRIDGE)
    spec = importlib.util.spec_from_loader("bridge_under_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


B = load_bridge()


def check(name, got, want):
    if got == want:
        print("   ok    %s" % name)
    else:
        FAILS.append(name)
        print("   FAIL  %s\n           erwartet: %r\n           bekommen: %r" % (name, want, got))


def jpeg(size):
    """A fake JPEG of an exact byte length, so the pick can be identified by size."""
    head = b"\xff\xd8"
    return head + b"x" * max(0, size - len(head))


def picked(files):
    """Write a library with the given (name, size) files and return the chosen bytes."""
    base = tempfile.mkdtemp(prefix="mpd-cover-")
    album = os.path.join(base, "Album")
    os.makedirs(album)
    for name, size in files:
        with open(os.path.join(album, name), "wb") as handle:
            handle.write(jpeg(size))
    saved = B.music_directory
    B.music_directory = lambda: base
    try:
        data, _mime = B.local_cover("Album/track.mp3")
        return data
    finally:
        B.music_directory = saved
        shutil.rmtree(base, ignore_errors=True)


print("=== Cover-Auswahl (local_cover) ===")
# The classic names win over everything else, "folder" is the one this library uses.
check("folder.jpg schlaegt die Windows-Dateien",
      len(picked([("AlbumArt_{0F838ADF}_Large.jpg", 500), ("folder.jpg", 900)])), 900)
# A front cover has to beat a back cover, even when the back one is the bigger scan.
check("Front schlaegt Back",
      len(picked([("X - Front Cover.jpg", 400), ("X - Back Cover.jpg", 900)])), 400)
# Nothing but a GUID-named Windows file (the case that motivated the pattern ranking).
check("AlbumArt_{GUID}_Large wird gefunden",
      len(picked([("AlbumArt_{0F838ADF-41DB-4F92-9414-C6023070E2EA}_Large.jpg", 700)])), 700)
# Only the wrong side of the booklet: still better than nothing.
check("nur Back Cover wird genommen",
      len(picked([("X - Back Cover.jpg", 600)])), 600)
# "Album Art.jpg" is a classic name, "Album Art Small" is not.
check("Album Art schlaegt Album Art Small",
      len(picked([("Album Art.jpg", 300), ("Album Art Small.jpg", 800)])), 300)
# Within one rank the bigger file wins (the better scan).
check("innerhalb eines Rangs gewinnt die groessere Datei",
      len(picked([("cover.jpg", 200), ("folder.jpg", 800)])), 800)
# No image at all.
check("ohne Bild bleibt es leer", picked([("track.mp3", 100)]), b"")
# Larger than the plugin's limit: refuse it rather than read a huge file.
check("zu grosses Bild wird uebersprungen",
      picked([("folder.jpg", B.ART_LIMIT + 10)]), b"")

print("=== Filterausdruck (contains_expression) ===")
check("Kategorie-Filter mit (?i)", B.contains_expression("artist", "iam"), "(artist =~ '(?i)iam')")
# Two escaping layers are visible here and both are needed: `re.escape` doubles the
# metacharacters (the regex layer), `quote_filter_value` doubles the backslashes again
# (the filter's '...' layer). Verified against a live MPD with real album names
# ("#1's International Version", "( O )( O )( O ), cl-018") -- see tests/smoke_mpd.py.
check("Sonderzeichen werden escaped",
      B.contains_expression("album", "AC/DC + live"), "(album =~ '(?i)AC/DC\\\\ \\\\+\\\\ live')")
check("Apostroph im Bandnamen",
      B.quote_filter_value("O'Brien"), "O\\'Brien")
check("Backslash wird verdoppelt", B.quote_filter_value("a\\b"), "a\\\\b")

print("=== Cache-Schluessel (art_key) ===")
a = B.art_key({"file": "Rock/X/01.mp3", "album": "X", "albumartist": "Y"})
b = B.art_key({"file": "Rock/X/02.mp3", "album": "X", "albumartist": "Y"})
c = B.art_key({"file": "Rock/Z/01.mp3", "album": "X", "albumartist": "Y"})
check("gleiches Album -> gleicher Schluessel", a, b)
check("anderes Verzeichnis -> anderer Schluessel", a == c, False)
check("Schluessel ist 20 Zeichen", len(a), 20)

print("=== Bildtyp (extension_for) ===")
check("JPEG erkannt", B.extension_for(b"\xff\xd8\xff\xe0", ""), ".jpg")
check("PNG erkannt", B.extension_for(b"\x89PNG\r\n\x1a\n", ""), ".png")
check("WEBP erkannt", B.extension_for(b"RIFF\x00\x00\x00\x00WEBP", ""), ".webp")
check("Rueckfall auf den MIME-Typ", B.extension_for(b"????", "image/png"), ".png")
check("unbekannt", B.extension_for(b"????", ""), ".img")

print("=== Musikverzeichnis (music_directory) ===")
tmp = tempfile.mkdtemp(prefix="mpd-conf-")
try:
    os.makedirs(os.path.join(tmp, "mpd"))
    music = os.path.join(tmp, "Musik")
    os.makedirs(music)
    with open(os.path.join(tmp, "mpd", "mpd.conf"), "w") as handle:
        handle.write('music_directory    "%s"\n' % music)
    saved_env = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = tmp
    B._MUSIC_DIR = None                     # the module caches its answer
    check("liest music_directory aus mpd.conf", B.music_directory(), music)
    if saved_env is None:
        os.environ.pop("XDG_CONFIG_HOME", None)
    else:
        os.environ["XDG_CONFIG_HOME"] = saved_env
    B._MUSIC_DIR = None
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if FAILS:
    print("   %d von %d Pruefungen fehlgeschlagen: %s" % (
        len(FAILS), len(FAILS), ", ".join(FAILS)))
    raise SystemExit(1)
print("   alle Pruefungen bestanden")
