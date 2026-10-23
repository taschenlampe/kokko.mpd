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
  // The widget's own verdict (BarWidget.stale: connected, but the greeting probe
  // is failing). The card does not re-decide it from `connected` or from a health
  // detail -- it asks, so there is one definition on every surface.
  readonly property bool stale: !!service && service.stale === true
  readonly property real durNow: (service && service.duration > 0) ? service.duration : 0
  readonly property bool playing: service !== null && service.isPlaying === true
  // A stream: the widget answers this (BarWidget.isStream/seekable) -- a stream's
  // `file` is the URL itself, and it has no duration to seek in.
  readonly property bool streaming: service !== null && service.isStream === true
  readonly property bool seekable: service !== null && service.seekable
    ? service.seekable() : false

  // The bridge reports the position only when something changes, so the client
  // carries it forward between events; while dragging, the pointer wins.
  property real dragFrac: -1
  property bool dragging: false
  property real playPos: 0
  readonly property real frac: dragFrac >= 0 ? dragFrac
    : (durNow > 0 ? Math.min(1, Math.max(0, playPos / durNow)) : 0)

  // The clock format lives in the widget (`formatTime`) -- one format on every
  // surface was the point. This copy is only for the moment before the service
  // exists, and it rounds down like the widget: rounding to nearest made this card
  // show a second more than the band beside it.
  function fmt(sec) {
    if (service && service.formatTime) return service.formatTime(sec)
    sec = Math.max(0, Math.floor(Number(sec) || 0))
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
    // Gated on `stale` too: while the daemon is wedged the position stops
    // arriving, and a clock the card carries forward on its own would keep
    // claiming a progress nobody is measuring.
    running: mini.open && mini.hasTrack && mini.playing && !mini.stale && !mini.dragging && mini.dragFrac < 0
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
      // Clicking the card (not a button) opens the panel; the wheel changes the
      // volume -- the readout that used to sit here is gone, the function stays.
      onClicked: if (mini.service) mini.service.toggle()
      onWheel: function(wheel) {
        if (mini.service) mini.service.nudgeVolume(wheel.angleDelta.y > 0 ? 5 : -5)
      }
    }

    // The card's hover state comes from a handler on the card itself, not from the
    // click area above: the transport buttons bring hover areas of their own (the
    // tint on next/prev needs `hoverEnabled`), and a child that takes the pointer
    // makes its *sibling* click area report `containsMouse: false` -- the widget then
    // read the card as left and closed it 280 ms later. Measured on the row of
    // buttons: exactly the two x positions of prev and next closed the card, play
    // (no hover area of its own) was fine. The handler is attached to the card, so
    // the pointer being anywhere on it counts, children included.
    HoverHandler {
      id: cardHover
      onHoveredChanged: mini.hovered = hovered
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
        // While the daemon is wedged the last title is a memory rather than the
        // state of anything: the line says what the connection is doing instead.
        // The card stays up so the line can be read (BarWidget.stale).
        // The station's name for a stream, the title for a file (BarWidget.songTitle).
        text: mini.stale ? "MPD is not answering"
          : (mini.service
             ? (String(mini.service.songTitle ? mini.service.songTitle() : "")
                || String(mini.service.song.title || "") || mini.service.basename(mini.service.songFile))
             : "")
        color: mini.fg
        font.family: mini.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: {
          // And the second line follows the first: a queue position and a tag
          // line from the last answered status are a memory as well.
          if (mini.stale) return ""
          if (!mini.service) return ""
          var bits = []
          if (mini.streaming) {
            // A stream carries no artist and no album: what stands here is what is
            // running on the station, plus the bitrate (BarWidget.songMeta).
            var line = String(mini.service.songMeta ? mini.service.songMeta() : "")
            if (line !== "") bits.push(line)
          } else {
            if (mini.service.song.artist) bits.push(String(mini.service.song.artist))
            // And the album, whenever the track carries one. The second line names
            // the album and nothing else: on a single or an untagged rip whose
            // album tag equals the title it repeats the first line, and that
            // repetition is wanted -- the album belongs here. An absent tag adds
            // nothing; no placeholder is invented for it.
            var alb = String(mini.service.song.album || "")
            if (alb) bits.push(alb)
          }
          if (mini.service.queueLength > 0)
            bits.push("#" + (mini.service.queuePosition + 1) + "/" + mini.service.queueLength)
          return bits.join("  ·  ")
        }
        color: mini.dim
        font.family: mini.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      // Progress: click or drag to seek. A stream has neither (mini.seekable),
      // so the line is not drawn at all instead of sitting empty. While the
      // daemon is wedged there is nothing to aim at either: the fill would sit
      // where it froze and claim a position that stopped being measured.
      Item {
        id: bar
        width: parent.width
        height: Style.space(12)
        visible: mini.seekable && !mini.stale

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
      // 6 px between 26 px buttons: the plates need a box of their own, and this
      // row shares the card's width with the clock on its right -- 30 px buttons
      // at 10 px pushed "6:50 / 17:07" out past the card's edge (seen on the
      // running card). At 26/6 the row ends 20 px inside the frame.
      spacing: Style.space(6)
      height: Style.space(30)

      // The plate under the glyph is the pointer feedback (TransportButton) --
      // the colour swap alone was too close to the foreground to read on the
      // card, and the band marks its transport the same way now.
      TransportButton {
        glyph: "󰒮"
        size: Style.space(26)
        height: controls.height
        glyphSize: Style.font.title
        fontFamily: mini.fontFamily
        glyphColor: mini.fg
        activeColor: Color.accent
        onClicked: if (mini.service) mini.service.previousTrack()
      }

      // The same filled disc the band and the desktop card show, at 30 px:
      // the card is where the transport gets room.
      PlayButton {
        anchors.verticalCenter: parent.verticalCenter
        size: Style.space(30)
        glyphSize: Style.font.heading
        host: mini.service
        accentColor: Color.accent
        fontFamily: mini.fontFamily
      }

      TransportButton {
        glyph: "󰒭"
        size: Style.space(26)
        height: controls.height
        glyphSize: Style.font.title
        fontFamily: mini.fontFamily
        glyphColor: mini.fg
        activeColor: Color.accent
        onClicked: if (mini.service) mini.service.nextTrack()
      }

      TransportButton {
        glyph: mini.service && mini.service.randomOn ? "󰒝" : "󰒞"
        on: mini.service && mini.service.randomOn
        size: Style.space(26)
        height: controls.height
        glyphSize: Style.font.title
        fontFamily: mini.fontFamily
        glyphColor: mini.dim
        activeColor: Color.accent
        onClicked: if (mini.service) mini.service.toggleOption("random")
      }

      TransportButton {
        glyph: mini.service && mini.service.repeatOn
          ? (mini.service.singleMode !== "0" ? "󰑘" : "󰑖") : "󰑗"
        on: mini.service && mini.service.repeatOn
        size: Style.space(26)
        height: controls.height
        glyphSize: Style.font.title
        fontFamily: mini.fontFamily
        glyphColor: mini.dim
        activeColor: Color.accent
        onClicked: if (mini.service) mini.service.toggleOption("repeat")
      }

    }

    // The clock keeps the progress line's right edge instead of trailing the
    // buttons: inside the row it was pushed out past the card's frame as soon as
    // the transport grew its plates (seen on the running card: "6:50 / 17:07" ran
    // about 20 px over the border). Anchored here it stays flush with the bar
    // above, whatever the transport does -- and a long duration only grows it to
    // the left, into the gap the buttons leave.
    Text {
      id: clockText
      // A stream has no clock: `0:37 / --:--` says nothing about a live stream,
      // so the readout is left out rather than shown half empty -- and the same
      // goes while the daemon is wedged, where the number stopped moving.
      visible: !mini.streaming && !mini.stale
      anchors { right: parent.right; rightMargin: Style.space(10)
                verticalCenter: controls.verticalCenter }
      text: mini.fmt(mini.playPos) + " / " + (mini.durNow > 0 ? mini.fmt(mini.durNow) : "--:--")
      color: mini.dim
      font.family: mini.fontFamily
      font.pixelSize: Style.font.caption
    }

  }
}
