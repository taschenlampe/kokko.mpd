import QtQuick
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import qs.Commons
import qs.Ui

// The card on the wallpaper (design D).
//
// Laid out top to bottom in a single column so the card sizes itself. Fixed
// offsets in card height would be wrong here: they have to be adjusted with
// every change and break silently as soon as an element is added.
//
// Material: the theme's foundational palette with an alpha, not a surface role.
// No role in Color.qml describes a card that sits ON the wallpaper -- popups and
// tooltips are drawn over windows and are opaque enough to say so. The hairline
// comes from foreground, not accent: an accent outline turns every widget into a
// notification.
Item {
  id: card

  // The bar widget: state, cover and the cava levels come from there.
  property var host: null
  property int cardWidth: 300
  property bool showWave: true
  property bool dimWhenPaused: true
  readonly property int inset: 14

  readonly property color textColor: Color.foreground
  readonly property color faintColor: Util.alpha(Color.foreground, 0.55)
  readonly property color lineColor: Util.alpha(Color.foreground, 0.14)
  readonly property int cardRadius: Style.cornerRadius > 0 ? Style.cornerRadius : 16

  readonly property string coverPath: host ? String(host.artPath || "") : ""
  readonly property string title: (host && host.song && host.song.title) ? String(host.song.title) : "Nothing playing"
  readonly property string artist: (host && host.song && (host.song.artist || host.song.albumartist)) ? String(host.song.artist || host.song.albumartist) : ""
  readonly property bool playing: host ? !!host.isPlaying : false

  readonly property real progress: {
    if (!host) return 0
    var d = Number(host.duration) || 0
    if (d <= 0) return 0
    var e = Number(host.elapsed) || 0
    return Math.max(0, Math.min(1, e / d))
  }

  // Taken back while paused, not hidden: the card stays readable.
  opacity: (dimWhenPaused && !playing) ? 0.55 : 1.0
  Behavior on opacity { NumberAnimation { duration: 220 } }

  implicitWidth: cardWidth
  implicitHeight: column.implicitHeight + 2 * inset

  BorderSurface {
    id: frame
    anchors.fill: parent
    radius: card.cardRadius
    color: Util.alpha(Color.background, 0.86)
    borderSpec: Border.flat(card.lineColor, Style.normalBorderWidth)

    ColumnLayout {
      id: column
      anchors {
        top: parent.top
        left: parent.left
        right: parent.right
        margins: card.inset
      }
      spacing: Style.space(4)

      // 1. Cover in its own, slightly inset frame.
      BorderSurface {
        id: coverFrame
        Layout.fillWidth: true
        // Square: the height follows the width it is given.
        Layout.preferredHeight: width
        radius: Math.max(4, card.cardRadius - Math.round(Style.normalBorderWidth))
        color: Util.alpha(Color.foreground, 0.05)
        borderSpec: Border.flat(Util.alpha(Color.foreground, 0.10), 1)

        Item {
          id: coverBox
          anchors.fill: parent
          anchors.margins: coverFrame.contentTopInset
          visible: card.coverPath !== ""

          Image {
            id: coverImage
            anchors.fill: parent
            source: card.coverPath !== "" ? Util.fileUrl(card.coverPath) : ""
            sourceSize.width: Math.round(coverBox.width)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            smooth: true
            visible: false      // the mask below is what shows
          }

          // clip:true plus radius does NOT round in this runtime (measured on
          // the vinyl look). The mask is the way that really rounds.
          OpacityMask {
            anchors.fill: parent
            source: coverImage
            maskSource: Rectangle {
              width: coverImage.width
              height: coverImage.height
              radius: Math.max(3, coverFrame.radius - coverFrame.contentTopInset)
              color: "white"
              visible: false
            }
          }
        }

        // Fallback while there is no cover yet.
        Text {
          anchors.centerIn: parent
          visible: card.coverPath === ""
          text: "\u266b"
          color: card.faintColor
          font.pixelSize: Math.round(parent.width * 0.28)
          font.family: Style.font.family
        }
      }

      // 2. Title and artist.
      Column {
        Layout.fillWidth: true
        spacing: 2

        Text {
          width: parent.width
          text: card.title
          color: card.textColor
          font.family: Style.font.family
          font.pixelSize: Style.font.subtitle
          font.bold: true
          elide: Text.ElideRight
          maximumLineCount: 1
        }

        Text {
          width: parent.width
          text: card.artist
          color: card.faintColor
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
          maximumLineCount: 1
          visible: card.artist !== ""
        }
      }

      // 3. Wave: the same component the playback band uses, live from cava. It
      // reads the widget's levels because it lives in the same tree.
      Item {
        id: waveBox
        Layout.fillWidth: true
        // Without the wave the space goes away instead of staying empty.
        visible: card.showWave
        Layout.preferredHeight: card.showWave ? 42 : 0

        Visualizer {
          anchors.fill: parent
          count: 12
          levels: card.host ? card.host.vizBars : []
          barColor: card.playing ? Color.accent : card.faintColor
        }
      }

      // 4. Progress: track, fill in the accent, knob.
      Item {
        id: progressBox
        Layout.fillWidth: true
        Layout.preferredHeight: 14

        Rectangle {
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width
          height: 4
          radius: 2
          color: Util.alpha(Color.foreground, 0.16)
        }

        Rectangle {
          anchors.verticalCenter: parent.verticalCenter
          width: Math.round(parent.width * card.progress)
          height: 4
          radius: 2
          color: Color.accent
        }

        Rectangle {
          anchors.verticalCenter: parent.verticalCenter
          x: Math.round(parent.width * card.progress) - width / 2
          width: 11
          height: 11
          radius: 6
          color: Color.foreground
          border.width: 1
          border.color: Util.alpha(Color.background, 0.55)
        }
      }

      // 5. The five buttons: shuffle, previous, play as a filled circle, next,
      // queue. Everything goes through the widget -- the card keeps no MPD state
      // of its own.
      RowLayout {
        id: buttonsRow
        Layout.fillWidth: true
        Layout.topMargin: 4
        // The row sits centred, not flush left.
        Layout.alignment: Qt.AlignHCenter
        spacing: Style.spacing.xs

        PanelActionButton {
          iconText: "󰑖"            // Zufall
          tooltipText: "Shuffle"
          foreground: card.host && card.host.randomOn ? Color.accent : card.faintColor
          onClicked: if (card.host) card.host.toggleOption("random")
        }

        PanelActionButton {
          iconText: "󰒮"            // Zurueck
          tooltipText: "Previous"
          foreground: card.textColor
          onClicked: if (card.host) card.host.previousTrack()
        }

        // Play/pause as a filled circle: the one place the card carries colour,
        // so the state reads without comparing two icons.
        Rectangle {
          id: playButton
          Layout.preferredWidth: 38
          Layout.preferredHeight: 38
          radius: width / 2
          color: Color.accent

          Text {
            anchors.centerIn: parent
            text: card.playing ? "󰏤" : "󰐊"
            color: Color.background
            font.family: Style.font.family
            font.pixelSize: Style.font.icon
          }

          TapHandler {
            onTapped: if (card.host) card.host.toggleTrack()
          }

          HoverHandler { cursorShape: Qt.PointingHandCursor }
        }

        PanelActionButton {
          iconText: "󰒭"            // Vor
          tooltipText: "Next"
          foreground: card.textColor
          onClicked: if (card.host) card.host.nextTrack()
        }

        PanelActionButton {
          iconText: "󰝚"            // Queue
          tooltipText: "Queue"
          foreground: card.textColor
          onClicked: if (card.host) card.host.toggle()
        }
      }
    }
  }
}
