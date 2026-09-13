import QtQuick
import qs.Commons

// The player band, look "split": the artwork as a full-height column on the
// left rather than a square centred in the row -- a fixed-width slab, not a
// thumbnail. Everything else lives in its own column to the right: title at
// the top, metadata under it, progress and the control row at the bottom.
//
// Sits between "hero" (cover as the whole card's background) and "anker"
// (cover as the only picture, band grown tall to fit it): here the cover is
// a structural block, not a backdrop and not the point on its own. The panel
// stays plain for this look too (see Panel.qml, backdropMode) -- a second
// picture behind a band that already carries one full-height would be
// artwork twice over.
//
// The corner rounding on the cover comes from the outer card's clip, not the
// image's own radius -- an image radius'd on all four corners would round its
// inner edge too, which reads as a mistake once the two columns sit flush.
Item {
  id: band

  property var host: null
  property string fontFamily: Style.font.family
  property var vizBars: []
  property int vizCount: 12
  property bool showViz: true

  signal message(string text)
  signal hint(string text)

  readonly property real coverWidth: Style.space(108)

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color dim: Qt.darker(fg, 1.35)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.28)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)

  readonly property bool hasSong: !!host && host.hasSong === true
  readonly property string art: hasSong && host.artPath !== "" ? host.artPath : ""

  implicitHeight: hasSong ? Style.space(112) : 0
  visible: implicitHeight > 0

  Rectangle {
    id: card
    anchors.fill: parent
    color: Util.alpha(band.fg, 0.05)
    radius: Style.cornerRadius
    clip: true

    Rectangle {
      id: coverSlab
      anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
      width: band.coverWidth
      color: Util.alpha(band.fg, 0.06)
      clip: true

      Image {
        id: coverImage
        anchors.fill: parent
        source: band.art
        sourceSize.width: 220
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

    // A hairline where the two columns meet -- without it the slab and the
    // text panel read as one smudged surface once the cover is a busy photo.
    Rectangle {
      anchors { left: coverSlab.right; top: parent.top; bottom: parent.bottom }
      width: Math.max(1, Style.normalBorderWidth)
      color: band.line
    }
  }

  // Not a Column: the title/meta pair anchors to the top and progress/controls
  // to the bottom independently, so the gap between them stretches or shrinks
  // with the band's height instead of the two clumping together at the top.
  Item {
    id: info
    anchors { left: card.left; leftMargin: band.coverWidth + Style.space(16)
              right: parent.right; rightMargin: Style.space(16)
              top: parent.top; bottom: parent.bottom
              topMargin: Style.space(12); bottomMargin: Style.space(10) }

    Column {
      id: heading
      anchors { left: parent.left; right: parent.right; top: parent.top }
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
          if (band.host.song.date) bits.push(String(band.host.song.date))
          return bits.join("  ·  ")
        }
        color: band.dim
        font.family: band.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Item {
      id: progress
      anchors { left: parent.left; right: parent.right; bottom: controls.top; bottomMargin: Style.space(8) }
      height: Style.space(14)

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

    Row {
      id: controls
      anchors { right: parent.right; bottom: parent.bottom }
      height: Style.space(24)
      spacing: Style.space(14)

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
    }
  }
}
