import QtQuick
import qs.Commons
import Qt5Compat.GraphicalEffects

// The chassis every band look is built on (the seven looks are the table in
// README.md).
//
// A look decides one thing: how the cover is drawn -- `cover`, plus the size the
// picture needs. Everything else is built once, here, and therefore reads the
// same in all seven: title, meta line, clock, progress with click-and-drag seek,
// transport, spectrum. The seven files exist so `coverLook` can pick one, not so
// each of them can invent its own grammar for the same song.
//
// `cover: "none"` is the look whose identity is the missing picture, so the band
// collapses to a single line: with nothing to sit beside, a second row would be
// a block of empty air. Every other mode keeps the full block.
//
// The band owns its height (`implicitHeight`) so a look may be taller or shorter
// than another -- the panel only anchors it and lets the list follow its bottom.
// It owns no state: everything comes from the widget, and the two things it has
// to say (the flash line and the hover explanation) go back as signals, so the
// band never has to know the panel's footer.
Item {
  id: band

  property var host: null
  property string fontFamily: Style.font.family
  property var vizBars: []
  property int vizCount: 12

  signal message(string text)     // a line for the footer, e.g. "Shuffle on"
  signal hint(string text)        // explanation while the pointer rests on a glyph

  // How the picture is drawn. The seven looks map onto it like this:
  //   thumb  classic, sharp  -- rounded square beside the text
  //   big    anchor          -- the same square, as tall as the band allows
  //   card   hero            -- the square, plus the artwork as the card's own background
  //   disc   vinyl           -- round platter, spinning while it plays
  //   column split           -- full-height block against the left edge
  //   none   minimal         -- no picture at all, one line
  property string cover: "thumb"
  // The picture's side; for `column` its width.
  property real coverSize: Style.space(58)

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true
  readonly property string art: hasSong && host.artPath !== "" ? host.artPath : ""
  // What the picture is decoded at: 2.5x the side it is drawn with, enough for the
  // scale in use and one rule instead of a size table per look.
  readonly property int artDecode: Math.round(Math.max(160, band.coverSize * 2.5))
  // The thin look: no picture, so no second row to put anything in either.
  readonly property bool oneLine: cover === "none"

  // Never shorter than the picture plus a little air, otherwise a bigger cover
  // sticks out over the header rule and the list.
  readonly property real floorHeight: cover === "disc" ? Style.space(88) : Style.space(74)
  readonly property real coverAir: cover === "big" ? Style.space(22) : Style.space(12)

  implicitHeight: {
    if (!band.hasSong) return 0
    if (band.oneLine) return Style.space(38)
    // A full-height block cannot size the band: here the band sizes the block.
    if (band.cover === "column") return Style.space(112)
    return Math.max(band.floorHeight, band.coverSize + band.coverAir)
  }
  visible: implicitHeight > 0

  readonly property string title: {
    if (!band.hasSong) return ""
    return String(band.host.song.title || "") || band.host.basename(band.host.song.file)
  }

  // artist · album · #pos/len -- and nothing that only repeats the title, or a
  // track whose album tag is its own name would stand there twice.
  readonly property string meta: {
    if (!band.hasSong) return ""
    var bits = []
    var artist = String(band.host.song.artist || "")
    var album = String(band.host.song.album || "")
    if (artist !== "" && artist.toLowerCase() !== band.title.toLowerCase()) bits.push(artist)
    if (album !== "" && !band.oneLine && album.toLowerCase() !== band.title.toLowerCase()) bits.push(album)
    if (band.host.queueLength > 0)
      bits.push("#" + (band.host.queuePosition + 1) + "/" + band.host.queueLength)
    return bits.join("  ·  ")
  }

  // -------------------------------------------------------------------- card
  Rectangle {
    id: card
    anchors.fill: parent
    color: Util.alpha(band.fg, 0.05)
    radius: Style.cornerRadius
    clip: true

    // "card": the artwork is the card's own background, washed out under a
    // gradient -- the text standing on it has to stay readable.
    Image {
      anchors.fill: parent
      source: band.cover === "card" ? band.art : ""
      sourceSize.width: 900
      sourceSize.height: 400
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      opacity: 0.34
      visible: band.cover === "card" && status === Image.Ready
    }

    Rectangle {
      anchors.fill: parent
      visible: band.cover === "card"
      gradient: Gradient {
        GradientStop { position: 0.0; color: Util.alpha(Color.popups.background, 0.46) }
        GradientStop { position: 0.5; color: Util.alpha(Color.popups.background, 0.72) }
        GradientStop { position: 0.80; color: Color.popups.background }
        GradientStop { position: 1.0; color: Color.popups.background }
      }
    }
  }

  // ------------------------------------------------------------------- cover
  // The one thing a look decides. A click on it toggles the playback, the same
  // gesture in every look -- it is the only part of the band that is a picture
  // and the obvious thing to click.
  Item {
    id: coverBox
    visible: !band.oneLine

    // A rounded square beside the text -- or, for `column`, a slab against the
    // card's left edge over the full height.
    x: band.cover === "column" ? 0 : Style.space(8)
    y: band.cover === "column" ? 0 : (band.height - height) / 2
    width: band.coverSize
    height: band.cover === "column" ? band.height : band.coverSize

    Rectangle {
      id: plate
      anchors.fill: parent
      // No radius of its own for the column: the card's clip rounds it. A radius on
      // all four corners would round the inner edge too, and that reads as a
      // mistake once the two columns sit flush.
      radius: band.cover === "disc" ? width / 2
        : (band.cover === "column" ? 0 : Style.cornerRadius)
      color: Util.alpha(band.fg, 0.06)
      border.width: band.cover === "column" ? 0 : Math.max(1, Style.normalBorderWidth)
      border.color: band.line
      clip: true
      rotation: 0

      // Only the disc turns, and `paused` rather than `running`: that freezes the
      // interpolation where it is, so the record carries on from its angle instead
      // of jumping back to 0 degrees after a pause.
      RotationAnimation on rotation {
        paused: !(band.cover === "disc" && band.hasSong && band.host.isPlaying)
        loops: Animation.Infinite
        from: 0; to: 360
        duration: 9000
      }

      // The disc cuts its picture with a mask: this runtime clips a Rectangle on
      // its bounding box only, so radius+clip would give a square. An elliptical
      // maskSource does the real (antialiased) cut.
      Rectangle {
        id: discShape
        anchors.fill: parent
        radius: width / 2
        color: "white"
        visible: false
      }

      Image {
        id: coverImage
        anchors.fill: parent
        source: band.art
        // Decode at 2.5x what is drawn: enough for the scale in use, and one rule
        // instead of a size table per look.
        sourceSize.width: band.artDecode
        sourceSize.height: band.artDecode
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: band.cover !== "disc" && status === Image.Ready
      }

      // OpacityMask (Qt5Compat) is the proven way to clip to a shape here --
      // MultiEffect's maskSource did not cut in this runtime.
      OpacityMask {
        anchors.fill: parent
        source: coverImage
        maskSource: discShape
        visible: band.cover === "disc" && coverImage.status === Image.Ready
      }

      // No artwork: a glyph instead of an empty hole.
      Text {
        anchors.centerIn: parent
        visible: coverImage.status !== Image.Ready
        text: band.host && band.host.isPlaying ? "󰏤" : "󰐊"
        color: band.accent
        font.family: band.fontFamily
        font.pixelSize: Style.font.displayLarge
      }

      // The spindle: only worth drawing once there is a photo to sit on top of.
      Rectangle {
        anchors.centerIn: parent
        visible: band.cover === "disc" && coverImage.status === Image.Ready
        width: Style.space(12); height: width; radius: width / 2
        color: Util.alpha("#000000", 0.55)
        border.width: 1
        border.color: Util.alpha("#ffffff", 0.18)
      }
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: if (band.host) band.host.toggleTrack()
    }
  }

  // -------------------------------------------------------------------- text
  // Title and meta line. The thin look has one line for both, so there the meta
  // follows the title instead of standing under it.
  Column {
    id: heading
    anchors {
      left: parent.left
      leftMargin: band.oneLine ? Style.space(12)
        : (band.cover === "column" ? band.coverSize + Style.space(16)
           : Style.space(8) + band.coverSize + Style.space(14))
      right: band.oneLine ? progress.left : viz.left
      rightMargin: Style.space(12)
      verticalCenter: parent.verticalCenter
      // The progress line hangs under this column, so the pair is centred by
      // lifting the column by half of what the line adds.
      verticalCenterOffset: band.oneLine ? 0 : -(progress.height + heading.spacing) / 2
    }
    spacing: Style.space(3)

    Text {
      id: titleText
      width: parent.width
      // On the one line the meta follows the title, separated exactly the way it is
      // in its own line everywhere else.
      text: band.oneLine && band.meta !== "" ? (band.title + "  ·  " + band.meta) : band.title
      // Never the accent: the accent marks state (playing, on), the title is text.
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      id: metaText
      width: parent.width
      visible: !band.oneLine
      text: band.meta
      color: band.dim
      font.family: band.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }

  // ---------------------------------------------------------------- progress
  // One line for every look: elapsed on the left, duration on the right, the bar
  // between them, tabular figures so the clock does not jitter. The seek is one
  // gesture too: a press and a drag move the fill, and one command goes out when
  // the pointer is released -- a drag would otherwise flood the server (the
  // desktop card and the hover card do it the same way).
  Item {
    id: progress
    height: Style.space(16)
    // The thin line is as long as it needs to be, not as long as the band; the
    // full block fills the width of the text above it.
    width: band.oneLine ? Style.space(180) : heading.width
    // The look decides where the line sits; its insides are the same everywhere.
    anchors {
      left: band.oneLine ? undefined : heading.left
      top: band.oneLine ? undefined : heading.bottom
      topMargin: heading.spacing
      right: band.oneLine ? buttons.left : undefined
      rightMargin: Style.space(14)
      verticalCenter: band.oneLine ? parent.verticalCenter : undefined
    }

    // While the pointer drags, it wins over the clock: the line has to follow the
    // hand and not jump back under it between two events.
    property bool dragging: false
    property real dragFrac: -1
    readonly property real fraction: (band.host && band.host.duration > 0)
      ? Math.max(0, Math.min(1, band.host.elapsed / band.host.duration)) : 0
    readonly property real displayFrac: (dragging && dragFrac >= 0) ? dragFrac : fraction

    Text {
      id: elapsed
      anchors { left: parent.left; verticalCenter: parent.verticalCenter }
      text: band.hasSong ? band.host.formatTime(band.host.elapsed) : ""
      color: band.faint
      font.family: band.fontFamily
      font.pixelSize: Style.font.caption
      font.features: { "tnum": 1 }
    }

    Text {
      id: duration
      anchors { right: parent.right; verticalCenter: parent.verticalCenter }
      text: band.hasSong && band.host.duration > 0
        ? band.host.formatTime(band.host.duration) : ""
      color: band.faint
      font.family: band.fontFamily
      font.pixelSize: Style.font.caption
      font.features: { "tnum": 1 }
    }

    Rectangle {
      id: bar
      anchors { left: elapsed.right; leftMargin: Style.space(8)
                right: duration.left; rightMargin: Style.space(8)
                verticalCenter: parent.verticalCenter }
      height: Style.space(4)
      radius: height / 2
      color: band.line

      Rectangle {
        width: parent.width * progress.displayFrac
        height: parent.height
        radius: parent.radius
        color: band.accent
      }
    }

    MouseArea {
      anchors { left: bar.left; right: bar.right; top: parent.top; bottom: parent.bottom }
      cursorShape: Qt.PointingHandCursor
      onPressed: function(mouse) {
        if (!band.hasSong || band.host.duration <= 0) return
        progress.dragging = true
        progress.dragFrac = Math.max(0, Math.min(1, mouse.x / width))
      }
      onPositionChanged: function(mouse) {
        if (progress.dragging) progress.dragFrac = Math.max(0, Math.min(1, mouse.x / width))
      }
      onReleased: function(mouse) {
        if (!progress.dragging) return
        var frac = Math.max(0, Math.min(1, mouse.x / width))
        progress.dragging = false
        progress.dragFrac = -1
        band.host.bare("seek " + Math.round(frac * band.host.duration))
      }
      // A press that is taken away (the pointer leaves the surface) must not leave
      // the line frozen under a finger that is gone.
      onCanceled: { progress.dragging = false; progress.dragFrac = -1 }
    }
  }

  // ---------------------------------------------------------------- spectrum
  // Only while something plays: with cava stopped the levels are gone and every
  // bar would sit at its 2 px floor -- a frozen spectrum that claims something is
  // happening. One rule for every look.
  Visualizer {
    id: viz
    anchors { right: buttons.left; rightMargin: Style.space(14)
              verticalCenter: parent.verticalCenter }
    width: Style.space(150)
    height: Style.space(30)
    visible: !band.oneLine && band.host !== null && band.host.isPlaying
    levels: band.vizBars
    count: band.vizCount
  }

  // --------------------------------------------------------------- transport
  Row {
    id: buttons
    anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    spacing: Style.space(16)
    // Explicit height: the children say `height: parent.height`, and a Row whose
    // height comes from its children would resolve that to 0 -- which is exactly
    // how these buttons disappeared once.
    height: Style.space(30)

    Text {
      text: "󰒮"
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                  onClicked: if (band.host) band.host.previousTrack() }
    }

    // Play/pause keeps the one filled shape in this row (26 px inside the
    // 74 px band) while the neighbours stay flat glyphs: a disc carries the
    // accent and says which of the two the click does, and it is the same
    // component the hover card and the desktop card use.
    PlayButton {
      anchors.verticalCenter: parent.verticalCenter
      size: Style.space(26)
      host: band.host
      accentColor: band.accent
      fontFamily: band.fontFamily
    }

    Text {
      text: "󰒭"
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                  onClicked: if (band.host) band.host.nextTrack() }
    }

    // The same two playback options the hover card offers, in the same colours:
    // accent while on, dim while off. Not on the thin line: a line built to be thin
    // should not grow a second block of controls to fit them back in -- they are
    // one tap away in the hover card and the settings tab.
    Text {
      visible: !band.oneLine
      text: band.host && band.host.randomOn ? "󰒝" : "󰒞"
      color: band.host && band.host.randomOn ? band.accent : band.dim
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          if (!band.host) return
          var on = !band.host.randomOn
          band.host.toggleOption("random")
          band.message(on ? "Shuffle on" : "Shuffle off")
        }
      }
    }

    Text {
      visible: !band.oneLine
      text: band.host && band.host.repeatOn
        ? (band.host.singleMode !== "0" ? "󰑘" : "󰑖") : "󰑗"
      color: band.host && band.host.repeatOn ? band.accent : band.dim
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          if (!band.host) return
          var on = !band.host.repeatOn
          band.host.toggleOption("repeat")
          band.message(on ? "Repeat on" : "Repeat off")
        }
      }
    }

    // Queue: icons instead of the words -- two glyphs that are distinct from the
    // per-row bin, with the full wording in the footer while the pointer rests on
    // them.
    Item {
      visible: !band.oneLine
      width: Style.space(26)
      height: parent.height

      Text {
        anchors.centerIn: parent
        text: "󰗩"                     // delete_sweep: everything out
        color: clearArea.containsMouse ? band.accent : band.dim
        font.family: band.fontFamily
        font.pixelSize: Style.font.subtitle
      }

      MouseArea {
        id: clearArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: band.hint("Clear the queue — remove every track (D)")
        onExited: band.hint("")
        onClicked: {
          if (!band.host) return
          band.host.clearQueue()
          band.message("Queue cleared")
        }
      }
    }

    Item {
      visible: !band.oneLine
      width: Style.space(26)
      height: parent.height

      Text {
        anchors.centerIn: parent
        text: "󰆐"                     // content_cut: cut the rest away
        color: keepArea.containsMouse ? band.accent : band.dim
        font.family: band.fontFamily
        font.pixelSize: Style.font.subtitle
      }

      MouseArea {
        id: keepArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: band.hint("Keep only the playing track — drop the rest (C)")
        onExited: band.hint("")
        onClicked: {
          if (!band.host) return
          band.host.cropQueue()
          band.message("everything except the playing track removed")
        }
      }
    }
  }
}
