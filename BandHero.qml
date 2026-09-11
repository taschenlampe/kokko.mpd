import QtQuick
import qs.Commons

// The player band, look "hero": the cover is not behind the panel any more, it is
// the player card's own background -- one cover as one surface instead of a
// backdrop plus a thumbnail. The panel stays plain in this look (see Panel.qml,
// backdropMode).
//
// Taller than the classic band (the controls get a row of their own at the
// bottom), so the list gives up a couple of rows; that is the trade for the
// picture.
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
  readonly property color bg: Color.popups.background
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true
  readonly property string art: hasSong && host.artPath !== "" ? host.artPath : ""

  implicitHeight: hasSong ? Style.space(126) : 0
  visible: implicitHeight > 0

  // ---------------------------------------------------------------- the card
  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: Util.alpha(band.fg, 0.05)
    clip: true

    Image {
      anchors.fill: parent
      source: band.art
      sourceSize.width: 900
      sourceSize.height: 400
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      opacity: 0.34
      visible: status === Image.Ready
    }

    Rectangle {
      anchors.fill: parent
      gradient: Gradient {
        GradientStop { position: 0.0; color: Util.alpha(band.bg, 0.46) }
        GradientStop { position: 0.5; color: Util.alpha(band.bg, 0.72) }
        GradientStop { position: 0.80; color: band.bg }
        GradientStop { position: 1.0; color: band.bg }
      }
    }
  }

  // ------------------------------------------------------------------ the row
  Rectangle {
    id: cover
    anchors { left: parent.left; leftMargin: Style.space(12); top: parent.top; topMargin: Style.space(12) }
    width: Style.space(92)
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
      sourceSize.width: 220
      sourceSize.height: 220
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

  // Transport at the top right: the three that matter, away from the options.
  Row {
    id: transport
    anchors { right: parent.right; rightMargin: Style.space(14); top: parent.top; topMargin: Style.space(14) }
    spacing: Style.space(18)
    height: Style.space(30)

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
  }

  Column {
    id: text
    anchors { left: cover.right; leftMargin: Style.space(14)
              right: transport.left; rightMargin: Style.space(14)
              top: parent.top; topMargin: Style.space(14) }
    spacing: Style.space(4)

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

  // --------------------------------------------------- bottom row: levels + options
  Item {
    id: foot
    anchors { left: parent.left; leftMargin: Style.space(14)
              right: parent.right; rightMargin: Style.space(14)
              bottom: parent.bottom; bottomMargin: Style.space(12) }
    height: Style.space(30)

    Visualizer {
      id: viz
      anchors { left: parent.left; verticalCenter: parent.verticalCenter }
      width: Style.space(150)
      height: Style.space(30)
      visible: band.showViz && band.host !== null && band.host.queueLength > 0
      levels: band.vizBars
      count: band.vizCount
    }

    Row {
      id: buttons
      anchors { right: parent.right; verticalCenter: parent.verticalCenter }
      spacing: Style.space(14)
      height: Style.space(30)

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
}
