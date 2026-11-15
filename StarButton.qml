import QtQuick
import qs.Commons

// The star, wherever one surface needs it: filled in `activeColor` while the
// playing uri is in MPD's `favorites` playlist (BarWidget.favoriteCurrent), dim
// while it is not.
//
// It owns no state and no opinion: `host` is the widget, which holds the set and
// the write, so a click here is the same mutation the panel's rows, the hover
// card and the card on the wallpaper send. Nothing is hovered-into-view -- a
// favourite that has to be found by pointing at it is not one (the rule the
// panel's rows already follow).
Item {
  id: star

  property var host: null
  property real glyphSize: Style.font.body
  property string fontFamily: Style.font.family
  property color glyphColor: Color.popups.text
  property color activeColor: Color.accent

  signal clicked()
  signal entered()
  signal exited()

  readonly property bool on: !!host && host.favoriteCurrent === true
  readonly property bool hot: area.containsMouse

  implicitWidth: Style.space(22)
  implicitHeight: Style.space(22)

  Text {
    anchors.centerIn: parent
    text: "★"
    // The pointer lifts the dim glyph to full strength before it is clicked, so
    // the aim point answers even where the star is not set.
    color: star.on ? star.activeColor : star.glyphColor
    opacity: star.on || star.hot ? 1.0 : 0.5
    font.family: star.fontFamily
    font.pixelSize: star.glyphSize
    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on opacity { NumberAnimation { duration: 120 } }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    enabled: star.enabled
    cursorShape: star.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    onClicked: star.clicked()
    onEntered: star.entered()
    onExited: star.exited()
  }
}
