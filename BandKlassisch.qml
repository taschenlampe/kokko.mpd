import QtQuick
import qs.Commons

// The player band, look "klassisch": the artwork as a small square on the left,
// title and artist beside it, the progress line under them, then cava and the
// controls on the right.
//
// The band owns its height (`implicitHeight`) so a look may be taller or shorter
// than another -- the panel only anchors it and lets the list follow its bottom.
// It owns no state: everything comes from the widget, and the two footers it
// needs (the flash line and the hover explanation) go back as signals, so the
// band never has to know the panel's footer.
Item {
  id: band

  property var host: null
  property string fontFamily: Style.font.family
  property var vizBars: []
  property int vizCount: 12
  property bool showViz: true

  signal message(string text)     // a line for the footer, e.g. "Zufall an"
  signal hint(string text)        // explanation while the pointer rests on a glyph

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true

  implicitHeight: hasSong ? Style.space(74) : 0
  visible: implicitHeight > 0

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(band.fg, 0.05)
    radius: Style.cornerRadius
  }

  Rectangle {
    id: cover
    anchors { left: parent.left; leftMargin: Style.space(8); verticalCenter: parent.verticalCenter }
    width: Style.space(58)
    height: width
    radius: Style.cornerRadius
    color: Util.alpha(band.fg, 0.06)
    border.width: Math.max(1, Style.normalBorderWidth)
    border.color: band.line
    clip: true

    Image {
      id: coverImage
      anchors.fill: parent
      source: band.host && band.hasSong ? band.host.artPath : ""
      sourceSize.width: 160
      sourceSize.height: 160
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      visible: status === Image.Ready
    }

    Text {
      anchors.centerIn: parent
      visible: coverImage.status !== Image.Ready
      text: band.host && band.host.isPlaying ? "󰏤" : "󰐊"
      color: band.accent
      font.family: band.fontFamily
      font.pixelSize: Style.font.displayLarge
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: if (band.host) band.host.toggleTrack()
    }
  }

  Column {
    id: text
    anchors { left: cover.right; leftMargin: Style.space(12)
              right: viz.left; rightMargin: Style.space(12)
              verticalCenter: parent.verticalCenter }
    spacing: Style.space(3)

    Text {
      width: parent.width
      text: band.hasSong
        ? (String(band.host.song.title || "") || band.host.basename(band.host.song.file))
        : ""
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      font.bold: true
      elide: Text.ElideRight
    }

    Text {
      width: parent.width
      text: {
        if (!band.hasSong) return ""
        var bits = []
        if (band.host.song.artist) bits.push(String(band.host.song.artist))
        if (band.host.song.album) bits.push(String(band.host.song.album))
        if (band.host.queueLength > 0)
          bits.push("#" + (band.host.queuePosition + 1) + "/" + band.host.queueLength)
        return bits.join("  ·  ")
      }
      color: band.dim
      font.family: band.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    // Progress: times beside the line, click on the line to seek there.
    Item {
      id: progress
      width: parent.width
      height: Style.space(16)

      readonly property real fraction: (band.host && band.host.duration > 0)
        ? Math.max(0, Math.min(1, band.host.elapsed / band.host.duration)) : 0

      Text {
        id: elapsed
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        text: band.hasSong ? band.host.formatTime(band.host.elapsed) : ""
        color: band.faint
        font.family: band.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        id: duration
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        text: (band.hasSong && band.host.duration > 0)
          ? band.host.formatTime(band.host.duration) : ""
        color: band.faint
        font.family: band.fontFamily
        font.pixelSize: Style.font.caption
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
          width: parent.width * progress.fraction
          height: parent.height
          radius: parent.radius
          color: band.accent
        }
      }

      MouseArea {
        anchors { left: bar.left; right: bar.right; top: parent.top; bottom: parent.bottom }
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
          if (!band.hasSong || band.host.duration <= 0) return
          band.host.bare("seek " + Math.round((mouse.x / width) * band.host.duration))
        }
      }
    }
  }

  // cava, live: the bars sit between the text and the buttons.
  Visualizer {
    id: viz
    anchors { right: buttons.left; rightMargin: Style.space(14)
              verticalCenter: parent.verticalCenter }
    width: Style.space(150)
    height: Style.space(30)
    visible: band.showViz && band.host !== null && band.host.queueLength > 0
    levels: band.vizBars
    count: band.vizCount
  }

  Row {
    id: buttons
    anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    spacing: Style.space(16)
    // Explicit height: the children say `height: parent.height`, and a Row whose
    // height comes from its children would resolve that to 0 -- which is exactly
    // how these buttons disappeared.
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

    Text {
      text: band.host && band.host.isPlaying ? "󰏤" : "󰐊"
      color: band.accent
      font.family: band.fontFamily
      font.pixelSize: Style.font.title
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                  onClicked: if (band.host) band.host.toggleTrack() }
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
    // accent while on, dim while off.
    Text {
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
          band.message(on ? "Zufall an" : "Zufall aus")
        }
      }
    }

    Text {
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
          band.message(on ? "Wiederholen an" : "Wiederholen aus")
        }
      }
    }

    // Queue: icons instead of the words "löschen"/"nur dieses" -- two glyphs that
    // are distinct from the per-row bin, with the full wording in the footer while
    // the pointer rests on them.
    Item {
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
        onEntered: band.hint("Queue leeren — alle Titel entfernen (D)")
        onExited: band.hint("")
        onClicked: {
          if (!band.host) return
          band.host.clearQueue()
          band.message("Queue geleert")
        }
      }
    }

    Item {
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
        onEntered: band.hint("nur das Laufende behalten — alles andere aus der Queue (C)")
        onExited: band.hint("")
        onClicked: {
          if (!band.host) return
          band.host.cropQueue()
          band.message("alles außer dem laufenden Titel entfernt")
        }
      }
    }
  }
}
