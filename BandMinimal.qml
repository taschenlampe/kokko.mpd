import QtQuick
import qs.Commons

// The player band, look "minimal": no artwork at all, one thin line -- state
// glyph, title and artist, a slim progress bar, the clock, prev/next. For
// people who leave `showArt` off in the bar and don't want a picture in the
// panel either, just the transport.
//
// Deliberately drops the options row (Zufall/Wiederholen) and the two queue
// glyphs that every other look carries -- they're one tap away in the hover
// card and the settings tab, and a line built to be thin shouldn't grow a
// second row to fit them back in. If that trade-off turns out wrong in
// practice, the fix is a taller variant, not stuffing this one.
//
// The panel forces `backdropMode: "off"` for this look (see Panel.qml) --
// a blurred cover behind a band that shows no cover of its own would be a
// picture appearing from nowhere.
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

  implicitHeight: hasSong ? Style.space(38) : 0
  visible: implicitHeight > 0

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(band.fg, 0.05)
    radius: Style.cornerRadius
  }

  Text {
    id: playGlyph
    anchors { left: parent.left; leftMargin: Style.space(12); verticalCenter: parent.verticalCenter }
    text: band.host && band.host.isPlaying ? "󰏤" : "󰐊"
    color: band.accent
    font.family: band.fontFamily
    font.pixelSize: Style.font.subtitle
    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                onClicked: if (band.host) band.host.toggleTrack() }
  }

  Row {
    id: transport
    anchors { right: parent.right; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    spacing: Style.space(14)
    height: Style.space(20)

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
      text: "󰒭"
      color: band.fg
      font.family: band.fontFamily
      font.pixelSize: Style.font.subtitle
      height: parent.height
      verticalAlignment: Text.AlignVCenter
      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                  onClicked: if (band.host) band.host.nextTrack() }
    }
  }

  Text {
    id: clock
    anchors { right: transport.left; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    horizontalAlignment: Text.AlignRight
    color: band.faint
    font.family: band.fontFamily
    font.pixelSize: Style.font.caption
    text: band.hasSong && band.host.duration > 0
      ? (band.host.formatTime(band.host.elapsed) + " / " + band.host.formatTime(band.host.duration))
      : ""
  }

  Rectangle {
    id: bar
    anchors { right: clock.left; rightMargin: Style.space(10); verticalCenter: parent.verticalCenter }
    width: Style.space(64)
    height: Style.space(4)
    radius: height / 2
    color: band.line

    readonly property real fraction: (band.host && band.host.duration > 0)
      ? Math.max(0, Math.min(1, band.host.elapsed / band.host.duration)) : 0

    Rectangle {
      width: parent.width * parent.fraction
      height: parent.height
      radius: parent.radius
      color: band.accent
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: function(mouse) {
        if (!band.hasSong || band.host.duration <= 0) return
        band.host.bare("seek " + Math.round((mouse.x / width) * band.host.duration))
      }
    }
  }

  Text {
    id: label
    anchors { left: playGlyph.right; leftMargin: Style.space(10)
              right: bar.left; rightMargin: Style.space(12)
              verticalCenter: parent.verticalCenter }
    elide: Text.ElideRight
    color: band.fg
    font.family: band.fontFamily
    font.pixelSize: Style.font.caption
    text: {
      if (!band.hasSong) return ""
      var t = String(band.host.song.title || "") || band.host.basename(band.host.song.file)
      return band.host.song.artist ? (t + "  —  " + String(band.host.song.artist)) : t
    }
  }
}
