# kokko.mpd

MPD in der Omarchy-Leiste: was gerade läuft mit Label, Cover und Transport —
ein Klick öffnet das Panel mit Queue, lokaler Suche, Bibliothek nach
Alben/Künstlern/Genres, Dateibaum und gespeicherten Playlists.

Repository: `ssh://git@git.m2control.de:222/bm/omarchympd.git` — das Repo heißt
nach dem Projekt, die **Plugin-ID bleibt `kokko.mpd`** (der Ordner unter
`~/.config/omarchy/plugins/`).

```
omarchy plugin enable kokko.mpd --section center   # eintragen
omarchy restart shell                              # laden
```

## In der Leiste

Das Widget zeigt **Icon und Titel** — die Bedienknöpfe stehen in der Karte
(Zeiger drauf) und im Panel-Band, nicht mehr in der Leiste.

| | |
| --- | --- |
| Linksklick | Panel öffnen |
| Mittelklick | nächster Titel |
| Scrollen | je nach `wheelAction`: Lautstärke, Spulen oder Titelwechsel |
| Zeiger drauf | Karte mit Cover, Titel, Fortschritt, **großen** Transport- und Optionsknöpfen (abschaltbar über `hoverCard`) |

Bei Titelwechsel erscheint eine Karte kurz unten in der Mitte; optional
eine Desktop-Benachrichtigung mit Cover (`notifyTrack`).

Einstellungen liegen in `~/.config/omarchy/shell.json` im Widget-Eintrag:
`host`, `port`, `password`, `format`, `maxWidth`, `overflow`, `showArt`,
`showStateIcon`, `whenIdle`, `wheelAction`, `hoverCard`, `backdrop`,
`osdOnChange`, `osdOnHover`, `osdDuration`, `notifyTrack`.
Änderungen dort greifen ohne Shell-Neustart.

## In die Queue legen

- **Aus der Suche:** `/`, dann tippen (`prince`) — gesucht wird während des
  Tippens. Die Treffer sind nach **Künstler** und **Album** gruppiert, jeweils mit
  Trefferzahl, darunter die einzelnen Titel.
  - **Tippen filtert, Pfeile wählen aus:** `↓` verlässt das Feld und setzt die
    Auswahl auf den **ersten** Treffer, `↑` auf den **letzten**. Der Suchbegriff
    bleibt stehen — `/` holt das Feld mit dem Begriff zurück, `ctrl+u` leert es.
    Ab dem Moment gehören die Tasten der Liste: `a` hängt an, `enter` öffnet,
    `j`/`k` bewegen, `i` zeigt die Songinfo.
  - **Die Ziffern bleiben Tab-Wechsel**, solange das Feld leer ist: `1` `2` `3`
    nacheinander führt also über Queue → Suche → Alben, ohne als „23" im
    Suchfeld zu landen. Erst wenn Text im Feld steht, sind Ziffern Suchtext.
  - **Eine Suche, die mit einer Ziffer beginnt** (z. B. „2 Unlimited"): erst `/`
    drücken — das ist die ausdrückliche Ansage „ich will tippen". Dann sind auch
    Ziffern Suchtext. Dasselbe gilt für ein leeres, per `/` geöffnetes Feld.
  - `enter` **im Feld** nimmt den markierten Treffer: einen Titel spielt es (Feld
    bleibt offen, für die nächste Suche), eine Gruppe öffnet es.
  - `a` oder das **`+`** rechts in der Zeile hängt an, was die Zeile *ist*: alle
    Titel des Künstlers, das ganze Album, oder den einzelnen Titel.
  - `A` hängt alle Treffer der Suche an.
  - **Ein Album aus den Treffern** öffnet sich über die Alben seines Künstlers:
    `h` bzw. `esc` führt aus den Titeln also zu den **anderen Alben desselben
    Künstlers**, ein weiteres Mal zurück zu den Treffern.
  - **Künstler ohne Album-Tags** (z. B. Sampler-Tracks): statt einer leeren
    Album-Liste erscheinen direkt die Titel — kein leerer Frame.
  - Zurück geht immer mit **`h`**, **`←`**, **`backspace`** oder **`esc`** — die
    Fußzeile nennt es jeweils. `esc` räumt dabei von oben nach unten ab: erst die
    Songinfo, dann eine Ebene, am Anfang das Panel.
- **Aus der Bibliothek:** Alben/Künstler/Genres-Tab, `enter` hinein, `a` auf einem
  Album hängt das Album an, `A` auf der Künstlerebene alles darunter.
- **Aus dem Dateibaum:** `enter` in einen Ordner, `a` hängt alles darunter an
  (`A` im Ordner dasselbe von der Ordnerzeile aus), `a` auf einer Datei nur sie.
- **Playlists:** `a` lädt die Liste (ersetzt die Queue), `a` in einer offenen Liste
  hängt einzelne Titel an.

Angehängt wird immer als **ein** MPD-Befehl (`findadd`/`searchadd`), nicht als
`add` pro Titel — ein Künstler mit 900 Titeln kostet eine Abfrage. Jede Aktion
meldet sich in der Fußzeile („angehängt: …"); findet ein Filter nichts, sagt MPD
von sich aus nur OK, deshalb reicht die Bridge das als Meldung durch.

Die Fußzeile zeigt außerdem jederzeit, welche Tasten in der aktuellen Ansicht
etwas tun — `a` und `A` muss man also nicht auswendig kennen.

## Cover, Karte, Spektrum

- **Cover** stehen dort, wo man sie sieht: groß im Band des Panels (was läuft),
  als kleine Marke in der Kopfzeile (was gerade ausgewählt ist) und groß in der
  Songinfo (`i`). Nicht in jeder Queue-Zeile — das wären bei 300 Einträgen
  300 MPD-Abfragen und 300 Bilder. Die Bridge cached Cover je Album unter
  `~/.cache/kokko-mpd`; fehlt eines, steht dort ein Glyph.
- **Hinter dem Panel** liegt das Cover des laufenden Titels als Hintergrund.
  **`backdrop`** (0–100, Standard 60) regelt, wie präsent es ist: 0 schaltet es
  aus, höhere Werte heben Deckkraft, Sättigung und Schärfe **gemeinsam** an —
  einzeln betrachtet bringt nur mehr Deckkraft ein matschiges Bild und nur
  weniger Unschärfe einen unruhigen Hintergrund. Nach unten verblasst der
  Hintergrund in die Panel-Farbe; je höher der Wert, desto später beginnt diese
  Blende, desto mehr Cover steht über der Liste. Bei **hellen Covern** leidet ab
  etwa 85 die Lesbarkeit der Kopf- und ersten Zeilen — 60–75 ist der ruhige
  Bereich. Ohne Cover (oder mit `backdrop: 0`) bleibt das Panel einfarbig.
  Technik: `Image` (`visible: false`) + `MultiEffect` aus `QtQuick.Effects` —
  dasselbe Muster wie im Sperrbildschirm der Shell.
- **Die Karte beim Überfahren** (`hoverCard`) ist die Kurzfassung des Panels:
  Cover, Titel, Interpret · Album · Position, Fortschritt (ziehen = spulen),
  **große** Knöpfe ⏮ ⏸ ⏭, Zufall/Repeat und die Lautstärke (Rad über der Karte;
  die Zahlenanzeige dafür gibt es nicht mehr). Das Spektrum ist hier bewusst
  nicht — der Platz gehört den Knöpfen.
  Sie bleibt offen, solange der Zeiger auf dem Widget *oder* auf der Karte
  steht — die 280 ms dazwischen sind die Gnadenfrist, um die Lücke zu
  überqueren. Klick auf die Karte öffnet das Panel.
- **Bei Titelwechsel** erscheint dieselbe Karte kurz unten in der Mitte
  (`osdOnChange`); sie nimmt keine Klicks an. Wer die Karte auch beim Überfahren
  als einfache Anzeige will, schaltet `osdOnHover` ein.
- **Das Spektrum** kommt von **cava** (`/usr/bin/cava`, Konfiguration
  `bin/cava.conf`, 12 Balken bei 30 fps) und steht im **Panel-Band**. Der
  Prozess läuft nur, solange etwas spielt *und* das Panel offen ist — cava liest
  das Audiogerät, ungesehen wäre es Arbeit für niemanden.
  Prüfen: `pgrep -a cava`, Werte stehen in `omarchy-shell kokko.mpd state` als
  `viz` und `vizRunning`.

## Einstellungen im Panel

Tab **8** („Einstellungen") — für die Werte, die man beim Hören anfasst:

| Einstellung | Wirkung |
| --- | --- |
| Karte beim Überfahren | die Karte mit Cover, Fortschritt und den großen Knöpfen unter der Leiste |
| Cover-Hintergrund | Präsenz des weichgezeichneten Covers hinter dem Panel (0 = aus) |
| Label-Format | `mpc`-Platzhalter für das Label in der Leiste, mit **Live-Vorschau** |
| Karte sichtbar | wie lange die Karte bei Titelwechsel stehen bleibt (ms) |
| Benachrichtigung bei Titelwechsel | Desktop-Hinweis mit Cover |

Bedienung: `enter`/`space` schaltet um, `-`/`+` ändert Zahlen (0–100 in
10er-Schritten bzw. 500 ms), `enter` auf dem Label-Format öffnet ein Eingabefeld
— währenddessen zeigt die Fußzeile, was das Muster mit dem **laufenden Titel**
macht (`→ Air - Kelly, Watch The Stars! …`), `enter` speichert, `esc` bricht ab.

Geschrieben wird über die Shell (`omarchy-shell shell setBarWidget`), also
derselbe Weg wie im Plugin-Einstellungsdialog: **ein** Schreiber für
`shell.json`, und die Änderung greift sofort. Der Tab braucht keine Verbindung
zu MPD — er ist auch erreichbar, wenn der Server aus ist.

## Queue aufräumen

- **Einzelne Titel:** das **🗑** rechts in der Zeile anklicken oder `d`. In einer
  Playlist entfernt dieselbe Taste den Titel aus der Playlist (die Datei bleibt).
- **Ganze Queue:** `D` oder der **Papierkorb-Knopf** im Band (MPD `clear`). Der
  Zeiger darauf nennt unten die ausgeschriebene Bedeutung.
- **Nur das Laufende behalten:** `C` oder der **Scheren-Knopf** im Band
  (MPD `crop`). Beides geschieht sofort; die Fußzeile meldet es.

## Im Panel

Oben das **Band** mit Cover, Fortschritt, Spektrum, den Transport-, Zufall-/
Wiederholen- und Queue-Knöpfen — der eine Controller. Die Options-Glyphen sind
orange, wenn die Option an ist, grau wenn aus. Unten eine Zeile mit dem, was
gerade passiert, und den Tasten, die hier etwas tun. Die Kopfzeile zeigt nur `MPD` und
den Pfad (z. B. `Queue`); Adresse und MPD-Version erscheinen nur, wenn keine
Verbindung steht — dann mit der Fehlermeldung.

| Taste | Wirkung |
| --- | --- |
| `1` … `8`, `tab` | Queue · Suche · Alben · Künstler · Genres · Dateien · Playlists · Einstellungen — die Ziffern wirken auch bei leerem Suchfeld |
| `j` `k`, `↑` `↓`, `ctrl+u` `ctrl+d`, `pgup` `pgdn` | bewegen |
| `g` `G` | Anfang / Ende |
| `enter`, `l` | öffnen — Ordner/Album/Künstler bzw. abspielen |
| `h`, `←`, `backspace` | eine Ebene zurück |
| `a` | anhängen: Titel, Album, Künstler oder Ordner — was die Zeile ist |
| `+` (Maus) | dasselbe, rechts in der Zeile |
| `A` | alles anhängen, was diese Liste ist (alle Treffer / die ganze Liste) |
| `d` `D` | löschen: Queue-Eintrag, Playlist, Playlist-Titel / Queue leeren |
| `C` | nur den laufenden Titel behalten (MPD `crop`) |
| 🗑 (Maus) | Queue-Eintrag bzw. Playlist-Titel löschen — rechts in der Zeile |
| `J` `K` | Queue-Eintrag verschieben |
| `x` | Queue mischen |
| `i` | Songinfo: alle Tags, die MPD kennt |
| `/` | Suchfeld öffnen (wechselt auf den Suche-Tab) |
| tippen | die Suche läuft während der Eingabe, Trefferzahl steht in der Fußzeile |
| `ctrl+u` | Suchfeld leeren |
| `s` | Queue als Playlist speichern |
| `r` | Playlist umbenennen (im Playlists-Tab) |
| `space`, `p` | Play/ Pause |
| `z` `R` `c` `v` | Repeat, Random, Consume, Single — Zufall und Wiederholen auch als Knopf im Band |
| `+` `-` | Lautstärke ±5 |
| `,` `.` | 5 s zurück / vor |
| `esc` | Songinfo schließen → eine Ebene zurück → am Anfang das Panel schließen |

Kein Netz: gesucht wird im MPD-Index (alle Tags), Cover kommen aus den Tags
bzw. der Datei daneben und werden unter `~/.cache/kokko-mpd` zwischengespeichert.

Gesucht wird beim Tippen (250 ms Ruhe, danach eine MPD-Abfrage — die Bridge
verwirft die überholte Query auf demselben Kanal, also kostet ein Wort eine
Abfrage statt einer pro Taste). Ein `/` im leeren Suchfeld ist die Geste, die das
Feld öffnet, und wird nicht als Zeichen übernommen; `enter` lässt das Feld offen,
`esc` verlässt es, `tab` wechselt weiter den Tab.

Für gespeicherte Playlists muss MPDs `playlist_directory` existieren
(`~/.config/mpd/mpd.conf`); fehlt der Ordner, antwortet MPD auf `listplaylists`
mit einem Fehler, den das Panel anzeigt.

## Von der Kommandozeile

```bash
omarchy-shell kokko.mpd state                 # JSON: Zustand, Label, Panel, OSD
omarchy-shell -q kokko.mpd toggle             # play/pause (auch next, prev, stop, play, pause)
omarchy-shell -q kokko.mpd volume +5          # Vorzeichen = nudgen, Zahl = setzen
omarchy-shell -q kokko.mpd seek 90
omarchy-shell -q kokko.mpd option random      # repeat, random, single, consume
omarchy-shell kokko.mpd panel                 # Panel auf/zu
omarchy-shell kokko.mpd osd                   # Karte zeigen
omarchy-shell kokko.mpd notify                # Benachrichtigung zeigen
omarchy-shell kokko.mpd tab artists           # Tab setzen (queue|search|albums|artists|genres|files|playlists)
omarchy-shell kokko.mpd find "kate bush"      # Suche im Panel ausführen
omarchy-shell kokko.mpd files "Rock/Wire"     # Dateibaum dorthin stellen
omarchy-shell kokko.mpd select 7              # Auswahl setzen
omarchy-shell kokko.mpd key j                 # Tastendruck simulieren (j k h l g enter esc tab up down space i)
omarchy-shell kokko.mpd hover on              # Karte ohne Maus öffnen (on|off), für Screenshots/Tests
omarchy-shell kokko.mpd crop                  # nur den laufenden Titel in der Queue behalten
omarchy-shell kokko.mpd debug on              # Query/Antwort-Protokoll aufs Shell-Log
```

Hyprland-Bindings (`~/.config/hypr/bindings.lua`, bei mir bereits eingetragen):

```lua
o.bind("SUPER + CTRL + M", "MPD player", "omarchy-shell kokko.mpd panel")
o.bind("XF86AudioPlay", "Play/pause", "omarchy-shell -q kokko.mpd toggle", { locked = true })
o.bind("XF86AudioNext", "Nächster Titel", "omarchy-shell -q kokko.mpd next", { locked = true })
o.bind("XF86AudioPrev", "Vorheriger Titel", "omarchy-shell -q kokko.mpd prev", { locked = true })
```

## Aufbau

`bin/mpd-bridge` (Python, nur stdlib) hält die MPD-Verbindungen über TCP oder
einen Unix-Socket und spricht mit dem Widget über je eine JSON-Zeile pro
Richtung: Kommandos und Queries hinein, `state`/`art`/`database`/`result`
heraus. Der Zustand kommt per MPD-`idle`-Push, es wird nicht gepollt. Queries
tragen einen `channel`: eine ältere Query auf demselben Kanal wird verworfen,
damit Tippen im Suchfeld eine Abfrage kostet statt einer pro Taste.

Die Bridge ist ein **Kindprozess des Widgets**, nicht ein Shell-Service: unter
einer Fremd-Leiste (`charlieras262.floating-bar`) kann ein Widget seinen
eigenen Service nicht erreichen — deshalb hat dieses Plugin kein
`service`-Kind. Preis: eine Bridge pro Monitor, auf einem Monitor also eine.

Die **Karte** ist eine eigene Layer-Surface (`kokko-mpd-card`), bildschirmbreit
und nur so hoch wie die Karte; die Eingabemaske (`mask`) deckt nur die Karte ab,
der Rest bleibt klickdurchlässig. Kein `PopupWindow`: ein Quickshell-Popup an
einer Layer-Surface lässt in diesem Compositor die Bildschirmaufnahme hängen
(`grim` lief minutenlang nicht mehr). Aus demselben Grund wird das
**OSD-Fenster** nur erzeugt, solange es sichtbar ist — eine gemappte Fläche ohne
gezeichneten Puffer blockiert Screencopy ebenfalls.

Das Spektrum hängt an einem **cava**-Kindprozess des Widgets (`bin/cava.conf`,
rohe ASCII-Balken, ein Frame pro Zeile); das Widget reicht die Werte als
`vizBars` an das Panel-Band weiter und lässt den Prozess laufen, solange dieser
sichtbar ist und Musik läuft.

Das Panel hält seine Position als Stapel von Frames (Queue, Tag-Werte,
Titel-Listen, Verzeichnisse, Playlists); `h`/`l` gehen darin auf und ab, die
Kopfzeile zeigt den Pfad. Antworten tragen eine Generation, damit eine spät
eintreffende Antwort keine neuere Ansicht überschreibt.

## Herkunft

`bin/mpd-bridge` und `Format.js` stammen aus [matjam/omajam](https://github.com/matjam/omajam)
(MIT, Copyright (c) 2026 Nathan Ollerenshaw) — siehe `NOTICE.md` für die
Änderungen. `BarWidget.qml` und `Panel.qml` sind eigenständig.

## Noch offen

- **Einstellungen im Panel:** erledigt (Tab 8) für die fünf Werte, die man beim
  Hören anfasst. Server/Port/Passwort und die Feineinstellungen (`maxWidth`,
  `overflow`, `whenIdle`, `wheelAction`, `showArt`, `showStateIcon`, `osdOnChange`,
  `osdOnHover`) bleiben in den Plugin-Einstellungen bzw. `shell.json`.
- Sortierung der Listen wählbar.
