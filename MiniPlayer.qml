import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The card that drops out of the bar while the pointer is on the widget: cover,
// what is playing, the transport and the two playback options -- the panel's
// controls without the panel coming up, with the buttons given the room.
//
// A layer surface of its own, not a PopupWindow: a Quickshell popup anchored to
// the bar (an xdg-popup with a grab on a layer-shell parent) makes screencopy
// stall in this compositor -- grim hung for minutes while the card was open.
// A plain PanelWindow behaves: the surface spans the screen width, the card sits
// inside it, and the input mask covers the card only, so clicks elsewhere pass
// through to whatever is below.
PanelWindow {
  id: mini

  property QtObject service: null      // our bar widget, the owner of the bridge
  property Item anchorItem: null

  property bool open: false            // set by the widget
  property bool hovered: false         // read by the widget: the pointer is on us

  readonly property var anchorWindow: (anchorItem && anchorItem.QsWindow)
    ? anchorItem.QsWindow.window : null
  readonly property int gap: Style.space(7)
  readonly property string barPosition: (service && service.bar && service.bar.position)
    ? service.bar.position : "top"
  readonly property real barH: anchorWindow ? anchorWindow.height : 0
  readonly property real barW: anchorWindow ? anchorWindow.width : 0
  readonly property real screenW: screen ? screen.width : 0
  // The bar is inset from the screen edge (a floating bar), and mapToItem gives
  // coordinates inside the bar's surface -- so the inset has to go back on.
  readonly property real barInset: screenW > 0 && barW > 0
    ? Math.max(0, (screenW - barW) / 2) : 0
  readonly property real anchorX: (anchorItem && anchorWindow)
    ? anchorItem.mapToItem(anchorWindow.contentItem, 0, 0).x + barInset : 0

  // The x the card's centre should sit at, handed over by the widget: it is the one
  // that knows where it is, and its right edge is what stays put when the label
  // changes. Screen coordinates -- this surface is screen-wide, so scene == local.
  // (Mapping the anchor from inside this window gave wrong numbers: the card window
  // is not the window the bar widget lives in.)
  property real cardCenterX: NaN

  // Where the card ends up -- exposed so a test can prove it does not hop.
  readonly property real cardX: card.x

  // ---- the surface: screen-wide, as tall as the card, top-anchored ----
  visible: (open || card.opacity > 0) && hasTrack
  color: "transparent"
  anchors { top: true; left: true; right: true }
  implicitHeight: Math.ceil(barH + gap + card.height + Style.space(8))
  WlrLayershell.namespace: "kokko-mpd-card"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
  exclusionMode: ExclusionMode.Ignore
  // Input only where the card is: the rest of the strip stays click-through.
  mask: Region { item: card }

  readonly property color fg: Color.popups.text
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property color line: Qt.rgba(fg.r, fg.g, fg.b, 0.14)
  readonly property string fontFamily: (service && service.fontFamily)
    ? service.fontFamily : Style.font.family

  readonly property bool hasTrack: service !== null && service.hasSong === true
  readonly property real durNow: (service && service.duration > 0) ? service.duration : 0
  readonly property bool playing: service !== null && service.isPlaying === true

  // The bridge reports the position only when something changes, so the client
  // carries it forward between events; while dragging, the pointer wins.
  property real dragFrac: -1
  property bool dragging: false
  property real playPos: 0
  readonly property real frac: dragFrac >= 0 ? dragFrac
    : (durNow > 0 ? Math.min(1, Math.max(0, playPos / durNow)) : 0)

  function fmt(sec) {
    sec = Math.max(0, Math.round(Number(sec) || 0))
    var m = Math.floor(sec / 60)
    var s = sec % 60
    return m + ":" + (s < 10 ? "0" : "") + s
  }

  onOpenChanged: {
    if (open && service) {
      playPos = service.elapsed
      dragFrac = -1
      dragging = false
    }
  }

  Connections {
    target: mini.service
    function onElapsedChanged() { if (!mini.dragging) mini.playPos = mini.service.elapsed }
  }

  Timer {
    interval: 250
    repeat: true
    running: mini.open && mini.hasTrack && mini.playing && !mini.dragging && mini.dragFrac < 0
    onTriggered: mini.playPos = mini.playPos + 0.25
  }

  Rectangle {
    id: card
    width: Style.space(346)
    height: Style.space(122)
    // Under the widget it belongs to: the centre is dictated by the widget (stable
    // while the label changes), here only clamped to stay on screen.
    x: Math.max(mini.gap,
         Math.min(mini.cardCenterX - width / 2,
                  Math.max(mini.gap, mini.width - width - mini.gap)))
    y: mini.barH + mini.gap
    color: Util.alpha(Color.background, 0.98)
    radius: Style.cornerRadius
    border.width: Math.max(1, Style.normalBorderWidth)
    border.color: Color.popups.border
    opacity: mini.open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.AllButtons
      onEntered: mini.hovered = true
      onExited: mini.hovered = false
      // Clicking the card (not a button) opens the panel; the wheel changes the
      // volume -- the readout that used to sit here is gone, the function stays.
      onClicked: if (mini.service) mini.service.toggle()
      onWheel: function(wheel) {
        if (mini.service) mini.service.nudgeVolume(wheel.angleDelta.y > 0 ? 5 : -5)
      }
    }

    // ------------------------------------------------------------- cover + text
    Rectangle {
      id: cover
      anchors { left: parent.left; leftMargin: Style.space(10)
                top: parent.top; topMargin: Style.space(10) }
      width: Style.space(58)
      height: width
      radius: Style.cornerRadius
      color: Util.alpha(mini.fg, 0.06)
      border.width: Math.max(1, Style.normalBorderWidth)
      border.color: mini.line
      clip: true

      Image {
        id: coverImage
        anchors.fill: parent
        source: mini.service ? mini.service.artPath : ""
        sourceSize.width: 160
        sourceSize.height: 160
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: status === Image.Ready
      }

      Text {
        anchors.centerIn: parent
        visible: coverImage.status !== Image.Ready
        text: mini.playing ? "󰏤" : "󰐊"
        color: Color.accent
        font.family: mini.fontFamily
        font.pixelSize: Style.font.displayLarge
      }

      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: if (mini.service) mini.service.toggle()
      }
    }

    Column {
      anchors { left: cover.right; leftMargin: Style.space(12)
                right: parent.right; rightMargin: Style.space(10)
                top: cover.top }
      spacing: Style.space(3)

      Text {
        width: parent.width
        text: mini.service
          ? (String(mini.service.song.title || "") || mini.service.basename(mini.service.songFile))
          : ""
        color: mini.fg
        font.family: mini.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: {
          if (!mini.service) return ""
          var bits = []
          if (mini.service.song.artist) bits.push(String(mini.service.song.artist))
          // Album equals title on singles and untagged rips; the second line should always
          // add information instead of repeating the first one.
          var alb = String(mini.service.song.album || "")
          if (alb && alb !== String(mini.service.song.title || "")) bits.push(alb)
          if (mini.service.queueLength > 0)
            bits.push("#" + (mini.service.queuePosition + 1) + "/" + mini.service.queueLength)
          return bits.join("  ·  ")
        }
        color: mini.dim
        font.family: mini.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      // Progress: click or drag to seek.
      Item {
        id: bar
        width: parent.width
        height: Style.space(12)

        Rectangle {
          anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
          height: Style.space(4)
          radius: height / 2
          color: mini.line

          Rectangle {
            width: parent.width * mini.frac
            height: parent.height
            radius: parent.radius
            color: Color.accent
          }
        }

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onPressed: function(mouse) {
            mini.dragging = true
            mini.dragFrac = Math.max(0, Math.min(1, mouse.x / width))
          }
          onPositionChanged: function(mouse) {
            if (mini.dragging) mini.dragFrac = Math.max(0, Math.min(1, mouse.x / width))
          }
          // A stolen grab (another surface takes the pointer) never delivers onReleased:
          // without this, `dragging` stays true and the clock above stays gated off, so the
          // bar freezes until the card is closed.
          onCanceled: { mini.dragging = false; mini.dragFrac = -1 }
          onReleased: function(mouse) {
            if (!mini.dragging) return
            var target = mini.dragFrac * mini.durNow
            mini.dragging = false
            mini.dragFrac = -1
            if (mini.service && mini.durNow > 0) mini.service.bare("seek " + Math.round(target))
          }
        }
      }
    }

    // ----------------------------------------------------------- transport
    // Big enough to hit without aiming: the card is the one place where the
    // controls get room, so the bars went and the buttons grew.
    Row {
      id: controls
      anchors { left: cover.right; leftMargin: Style.space(12)
                bottom: parent.bottom; bottomMargin: Style.space(12) }
      spacing: Style.space(24)
      height: Style.space(34)

      Text {
        text: "󰒮"
        color: mini.fg
        font.family: mini.fontFamily
        font.pixelSize: Style.font.title
        height: controls.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (mini.service) mini.service.previousTrack() }
      }

      Text {
        text: mini.playing ? "󰏤" : "󰐊"
        color: Color.accent
        font.family: mini.fontFamily
        font.pixelSize: Style.font.displayLarge
        height: controls.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (mini.service) mini.service.toggleTrack() }
      }

      Text {
        text: "󰒭"
        color: mini.fg
        font.family: mini.fontFamily
        font.pixelSize: Style.font.title
        height: controls.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (mini.service) mini.service.nextTrack() }
      }

      Text {
        text: mini.service && mini.service.randomOn ? "󰒝" : "󰒞"
        color: mini.service && mini.service.randomOn ? Color.accent : mini.dim
        font.family: mini.fontFamily
        font.pixelSize: Style.font.title
        height: controls.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (mini.service) mini.service.toggleOption("random") }
      }

      Text {
        text: mini.service && mini.service.repeatOn
          ? (mini.service.singleMode !== "0" ? "󰑘" : "󰑖") : "󰑗"
        color: mini.service && mini.service.repeatOn ? Color.accent : mini.dim
        font.family: mini.fontFamily
        font.pixelSize: Style.font.title
        height: controls.height
        verticalAlignment: Text.AlignVCenter
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: if (mini.service) mini.service.toggleOption("repeat") }
      }

      Text {
        text: mini.fmt(mini.playPos) + " / " + (mini.durNow > 0 ? mini.fmt(mini.durNow) : "--:--")
        color: mini.dim
        font.family: mini.fontFamily
        font.pixelSize: Style.font.caption
        height: controls.height
        verticalAlignment: Text.AlignVCenter
      }
    }

  }
}
