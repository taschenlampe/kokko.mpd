# kokko.mpd

**Dein MPD in der Omarchy-Leiste.** Was gerade läuft, mit Cover — und ein Klick
öffnet den ganzen Player: Queue, Suche, Bibliothek, Playlists. Alles mit der
Maus bedienbar, Tasten sind Zugabe.

![Leiste mit Karte](docs/karte.png)

## Was es kann

**In der Leiste** — Label mit laufendem Titel (Scrollen oder Kürzen einstellbar),
Statusicon, Mittelklick = nächster Titel, Scrollen = Lautstärke/Spulen/Titel.

**Auf Zeigen** — dieselbe Musik als Karte unter der Leiste: Cover, Fortschritt
(zum Spulen ziehen), **große** Knöpfe ⏮ ⏸ ⏭, Zufall/Wiederholen, Lautstärke per
Rad. Bleibt offen, solange der Zeiger auf der Leiste oder der Karte steht.

**Im Panel** — Transport, Spektrum (cava), Queue, Bibliothek, Dateibaum und
gespeicherte Playlists an einem Ort. Das Cover des laufenden Titels liegt weich
im Hintergrund, die Präsenz regelt ein Regler.

**Suchen wie im Netz** — tippen, Treffer erscheinen nach **Künstler** und
**Album** gruppiert, während du tippst. `+` an einer Zeile hängt an, was die
Zeile *ist* — einzelnen Titel, ganzes Album, alles von einem Künstler.

**Suchen in der Kategorie** — in Alben, Künstlern und Genres sucht `/` nicht in
der ganzen Bibliothek, sondern nur in dem, was du gerade ansiehst („Alben ·
danzig", 2 statt 1789 Zeilen). Groß- und Kleinschreibung ist dabei egal: „iam"
findet auch „IAM".

**Aufräumen** — Papierkorb je Zeile, ganze Queue leeren, oder nur das Laufende
behalten. Ein Klick, sofort, mit Rückmeldung.

**Bei jedem neuen Titel** — kurz eine Karte unten, optional eine
Desktop-Benachrichtigung mit Cover. Beides einzeln abschaltbar.

**Einstellungen im Panel** — Tab **8** für die Werte, die man beim Hören
anfasst, mit Live-Vorschau. Kein JSON-Bearbeiten nötig.

## Loslegen

```bash
omarchy plugin enable kokko.mpd --section center
omarchy restart shell
```

Beim ersten Start verbindet es sich mit MPD auf `127.0.0.1:6600` (änderbar in den
Plugin-Einstellungen). Panel-Toggle: **`SUPER + CTRL + M`**.

## Die Ansichten

**Queue — der Player.** Band oben: Cover, Fortschritt, Spektrum, ein Controller.
Darunter die Warteschlange, unten was gerade passiert und was Tasten tun.
Beim Öffnen steht die **Auswahl auf dem laufenden Titel** und die Liste ist dorthin
gescrollt — bei 300 Einträgen wäre der Anfang die eine Stelle, an der die Musik
nicht ist. Mit `t` springt man jederzeit zurück (auch aus einem anderen Tab).

![Queue](docs/panel-queue.png)

**Suche.** Treffer gruppiert, `+` hängt an, `enter` spielt.

![Suche](docs/panel-suche.png)

**Einstellungen.** Sieben Werte, direkt bedienbar.

![Einstellungen](docs/einstellungen.png)

**Bei Titelwechsel.** Kurz, mit Cover, verschwindet von allein.

![Karte bei Titelwechsel](docs/titelwechsel.png)

## Bedienung — der kurze Weg

### In die Queue legen: drei Griffe

1. **Suchen**: `/` drücken und tippen (oder den Suche-Tab öffnen).
2. **`+` rechts in der Zeile** — hängt an, was diese Zeile ist: den Titel, das
   Album, alles von dem Künstler.
3. **`enter`** spielt sofort, statt anzuhängen.

Mehr muss man nicht wissen. (Wer mag: `a` ist die Tastatur-Fassung von `+`,
`A` hängt die ganze Trefferliste an.)

### Leiste

| Maus | Wirkung |
| --- | --- |
| Linksklick | Panel öffnen/schließen |
| Mittelklick | nächster Titel |
| Scrollen | Lautstärke (einstellbar: Spulen oder Titelwechsel) |
| Zeiger drauf | Karte mit Cover, Fortschritt und Bedienknöpfen |

### Karte

Klick öffnet das Panel, die Knöpfe steuern direkt, über dem Fortschritt ziehen
spult, Rad über der Karte ändert die Lautstärke. Die Schalter rechts setzen
Zufall und Wiederholen — orange heißt an.

### Panel

`←`/`h`, `esc` und `backspace` gehen eine Ebene zurück; die Fußzeile sagt jederzeit,
welche Taste hier gerade etwas tut. Am Anfang schließt `esc` das Panel.

## Wenn du Tasten magst

| Taste | Wirkung |
| --- | --- |
| `1` … `8`, `tab` | Queue · Suche · Alben · Künstler · Genres · Dateien · Playlists · Einstellungen |
| `t` | **zum laufenden Titel** — aus jedem Tab: wechselt in die Queue und stellt ihn mittig |
| `<` `>` | vorheriger / nächster Titel (die Belegung von `ncmpcpp`, nicht von `mpc` — das schreibt `prev`/`next`) |
| `/` | **Feld für das, was du gerade siehst**: in Alben/Künstler/Genres sucht es nur in dieser Kategorie („Alben · danzig"), in Dateien/Playlists filtert es die geladene Liste („4 von 19", `esc` zeigt wieder alles) — in Queue und Suche bleibt es die globale Suche. **Groß- und Kleinschreibung ist überall egal** („iam" findet auch „IAM") |
| `j` `k`, `↑` `↓`, `pgup` `pgdn`, `g` `G` | bewegen |
| `enter` | öffnen bzw. spielen |
| `a` / `A` | anhängen, was die Zeile ist / alles in dieser Liste |
| `+` `-` · `,` `.` · `space` | lauter/leiser · 5 s zurück/vor · Play/Pause |
| `z` `R` `c` `v` | Zufall, Wiederholen, Consume, Single |
| `d` `D` `C` | Zeile löschen · Queue leeren · nur Laufendes behalten |
| `J` `K` `x` | Queue-Eintrag verschieben · Queue mischen |
| `i` / `/` / `s` / `r` | Songinfo · Suche · Queue speichern · Playlist umbenennen |

<details>
<summary>Alle Tasten im Detail</summary>

- **Suche:** `↓` verlässt das Feld und wählt den **ersten** Treffer, `↑` den
  **letzten** — der Begriff bleibt stehen, `/` holt das Feld zurück, `ctrl+u`
  leert es.
- **Ziffern** bleiben Tab-Wechsel, solange das Suchfeld leer ist: `1` `2` `3`
  führt über Queue → Suche → Alben, ohne als „123" im Feld zu landen. Erst mit
  Text im Feld werden Ziffern zu Suchtext; eine Suche, die mit einer Ziffer
  beginnt, öffnet man mit `/` (die Ansage „ich will tippen").
- **`enter` im Suchfeld** nimmt den markierten Treffer: ein Titel spielt, eine
  Gruppe öffnet.
- **Ein Album aus den Treffern** öffnet sich über die Alben seines Künstlers —
  von den Titeln mit `h`/`esc` also erst zu den **anderen Alben**, ein weiteres
  Mal zurück zu den Treffern.
- **Zurück** geht immer mit `h`, `←`, `backspace` oder `esc`; `esc` räumt von
  oben nach unten ab: Songinfo, eine Ebene, Panel.
- **Künstler ohne Album-Tags** (Sampler): statt leerer Album-Liste direkt die
  Titel.
- Für **gespeicherte Playlists** muss MPDs `playlist_directory` existieren
  (`~/.config/mpd/mpd.conf`).

</details>

## Einstellungen

Tab **8** im Panel — Klick oder `enter` schaltet, `-`/`+` ändert Zahlen, `enter`
auf dem Label-Format öffnet ein Eingabefeld. Währenddessen zeigt die Fußzeile,
was das Muster mit dem **laufenden Titel** macht.

| Einstellung | Wirkung |
| --- | --- |
| Karte beim Zeigen mit der Maus | die Karte unter der Leiste (nur bei geschlossenem Panel — offen ist es schon die große Ansicht) |
| Cover-Hintergrund | Präsenz des Covers im Panel, 0 schaltet es aus; höhere Werte lassen es **weiter nach unten durchlaufen** (bis hinter die letzte Zeile), nicht nur kräftiger |
| Cover im Player | **vier Looks** für das Band: `klassisch`, `scharf`, `hero`, `anker` — `enter` oder `-`/`+` schaltet durch, wirkt sofort |
| Label-Format | `mpc`-Platzhalter für das Label in der Leiste, mit Live-Vorschau |
| Karte bei Titelwechsel | blitzt bei jedem neuen Titel auf — hier ganz abschalten |
| … sichtbar für | wie lange sie dann bleibt; `enter` zeigt sie sofort |
| System-Benachrichtigung bei Titelwechsel | Sprechblase des Desktops (App „MPD") — **unabhängig von der Karte** |

**Vier Looks für das Band** (`Cover im Player`) — dieselben Daten, vier Bilder:

![Die vier Cover-Looks](docs/cover-looks.png)

| Look | Was er macht | Preis |
| --- | --- | --- |
| `klassisch` | weichgezeichnetes Cover hinter dem Panel, 58 px im Band | — |
| `scharf` | dasselbe Band mit 88 px Cover, und das Cover hinter dem Panel bleibt ein **Bild** (Deckkraft + Verlauf statt Unschärfe) | bei hohem „Cover-Hintergrund" präsenter als der weiche — Regler ggf. zurücknehmen |
| `hero` | das Cover **ist** der Hintergrund der Player-Karte, Panel flach | Band höher: rund zwei Listenzeilen weniger |
| `anker` | großes Cover (104 px), alles andere Text und **eine** Bedienzeile, Panel flach | Band höher: rund zwei Listenzeilen weniger |

Alles andere (Server, Port, Passwort, Labelbreite, Scroll-Verhalten, Karten-Dauer
beim Zeigen) steht in den Plugin-Einstellungen bzw. in `shell.json`; Änderungen
greifen ohne Neustart.

## Für Neugierige

**Suchen in der Kategorie.** In den Bibliothek-Tabs sucht `/` nicht global, sondern
in *dieser* Kategorie: `list artist "(artist =~ '(?i)iam')"` — MPD filtert also
selbst. Zwei Eigenheiten von MPD stecken darin: `contains` vergleicht im
`list`-Filter **groß-/kleinschreibungsabhängig** („iam" fand 5 Künstler, „IAM" war
nicht dabei), der Regex-Operator `=~` mit `(?i)` findet beide — deshalb der Regex,
mit `re.escape` für Sonderzeichen und einem Rückfall auf `contains`, falls ein MPD
ohne Regex gebaut wurde. Und MPD will den ganzen Ausdruck als **ein** Argument
(sonst zerlegt es ihn an den Leerzeichen: „Invalid unquoted character"). Zwei
Kategorien auf einmal gehen nicht: dieses MPD verbindet Filter nur mit `AND`, nicht
mit `OR` — was genau der „nur diese Kategorie"-Idee entspricht. In der *globalen*
Suche (Tab 2) ist die Schreibweise ohnehin egal, das ist MPDs eigene Suche. Dateien
und Playlists haben bei MPD keinen Filter (Pfade und Playlistnamen sind keine Tags),
dort filtert das Feld die geladene Liste vor Ort; die Info-Zeile sagt dann „4 von
19", und ein `esc` zeigt wieder alles. Auf MPD 0.20 (NAS) wird daraus ein exakter
Treffer statt eines Teiltreffers.

**Cover-Dateien.** MPD gibt über `albumart` nur Bilddateien heraus, deren Namen es
kennt — in MPD 0.24 ist das `cover.*`. Ein `folder.jpg` daneben wird ignoriert
(gemessen: `albumart` antwortet „No file exists" für `folder.jpg`, `album.jpg` oder
`Album Art.jpg`; dieselben Bytes liefern sofort ein Ergebnis, sobald eine
`cover.jpg` existiert). Deshalb sucht die Bridge selbst im Musikverzeichnis (Pfad
aus MPDs `mpd.conf`, `music_directory`) — und zwar nach Mustern, nicht nach einer
festen Namensliste:

| Rang | trifft zu auf | Beispiel |
| --- | --- | --- |
| 1 | `cover`, `front`, `folder`, `album`, `album art`, `albumart`, `artwork` (exakt) | `folder.jpg` |
| 2 | „front" + „cover/art" irgendwo | `Danzig - Danzig - Front Cover.jpg` |
| 3 | „cover", „artwork" oder „album art" irgendwo | `AlbumArt_{0F838ADF-…}_Large.jpg` |
| 4 | `case`, `scan`, `cd`, `thumb` (exakt) | — |

Innerhalb eines Rangs gewinnt die **größere** Datei (in der Regel der weniger
beschnittene Scan). Namen, die meist die falsche Seite zeigen — `back`, `inside`,
`inlay`, `booklet`, `small`, `disc`, `cd`, `thumb` — werden ans Ende sortiert:
Ein Album mit nur einem Rückseiten-Scan zeigt den trotzdem, aber eine Vorderseite
gewinnt immer. Erlaubte Endungen: `.jpg .jpeg .png .webp .gif .bmp`. Eingebettete
Bilder kommen unverändert über `readpicture`; eine Coverdatei schlägt sie, weil sie
in der Regel die größere ist — dieselbe Reihenfolge, die MPD selbst wählt.
Wichtig: Die Dateien müssen für den Benutzer lesbar sein, unter dem die Bridge
läuft (bei einer Bibliothek auf einem NAS in der Regel kein Problem).



<details>
<summary>Aufbau, Kommandozeile, Feineinstellungen</summary>

**Cover** stehen dort, wo man sie sieht: groß im Band, klein in der Kopfzeile,
groß in der Songinfo — nicht in jeder Queue-Zeile (bei 300 Einträgen wären das
300 MPD-Abfragen und 300 Bilder). Die Bridge cached sie unter
`~/.cache/kokko-mpd`.

**Spektrum** kommt von **cava** (`bin/cava.conf`, 12 Balken, 30 fps) und läuft
nur, solange Musik spielt *und* das Panel offen ist — ungesehen wäre es Arbeit
für niemanden.

**Die Bridge** (`bin/mpd-bridge`, Python, nur stdlib) hält die
MPD-Verbindungen und spricht mit dem Widget über je eine JSON-Zeile pro
Richtung; der Zustand kommt per MPD-`idle`-Push, nicht per Polling. Sie ist ein
**Kindprozess des Widgets**, kein Shell-Service — unter einer Fremd-Leiste
(`charlieras262.floating-bar`) erreicht ein Widget seinen eigenen Service nicht.
Preis: eine Bridge pro Monitor.

**Die Karte** ist eine eigene Layer-Surface mit Eingabemaske nur über der Karte
(der Rest bleibt klickdurchlässig) und wird nur erzeugt, solange sie sichtbar
ist. Kein `PopupWindow`: ein Quickshell-Popup an einer Layer-Surface lässt in
diesem Compositor die Bildschirmaufnahme hängen.

**Angehängt** wird immer als *ein* MPD-Befehl (`findadd`/`searchadd`), nicht als
`add` pro Titel — ein Künstler mit 900 Titeln kostet eine Abfrage. Jede Aktion
meldet sich in der Fußzeile.

**Einstellungen** liegen in `~/.config/omarchy/shell.json` im Widget-Eintrag:
`host`, `port`, `password`, `format`, `maxWidth`, `overflow`, `showArt`,
`showStateIcon`, `whenIdle`, `wheelAction`, `hoverCard`, `backdrop`,
`osdOnChange`, `osdOnHover`, `osdDuration`, `notifyTrack`, `coverLook`.

**Von der Kommandozeile:**

```bash
omarchy-shell kokko.mpd state                 # JSON: Verbindung, Label, Panel, Karte
omarchy-shell -q kokko.mpd toggle             # play/pause (auch next, prev, stop)
omarchy-shell -q kokko.mpd volume +5          # Vorzeichen = nudgen, Zahl = setzen
omarchy-shell -q kokko.mpd option random      # repeat, random, single, consume
omarchy-shell kokko.mpd panel                 # Panel auf/zu
omarchy-shell kokko.mpd tab artists           # Tab setzen
omarchy-shell kokko.mpd find "kate bush"      # Suche ausführen
omarchy-shell kokko.mpd key j                 # Tastendruck simulieren
omarchy-shell kokko.mpd hover on              # Karte ohne Maus zeigen (Screenshots/Tests)
omarchy-shell kokko.mpd debug on              # Protokoll aufs Shell-Log
```

**Hyprland** (`~/.config/hypr/bindings.lua`):

```lua
o.bind("SUPER + CTRL + M", "MPD player", "omarchy-shell kokko.mpd panel")
o.bind("XF86AudioPlay", "Play/pause", "omarchy-shell -q kokko.mpd toggle", { locked = true })
o.bind("XF86AudioNext", "Nächster Titel", "omarchy-shell -q kokko.mpd next", { locked = true })
o.bind("XF86AudioPrev", "Vorheriger Titel", "omarchy-shell -q kokko.mpd prev", { locked = true })
```

</details>

## Tests

Alles, was sich ohne Klick prüfen lässt, läuft in einem Aufruf:

```sh
tests/run.sh            # alles, inklusive Rauchtest gegen ein laufendes MPD
tests/run.sh --fast     # ohne MPD -- das benutzt der pre-commit-Hook
tests/install-hooks.sh  # einmal pro Klon: aktiviert den Hook
```

Der Hook ist der eigentliche Grund für die Tests: **ein QML-Syntaxfehler ist hier
unsichtbar** — die Shell startet, das Widget ist einfach weg, ohne Meldung.
`qmllint` findet ihn (`omarchy plugin validate` tut das nicht), deshalb läuft er vor
jedem Commit. Im Notfall: `git commit --no-verify`.

Geprüft wird zweierlei. Ohne MPD: die reinen Python-Teile der Bridge — Cover-Auswahl
mit Rangfolge und Größenlimit, der Filterausdruck samt beider Escape-Schichten, der
Cache-Schlüssel, der Bildtyp, `music_directory` aus `mpd.conf`. Dazu `qmllint` und
`omarchy plugin validate`. Mit laufendem MPD: dass die Bridge antwortet, ein Cover
holt, und dass Titel mit Sonderzeichen (`#1's …`, `( O )( O )( O ), cl-018`) sich
über den Filterausdruck selbst finden.

Was **nicht** automatisch geht, steht als Issue im Repo (Mauspfade, `crop`) — die
brauchen einen Menschen mit Zeiger.

## Herkunft

`bin/mpd-bridge` und `Format.js` stammen aus
[matjam/omajam](https://github.com/matjam/omajam) (MIT, Copyright (c) 2026
Nathan Ollerenshaw) — Änderungen siehe `NOTICE.md`. `BarWidget.qml`, `Panel.qml`,
`MiniPlayer.qml` und `Visualizer.qml` sind eigenständig.

Das Plugin wohnt in einem eigenen Repo mit Issue-Tracker:
**https://git.m2control.de/bm/omarchympd** — Fehler und Wünsche gehören dorthin,
nicht in eine Chat-Sitzung, die morgen vergessen ist.

## Später / offen

Die offenen Punkte stehen im **Issue-Tracker** des Repos
(https://git.m2control.de/bm/omarchympd/issues) — mit Labels, Milestone und einem
„fertig, wenn" pro Eintrag. Nach Nutzen sortiert, nicht nach Aufwand:

1. **Mauspfade von Hand durchspielen** — die vier Band-Looks, Fortschritt ziehen,
   🗑 und `+` in den Listenzeilen, `crop`. Tastatur- und IPC-Pfade sind geprüft,
   echte Klicks nicht (in dieser VM nicht auslösbar).
2. **cava sichtbar machen, wenn es fehlt** — sonst bleibt das Band stumm leer
   statt „cava fehlt" zu sagen.
3. **Kategoriesuche auch in der Queue** (`playlistsearch`).
4. **Auslieferung**: Tag, Release und `omarchy plugin add`; danach das
   Marketplace-Listing (dafür müsste das Repo öffentlich sein).
5. **Kleinkram**: Sortierung der Listen wählbar, Sortierung der Looks, zwei
   Sicherungen bzw. Kommentare in der Bridge — die genauen Zuschnitte und die
   Begründung, warum zwei davon *keine* Bugs sind, stehen in den Issues.

Bewusst **nicht** geplant: `bin/mpd-bridge` in Module zerlegen oder `with_cmd`
umschreiben. Die Datei ist eine gepflegte Kopie von omajam (siehe `NOTICE.md`);
ein Modulschnitt würde den Upstream-Vergleich zerstören und damit mehr kosten als
die Struktur einbringt.
