import QtQuick
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import qs.Commons
import qs.Ui

// Die Karte auf dem Hintergrundbild (Entwurf D).
//
// Aufbau von oben nach unten in einer Spalte, damit sich die Karte selbst
// dimensioniert. Feste Abstaende in Kartenhoehe waeren hier falsch: sie muessen
// bei jeder Aenderung nachgezogen werden und brechen still, sobald ein Element
// dazukommt.
//
// Material: die Grundpalette des Themes mit Deckkraft, keine Oberflaechenrolle.
// Keine der Rollen in Color.qml beschreibt eine Karte, die AUF dem
// Hintergrundbild liegt -- Popups und Tooltips werden ueber Fenstern gezeichnet
// und sind entsprechend deckend. Der Haarstrich kommt aus foreground, nicht aus
// accent: eine Akzentkontur macht aus jedem Widget eine Benachrichtigung.
Item {
  id: card

  // Das BarWidget: von dort kommen Zustand, Cover und die cava-Pegel.
  property var host: null
  property int cardWidth: 300
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

      // 1. Cover in eigenem, leicht eingelassenem Rahmen.
      BorderSurface {
        id: coverFrame
        Layout.fillWidth: true
        // Quadrat: die Hoehe folgt der zugeteilten Breite.
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
            visible: false      // sichtbar wird die Maske darunter
          }

          // clip:true plus radius rundet in dieser Laufzeit NICHT (am
          // Vinyl-Look gemessen). Die Maske ist der Weg, der wirklich rundet.
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

        // Rueckfall, solange kein Cover da ist.
        Text {
          anchors.centerIn: parent
          visible: card.coverPath === ""
          text: "\u266b"
          color: card.faintColor
          font.pixelSize: Math.round(parent.width * 0.28)
          font.family: Style.font.family
        }
      }

      // 2. Titel und Interpret.
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

      // 3. Welle: dieselbe Komponente wie die Spielleiste, 18 Balken, live von
      // cava. Sie liest die Pegel des Widgets, weil sie im selben Baum lebt.
      Item {
        id: waveBox
        Layout.fillWidth: true
        Layout.preferredHeight: 42

        Visualizer {
          anchors.fill: parent
          count: 12
          levels: card.host ? card.host.vizBars : []
          barColor: card.playing ? Color.accent : card.faintColor
        }
      }

      // 4. Fortschritt: Spur, Fuellung im Akzent, Knopf.
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

      // 5. Die fuenf Knoepfe: Zufall, Zurueck, Play als gefuellter Kreis, Vor,
      // Queue. Alles laeuft ueber das Widget -- die Karte haelt keinen eigenen
      // MPD-Zustand.
      RowLayout {
        id: buttonsRow
        Layout.fillWidth: true
        Layout.topMargin: 4
        // Die Reihe sitzt mittig, nicht linksbuendig.
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

        // Play/Pause als gefuellter Kreis: die eine Stelle, an der die Karte
        // Farbe traegt, damit der Zustand ohne Icon-Vergleich ablesbar ist.
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
