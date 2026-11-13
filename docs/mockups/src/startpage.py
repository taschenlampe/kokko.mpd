#!/usr/bin/env python3
"""Mockups for the start screen: four HTML pages, rendered to PNG by hand.

    python3 docs/mockups/src/startpage.py     # writes start-*.html next to this file
    chromium --headless --screenshot=... --window-size=1120,740 start-1-hero.html

The canvas is the panel's own: 1120x740, the size of docs/panel-*.png (the panel
at device scale 1.25), JetBrainsMono Nerd Font, the colours of the running theme.
Covers are the real ones, pulled through the bridge (cache in ~/.cache/kokko-mpd).
Nothing here ships -- it is a picture of a proposal, not code for the plugin.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
html,body{margin:0;width:1120px;height:740px;overflow:hidden;background:#0d161c;
  font-family:"JetBrainsMono Nerd Font",monospace;color:#d8cbb0;
  -webkit-font-smoothing:antialiased}
.panel{position:absolute;inset:0;display:flex;flex-direction:column}
.header{height:48px;display:flex;align-items:center;padding:0 16px;flex:none}
.brand{font-size:13px;letter-spacing:2.4px;color:rgba(216,203,176,.75)}
.chips{margin-left:auto;display:flex;gap:4px}
.chip{font-size:12px;line-height:16px;padding:3px 9px;border-radius:4px;
  color:rgba(216,203,176,.55);border:1px solid rgba(216,203,176,.12)}
.chip.on{color:#f78b04;border-color:rgba(247,139,4,.55);background:rgba(247,139,4,.09)}
.list{flex:1;padding:0 12px;overflow:hidden}
.hero{display:grid;grid-template-columns:96px 1fr auto;gap:18px;align-items:center;
  padding:6px 4px 14px}
.hero .cov{width:96px;height:96px;border-radius:8px;object-fit:cover;display:block}
.hero .tt{font-size:23px;font-weight:700;line-height:1.15;letter-spacing:.2px}
.hero .sub{font-size:13px;color:rgba(216,203,176,.5);margin-top:5px}
.hero .why{font-size:11px;color:rgba(247,139,4,.85);margin-top:7px;letter-spacing:.6px}
.pill{font-size:12.5px;color:#f78b04;border:1px solid rgba(247,139,4,.6);
  border-radius:999px;padding:7px 14px;background:rgba(247,139,4,.08);white-space:nowrap}
.pill .k{color:rgba(216,203,176,.45);margin-left:8px;font-size:11.5px}
.sec{display:flex;align-items:center;height:30px;border-top:1px solid rgba(216,203,176,.09);
  padding:7px 4px 0;gap:8px}
.sec .t{font-size:10.5px;letter-spacing:1.6px;color:rgba(216,203,176,.52)}
.sec .n{font-size:10.5px;color:rgba(216,203,176,.3)}
.sec .more{margin-left:auto;font-size:10.5px;color:rgba(216,203,176,.3)}
.row{display:grid;grid-template-columns:30px 392px 1fr 26px;gap:14px;align-items:center;
  height:33px;padding:0 4px;border-radius:5px}
.row.sel{background:#14333a}
.row .cov{width:30px;height:30px;border-radius:5px;object-fit:cover;display:block}
.row .ti{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .su{font-size:12.5px;color:rgba(216,203,176,.42);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.row .rt{font-size:13px;color:rgba(216,203,176,.3);text-align:right}
.row .du{font-size:12px;color:rgba(216,203,176,.28);text-align:right}
.row.sel .rt{color:#f78b04}
.rows.tight .row{height:26px;grid-template-columns:24px 420px 1fr 26px}
.rows.tight .cov{width:24px;height:24px}
.rows.tight .ti{font-size:13.5px}
.rows.tight .su{font-size:11.5px}
.card{display:grid;grid-template-columns:52px 1fr auto;gap:16px;align-items:center;
  margin:6px 4px 12px;padding:12px 14px;border-radius:8px;
  background:rgba(216,203,176,.045);border:1px solid rgba(216,203,176,.07)}
.card .cov{width:52px;height:52px;border-radius:6px;object-fit:cover;display:block}
.card .tt{font-size:16px}
.card .sub{font-size:12px;color:rgba(216,203,176,.45);margin-top:3px}
.bar{height:3px;border-radius:2px;background:rgba(216,203,176,.14);margin-top:9px;width:300px}
.bar i{display:block;height:3px;border-radius:2px;background:#f78b04;width:32%}
.genres{display:flex;gap:8px;padding:4px 4px 0;height:44px;align-items:center}
.g{font-size:12.5px;padding:6px 11px;border-radius:5px;border:1px solid rgba(216,203,176,.11);
  color:rgba(216,203,176,.72)}
.g b{color:rgba(216,203,176,.38);font-weight:400;margin-left:7px}
.foot{height:40px;line-height:40px;padding:0 16px;font-size:12px;
  color:rgba(216,203,176,.34);flex:none;white-space:nowrap}
.foot .k{color:rgba(216,203,176,.55)}
.frame{display:grid;grid-template-columns:96px 1fr auto;gap:18px;align-items:center;
  padding:6px 4px 10px}
.frame .cov{width:96px;height:96px;border-radius:8px;object-fit:cover;display:block}
.cov.ph{background:linear-gradient(135deg,rgba(216,203,176,.13),rgba(216,203,176,.03))}
.surprise{display:grid;grid-template-columns:30px 1fr auto;gap:14px;align-items:center;
  height:44px;margin:14px 4px 0;padding:0 14px;border-radius:7px;
  border:1px dashed rgba(247,139,4,.35);background:rgba(247,139,4,.05)}
.surprise .t{font-size:13px;color:rgba(216,203,176,.8)}
.surprise .d{font-size:11.5px;color:rgba(216,203,176,.38);margin-left:10px}
.surprise .rt{font-size:12px;color:#f78b04}
.frame .tt{font-size:22px;font-weight:700}
.frame .sub{font-size:12.5px;color:rgba(216,203,176,.5);margin-top:5px}
.star{font-size:14px;color:rgba(216,203,176,.22);text-align:right}
.star.on{color:#f78b04}
.num{font-size:12px;color:rgba(216,203,176,.3);text-align:right}
"""

CHIPS = ["Queue", "Search", "Albums", "Artists", "Genres", "Library", "Playlists",
         "Radio", "Settings", "Start"]

C = lambda name: "covers/%s.jpg" % name


def chips(active):
    out = []
    for name in CHIPS:
        out.append('<div class="chip%s">%s</div>' % (" on" if name == active else "", name))
    return '<div class="chips">%s</div>' % "".join(out)


def head(active):
    return ('<div class="header"><div class="brand">MPD</div>%s</div>' % chips(active))


def row(title, sub, cover, sel=False, right="", tight=False):
    art = ('<img class="cov" src="%s">' % C(cover) if cover
           else '<div class="cov ph"></div>')
    return ('<div class="row%s">%s<div class="ti">%s</div>'
            '<div class="su">%s</div><div class="rt">%s</div></div>'
            % (" sel" if sel else "", art, title, sub, right))


def sec(title, count="", more=""):
    return ('<div class="sec"><div class="t">%s</div><div class="n">%s</div>'
            '<div class="more">%s</div></div>' % (title, count, more))


def genres(items):
    out = []
    for name, n in items:
        out.append('<div class="g">%s<b>· %s</b></div>' % (name, n))
    return '<div class="genres">%s</div>' % "".join(out)


def page(body, active="Start", foot=""):
    return ("<!doctype html><meta charset=utf-8><style>%s</style>"
            '<div class="panel">%s<div class="list">%s</div>'
            '<div class="foot">%s</div></div>' % (CSS, head(active), body, foot))


FOOT1 = ('<span class="k">enter</span> spielt &nbsp;·&nbsp; <span class="k">l</span> öffnet '
         '&nbsp;·&nbsp; <span class="k">a</span> hängt an &nbsp;·&nbsp; '
         '<span class="k">f</span> merkt &nbsp;·&nbsp; <span class="k">r</span> andere picks')


def variant1():
    body = (
        '<div class="hero"><img class="cov" src="%s"><div>'
        '<div class="tt">FENIAN</div><div class="sub">KNEECAP &nbsp;·&nbsp; 2026 &nbsp;·&nbsp; 14 Titel</div>'
        '<div class="why">HINZUGEFÜGT 24. SEP 2026</div></div>'
        '<div class="pill">▶ spielen<span class="k">enter</span></div></div>'
        % C("fenian")
        + sec("NEU IN DER BIBLIOTHEK", "· 2", "→ alle 12")
        + row("Never Enough", "Turnstile &nbsp;·&nbsp; 2025", "never-enough")
        + row("Alligator Bites Never Heal", "Doechii &nbsp;·&nbsp; 2025", "alligator")
        + sec("ZULETZT GEHÖRT", "· 3", "→ alle 20")
        + row("One-Armed Bandit", "Jaga Jazzist &nbsp;·&nbsp; vor 2 Std.", "one-armed")
        + row("Sound of Silver", "LCD Soundsystem &nbsp;·&nbsp; gestern", "silver")
        + row("Live", "Bad Brains &nbsp;·&nbsp; vor 3 Tagen", "live")
        + sec("FÜR DICH", "· 2", "r · andere")
        + row("Physik", "Die Kassierer &nbsp;·&nbsp; 2010 &nbsp;·&nbsp; tiefer Schnitt", "physik")
        + row("What Sound", "Lamb &nbsp;·&nbsp; 2001 &nbsp;·&nbsp; lange nicht gehört", "what-sound")
        + sec("GENRES")
        + genres([("Techno", "105"), ("Ambient", "257"), ("Hip-Hop", "1.189")])
        + '<div class="surprise"><div class="rt">↻</div><div class="t">Überrasch mich'
          '<span class="d">ein zufälliges Album, sofort</span></div>'
          '<div class="rt">enter</div></div>'
    )
    return page(body, "Start", FOOT1)


def variant2():
    body = (
        '<div class="card"><img class="cov" src="%s"><div>'
        '<div class="tt">One-Armed Bandit</div>'
        '<div class="sub">Jaga Jazzist &nbsp;·&nbsp; 2:14 / 7:08</div>'
        '<div class="bar"><i></i></div></div>'
        '<div class="pill">▶ weiter<span class="k">enter</span></div></div>'
        % C("one-armed")
        + sec("NEU IN DER BIBLIOTHEK", "· 2", "→ alle 12")
        + row("FENIAN", "KNEECAP &nbsp;·&nbsp; 2026", "fenian")
        + row("Never Enough", "Turnstile &nbsp;·&nbsp; 2025", "never-enough")
        + row("Alligator Bites Never Heal", "Doechii &nbsp;·&nbsp; 2025", "alligator")
        + sec("ZULETZT GEHÖRT", "· 2", "→ alle 20")
        + row("Sound of Silver", "LCD Soundsystem &nbsp;·&nbsp; gestern", "silver")
        + row("Live", "Bad Brains &nbsp;·&nbsp; vor 3 Tagen", "live")
        + sec("FÜR DICH", "· 3", "r · andere")
        + row("Physik", "Die Kassierer &nbsp;·&nbsp; 2010", "physik")
        + row("What Sound", "Lamb &nbsp;·&nbsp; 2001", "what-sound")
        + row("FENIAN", "KNEECAP &nbsp;·&nbsp; 2026 &nbsp;·&nbsp; ganz gehört", "fenian")
        + sec("GENRES")
        + genres([("Techno", "105"), ("Ambient", "257"), ("Hip-Hop", "1.189")])
    )
    return page(body, "Start", FOOT1)


def variant3():
    body = (
        sec("NEU IN DER BIBLIOTHEK", "· 3", "→ alle 12")
        + row("FENIAN", "KNEECAP &nbsp;·&nbsp; 2026", "fenian", right="★", tight=True)
        + row("Never Enough", "Turnstile &nbsp;·&nbsp; 2025", "never-enough", right="☆", tight=True)
        + row("Alligator Bites Never Heal", "Doechii &nbsp;·&nbsp; 2025", "alligator", right="☆", tight=True)
        + sec("ZULETZT GEHÖRT", "· 3", "→ alle 20")
        + row("One-Armed Bandit", "Jaga Jazzist &nbsp;·&nbsp; vor 2 Std.", "one-armed", right="☆", tight=True)
        + row("Sound of Silver", "LCD Soundsystem &nbsp;·&nbsp; gestern", "silver", right="★", tight=True)
        + row("Live", "Bad Brains &nbsp;·&nbsp; vor 3 Tagen", "live", right="☆", tight=True)
        + sec("FÜR DICH", "· 3", "r · andere")
        + row("Physik", "Die Kassierer &nbsp;·&nbsp; 2010", "physik", right="☆", tight=True)
        + row("What Sound", "Lamb &nbsp;·&nbsp; 2001", "what-sound", right="☆", tight=True)
        + row("FENIAN", "KNEECAP &nbsp;·&nbsp; 2026", "fenian", right="★", tight=True)
        + sec("GENRES", "", "→ alle 228")
        + row("Techno", "105 Titel &nbsp;·&nbsp; 34 Alben", "", tight=True)
        + row("Ambient", "257 Titel &nbsp;·&nbsp; 61 Alben", "", tight=True)
        + row("Hip-Hop", "1.189 Titel &nbsp;·&nbsp; 214 Alben", "", tight=True)
    )
    return page(body, "Start", FOOT1)


def variant4():
    tracks = [
        ("01", "Éire go Deo", "2:20", True),
        ("02", "Smugglers &amp; Scholars", "3:12", True),
        ("03", "Carnival", "2:52", False),
        ("04", "Palestine (feat. Fawzi)", "2:37", False),
        ("05", "Liars Tale", "3:18", True),
        ("06", "FENIAN", "3:15", False),
        ("07", "Big Bad Mo", "3:44", False),
        ("08", "Headcase", "2:41", False),
    ]
    rows = "".join(
        '<div class="row%s"><div class="num">%s</div><div class="ti">%s</div>'
        '<div class="du">%s</div><div class="star%s">%s</div></div>'
        % (" sel" if i == 0 else "", n, t, d, " on" if f else "", "★" if f else "☆")
        for i, (n, t, d, f) in enumerate(tracks))
    body = (
        '<div class="frame"><img class="cov" src="%s"><div>'
        '<div class="tt">FENIAN</div>'
        '<div class="sub">KNEECAP &nbsp;·&nbsp; 2026 &nbsp;·&nbsp; 14 Titel &nbsp;·&nbsp; 44:12</div></div>'
        '<div class="pill">★ gemerkt<span class="k">f</span></div></div>'
        % C("fenian")
        + '<div class="rows tight">%s</div>' % rows
    )
    foot = ('<span class="k">enter</span> spielt &nbsp;·&nbsp; <span class="k">f</span> merkt '
            '&nbsp;·&nbsp; <span class="k">h</span> zurück')
    return page(body, "Albums", foot)


def main():
    pages = {"start-1-hero": variant1(), "start-2-continue": variant2(),
             "start-3-dense": variant3(), "start-4-favorites": variant4()}
    for name, html in pages.items():
        path = os.path.join(HERE, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(path)


if __name__ == "__main__":
    main()
