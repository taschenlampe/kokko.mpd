#!/usr/bin/env python3
"""Old vs new search result for "abba", drawn from the live library.

    python3 docs/mockups/src/search-abba.py      # writes search-abba-*.html + .png
    chromium --headless --disable-gpu --no-sandbox --hide-scrollbars \\
        --window-size=1120,740 --virtual-time-budget=6000 \\
        --screenshot=docs/mockups/search-abba-old.png search-abba-old.html

Both panels are built from the real answer of `bin/mpd-bridge` against the
running MPD -- same rows, same order, same counts, no invented entry. The only
difference is the rule:

  old: every hit the bridge ranks (position only sorts them)
  new: hits that match in the middle of a longer word are dropped when a better
       hit exists -- "Sabbath", "Cabbage", "Jabba" go, "ABBA", "Frida" (her track
       sits on an ABBA-credited album) and "Claudio Abbado" stay.

The panels are the panel's own geometry (1120x740 = the panel at device scale
1.25), the running theme's colours and the covers from the bridge cache.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BRIDGE = os.path.join(os.path.dirname(ROOT), "bin", "mpd-bridge")
ART = os.path.expanduser("~/.cache/kokko-mpd")

BG, FG, ACCENT = "#05182e", "#f6dcac", "#faa968"
TERM = "abba"

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
.prompt{margin-left:auto;font-size:15px;color:rgba(246,220,172,.45)}
.list{flex:1;padding:0 13px;overflow:hidden}
.sec{display:flex;align-items:center;height:30px;margin-top:6px;
  border-top:1px solid rgba(246,220,172,.10);padding:8px 4px 0}
.sec .t{font-size:12.5px;letter-spacing:1.6px;color:rgba(246,220,172,.52);
  text-transform:uppercase}
.row{display:flex;align-items:center;gap:12px;height:29px;padding:0 4px;border-radius:5px}
.row .ti{font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:none;
  width:430px}
.row .su{font-size:14px;color:rgba(246,220,172,.42);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;flex:1;min-width:0}
.row .rt{font-size:14px;color:rgba(246,220,172,.32);font-variant-numeric:tabular-nums}
.row.group .ti{font-weight:700}
.row.group .rt{color:rgba(246,220,172,.5)}
.row.mid .ti{color:rgba(246,220,172,.45)}
.row.mid .rt{color:rgba(246,220,172,.22)}
.row.cut{color:rgba(246,220,172,.28)}
.row.cut .ti{text-decoration:line-through;text-decoration-color:rgba(246,220,172,.25)}
.foot{height:50px;line-height:50px;padding:0 20px;font-size:15px;flex:none;
  color:rgba(246,220,172,.34);white-space:nowrap}
.foot .k{color:rgba(246,220,172,.58)}
""" .replace("@@bg@@", BG).replace("@@fg@@", FG).replace("@@accent@@", ACCENT)

CHIPS = ["Queue", "Search", "Albums", "Artists", "Genres", "Library", "Playlists",
         "Radio", "Settings", "Start"]


def load_bridge():
    loader = importlib.machinery.SourceFileLoader("bridge_mock", BRIDGE)
    spec = importlib.util.spec_from_loader("bridge_mock", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def hits(br):
    conn = br.MPDConn(br.parse_target("127.0.0.1", 6600), "")
    conn.connect()
    return br.Bridge().execute_query(conn, "search", {"term": TERM, "limit": 500}), conn


def group_totals(br, conn, items):
    """MPD's own count per group -- the number `a` appends, as the panel shows it."""
    want, filters = [], []
    seen = set()
    for item in items:
        if item["kind"] != "group":
            continue
        key = (item["tag"], item["value"])
        if key in seen:
            continue
        seen.add(key)
        want.append(key)
        filters.append({"tag": item["tag"], "value": item["value"]})
    if not filters:
        return {}
    totals = br.Bridge().execute_query(conn, "counts", {"filters": filters})
    return {key: (totals[i] if i < len(totals) else 0) for i, key in enumerate(want)}


def group_rows(rows):
    """The panel's groupHits: artists, then albums, in its own order."""
    out = []

    def tally(key):
        order, counts, best = [], {}, {}
        for row in rows:
            value = str(row.get(key) or "")
            if value == "":
                continue
            if value not in counts:
                counts[value] = 0
                order.append(value)
            counts[value] += 1
            rank = int(row.get("rank", 99))
            if value not in best or rank < best[value]:
                best[value] = rank
        order.sort(key=lambda v: (best[v], -counts[v], v.lower()))
        return order, counts, best

    artists = tally("artist")
    if artists[0]:
        out.append({"kind": "header", "text": "Artists"})
        for name in artists[0][:30]:
            out.append({"kind": "group", "type": "group", "tag": "artist", "value": name,
                        "count": artists[1][name]})
    albums = tally("album")
    if albums[0]:
        out.append({"kind": "header", "text": "Albums"})
        for name in albums[0][:30]:
            out.append({"kind": "group", "type": "group", "tag": "album", "value": name,
                        "count": albums[1][name]})
    out.append({"kind": "header", "text": "Tracks — %d hits" % len(rows)})
    for row in rows[:300]:
        out.append({"kind": "track", "row": row})
    return out


def art_path(row):
    key = str(row.get("file") or "")
    return ""          # the search rows carry no cover of their own


def chips(active):
    return '<div class="chips">%s</div>' % "".join(
        '<div class="chip%s">%s</div>' % (" on" if n == active else "", n) for n in CHIPS)


def render(br, conn, title, rows, cut):
    items = group_rows(rows)
    totals = group_totals(br, conn, items)
    body = []
    for item in items:
        if item["kind"] == "header":
            body.append('<div class="sec"><div class="t">%s</div></div>' % item["text"])
        elif item["kind"] == "group":
            total = totals.get((item["tag"], item["value"]), item["count"])
            body.append('<div class="row group"><div class="ti">%s</div>'
                        '<div class="su"></div><div class="rt">%d %s</div></div>'
                        % (item["value"], total, "track" if total == 1 else "tracks"))
        else:
            row = item["row"]
            sub = "&nbsp; · &nbsp;".join(x for x in (row.get("artist") or "",
                                                     row.get("album") or "") if x)
            cls = "row"
            if row.get("pos") == 2:
                cls = "row cut" if cut else "row mid"
            body.append('<div class="%s"><div class="ti">%s</div><div class="su">%s</div>'
                        '<div class="rt">%s</div></div>'
                        % (cls, (row.get("title") or "")[:60], sub,
                           fmt(row.get("time"))))
    return ("<!doctype html><meta charset=utf-8><style>%s</style>"
            '<div class="panel"><div class="header"><div class="brand">MPD</div>%s</div>'
            '<div class="rule"></div>'
            '<div class="info">%s<span class="prompt">&nbsp;&nbsp;&nbsp;/ %s</span></div>'
            '<div class="list">%s</div>'
            '<div class="foot"><span class="k">enter</span> opens &nbsp;·&nbsp; '
            '<span class="k">a</span> appends &nbsp;·&nbsp; <span class="k">A</span> all hits'
            ' &nbsp;·&nbsp; <span class="k">h</span> back</div></div>'
            % (CSS, chips("Search"), title, TERM, "".join(body)))


def fmt(seconds):
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return "%d:%02d" % (total // 60, total % 60)


def main():
    br = load_bridge()
    rows, conn = hits(br)
    print("Treffer insgesamt: %d" % len(rows))
    better = [r for r in rows if r.get("pos", 2) < 2]
    if better:
        kept = better
    else:
        kept = list(rows)
    print("nach der neuen Regel: %d" % len(kept))

    old_html = render(br, conn, '<b>%d hits</b> for “%s”' % (len(rows), TERM), rows, False)
    new_html = render(br, conn, '<b>%d hits</b> for “%s”' % (len(kept), TERM), kept, True)
    for name, html in (("search-abba-old", old_html), ("search-abba-new", new_html)):
        path = os.path.join(HERE, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        png = os.path.join(os.path.dirname(HERE), name + ".png")
        subprocess.run(["chromium", "--headless", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", "--window-size=1120,740",
                        "--virtual-time-budget=6000", "--screenshot=" + png,
                        "file://" + path], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("   ", path, "->", png)


if __name__ == "__main__":
    main()
