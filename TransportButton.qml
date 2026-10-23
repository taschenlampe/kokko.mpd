import QtQuick
import qs.Commons

// A flat transport glyph on a plate: the glyph says what the click does, the
// plate says where the pointer is.
//
// Before this the flat controls of the band and of the hover card (previous,
// next, shuffle, repeat, clear, keep) only swapped their glyph colour to the
// accent while the pointer was on them -- and on both surfaces that change is
// easy to miss, because the accent and the popup foreground sit close together
// in the dark themes: measured side by side on the running desktop, the two
// states differ by a few percent of hue, and the pointer is the only real
// feedback. The plate is what makes the target visible: a rounded square the
// size of the *button*, not of the glyph, filled with the accent at 16% (22%
// pressed) and faded in over 120 ms. It also gives the aim point room -- the
// glyphs sit 13-14 px tall, the plate is 30 px.
//
// Not PanelActionButton (qs.Ui) on purpose: that one tints with the theme's
// hover token, 8% of the *foreground*, and shows a tooltip. On the band the
// footer hint already names the action, the card wants no tooltip either, and
// next to the filled play disc a foreground wash reads as nothing while an
// accent one reads as "this one".
Item {
  id: button

  property string glyph: ""
  // The plate's size. `height` may be set from outside (the card's row is
  // taller than the button) -- the plate then fills that, the glyph stays
  // centred.
  property real size: Style.space(30)
  property real glyphSize: Style.font.subtitle
  property string fontFamily: Style.font.family
  property color glyphColor: Color.popups.text
  property color activeColor: Color.accent
  // A toggle that is on keeps the accent without the pointer -- the rule the
  // shuffle and repeat glyphs already followed; the plate is pointer feedback.
  property bool on: false

  signal clicked()
  signal entered()
  signal exited()

  readonly property bool hovered: area.containsMouse
  readonly property bool pressed: area.pressed && area.containsMouse
  readonly property bool hot: enabled && (hovered || pressed)

  implicitWidth: size
  implicitHeight: size

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: Util.alpha(button.activeColor, button.pressed ? 0.22 : 0.16)
    opacity: button.hot ? 1 : 0
    // Fades instead of blinking, so moving along the row reads as one gesture.
    Behavior on opacity { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
  }

  Text {
    anchors.centerIn: parent
    text: button.glyph
    color: !button.enabled
      ? Qt.darker(button.glyphColor, 2.0)
      : (button.hot || button.on ? button.activeColor : button.glyphColor)
    font.family: button.fontFamily
    font.pixelSize: button.glyphSize
    Behavior on color { ColorAnimation { duration: 120 } }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    enabled: button.enabled
    cursorShape: button.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    onClicked: button.clicked()
    onEntered: button.entered()
    onExited: button.exited()
  }
}
