import QtQuick
import qs.Commons

// cava's bars: one row of rounded bars, centred in whatever width it is given.
//
// Present only while the caller has levels to show; the caller owns the cava
// process. `count` must match the `bars` setting in bin/cava.conf.
//
// Visibility is the caller's business, on purpose: a binding on `width` is not
// re-evaluated reliably when the width comes from anchors, and the bars then stay
// invisible even though the levels arrive (musify hit exactly that).
Item {
  id: root

  property var levels: []          // 0..1 per bar, index 0 leftmost
  property int count: 12
  property color barColor: Color.accent

  readonly property real gap: Style.space(2)
  readonly property real barW: Math.min(Style.space(5),
    Math.max(2, (width - (root.count - 1) * root.gap) / root.count))
  readonly property real span: root.count * root.barW + (root.count - 1) * root.gap

  Repeater {
    model: root.count

    delegate: Rectangle {
      required property int index

      readonly property real level: index < root.levels.length
        ? Math.max(0, Math.min(1, Number(root.levels[index]) || 0)) : 0

      x: (root.width - root.span) / 2 + index * (root.barW + root.gap)
      anchors.bottom: parent.bottom
      width: root.barW
      height: Math.max(Style.space(2), root.height * level)
      radius: width / 2
      gradient: Gradient {
        GradientStop { position: 0.0; color: root.barColor }
        GradientStop { position: 1.0; color: Qt.lighter(root.barColor, 1.45) }
      }

      Behavior on height {
        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
      }
    }
  }
}
