#!/usr/bin/env python3
"""Mockups: a mini cover in the search results -- and where it would sit.

    python3 docs/mockups/src/search-covers.py
    (renders four PNGs next to ../, at 1120x740, in the running theme)

The rows, the order and the counts come from the live bridge (`search` for the term
below), the covers from the bridge's own cache -- the same `art` query the panel
asks. Four stances:

  a  no cover                       -- what the search does today
  b  cover on every track row       -- a 24 px thumbnail, title indented like the
                                       start screen's album rows
  c  cover on the album groups only -- the section that stands for a record
  d  cover on the first row of each album run -- said once, like the album column

The queue's mockups argued against covers there because the panel header already
shows the playing album at 127 px. In a search that header shows the *playing*
track, not the hit -- so this is a different question.
"""
import importlib.machinery
import importlib.util
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BRIDGE = os.path.join(os.path.dirname(ROOT), "bin", "mpd-bridge")

BG, FG, ACCENT = "#05182e", "#f6dcac", "#faa968"
TERM = "a-ha"

CSS = """
*{box-sizing:border-box}
html,body{margin:0;width:1120px;height:740px;overflow:hidden;background:@@bg@@;
  font-family:"JetBrainsMono Nerd Font",monospace;color:@@fg@@;
  -webkit-font-smoothing:antialiased}
.panel{position:absolute;inset:0;display:flex;flex-direction:column}
.header{height:60px;display:flex;align-items:center;padding:0 20px;flex:none}
.brand{font-size:16px;letter-spacing:3px;color:rgba(246,220,172,.75)}
.chips{margin-left:auto;display:flex;gap:5px}
.chip{font-size:15px;line-height:20px;padding:4px 11px;border-radius:5px;
  color:rgba(246,220,172,.55);border:1px solid rgba(246,220,172,.12)}
.chip.on{color:@@accent@@;border-color:rgba(250,169,104,.55);background:rgba(250,169,104,.09)}
.rule{height:1px;background:rgba(246,220,172,.10);margin:0 13px}
.info{height:34px;line-height:34px;padding:0 20px;font-size:15px;flex:none;
  color:rgba(246,220,172,.62)}
.info b{color:@@accent@@;font-weight:400}
.list{flex:1;padding:0 13px;overflow:hidden}
.sec{display:flex;align-items:center;height:30px;margin-top:6px;
  border-top:1px solid rgba(246,220,172,.10);padding:8px 4px 0}
.sec .t{font-size:12.5px;letter-spacing:1.6px;color:rgba(246,220,172,.52);
  text-transform:uppercase}
.row{display:flex;align-items:center;gap:12px;height:29px;padding:0 4px;border-radius:5px}
.row .cov{width:22px;height:22px;border-radius:4px;object-fit:cover;display:block;flex:none}
.row .pad{width:22px;height:22px;flex:none;border-radius:4px;
  background:rgba(246,220,172,.04)}
.row .ti{font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:none;
  width:430px}
.row .su{font-size:14px;color:rgba(246,220,172,.42);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;flex:1;min-width:0}
.row .rt{font-size:14px;color:rgba(246,220,172,.32);font-variant-numeric:tabular-nums}
.row.group .ti{font-weight:700}
.row.group .rt{color:rgba(246,220,172,.5)}
.row.group .cov{width:26px;height:26px;border-radius:5px}
.foot{height:50px;line-height:50px;padding:0 20px;font-size:15px;flex:none;
  color:rgba(246,220,172,.34);white-space:nowrap}
.foot .k{color:rgba(246,220,172,.58)}
""".replace("@@bg@@", BG).replace("@@fg@@", FG).replace("@@accent@@", ACCENT)

CHIPS = ["Queue", "Search", "Albums", "Artists", "Genres", "Library", "Playlists",
         "Radio", "Settings", "Start"]


def load_bridge():
    loader = importlib.machinery.SourceFileLoader("bridge_cov", BRIDGE)
    spec = importlib.util.spec_from_loader("bridge_cov", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def fmt_time(seconds):
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return "%d:%02d" % (total // 60, total % 60)


def group_of(row, tag):
    return str(row.get(tag) or "")


def main():
    br = load_bridge()
    conn = br.MPDConn(br.parse_target("127.0.0.1", 6600), "")
    conn.connect()
    bridge = br.Bridge()
    rows = bridge.execute_query(conn, "search", {"term": TERM, "limit": 500})
    print("Treffer:", len(rows))

    # one cover per album, through the same `art` query the panel uses
    covers, art_missing = {}, 0
    for row in rows:
        album = group_of(row, "album")
        if not album or album in covers:
            continue
        answer = bridge.execute_query(conn, "art", {
            "uri": str(row.get("file") or ""), "album": album,
            "albumartist": group_of(row, "albumartist")})
        path = str((answer[0] if answer else {}).get("path") or "")
        covers[album] = path
        if not path:
            art_missing += 1
    print("Cover:", len([p for p in covers.values() if p]), "von", len(covers),
          "Alben (%d ohne Bild)" % art_missing)

    artists, albums = {}, {}
    for row in rows:
        artists[group_of(row, "artist")] = artists.get(group_of(row, "artist"), 0) + 1
        albums[group_of(row, "album")] = albums.get(group_of(row, "album"), 0) + 1

    def cov(album, size_class="cov"):
        path = covers.get(album, "")
        if not path:
            return '<div class="pad"></div>'
        return '<img class="%s" src="file://%s">' % (size_class, path)

    def group_row(name, count, album):
        return ('<div class="row group">%s<div class="ti">%s</div><div class="su"></div>'
                '<div class="rt">%d %s</div></div>'
                % (cov(album) if album else "", name, count,
                   "track" if count == 1 else "tracks"))

    def track_row(row, cover_album, indent):
        sub = "&nbsp; · &nbsp;".join(x for x in (row.get("artist") or "",
                                                 row.get("album") or "") if x)
        art = cov(cover_album) if cover_album else ('<div style="width:22px;flex:none"></div>'
                                                    if indent else "")
        return ('<div class="row">%s<div class="ti">%s</div><div class="su">%s</div>'
                '<div class="rt">%s</div></div>'
                % (art, (row.get("title") or "")[:58], sub, fmt_time(row.get("time"))))

    def panel(variant):
        body = ['<div class="sec"><div class="t">Artists</div></div>']
        for name, count in artists.items():
            # an artist has no single cover; the album section carries it
            body.append(group_row(name, count, "" if variant != "a" else ""))
        body.append('<div class="sec"><div class="t">Albums</div></div>')
        for name, count in albums.items():
            body.append('<div class="row group">%s<div class="ti">%s</div>'
                        '<div class="su"></div><div class="rt">%d %s</div></div>'
                        % (cov(name) if variant in ("c", "d") else "",
                           name, count, "track" if count == 1 else "tracks"))
        body.append('<div class="sec"><div class="t">Tracks — %d hits</div></div>' % len(rows))
        previous = None
        for row in rows[:12]:
            album = group_of(row, "album")
            if variant == "b":
                body.append(track_row(row, album, True))
            elif variant == "d":
                body.append(track_row(row, album if album != previous else "", True))
            else:
                body.append(track_row(row, "", False))
            previous = album
        return ("<!doctype html><meta charset=utf-8><style>%s</style>"
                '<div class="panel"><div class="header"><div class="brand">MPD</div>%s</div>'
                '<div class="rule"></div>'
                '<div class="info"><b>%d hits</b> for “%s”</div>'
                '<div class="list">%s</div>'
                '<div class="foot"><span class="k">enter</span> opens &nbsp;·&nbsp; '
                '<span class="k">a</span> appends &nbsp;·&nbsp; <span class="k">A</span> all hits'
                ' &nbsp;·&nbsp; <span class="k">h</span> back</div></div>'
                % (CSS, "".join('<div class="chip%s">%s</div>'
                                % (" on" if n == "Search" else "", n) for n in CHIPS),
                   len(rows), TERM, "".join(body)))

    names = {"a": "search-cover-a-none", "b": "search-cover-b-every-row",
             "c": "search-cover-c-albums", "d": "search-cover-d-first-of-run"}
    for key, name in names.items():
        html = panel(key)
        path = os.path.join(HERE, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        png = os.path.join(os.path.dirname(HERE), name + ".png")
        subprocess.run(["chromium", "--headless", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", "--window-size=1120,740",
                        "--virtual-time-budget=6000", "--screenshot=" + png,
                        "file://" + path], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("   ", png)


if __name__ == "__main__":
    main()
