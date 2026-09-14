import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Format.js" as Format

// MPD in the Omarchy bar: what is playing, with cover, state glyph and
// transport; a click opens the panel in Panel.qml.
//
// Deliberately a bar-widget with no `service` kind. Under a replacement bar
// (charlieras262.floating-bar) a widget can never reach a service of its own:
// `bar.shell` is scoped to the bar's plugin, pluginOwnsTarget() refuses foreign
// ids, and the entry facade a replacement bar receives is service-less
// (shell.qml createScopedPluginShell, plugins/bar/Bar.qml). matjam.omajam is
// built the other way round and stays invisible there. Here the bridge is a
// child of this widget instead, so any bar works; the cost is one bridge per
// monitor -- which is one on a single-screen desktop.
//
// bin/mpd-bridge takes one JSON object per line on stdin and answers the same
// way (see the header of that file): commands and queries in; `connected`,
// `state`, `art`, `database`, `ack` and one `result` per query out. The bridge
// is taken from matjam/omajam (MIT) -- see NOTICE.md.
Panel {
  id: root
  moduleName: "kokko.mpd"
  ipcTarget: "kokko.mpd"
  manageIpc: false

  readonly property string homeDir: Quickshell.env("HOME") || ""
  readonly property string pluginDir: homeDir === ""
    ? "" : homeDir + "/.config/omarchy/plugins/" + moduleName
  readonly property string bridgePath: pluginDir === ""
    ? "" : pluginDir + "/bin/mpd-bridge"

  // ------------------------------------------------------------- settings
  // Straight out of this widget's entry in shell.json, the same way every
  // built-in widget reads them; the shell re-injects the entry whenever it is
  // written, so a change reaches the connection without a restart.
  readonly property string host: String(setting("host", "")).trim()
  readonly property int port: Math.max(0, Number(setting("port", 6600)) || 0)
  readonly property string password: String(setting("password", ""))
  readonly property string connectionKey: host + "\u0000" + port + "\u0000" + password

  readonly property string format: String(setting("format", "[%artist% - ][%title%|%filename%]"))
  readonly property int maxWidth: Math.max(40, Number(setting("maxWidth", 240)) || 240)
  readonly property string overflow: String(setting("overflow", "scroll")) === "elide" ? "elide" : "scroll"
  // The strip shows the icon and the label; the transport lives in the hover
  // card and the panel band.
  readonly property bool showStateIcon: setting("showStateIcon", true) === true
  readonly property bool showArt: setting("showArt", false) === true
  readonly property string whenIdle: String(setting("whenIdle", "icon")) === "hide" ? "hide" : "icon"
  readonly property string wheelAction: {
    var value = String(setting("wheelAction", "volume"))
    return ["volume", "seek", "track", "none"].indexOf(value) !== -1 ? value : "volume"
  }
  readonly property bool notifyTrack: setting("notifyTrack", false) === true
  readonly property bool hoverCard: setting("hoverCard", true) === true

  // Which look the panel's player band shows: classic | sharp | hero | anchor.
  // The panel picks its band component from this and decides what the cover
  // behind it does.
  readonly property string coverLook: {
    var v = String(setting("coverLook", "classic"))
    return v === "" ? "classic" : v
  }
  // The blurred cover behind the panel: 0 = off, 100 = as present as it gets.
  // Die Desktop-Karte. Alle Werte kommen ueber setting(), das den Eintrag aus
  // dem Schema liest -- dieselbe Mechanik wie coverLook und backdrop.
  readonly property bool desktopWidget: {
    var v = setting("desktopWidget", true)
    return v === true || String(v) === "true"
  }
  readonly property string desktopSize: String(setting("desktopSize", "card"))
  readonly property string desktopCorner: String(setting("desktopCorner", "bottom-right"))
  readonly property string desktopLayer: String(setting("desktopLayer", "desktop"))
  readonly property bool desktopDimOnPause: {
    var v = setting("desktopDimOnPause", true)
    return v === true || String(v) === "true"
  }
  // Die Ecke in vier Wahrheitswerte zerlegt: die Layerschicht kennt nur
  // top/bottom/left/right, kein "unten rechts".
  readonly property bool dcBottom: desktopCorner.indexOf("bottom") === 0
  readonly property bool dcTop: desktopCorner.indexOf("top") === 0
  readonly property bool dcLeft: desktopCorner.indexOf("left") >= 0
  readonly property bool dcRight: desktopCorner.indexOf("right") >= 0
  readonly property bool dcMiddle: desktopCorner === "center"
  readonly property int dcMargin: 28


  readonly property int backdrop: {
    var n = Number(setting("backdrop", 60))
    return isNaN(n) ? 60 : Math.max(0, Math.min(100, Math.round(n)))
  }
  readonly property bool osdOnChange: setting("osdOnChange", true) === true
  readonly property bool osdOnHover: setting("osdOnHover", false) === true
  readonly property int osdDuration: {
    var ms = Number(setting("osdDuration", 4200))
    return isNaN(ms) ? 4200 : Math.max(1000, Math.min(60000, ms))
  }

  readonly property color fg: bar ? bar.barForeground : Color.foreground
  // Verbose query/answer logging on the shell's console. Off by default; the
  // IPC method `debug` turns it on for a diagnosis session.
  property bool debugProtocol: false
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  // The Panel base does not carry these (only BarWidget does); the strip needs
  // them either way, so they are declared here like omajam does.
  readonly property bool vertical: bar ? bar.vertical : false
  readonly property int barSize: bar ? bar.barSize : Style.bar.sizeHorizontal

  // ---------------------------------------------------------------- state
  property bool connected: false
  property string target: ""
  property string serverVersion: ""
  property var status: ({})
  property var song: ({})
  property var artMap: ({})
  property string lastError: ""
  property int databaseRevision: 0
  property string lastAck: ""

  // MPD spells every one of these as a string.
  readonly property string playbackState: String(status.state || "stop")
  readonly property bool isPlaying: connected && playbackState === "play"
  readonly property bool isPaused: connected && playbackState === "pause"
  readonly property string songFile: String(song.file || "")
  readonly property bool hasSong: connected && songFile !== ""
  readonly property bool idle: !hasSong

  // MPD reports elapsed only when something changes, so the clock is carried
  // forward locally and reset by every update -- otherwise a progress bar
  // stands still between events.
  property real elapsedAnchor: 0
  property double anchorAt: 0
  property int clockTick: 0

  readonly property real elapsed: {
    var tick = root.clockTick          // dependency: recompute once a second
    if (!root.isPlaying || root.anchorAt <= 0) return root.elapsedAnchor
    var walked = root.elapsedAnchor + (Date.now() - root.anchorAt) / 1000
    return root.duration > 0 ? Math.min(walked, root.duration) : walked
  }

  readonly property real duration: Number(status.duration) || 0
  readonly property int volume: status.volume !== undefined ? Number(status.volume) : -1
  readonly property int queuePosition: status.song !== undefined ? Number(status.song) : -1
  readonly property int queueLength: Number(status.playlistlength) || 0
  readonly property bool randomOn: String(status.random || "0") === "1"
  readonly property bool repeatOn: String(status.repeat || "0") === "1"
  readonly property string singleMode: String(status.single || "0")
  readonly property bool consumeOn: String(status.consume || "0") === "1"
  readonly property string bitrate: String(status.bitrate || "")
  readonly property string audioFormat: String(status.audio || "")

  readonly property string artPath: songFile === "" ? "" : String(artMap[songFile] || "")

  readonly property string stateIcon: isPlaying ? "󰐊" : (isPaused ? "󰏤" : "󰓛")
  readonly property string stateGlyph: !connected ? "󰝛" : (hasSong ? stateIcon : "󰝚")

  // Die Desktop-Flaeche (Plugin-Art "panel") bekommt denselben Zustand wie das
  // Panel: sie kennt ihr eigenes QML, aber nicht die Bridge. Statt sie zweimal
  // verbinden zu lassen, reicht das Widget sich selbst weiter, sobald die Shell
  // den Loader der Flaeche registriert hat.


  function formatTime(seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0))
    var mins = Math.floor(total / 60)
    var secs = total % 60
    return mins + ":" + (secs < 10 ? "0" + secs : String(secs))
  }

  function basename(path) {
    var text = String(path || "")
    var cut = text.lastIndexOf("/")
    text = cut >= 0 ? text.substring(cut + 1) : text
    var dot = text.lastIndexOf(".")
    return dot > 0 ? text.substring(0, dot) : text
  }

  function dirname(path) {
    var text = String(path || "")
    var cut = text.lastIndexOf("/")
    return cut > 0 ? text.substring(0, cut) : ""
  }

  // Everything the label format may name, rebuilt on every state change and on
  // the clock tick above (which is what keeps %elapsed% moving).
  readonly property var tokens: {
    var s = song
    var has = hasSong
    var pos = queuePosition
    var out = {
      artist: String(s.artist || ""),
      albumartist: String(s.albumartist || ""),
      title: String(s.title || ""),
      album: String(s.album || ""),
      track: String(s.track || ""),
      disc: String(s.disc || ""),
      date: String(s.date || ""),
      genre: String(s.genre || ""),
      composer: String(s.composer || ""),
      performer: String(s.performer || ""),
      comment: String(s.comment || ""),
      // `name` is what an internet radio stream carries as its title.
      name: String(s.name || ""),
      file: String(s.file || ""),
      filename: basename(s.file),
      folder: dirname(s.file),
      state: isPlaying ? "playing" : (isPaused ? "paused" : "stopped"),
      stateicon: stateIcon,
      elapsed: has ? formatTime(elapsed) : "",
      duration: duration > 0 ? formatTime(duration) : "",
      remaining: duration > 0 ? formatTime(Math.max(0, duration - elapsed)) : "",
      position: pos >= 0 ? String(pos + 1) : "",
      length: queueLength > 0 ? String(queueLength) : "",
      volume: volume >= 0 ? String(volume) : "",
      bitrate: bitrate,
      audio: audioFormat,
      repeat: repeatOn ? "repeat" : "",
      random: randomOn ? "random" : "",
      single: singleMode !== "0" ? "single" : "",
      consume: consumeOn ? "consume" : ""
    }
    out.time = out.duration === "" ? out.elapsed : out.elapsed + "/" + out.duration
    return out
  }

  readonly property string label: hasSong ? Format.render(format, tokens) : ""
  readonly property bool artIsTheIcon: showArt && !showStateIcon && label === ""

  // ----------------------------------------------------------- the bridge
  // Line in, line out. Commands are fire-and-forget (the bridge pushes `state`
  // after anything that changes it); queries are matched back by id.
  property int nextQueryId: 1
  property var pending: ({})
  property var channelIds: ({})

  function send(line) {
    if (!bridge.running) return false
    bridge.write(String(line) + "\n")
    return true
  }

  function sendConfig() {
    if (!bridge.running) return
    send("config " + JSON.stringify({ host: host, port: port, password: password }))
  }

  // Commands with no answer of their own.
  function bare(command) { send(command) }

  // One queue or library mutation: {op, ...} as bin/mpd-bridge documents.
  function mutation(op, args) {
    var obj = { op: op }
    if (args) for (var k in args) obj[k] = args[k]
    send("cmd " + JSON.stringify(obj))
  }

  // One question; `cb(rows, error)` runs when the answer arrives. Queries
  // carrying a channel replace the one before them on that channel, which is
  // what makes typing in the search box cost one query rather than one per key.
  function query(kind, args, channel, cb) {
    if (!bridge.running) {
      if (cb) cb([], "bridge is not running")
      return
    }
    var id = nextQueryId++
    var name = String(channel || "")
    if (name !== "") channelIds[name] = id
    pending[id] = { cb: cb || null, channel: name }
    var obj = { id: id, kind: kind }
    if (args) for (var k in args) obj[k] = args[k]
    if (name !== "") obj.channel = name
    if (root.debugProtocol) console.warn("kokko.mpd: q#" + id + " " + kind + " ch=" + name)
    send("query " + JSON.stringify(obj))
  }

  // The bridge died with answers still owed: without this the panel would wait
  // for a line that can never arrive.
  function failPending(reason) {
    var owed = pending
    pending = ({})
    for (var id in owed) {
      var entry = owed[id]
      if (entry && entry.cb) entry.cb([], reason)
    }
  }

  function handle(line) {
    var text = String(line || "").trim()
    if (text === "") return
    var event = null
    try { event = JSON.parse(text) } catch (e) { return }
    if (!event || typeof event !== "object") return

    var name = String(event.event || "")

    if (name === "connected") {
      connected = true
      target = String(event.target || "")
      serverVersion = String(event.version || "")
      lastError = ""
      return
    }

    if (name === "disconnected") {
      connected = false
      status = ({})
      song = ({})
      lastError = String(event.error || "")
      return
    }

    if (name === "state") {
      status = event.status || ({})
      song = event.song || ({})
      elapsedAnchor = Number(status.elapsed) || 0
      anchorAt = Date.now()
      return
    }

    if (name === "art") {
      var uri = String(event.uri || "")
      if (uri === "" || !event.path) return
      var next = ({})
      for (var key in artMap) next[key] = artMap[key]
      next[uri] = String(event.path)
      artMap = next
      return
    }

    if (name === "database") {
      // The library changed; anything showing it is stale from here on.
      databaseRevision++
      return
    }

    if (name === "ack") {
      lastAck = String(event.error || "")
      return
    }

    if (name === "result") {
      var id = Number(event.id)
      var entry = pending[id]
      delete pending[id]
      if (root.debugProtocol)
        console.warn("kokko.mpd: r#" + id + " " + String(event.kind || "")
          + " rows=" + ((event.rows || []).length) + " err=" + String(event.error || ""))
      if (entry && entry.channel !== "" && channelIds[entry.channel] === id)
        delete channelIds[entry.channel]
      if (entry && entry.cb) {
        var error = String(event.error || "")
        if (error !== "") entry.cb([], error)
        else entry.cb(event.rows || [], "")
      }
      return
    }
  }

  // -------------------------------------------------------------- actions
  function toggleTrack() { bare("toggle") }
  function play() { bare("play") }
  function pause() { bare("pause") }
  function stopPlayback() { bare("stop") }
  function nextTrack() { bare("next") }
  function previousTrack() { bare("prev") }
  function playId(id) { mutation("playid", { id: Number(id) }) }
  function playPosition(pos) { mutation("playpos", { pos: Number(pos) }) }
  function addUri(uri) { mutation("add", { uri: String(uri) }) }
  function addAndPlay(uri) { mutation("addplay", { uri: String(uri) }) }
  function addFilter(filter) { mutation("findadd", { filter: filter }) }
  function removeId(id) { mutation("remove", { id: Number(id) }) }
  function moveSong(from, to) { mutation("move", { from: Number(from), to: Number(to) }) }
  function clearQueue() { mutation("clear") }
  function shuffleQueue() { mutation("shuffle") }
  function toggleOption(name) {
    var current = false
    if (name === "random") current = randomOn
    else if (name === "repeat") current = repeatOn
    else if (name === "consume") current = consumeOn
    else if (name === "single") current = singleMode !== "0"
    bare("setopt " + name + " " + (current ? "0" : "1"))
  }

  function nudgeVolume(delta) {
    var base = volume >= 0 ? volume : 100
    bare("volume " + Math.max(0, Math.min(100, base + delta)))
  }

  function nudgeSeek(delta) {
    bare("seek " + Math.max(0, Math.round(elapsed + delta)))
  }

  // ---------------------------------------------------------- panel loader
  // The Panel base owns the open state (its controller); the panel window in
  // Panel.qml follows it, so there is one truth for "is the panel up".
  readonly property bool panelOpen: opened

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.hostWidget = root
    panelLoader.item.anchorItem = strip
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  onBarChanged: injectPanel()

  // ---------------------------------------------------------------- strip
  visible: !(idle && whenIdle === "hide") || panelOpen
  implicitWidth: visible ? (vertical ? barSize : strip.implicitWidth) : 0
  implicitHeight: visible ? (vertical ? strip.implicitHeight : barSize) : 0

  Behavior on implicitWidth {
    enabled: !root.vertical
    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
  }

  // What the widget occupies: cover, state glyph, label reserve and the gaps
  // between them -- computed from the configured maximum, *not* from the current
  // title. The content inside is right-aligned, so the unused rest of the reserve
  // shows up at the left, where nothing of ours follows it.
  readonly property real stripReserve: {
    var w = Style.space(10)
    if (showArt && artPath !== "")
      w += barSize + Style.space(6)
    if (showStateIcon)
      w += stateIconText.implicitWidth + Style.space(6)
    return w + maxWidth
  }

  // %elapsed% and %remaining% move once a second; MPD only reports elapsed
  // when something changes, so the clock is what keeps it honest.
  Timer {
    id: clock
    interval: 1000
    running: root.isPlaying
    repeat: true
    onTriggered: root.clockTick++
  }

  Grid {
    id: strip
    anchors.centerIn: parent
    rows: root.vertical ? 99 : 1
    spacing: 0


    // Cover, state glyph and label together: one hover target and one click
    // target, so a click anywhere on what is playing opens the panel.
    Item {
      id: nowPlaying
      visible: info.implicitWidth > 0
      // As wide as what it shows: the label grows and shrinks with the title, and a
      // reserved width would leave that space as a visible hole next to the cover or
      // the label. What the hover card needs is not a wide widget but a stable
      // reference -- it gets `stripReserve` passed as its anchor width.
      implicitWidth: root.vertical ? root.barSize : info.implicitWidth + Style.space(10)
      implicitHeight: root.vertical ? info.implicitHeight + Style.space(8) : root.barSize

      Row {
        id: info
        anchors.centerIn: parent
        spacing: Style.space(6)

        // The cover, as a small square before the text (showArt).
        Item {
          visible: root.showArt && root.artPath !== ""
          implicitWidth: visible ? root.barSize : 0
          implicitHeight: root.barSize

          Image {
            anchors.centerIn: parent
            width: parent.implicitWidth - Style.space(6)
            height: width
            source: root.artPath
            sourceSize.width: 128
            sourceSize.height: 128
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            visible: status === Image.Ready
          }
        }

        // The play state, unless the user turned it off.
        Text {
          id: stateIconText
          visible: root.showStateIcon
          text: root.stateGlyph
          color: root.isPlaying ? Color.accent : root.fg
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          verticalAlignment: Text.AlignVCenter
          height: root.barSize
        }

        // The label. Clipped, because the marquee walks out of it. The box is only
        // as wide as the text (at most `maxWidth`), so it sits right next to the
        // state glyph; the fixed width that keeps the bar and the hover card still
        // lives in `stripReserve`, not here.
        Item {
          id: labelBox
          visible: root.vertical ? root.label !== "" : true
          clip: true
          implicitWidth: root.label === "" ? 0 : Math.min(labelText.implicitWidth, root.maxWidth)
          implicitHeight: root.barSize
          readonly property bool overflowing: labelText.implicitWidth > width

          Text {
            id: labelText
            x: 0
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            text: root.label
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            elide: (root.overflow === "elide" || labelBox.scrolling) ? Text.ElideRight : Text.ElideNone
          }

          readonly property bool scrolling: overflowing && root.overflow === "scroll" && width > 0

          SequentialAnimation {
            running: labelBox.scrolling
            loops: Animation.Infinite
            PauseAnimation { duration: 2000 }
            NumberAnimation {
              target: labelText
              property: "x"
              to: -(labelText.implicitWidth - labelBox.width)
              duration: Math.max(600, (labelText.implicitWidth - labelBox.width) * 24)
            }
            PauseAnimation { duration: 1400 }
            NumberAnimation { target: labelText; property: "x"; to: 0; duration: 240 }
          }

          onScrollingChanged: if (!scrolling) labelText.x = 0
        }

        // Nothing playing: say what the connection is doing instead of sitting
        // there empty. Only when the label has nothing to say.
        Text {
          visible: !root.hasSong
          text: root.connected ? "" : (root.lastError !== "" ? root.lastError : "warte auf MPD …")
          color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.6)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          height: root.barSize
          verticalAlignment: Text.AlignVCenter
          elide: Text.ElideRight
          width: Math.min(implicitWidth, root.maxWidth)
        }
      }

      MouseArea {
        id: pointer
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onClicked: function(mouse) {
          if (mouse.button === Qt.LeftButton) root.toggle()
          else if (mouse.button === Qt.MiddleButton) root.nextTrack()
          else root.toggle()
        }

        onWheel: function(wheel) {
          var delta = wheel.angleDelta.y > 0 ? 1 : -1
          if (root.wheelAction === "volume") root.nudgeVolume(delta > 0 ? 5 : -5)
          else if (root.wheelAction === "seek") root.nudgeSeek(delta > 0 ? 5 : -5)
          else if (root.wheelAction === "track") delta > 0 ? root.nextTrack() : root.previousTrack()
        }
      }
    }

  }


  // ------------------------------------------------------------- visualiser
  //
  // cava as a child process: raw ASCII bars on stdout, one frame per line (see
  // bin/cava.conf). It only runs while something is playing *and* the bars are
  // somewhere on screen -- cava reads the audio device, so running it unseen
  // would be work for nobody.
  property var vizBars: []
  readonly property int vizCount: 12
  property bool miniOpen: false
  // cava feeds the panel band only -- the hover card trades the bars for bigger
  // buttons, so the process runs exactly while the panel is up.
  // Die Karte auf dem Hintergrundbild braucht die Welle ebenfalls -- sonst
  // stuende sie still, sobald das Panel zu ist.
  property bool desktopCardVisible: true
  readonly property bool vizWanted: isPlaying && (panelOpen || desktopCardVisible)

  function applyViz(line) {
    var parts = String(line).split(";")
    var out = []
    for (var i = 0; i < root.vizCount; i++)
      out.push(Math.min(1, (Number(parts[i]) || 0) / 700))   // ascii_max_range is 1000
    root.vizBars = out
  }

  Process {
    id: vizProc
    command: root.pluginDir === "" ? [] : ["/usr/bin/cava", "-p", root.pluginDir + "/bin/cava.conf"]
    running: root.vizWanted
    onExited: root.vizBars = []
    stdout: SplitParser {
      onRead: function(line) { root.applyViz(String(line)) }
    }
  }

  // ---------------------------------------------------------- the hover card
  //
  // Open while the pointer is on the widget *or* on the card: the two are separate
  // surfaces with a gap between them, and the short grace period is what lets the
  // pointer cross it without the card vanishing on the way.
  property bool miniHovered: false
  // For `omarchy-shell kokko.mpd hover on`: opens the card without a pointer, for
  // checking it on a machine whose pointer cannot be driven from a script.
  property bool miniForced: false
  readonly property bool miniAllowed: hoverCard && hasSong && !panelOpen

  // The card is *created* when it should be on screen (Loader), not kept mapped
  // in a hidden state: a mapped layer surface with no client behind it makes
  // screencopy stall -- grim hung for minutes. Same reason as the OSD window.
  property bool miniKeepAlive: false

  function cardHovered() {
    return miniLoader.item !== null && miniLoader.item.hovered === true
  }

  function syncMini() {
    root.miniHovered = root.cardHovered()
    if (root.miniAllowed && (root.hovering || root.miniHovered || root.miniForced)) {
      miniHide.stop()
      root.miniOpen = true
      return
    }
    if (root.miniOpen && !miniHide.running) miniHide.restart()
  }

  onMiniOpenChanged: {
    if (root.miniOpen) {
      root.miniKeepAlive = true
      miniSettle.stop()
      return
    }
    // Outlive the card's own fade, then let the window go.
    if (root.miniKeepAlive) miniSettle.restart()
  }

  onMiniHoveredChanged: root.syncMini()
  onMiniAllowedChanged: root.syncMini()
  onPanelOpenChanged: root.syncMini()
  // `onHoveringChanged` already calls syncMini: it lives with the OSD block, since
  // the signal may only be handled once per object.

  Timer {
    id: miniHide
    interval: 280
    repeat: false
    onTriggered: root.miniOpen = false
  }

  Timer {
    id: miniSettle
    interval: 260
    repeat: false
    onTriggered: root.miniKeepAlive = false
  }

  Loader {
    id: miniLoader
    active: root.hasSong && (root.miniOpen || root.miniKeepAlive)
    source: Qt.resolvedUrl("MiniPlayer.qml")

    onLoaded: {
      item.service = root
      item.anchorItem = strip
      // The widget's right edge is the point that does not move (the bar makes the
      // widget grow to the left), so the card is centred on a fixed offset back from
      // it. Mapped *here*, in the widget's own window: mapping from inside the card's
      // surface (a different layer window) returned nonsense.
      item.cardCenterX = Qt.binding(function() {
        return root.mapToItem(null, root.width, 0).x - root.stripReserve / 2
      })
      item.open = Qt.binding(function() { return root.miniOpen })
      item.hoveredChanged.connect(function() { root.syncMini() })
    }
  }

  // ------------------------------------------------------------- settings
  //
  // Write a setting the way the plugin settings dialog does: the shell owns
  // shell.json, we ask it to change the key and it pushes the new value back to
  // us -- so the change is live, no restart, and there is only one writer.
  //
  // The shell takes the value as *JSON* (`setBarWidget(id, key, valueJson, …)`),
  // so a string has to arrive quoted: a raw `[%artist% - ]` is not valid JSON and
  // the write is dropped without a word. Numbers and booleans are their own JSON.
  // argv, not a shell string: a label format may contain anything.
  function setSetting(key, value) {
    var json
    if (value === true) json = "true"
    else if (value === false) json = "false"
    else if (typeof value === "number") json = String(value)
    else json = JSON.stringify(String(value))
    Util.execArgv(["omarchy-shell", "shell", "setBarWidget", String(moduleName), String(key), json, "{}"])
  }

  // Preview for the settings tab: what a pattern would produce for the song that
  // is playing right now.
  function previewLabel(pattern) {
    if (!hasSong) return ""
    return Format.render(String(pattern || ""), tokens)
  }

  // ---------------------------------------------------------------- covers
  //
  // The bridge caches covers by album and answers with a file path. Each request
  // goes on its own channel keyed by uri, because the bridge drops every query a
  // newer one supersedes on the same channel -- a shared channel would answer
  // only the last cover asked for and leave the rest empty.
  property var artCache: ({})
  property int artCacheCount: 0

  function artFor(uri, album, albumartist, cb) {
    var key = String(uri || "")
    if (key === "") { if (cb) cb(""); return }
    if (root.artCache[key] !== undefined) { if (cb) cb(String(root.artCache[key] || "")); return }
    root.query("art", { uri: key, album: String(album || ""), albumartist: String(albumartist || "") },
      "art:" + key, function(rows, error) {
        var path = ""
        if (error === "" && rows && rows.length > 0) path = String(rows[0].path || "")
        var next = ({})
        for (var k in root.artCache) next[k] = root.artCache[k]
        // Bounded: a browsing session would otherwise keep every cover it ever saw.
        var keys = Object.keys(next)
        if (keys.length >= 64) delete next[keys[0]]
        next[key] = path
        root.artCache = next
        root.artCacheCount = Object.keys(next).length
        if (cb) cb(path)
      })
  }

  // Keep only what is playing: the queue's own "delete everything else".
  function cropQueue() { root.mutation("crop") }

  // ------------------------------------------------------------- osd / notify
  // A track change is a new song file. The cover for it arrives a moment later
  // (the bridge fetches it), which is what the short delay is for -- otherwise
  // the card and the notification would show the previous record's art.
  property string lastAnnouncedFile: ""

  onSongFileChanged: {
    if (songFile === "" || songFile === lastAnnouncedFile) return
    lastAnnouncedFile = songFile
    announceTimer.restart()
  }

  Timer {
    id: announceTimer
    interval: 600
    repeat: false
    onTriggered: {
      if (root.notifyTrack) root.notifyTrackChange()
      if (root.osdOnChange) root.showOsd(false)
    }
  }

  function notifyTrackChange() {
    var title = String(song.title || basename(songFile))
    if (title === "") return
    var parts = []
    if (song.artist) parts.push(String(song.artist))
    if (song.album) parts.push(String(song.album))
    notifyProc.command = ["notify-send", "-a", "MPD",
      "-i", (artPath !== "" ? artPath : "audio-x-generic"),
      title, parts.join("  ·  ")]
    notifyProc.running = true
  }

  Process { id: notifyProc }

  // The card itself: our own overlay window rather than the bar's tooltip,
  // which takes one line of text and nothing else -- and the cover is the point.
  property bool osdVisible: false
  property bool osdOn: false

  function showOsd(persist) {
    osdVisible = true
    osdOn = true
    if (persist) osdHide.stop()
    else osdHide.restart()
    if (root.debugProtocol)
      console.warn("kokko.mpd: osd shown — art " + (root.artPath !== "")
        + " hover " + root.hovering)
  }

  function hideOsd() {
    osdOn = false
    osdFade.restart()
  }

  readonly property bool hovering: pointer.containsMouse

  onHoveringChanged: {
    // The hover card (see below) watches the same signal; one handler, because a
    // second `onHoveringChanged` on this object makes the whole widget fail to
    // load with "Property value set multiple times".
    root.syncMini()
    if (!root.osdOnHover || !root.hasSong) return
    if (root.hovering) root.showOsd(true)
    else root.hideOsd()
  }

  Timer {
    id: osdHide
    interval: root.osdDuration
    repeat: false
    onTriggered: root.hideOsd()
  }

  Timer {
    id: osdFade
    interval: 220
    repeat: false
    onTriggered: root.osdVisible = false
  }

  // The window is created only while the card is up (Loader), not kept mapped
  // forever in a hidden state: a mapped layer surface that never drew a buffer
  // makes screencopy stall -- grim hung for minutes with this plugin loaded.
  Loader {
    id: osdLoader
    active: root.osdVisible
    sourceComponent: osdComponent
  }

  Component {
    id: osdComponent

    PanelWindow {
        id: osdWindow
        anchors { top: true; bottom: true; left: true; right: true }
      color: "transparent"
      WlrLayershell.namespace: "kokko-mpd-osd"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      exclusionMode: ExclusionMode.Ignore
      mask: Region {}          // visual only, never steals a click

      Rectangle {
        id: osdCard
        width: Style.space(300)
        height: Style.space(76)
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(64)
        radius: Style.cornerRadius
        color: Util.alpha(Color.background, 0.97)
        border.width: Math.max(1, Style.normalBorderWidth)
        border.color: Color.popups.border
        opacity: root.osdOn ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180 } }

        Row {
          anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                    margins: Style.space(10) }
          spacing: Style.space(12)

          Rectangle {
            width: Style.space(56)
            height: Style.space(56)
            radius: Style.cornerRadius
            color: Util.alpha(Color.foreground, 0.06)
            border.width: Math.max(1, Style.normalBorderWidth)
            border.color: Util.alpha(Color.foreground, 0.12)
            clip: true

            Image {
              id: osdCover
              anchors.fill: parent
              source: root.artPath
              sourceSize.width: 128
              sourceSize.height: 128
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              visible: status === Image.Ready
            }

            Text {
              anchors.centerIn: parent
              visible: osdCover.status !== Image.Ready
              text: "󰝚"
              color: root.isPlaying ? Color.accent : root.fg
              font.family: root.fontFamily
              font.pixelSize: Style.font.displayLarge
            }
          }

          Column {
            width: parent.width - Style.space(68)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(4)

            Text {
              width: parent.width
              text: String(root.song.title || root.basename(root.songFile) || "—")
              color: Color.popups.text
              font.family: root.fontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              text: {
                var bits = []
                if (root.song.artist) bits.push(String(root.song.artist))
                if (root.song.album) bits.push(String(root.song.album))
                return bits.join("  ·  ")
              }
              color: Qt.darker(Color.popups.text, 1.35)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            // How far in: a line, not a bar with a handle -- it is a glance.
            Rectangle {
              width: parent.width
              height: Style.space(3)
              radius: height / 2
              color: Util.alpha(Color.foreground, 0.12)
              visible: root.duration > 0

              Rectangle {
                width: parent.width * (root.duration > 0
                  ? Math.max(0, Math.min(1, root.elapsed / root.duration)) : 0)
                height: parent.height
                radius: parent.radius
                color: Color.accent
              }
            }
          }
        }
      }
  }
  }

  // ------------------------------------------------------------------ IPC
  // Scripted from a keybind or a shell: omarchy-shell kokko.mpd state
  IpcHandler {
    target: root.ipcTarget

    function state(): string {
      return JSON.stringify({
        connected: root.connected,
        target: root.target,
        version: root.serverVersion,
        state: root.playbackState,
        volume: root.volume,
        elapsed: root.elapsed,
        duration: root.duration,
        song: root.song,
        art: root.artPath,
        artCache: root.artCacheCount,
        viz: root.vizBars,
        vizRunning: vizProc.running,
        lastError: root.lastError,
        lastAck: root.lastAck,
        queue: { position: root.queuePosition, length: root.queueLength },
        options: {
          random: root.randomOn, repeat: root.repeatOn,
          single: root.singleMode, consume: root.consumeOn
        },
        panelOpen: root.panelOpen,
        look: root.coverLook,
        backdrop: root.backdrop,
        osd: { visible: root.osdVisible, on: root.osdOn, hovering: root.hovering },
        hover: { open: root.miniOpen, hovered: root.miniHovered, allowed: root.miniAllowed },
        notifyOnTrack: root.notifyTrack,
        panel: panelLoader.item ? {
          tab: panelLoader.item.tab,
          frame: panelLoader.item.frameMode,
          breadcrumb: panelLoader.item.breadcrumb(),
          rows: panelLoader.item.rows.length,
          sel: panelLoader.item.sel,
          info: panelLoader.item.infoText,
          prompt: panelLoader.item.promptMode,
          promptText: panelLoader.item.promptText,
          preview: panelLoader.item.promptMode === "format" ? panelLoader.item.formatPreview : "",
          hint: panelLoader.item.hint,
          flash: panelLoader.item.flashText,
          peek: panelLoader.item.peek(8),
          hintTruncated: panelLoader.item.hintTruncated,
          bandHeight: Math.round(panelLoader.item.bandHeight),
          listY: Math.round(panelLoader.item.listY),
          filterText: panelLoader.item.filterText,
          promptLabel: panelLoader.item.promptLabel,
          frameTitle: panelLoader.item.frameTitle,
          // What the list is actually showing -- a selection can be right and
          // still sit off-screen, and no other field would say so.
          visible: (function () {
            var l = panelLoader.item.listView
            if (!l) return {}
            return { first: l.indexAt(0, l.contentY + 4), last: l.indexAt(0, l.contentY + l.height - 6),
                     y: Math.round(l.contentY), h: Math.round(l.height) }
          })(),
          gen: panelLoader.item.loadGeneration,
          sent: panelLoader.item.sentQueries,
          answered: panelLoader.item.answeredLoads,
          stale: panelLoader.item.staleAnswers,
          frameTerm: panelLoader.item.frame ? String(panelLoader.item.frame.term || "") : "",
          frameTag: panelLoader.item.frame ? String(panelLoader.item.frame.tag || "") : "",
          details: panelLoader.item.detailRow !== null
        } : null,
        strip: {
          label: root.label,
          hasSong: root.hasSong,
          showArt: root.showArt,
          artIsTheIcon: root.artIsTheIcon,
          stripWidth: root.implicitWidth,
          // The widget's own x on screen: does a shorter title move the widget (bar
          // centres its section) or not? Needed to place the card stably.
          stripX: Math.round(strip.mapToItem(null, 0, 0).x),
          // The widget's own edges in scene coordinates: the right one must not move
          // when the label changes, the left one may.
          widgetX: Math.round(root.mapToItem(null, 0, 0).x),
          widgetRight: Math.round(root.mapToItem(null, root.width, 0).x),
          // Where the hover card actually sits -- the number that proves it does not
          // hop when the label changes.
          cardX: miniLoader.item ? Math.round(miniLoader.item.cardX) : -1,
          // Where the content sits in the reserved width -- so "is the play glyph
          // right next to the text, and does the content end flush right?" is a
          // number, not a screenshot. `reserve` is the reserved width, `boxW` the
          // label box, `textW` the text, `contentRight` the right edge of the row.
          reserve: Math.round(root.stripReserve),
          boxW: Math.round(labelBox.width),
          textW: Math.round(labelText.implicitWidth),
          contentRight: Math.round(info.x + info.width),
          // The two distances the eye notices: glyph -> label (was the complaint)
          // and content -> right edge of the reserve.
          glyphGap: Math.round(labelBox.x - (stateIconText.x + stateIconText.width)),
          rightGap: Math.round(root.stripReserve - (info.x + info.width)),
          textX: Math.round(labelText.x),
          trunc: labelText.truncated
        }
      })
    }

    function toggle(): void { root.toggleTrack() }
    function play(): void { root.play() }
    function pause(): void { root.pause() }
    function stop(): void { root.stopPlayback() }
    function next(): void { root.nextTrack() }
    function previous(): void { root.previousTrack() }
    function prev(): void { root.previousTrack() }
    function refresh(): void { root.bare("refresh") }
    function reconnect(): void { root.sendConfig() }
    function update(): void { root.bare("update") }

    // Debug: open or close the hover card without a pointer. The card itself is
    // verified with `hover on` plus a screenshot; the pointer path is the same
    // signal the OSD uses.
    function hover(value: string): string {
      var v = String(value).toLowerCase()
      if (v !== "on" && v !== "off") return "usage: hover on|off"
      root.miniForced = (v === "on")
      root.syncMini()
      return root.miniOpen ? "open" : "closed"
    }

    function crop(): string {
      root.cropQueue()
      return "ok"
    }

    function debug(value: string): string {
      root.debugProtocol = String(value) === "on" || String(value) === "1"
      return root.debugProtocol ? "on" : "off"
    }

    // Both halves of the track-change feedback, on demand.
    function osd(): string {
      if (!root.hasSong) return "nothing playing"
      root.showOsd(false)
      return "ok"
    }

    function notify(): string {
      if (!root.hasSong) return "nothing playing"
      root.notifyTrackChange()
      return "ok"
    }

    function volume(level: string): string {
      if (String(level).trim() === "") return String(root.volume)
      var text = String(level).trim()
      if (text.charAt(0) === "+" || text.charAt(0) === "-") root.nudgeVolume(Number(text))
      else root.bare("volume " + Math.max(0, Math.min(100, Number(text))))
      return "ok"
    }

    function seek(seconds: string): string {
      root.bare("seek " + Math.round(Number(seconds)))
      return "ok"
    }

    function option(name: string): string {
      root.toggleOption(String(name))
      return "ok"
    }

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function panel(): void { root.toggle() }

    // Scriptable panel: omarchy-shell kokko.mpd find "kate bush"
    function find(term: string): string {
      if (!panelLoader.item) return "panel not loaded"
      root.open()
      panelLoader.item.setTab("search")
      panelLoader.item.promptMode = "search"
      panelLoader.item.promptText = String(term)
      panelLoader.item.submitPrompt()
      return "ok"
    }

    function files(path: string): string {
      if (!panelLoader.item) return "panel not loaded"
      root.open()
      panelLoader.item.setTab("files")
      if (String(path) !== "")
        panelLoader.item.pushFrame({ mode: "files", path: String(path),
                                     title: String(path).split("/").pop() })
      return "ok"
    }

    function tab(name: string): string {
      if (!panelLoader.item) return "panel not loaded"
      root.open()
      panelLoader.item.setTab(String(name))
      return String(panelLoader.item.tab)
    }

    function select(index: string): string {
      if (!panelLoader.item) return "panel not loaded"
      var at = Math.round(Number(index))
      if (isNaN(at)) return "not a number"
      panelLoader.item.sel = Math.max(0, Math.min(panelLoader.item.rows.length - 1, at))
      return String(panelLoader.item.sel)
    }

    // One key, as if it had been typed in the panel — for binds and for tests.
    function key(spec: string): string {
      if (!panelLoader.item) return "panel not loaded"
      var name = String(spec)
      var codes = {
        j: Qt.Key_J, k: Qt.Key_K, h: Qt.Key_H, l: Qt.Key_L, g: Qt.Key_G,
        enter: Qt.Key_Return, esc: Qt.Key_Escape, tab: Qt.Key_Tab,
        up: Qt.Key_Up, down: Qt.Key_Down, left: Qt.Key_Left, right: Qt.Key_Right,
        space: Qt.Key_Space, backspace: Qt.Key_Backspace, i: Qt.Key_I,
        pageup: Qt.Key_PageUp, pagedown: Qt.Key_PageDown, slash: Qt.Key_Slash,
        minus: Qt.Key_Minus, plus: Qt.Key_Plus, equal: Qt.Key_Equal
      }
      var code = codes[name] !== undefined ? codes[name] : 0
      // Faithful to a real keyboard: Qt delivers a text for printable keys, so
      // symbols have to carry theirs too (the field decides on `text`).
      var texts = { space: " ", slash: "/", minus: "-", plus: "+", equal: "=" }
      var text = name.length === 1 ? name : (texts[name] !== undefined ? texts[name] : "")
      panelLoader.item.handleKey({ key: code, text: text, modifiers: 0, accepted: false })
      return "ok"
    }
  }

  // ---------------------------------------------------------- bridge process
  onBridgePathChanged: Qt.callLater(syncBridge)
  Component.onCompleted: Qt.callLater(syncBridge)
  onConnectionKeyChanged: Qt.callLater(sendConfig)

  function syncBridge() {
    if (bridgePath === "") return
    if (bridge.running) return
    bridge.running = true
  }

  Process {
    id: bridge
    running: false
    // Through the interpreter rather than the shebang, so a checkout that lost
    // its executable bit still runs.
    command: ["python3", root.bridgePath]
    stdinEnabled: true

    onStarted: {
      root.lastError = ""
      root.sendConfig()
    }

    onExited: function(code, exitStatus) {
      root.connected = false
      root.status = ({})
      root.song = ({})
      root.lastError = "Bridge beendet (Code " + code + ")"
      console.warn("kokko.mpd: Bridge beendet (Code " + code + ") — restarting in 2.5s")
      root.failPending("Bridge beendet")
      restartTimer.restart()
    }

    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(line) { root.handle(String(line)) }
    }

    stderr: SplitParser {
      splitMarker: "\n"
      onRead: function(line) {
        var text = String(line || "").trim()
        if (text !== "") console.warn("kokko.mpd: " + text)
      }
    }
  }

  Timer {
    id: restartTimer
    interval: 2500
    repeat: false
    onTriggered: if (root.bridgePath !== "" && !bridge.running) bridge.running = true
  }

  // Die Karte auf dem Hintergrundbild. Das Fenster gehoert bewusst dem Widget
  // selbst und nicht der panel-Art: die Shell laedt eine panel-Flaeche zwar,
  // gibt dem Widget aber keinen Zugriff darauf (panelLoaders enthaelt nur die
  // eingebauten Panels, panelEntries nur unseren Manifest-Eintrag). So hat die
  // Flaeche den Zustand, weil dasselbe Objekt beides besitzt.
  Variants {
    model: Quickshell.screens
    delegate: Component {
      PanelWindow {
        required property var modelData
        screen: modelData
        // Der Schalter aus dem Einstellungstab: aus heisst, es gibt gar keine
        // Flaeche -- nicht nur eine unsichtbare.
        visible: root.desktopWidget
        color: "transparent"
        // Position aus der Einstellung. Bei "center" bleibt bewusst jede Kante
        // unverankert: die Layerschicht zentriert dann von selbst.
        anchors {
          top: root.dcTop
          bottom: root.dcBottom
          left: root.dcLeft
          right: root.dcRight
        }
        margins {
          top: root.dcMargin
          bottom: root.dcMargin
          left: root.dcMargin
          right: root.dcMargin
        }
        exclusiveZone: 0

        // Eingabebereich: standardmaessig nimmt die Flaeche KEINE Klicks an,
        // damit sie dem Desktop und den Fenstern nichts wegnimmt. Die Maske
        // gibt genau das Rechteck der Karte zurueck -- nicht mehr. Die Karte
        // ist damit immer bedienbar, ohne dass eine Einstellung sie stumm
        // schalten kann.
        mask: Region {
          id: inputMask
          x: 0
          y: 0
          width: desktopCard.width
          height: desktopCard.height
        }

        WlrLayershell.namespace: "kokko-mpd-desktop"
        // Bottom: die Karte liegt auf dem Hintergrundbild, unter jedem Fenster.
        // Die Einstellung darf sie darueber heben, etwa fuer Vollbildvideos.
        WlrLayershell.layer: root.desktopLayer === "above" ? WlrLayer.Top : WlrLayer.Bottom
        implicitWidth: desktopCard.implicitWidth
        implicitHeight: desktopCard.implicitHeight

        DesktopCard {
          id: desktopCard
          host: root
          cardWidth: root.desktopSize === "mini" ? 200 : 300
          showWave: root.desktopSize !== "mini"
          dimWhenPaused: root.desktopDimOnPause
        }
      }
    }
  }

}
