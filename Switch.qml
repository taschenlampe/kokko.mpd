import QtQuick
import qs.Commons

// The on/off mark in the settings rows: a short track with a round knob.
//
// Presentation only. The row is the click target (its MouseArea calls
// `activate`), so this component deliberately has no MouseArea of its own -- a
// second one inside the row would fire the same setting twice. `checked` is read
// from the setting, never written here.
Item {
  id: sw

  property bool checked: false
  property color foreground: Color.popups.text
  property color accentColor: Color.accent

  // The mockup's track: 24 wide, 13 tall, and the knob 9 across. Kept as named
  // expressions so the state test can read the same numbers the drawing uses.
  readonly property real trackWidth: Style.space(24)
  readonly property real trackHeight: Style.space(13)
  readonly property real knobSize: Style.space(9)

  implicitWidth: sw.trackWidth
  implicitHeight: sw.trackHeight

  Rectangle {
    anchors.fill: parent
    radius: height / 2
    color: sw.checked ? Util.alpha(sw.accentColor, 0.55)
      : Util.alpha(sw.foreground, 0.16)
  }

  Rectangle {
    width: sw.knobSize
    height: sw.knobSize
    radius: width / 2
    anchors.verticalCenter: parent.verticalCenter
    x: sw.checked ? parent.width - width - Style.space(2) : Style.space(2)
    color: sw.foreground

    Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
  }
}
