import QtQuick
import qs.Commons
import QtQuick.Effects
import Qt5Compat.GraphicalEffects

// The player band, look "vinyl": the artwork sits inside a spinning disc
// instead of a square. Standalone rather than built on BandKlassisch, because
// a circular clip and its rotation don't fit that band's Rectangle-with-corner-
// radius cover -- everything past the cover (text, progress, viz, buttons) is
// the same arrangement as klassisch, just copied rather than inherited.
//
// The disc turns while playing and holds its angle when paused -- toggling
// `running` on a RotationAnimation freezes the interpolation exactly where it
// was, no separate angle bookkeeping needed. Duration is decorative, not a
// reproduction of 33/45 RPM: slow enough to read as a record, fast enough that
// it doesn't look stuck at a glance.
Item {
  id: band

  property var host: null
  property string fontFamily: Style.font.family
  property var vizBars: []
  property int vizCount: 12
  property bool showViz: true

  signal message(string text)
  signal hint(string text)

  property real coverSize: Style.space(72)

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true
  readonly property string art: hasSong && host.artPath !== "" ? host.artPath : ""

  implicitHeight: hasSong ? Math.max(Style.space(88), coverSize + Style.space(16)) : 0
  visible: implicitHeight > 0

  Rectangle {
    id: card
    anchors.fill: parent
    color: Util.alpha(band.fg, 0.05)
    radius: Style.cornerRadius
    clip: true
  }

  // The disc: a plain circular clip (radius = half the side) rather than the
  // rounded-square the other looks use. The centre dot sits above the image so
  // it reads as a spindle instead of a random dark patch when the cover is busy.
  Item {
    id: disc
    anchors { left: parent.left; leftMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    width: band.coverSize
    height: width

    // The mask shape and its texture live outside the rotating platter so the
    // cut stays put while the artwork spins inside it.
    Rectangle {
      id: discMaskShape
      width: parent.width
      height: parent.height
      radius: width / 2
      color: "white"
      visible: false
    }

    Rectangle {
      id: platter
      anchors.fill: parent
      radius: width / 2
      color: Util.alpha(band.fg, 0.06)
      border.width: Math.max(1, Style.normalBorderWidth)
      border.color: band.line
      clip: true
      rotation: 0

      RotationAnimation on rotation {
        running: band.hasSong && band.host.isPlaying
        loops: Animation.Infinite
        from: 0; to: 360
        duration: 9000
      }

      // The cover is clipped by a *mask*, not by `clip: true`: this Qt runtime
      // clips a Rectangle along its bounding box only, so radius+clip gives a
      // square. An elliptical maskSource does the real (antialiased) cut.
      Image {
        id: coverImage
        anchors.fill: parent
        source: band.art
        sourceSize.width: 160
        sourceSize.height: 160
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: false
      }

      // OpacityMask (Qt5Compat) is the proven way to clip to a shape here --
      // MultiEffect's maskSource did not cut in this runtime.
      OpacityMask {
        anchors.fill: parent
        source: coverImage
        maskSource: discMaskShape
        visible: coverImage.status === Image.Ready
      }

      Text {
        anchors.centerIn: parent
        visible: coverImage.status !== Image.Ready
        text: band.host && band.host.isPlaying ? "󰏤" : "󰐊"
        color: band.accent
        font.family: band.fontFamily
        font.pixelSize: Style.font.displayLarge
      }

      Rectangle {
        // the spindle: only worth drawing once there's a photo to sit on top of
        anchors.centerIn: parent
        visible: coverImage.status === Image.Ready
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

  Column {
    id: text
    anchors { left: disc.right; leftMargin: Style.space(14)
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
  }
}
