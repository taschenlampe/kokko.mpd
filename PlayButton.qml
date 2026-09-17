import QtQuick
import qs.Commons

// The round, filled play/pause button: the one control that carries colour on
// every surface.
//
// It stood three times before -- once in the band, once in the hover card, once
// on the desktop card -- and the copies had drifted apart in size and in glyph
// colour. The circle, the state glyph and the click live here once; what a
// surface legitimately decides for itself stays a property: how big the circle
// is and which accent fills it.
//
// Not a `PanelActionButton`: that one is a flat glyph with a hover tint, and this
// one is a filled disc whose glyph takes the colour behind it -- the state has to
// read without comparing two icons.
Item {
  id: play

  // Whoever owns the playback: it has to answer `toggleTrack()` and report
  // `isPlaying` / `isPaused`. `null` is allowed -- every surface builds before
  // the bridge has said a word, and the button still has to render then.
  property var host: null

  property real size: 38
  // The fill comes from outside: the band and the desktop card pass their own
  // accent, the hover card has no band of its own and passes the theme's.
  property color accentColor: Color.accent
  // The glyph sits IN the fill and takes the colour behind the button, so the
  // circle reads as one button instead of an icon with a ring around it.
  property color glyphColor: Color.background
  property real glyphSize: Style.font.icon
  property string fontFamily: Style.font.family

  // Three states, like the widget's own state glyph: playing, paused, stopped.
  // A stopped deck with a track loaded is one click away from playing again, so it
  // is not a state of its own here.
  readonly property string playbackState: {
    if (!host) return "stopped"
    if (host.isPlaying === true) return "playing"
    if (host.isPaused === true) return "paused"
    return "stopped"
  }

  // The glyph is the ACTION, not the report: while it plays the button offers
  // pause, otherwise it offers play -- the pair all three copies used. No stop
  // glyph on purpose: a stop symbol on a merely paused deck would promise
  // something else than the click does.
  readonly property string glyph: playbackState === "playing" ? "\uF04C" : "\uF04B"

  implicitWidth: size
  implicitHeight: size

  Rectangle {
    anchors.fill: parent
    radius: width / 2
    color: play.accentColor

    Text {
      anchors.centerIn: parent
      text: play.glyph
      color: play.glyphColor
      font.family: play.fontFamily
      font.pixelSize: play.glyphSize
    }
  }

  // A MouseArea and not the desktop card's original TapHandler: the band and the
  // hover card both carry a click area over the whole surface (there a click opens
  // the panel or toggles the track), and the two flat play glyphs this replaces
  // were MouseAreas for exactly that reason -- as a child, the area keeps the
  // click to itself. Where no such area exists (the desktop card) nothing about
  // this button changes.
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: if (play.host) play.host.toggleTrack()
  }
}
