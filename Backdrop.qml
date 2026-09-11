import QtQuick
import QtQuick.Effects
import qs.Commons

// The cover behind the panel. Two ways of getting out of its own way:
//
//  - "blur": the artwork is blurred and faded into the panel colour. How loud it
//    is comes from one setting (`backdrop`), because the three levers pull the
//    same way: opacity up, blur down and saturation up together make a cover read
//    as "more cover". Turning one of them alone either leaves it washed out (only
//    opacity) or turns it into confetti (only blur).
//
//  - "sharp": the artwork stays an image (kokko.musify's trick). No MultiEffect:
//    the dimming comes from image opacity plus a gradient, so it reads like a
//    photograph instead of a smear and the rows stay readable.
//
// `level` (0..1) is the `backdrop` setting in both modes; 0 hides the whole thing.
Item {
  id: root

  property string mode: "blur"        // blur | sharp | off
  property real level: 0.6
  property string source: ""

  readonly property color bg: Color.popups.background
  readonly property bool shows: level > 0 && mode !== "off" && source !== ""

  visible: shows
  clip: true

  Image {
    id: art
    anchors.fill: parent
    source: root.source
    sourceSize.width: root.mode === "blur" ? 1200 : 1800
    sourceSize.height: root.mode === "blur" ? 800 : 1200
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    // In blur mode MultiEffect draws it; showing it too would double it.
    visible: root.mode === "sharp" && status === Image.Ready
    opacity: root.mode === "sharp" ? 0.22 + 0.40 * root.level : 1
  }

  MultiEffect {
    anchors.fill: parent
    visible: root.mode === "blur"
    source: art
    autoPaddingEnabled: false
    blurEnabled: root.mode === "blur" && art.status === Image.Ready
    blur: 1.0
    blurMax: 96
    // 0 -> soft and barely there, 1 -> shapes stay recognisable.
    blurMultiplier: 1.5 - 1.1 * root.level
    saturation: 0.5 * root.level
    brightness: 0.03 * root.level
    opacity: 0.18 + 0.62 * root.level
  }

  Rectangle {
    anchors.fill: parent
    gradient: root.mode === "sharp"
      ? sharpGradient
      : blurGradient
  }

  // Sharp: fade late and firmly, so the cover keeps its shape above the list.
  readonly property var sharpGradient: Gradient {
    GradientStop { position: 0.0; color: Util.alpha(root.bg, 0.40 - 0.15 * root.level) }
    GradientStop { position: 0.55; color: Util.alpha(root.bg, 0.92 - 0.12 * root.level) }
    GradientStop { position: 0.72; color: root.bg }
    GradientStop { position: 1.0; color: root.bg }
  }

  // Blur: the fade down starts lower the bolder the backdrop is, so more of the
  // cover survives above the list.
  readonly property var blurGradient: Gradient {
    GradientStop { position: 0.0; color: Util.alpha(root.bg, 0.36 - 0.26 * root.level) }
    GradientStop { position: 0.40; color: Util.alpha(root.bg, 0.86 - 0.26 * root.level) }
    GradientStop { position: 0.66 + 0.12 * root.level; color: root.bg }
    GradientStop { position: 1.0; color: root.bg }
  }
}
