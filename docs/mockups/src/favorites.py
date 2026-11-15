#!/usr/bin/env python3
"""Mockups: the star in the band, and a Favourites section on the start screen.

    python3 docs/mockups/src/favorites.py
    for f in fav-*.html; do chromium --headless --disable-gpu --no-sandbox \\
        --hide-scrollbars --window-size=1120,740 --virtual-time-budget=6000 \\
        --screenshot="${f%.html}.png" "file://$PWD/$f"; done

The canvas is the panel's own (1120x740 = the panel at device scale 1.25), the
colours are the running theme's (colors.toml: bg #05182e, fg #f6dcac, accent
#faa968), the font is JetBrainsMono Nerd Font, the covers are the real ones from
the bridge cache. The band is drawn in the look that is switched on (`anchor`,
big cover), because that is the one a proposal has to survive.

Nothing here ships. It is a picture of a proposal, not plugin code.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

BG = "#05182e"
FG = "#f6dcac"
ACCENT = "#faa968"

CSS = """
*{box-sizing:border-box}
html,body{margin:0;width:1120px;height:740px;overflow:hidden;background:@@bg@@;
  font-family:"JetBrainsMono Nerd Font",monospace;color:@@fg@@;
  -webkit-font-smoothing:antialiased}
/* the cover as the panel backdrop (Backdrop.qml, presence 60) */
.wash{position:fixed;inset:-40px;background-size:cover;background-position:center;
  filter:blur(46px) saturate(1.25);opacity:.30;z-index:0}
.scrim{position:fixed;inset:0;z-index:1;
  background:linear-gradient(180deg,rgba(5,24,46,.55) 0%,rgba(5,24,46,.88) 45%,rgba(5,24,46,.96) 100%)}
.panel{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column}

/* ---------------------------------------------------------------- header */
.header{height:60px;display:flex;align-items:center;padding:0 20px;flex:none}
.brand{font-size:16px;letter-spacing:3px;color:rgba(246,220,172,.75)}
.chips{margin-left:auto;display:flex;gap:5px}
.chip{font-size:15px;line-height:20px;padding:4px 11px;border-radius:5px;
  color:rgba(246,220,172,.55);border:1px solid rgba(246,220,172,.12)}
.chip.on{color:@@accent@@;border-color:rgba(250,169,104,.55);
  background:rgba(250,169,104,.09)}

/* ------------------------------------------------------------------ band */
.band{display:flex;align-items:center;gap:18px;padding:8px 13px 0 13px;flex:none}
.band .cov{width:130px;height:130px;border-radius:10px;object-fit:cover;display:block;
  box-shadow:0 6px 20px rgba(0,0,0,.35)}
.band .mid{flex:1;min-width:0}
.titlerow{display:flex;align-items:center;gap:8px}
.tt{font-size:25px;font-weight:700;letter-spacing:.2px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.tt.grow{flex:1}
.star{font-size:25px;line-height:1;color:@@accent@@}
.star.dim{color:rgba(246,220,172,.30)}
.meta{font-size:15px;color:rgba(246,220,172,.55);margin-top:5px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.prog{display:grid;grid-template-columns:auto 1fr auto;gap:11px;align-items:center;
  margin-top:14px}
.time{font-size:15px;color:rgba(246,220,172,.38);font-variant-numeric:tabular-nums}
.track{height:5px;border-radius:3px;background:rgba(246,220,172,.16);position:relative}
.track i{position:absolute;inset:0 auto 0 0;width:31%;border-radius:3px;background:@@accent@@}
.viz{display:flex;align-items:flex-end;gap:4px;height:38px;width:188px;flex:none;
  opacity:.55}
.viz i{flex:1;background:@@accent@@;border-radius:2px 2px 0 0}
.buttons{display:flex;align-items:center;gap:7px;flex:none}
.btn{width:38px;height:38px;display:flex;align-items:center;justify-content:center;
  font-size:21px;color:rgba(246,220,172,.92)}
.btn.dim{color:rgba(246,220,172,.45)}
.btn.play{background:@@accent@@;color:@@bg@@;border-radius:19px;font-size:19px}
.btn.star{color:@@accent@@;font-size:23px}
.rule{height:1px;background:rgba(246,220,172,.10);margin:0 13px}

/* ------------------------------------------------------- thin band (minimal) */
.band.thin{padding:0 13px;height:60px;gap:14px}
.band.thin .tt{font-size:17px;font-weight:400}
.band.thin .tt b{font-weight:700}
.band.thin .meta{font-size:14px;margin:0;color:rgba(246,220,172,.45)}
.band.thin .prog{margin:0;width:225px;flex:none}
.band.thin .track i{width:44%}

/* ------------------------------------------------------------------ list */
.list{flex:1;padding:8px 13px 0 13px;overflow:hidden}
.sec{display:flex;align-items:center;height:37px;margin-top:4px;
  border-top:1px solid rgba(246,220,172,.10);padding:6px 4px 0}
.sec .t{font-size:14px;color:rgba(246,220,172,.52);letter-spacing:.2px}
.sec .more{margin-left:auto;font-size:14px;color:rgba(246,220,172,.32)}
.row{display:flex;align-items:center;gap:12px;height:34px;padding:0 4px;
  border-radius:5px}
.row.sel{background:rgba(250,169,104,.10)}
.row .cov{width:28px;height:28px;border-radius:5px;object-fit:cover;display:block;flex:none}
.row .cov.ph{background:linear-gradient(135deg,rgba(246,220,172,.12),rgba(246,220,172,.03))}
.row .ti{font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  width:430px;flex:none}
.row .su{font-size:14px;color:rgba(246,220,172,.42);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}
.row .rt{font-size:15px;color:rgba(246,220,172,.30);font-variant-numeric:tabular-nums}
.row .st{font-size:19px;color:@@accent@@;flex:none;width:26px;text-align:right}
.row .st.off{color:rgba(246,220,172,.20)}
.row .num{font-size:14px;color:rgba(246,220,172,.30);width:22px;flex:none;text-align:right}

/* ------------------------------------------------------------------ foot */
.foot{height:50px;line-height:50px;padding:0 20px;font-size:15px;
  color:rgba(246,220,172,.34);flex:none;white-space:nowrap}
.foot .k{color:rgba(246,220,172,.58)}
""".replace("@@bg@@", BG).replace("@@fg@@", FG).replace("@@accent@@", ACCENT)

CHIPS = ["Queue", "Search", "Albums", "Artists", "Genres", "Library", "Playlists",
         "Radio", "Settings", "Start"]
C = lambda name: "covers/%s.jpg" % name


def chips(active):
    return '<div class="chips">%s</div>' % "".join(
        '<div class="chip%s">%s</div>' % (" on" if n == active else "", n)
        for n in CHIPS)


def top(active, wash):
    return ('<div class="wash" style="background-image:url(%s)"></div>'
            '<div class="scrim"></div>'
            '<div class="panel"><div class="header"><div class="brand">MPD</div>%s</div>'
            '<div class="rule"></div>' % (C(wash), chips(active)))


def viz():
    # 12 bars, the shape cava draws while music plays (accent, 55 %).
    hs = [10, 17, 26, 33, 38, 30, 22, 27, 34, 24, 15, 9]
    return '<div class="viz">%s</div>' % "".join(
        '<i style="height:%dpx"></i>' % h for h in hs)


def icon(g):
    return '<div class="btn %s">%s</div>' % (g[1], g[0])


def buttons(star_in_row=False, thin=False):
    b = ['<div class="btn">󰒮</div>' if not thin else '<div class="btn dim">󰒮</div>',
         '<div class="btn play">󰏤</div>',
         '<div class="btn">󰒭</div>']
    if not thin:
        b += ['<div class="btn dim">󰒝</div>', '<div class="btn dim">󰑖</div>',
              '<div class="btn dim">󰗩</div>', '<div class="btn dim">󰆐</div>']
    if star_in_row:
        b.append('<div class="btn star">★</div>')
    return '<div class="buttons">%s</div>' % "".join(b)


def band(title="One-Armed Bandit", artist="Jaga Jazzist", album="One-Armed Bandit",
         pos="#3/12", elapsed="2:14", total="7:08", cover="one-armed",
         star="title", fill=31, thin=False):
    """star: "title" (title line), "row" (an extra glyph in the transport),
    "none"."""
    head = ""
    if star == "title":
        head = ('<div class="titlerow"><div class="tt grow">%s</div>'
                '<div class="star">★</div></div>' % title)
    elif star == "inline":
        head = ('<div class="titlerow" style="justify-content:flex-start">'
                '<div class="tt" style="flex:none">%s</div>'
                '<div class="star" style="margin-left:10px">★</div></div>' % title)
    else:
        head = '<div class="tt">%s</div>' % title
    mid = ('<div class="mid">%s<div class="meta">%s&nbsp; ·&nbsp; %s&nbsp; ·&nbsp; %s</div>'
           '<div class="prog"><div class="time">%s</div>'
           '<div class="track"><i style="width:%d%%"></i></div>'
           '<div class="time">%s</div></div></div>'
           % (head, artist, album, pos, elapsed, fill, total))
    if thin:
        return ('<div class="band thin">'
                '<div class="mid" style="display:flex;align-items:center;gap:10px;min-width:0">'
                '<div class="tt"><b>%s</b></div>'
                '<div class="meta">%s&nbsp; ·&nbsp; %s&nbsp; ·&nbsp; %s</div></div>'
                '<div class="prog"><div class="time">%s</div>'
                '<div class="track"><i style="width:%d%%"></i></div>'
                '<div class="time">%s</div></div>'
                '%s</div>' % (title, artist, album, pos, elapsed, fill, total,
                              buttons(True, thin=True)))
    return ('<div class="band"><img class="cov" src="%s">%s%s%s</div>'
            % (C(cover), mid, viz(), buttons(star == "row")))


def sec(title, more=""):
    return ('<div class="sec"><div class="t">%s</div>'
            '<div class="more">%s</div></div>' % (title, more))


def row(title, sub, cover="", star="★", right="", num=""):
    art = (""
           if cover is None
           else ('<img class="cov" src="%s">' % C(cover) if cover
                 else '<div class="cov ph"></div>'))
    lead = '<div class="num">%s</div>' % num if num else ""
    st = ('<div class="st%s">%s</div>' % ("" if star == "★" else " off", star)
          if star else "")
    rt = '<div class="rt">%s</div>' % right if right else ""
    return ('<div class="row">%s%s<div class="ti">%s</div>'
            '<div class="su">%s</div>%s%s</div>' % (art, lead, title, sub, rt, st))


def page(body, active, wash, foot):
    return ("<!doctype html><meta charset=utf-8><style>%s</style>%s%s"
            '<div class="foot">%s</div></div>' % (CSS, top(active, wash), body, foot))


FOOT_QUEUE = ('<span class="k">enter</span> plays &nbsp;·&nbsp; '
              '<span class="k">a</span> appends &nbsp;·&nbsp; '
              '<span class="k">d</span> removes &nbsp;·&nbsp; '
              '<span class="k">D</span> clears &nbsp;·&nbsp; '
              '<span class="k">C</span> keeps only the playing track')
FOOT_START = ('<span class="k">enter</span> plays &nbsp;·&nbsp; '
              '<span class="k">l</span> opens &nbsp;·&nbsp; '
              '<span class="k">a</span> appends &nbsp;·&nbsp; '
              '<span class="k">f</span> stars &nbsp;·&nbsp; '
              '<span class="k">r</span> other picks &nbsp;·&nbsp; '
              '<span class="k">0</span> is here')

QUEUE = [("Total Damage", "ADULT.", "Perception Is/As/Of Deception", "3:58", False),
         ("Have I Started at the End", "ADULT.", "Perception Is/As/Of Deception",
          "5:12", False),
         ("All My Friends", "LCD Soundsystem", "Sound of Silver", "7:37", True),
         ("Bananie", "Jaga Jazzist", "One-Armed Bandit", "5:21", False),
         ("Éire go Deo", "KNEECAP", "FENIAN", "2:20", False),
         ("Smugglers & Scholars", "KNEECAP", "FENIAN", "3:12", False),
         ("Nightcall", "Kavinsky", "OutRun", "4:18", False)]


def queue_list(sel=-1):
    out = []
    for i, (t, a, al, d, playing) in enumerate(QUEUE):
        cls = "row sel" if i == sel else ("row sel" if playing else "row")
        st = ('<div class="st">★</div>' if t == "All My Friends"
              else '<div class="st off">☆</div>')
        out.append('<div class="%s"><div class="ti">%s</div>'
                   '<div class="su">%s&nbsp; ·&nbsp; %s</div>'
                   '<div class="rt">%s</div>%s</div>' % (cls, t, a, al, d, st))
    return '<div class="list">%s</div>' % "".join(out)


# ---------------------------------------------------------------- the pages
def p1_band_title():
    return page(band(star="title") + '<div class="rule"></div>' + queue_list(2),
                "Queue", "one-armed", FOOT_QUEUE)


def p2_band_row():
    return page(band(star="row") + '<div class="rule"></div>' + queue_list(2),
                "Queue", "one-armed", FOOT_QUEUE)


def p3_band_minimal():
    return page(band(star="title", thin=True) + '<div class="rule"></div>'
                + queue_list(2), "Queue", "one-armed", FOOT_QUEUE)


FAVS = [("All My Friends", "LCD Soundsystem&nbsp; ·&nbsp; Sound of Silver", "silver"),
        ("Bananie", "Jaga Jazzist&nbsp; ·&nbsp; One-Armed Bandit", "one-armed"),
        ("Éire go Deo", "KNEECAP&nbsp; ·&nbsp; FENIAN", "fenian")]


def start_sections(fav_pos, fav_rows):
    new = [("Never Enough", "Turnstile&nbsp; ·&nbsp; 2025", "never-enough"),
           ("Alligator Bites Never Heal", "Doechii&nbsp; ·&nbsp; 2025", "alligator"),
           ("FENIAN", "KNEECAP&nbsp; ·&nbsp; 2026", "fenian")]
    recent = [("One-Armed Bandit", "Jaga Jazzist&nbsp; ·&nbsp; 2 hours ago", "one-armed"),
              ("Sound of Silver", "LCD Soundsystem&nbsp; ·&nbsp; yesterday", "silver")]
    picks = [("Physik", "Die Kassierer&nbsp; ·&nbsp; 2010", "physik"),
             ("What Sound", "Lamb&nbsp; ·&nbsp; 2001", "what-sound")]
    genres = [("Techno", "105"), ("Ambient", "257")]

    def block(name, rows, more):
        return sec(name, more) + "".join(row(*r) for r in rows)

    def block_starred(name, rows, more):
        return sec(name, more) + "".join(
            row(t, s, c, star="★") for t, s, c in rows)

    def block_dim(name, rows, more):
        return sec(name, more) + "".join(
            row(t, s, c, star="☆") for t, s, c in rows)

    fav = block_starred("Favourites · 12", fav_rows, "›")
    out = ""
    out += block_dim("New in the library · 3", new, "›")
    if fav_pos == "new":
        out += fav
    out += block_dim("Recently played · 2", recent, "›")
    if fav_pos == "recent":
        out += fav
    out += block_dim("Random · 2", picks, "")
    out += sec("Genres", "›") + "".join(
        row(g, "%s tracks" % n, None, star="") for g, n in genres)
    return out


def p4_start_after_recent():
    return page('<div class="list">%s</div>' % start_sections("recent", FAVS),
                "Start", "fenian", FOOT_START)


def p5_start_under_new():
    return page('<div class="list">%s</div>' % start_sections("new", FAVS),
                "Start", "fenian", FOOT_START)


ALBUMS = [("One-Armed Bandit", "Jaga Jazzist&nbsp; ·&nbsp; 2010", "one-armed"),
          ("Sound of Silver", "LCD Soundsystem&nbsp; ·&nbsp; 2007", "silver"),
          ("FENIAN", "KNEECAP&nbsp; ·&nbsp; 2026", "fenian")]


def p6_start_albums():
    return page('<div class="list">%s</div>' % start_sections("recent", ALBUMS),
                "Start", "fenian", FOOT_START)


def p7_band_compare():
    """One sheet, two bands, so the two placements sit in the same picture."""
    cap = ('<div style="font-size:16px;color:rgba(246,220,172,.55);'
           'padding:26px 18px 2px">%s</div>')
    body = (cap % "A · star at the right end of the text column (fixed position)"
            + band(star="title")
            + cap % "B · star directly after the title (moves with the title)"
            + band(star="inline"))
    return ("<!doctype html><meta charset=utf-8><style>%s</style>"
            '<style>html,body{height:470px}</style>%s' % (CSS, body))


PAGES = {
    "fav-1-band-title": p1_band_title,
    "fav-2-band-row": p2_band_row,
    "fav-3-band-minimal": p3_band_minimal,
    "fav-4-start-after-recent": p4_start_after_recent,
    "fav-5-start-under-new": p5_start_under_new,
    "fav-6-start-albums": p6_start_albums,
    "fav-7-band-compare": p7_band_compare,
}


def main():
    for name, build in PAGES.items():
        path = os.path.join(HERE, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build())
        print(path)


if __name__ == "__main__":
    main()
