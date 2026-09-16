import QtQuick
import qs.Commons

// The player band, look "anchor": the artwork is the anchor -- big, slightly
// bleeding over the header rule, with everything else reduced to text and one row
// of controls. The panel stays plain (Backdrop mode "off"), so the cover is the
// only picture on screen.
//
// Widest change of the four: this band is taller, so the list shows a couple of
// rows less. Worth it only if the picture is the point.
Item {
  id: band

  property var host: null
  property string fontFamily: Style.font.family
  property var vizBars: []
  property int vizCount: 12
  property bool showViz: true

  signal message(string text)
  signal hint(string text)

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true
  readonly property string art: hasSong && host.artPath !== "" ? host.artPath : ""
  readonly property real coverSide: Style.space(104)

  // No bleed: a cover overlapping the header rule looks good in a mockup and eats
  // the tab chips in real use -- and those are how a mouse user switches tabs.
  // The band is taller for the picture, nothing more.
  readonly property real bleed: 0

  implicitHeight: hasSong ? coverSide + Style.space(22) : 0
  visible: implicitHeight > 0

  Rectangle {
    id: cover
    anchors { left: parent.left; top: parent.top; topMargin: -band.bleed }
    width: band.coverSide
    height: width
    radius: Style.cornerRadius
    color: Util.alpha(band.fg, 0.06)
    border.width: Math.max(1, Style.normalBorderWidth)
    border.color: band.line
    clip: true

    Image {
      id: coverImage
      anchors.fill: parent
      source: band.art
      sourceSize.width: 260
      sourceSize.height: 260
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
    anchors { left: cover.right; leftMargin: Style.space(16)
              right: parent.right; verticalCenter: cover.verticalCenter }
    spacing: Style.space(5)

    Text {
      width: parent.width
      text: band.hasSong
        ? (String(band.host.song.title || "") || band.host.basename(band.host.song.file))
        : ""
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
      elide: Text.ElideRight
    }

    // One line for everything that is not the title: artist, album, place in the
    // queue and the clock. Fewer lines, less to read.
    Text {
      width: parent.width
      text: {
        if (!band.hasSong) return ""
        var bits = []
        if (band.host.song.artist) bits.push(String(band.host.song.artist))
        if (band.host.song.album) bits.push(String(band.host.song.album))
        if (band.host.queueLength > 0)
          bits.push("#" + (band.host.queuePosition + 1) + "/" + band.host.queueLength)
        if (band.host.duration > 0)
          bits.push(band.host.formatTime(band.host.elapsed) + " / " + band.host.formatTime(band.host.duration))
        return bits.join("  ·  ")
      }
      color: band.dim
      font.family: band.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    Item {
      id: progress
      width: parent.width
      height: Style.space(14)

      readonly property real fraction: (band.host && band.host.duration > 0)
        ? Math.max(0, Math.min(1, band.host.elapsed / band.host.duration)) : 0

      Rectangle {
        id: bar
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
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
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom }
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
          if (!band.hasSong || band.host.duration <= 0) return
          band.host.bare("seek " + Math.round((mouse.x / width) * band.host.duration))
        }
      }
    }

    // The one row: transport, options, queue, levels -- left to right.
    Row {
      id: controls
      width: parent.width
      height: Style.space(28)
      spacing: Style.space(18)

      Text {
        text: "󰒮"
        color: band.fg
        font.family: band.fontFamily
        font.pixelSize: Style.font.title
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
        font.pixelSize: Style.font.title
        height: parent.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (band.host) band.host.nextTrack() }
      }

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
            band.message(on ? "Shuffle on" : "Shuffle off")
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
            band.message(on ? "Repeat on" : "Repeat off")
          }
        }
      }

      Item {
        width: Style.space(26)
        height: parent.height

        Text {
          anchors.centerIn: parent
          text: "󰗩"
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
        width: Style.space(26)
        height: parent.height

        Text {
          anchors.centerIn: parent
          text: "󰆐"
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

      // The levels are the last child of the row: an anchor across the parent
      // boundary sat about 15 px too high, and inside the row they cannot be
      // misaligned at all. Right after the glyphs, like the classic band has them
      // right after the text.
      Visualizer {
        id: viz
        width: Style.space(150)
        height: parent.height
        // While it plays, not while a queue exists: with cava stopped the levels are
    // gone, and every bar would sit at its 2 px floor -- a frozen spectrum that
    // claims something is happening.
    visible: band.showViz && band.host !== null && band.host.isPlaying
        levels: band.vizBars
        count: band.vizCount
      }
    }
  }
}
