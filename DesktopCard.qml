import QtQuick
import Qt5Compat.GraphicalEffects
import qs.Commons
import qs.Ui

// Die Karte auf dem Hintergrundbild (Entwurf D, Haeeppchen 1: Rahmen und Cover).
//
// Material: die Grundpalette des Themes mit Deckkraft, keine Oberflaechenrolle.
// Keine der Rollen in Color.qml beschreibt eine Karte, die AUF dem
// Hintergrundbild liegt -- Popups und Tooltips werden ueber Fenstern gezeichnet
// und sind entsprechend deckend. Und der Haarstrich kommt aus foreground, nicht
// aus accent: eine Akzentkontur macht aus jedem Widget eine Benachrichtigung.
Item {
  id: card

  // Das BarWidget: von dort kommen Zustand und Cover.
  property var host: null
  property int cardWidth: 300

  implicitWidth: cardWidth
  // Platz fuer Welle, Fortschritt und Knoepfe (Haeeppchen 2 und 3).
  implicitHeight: cardWidth + 138

  // Alle Texte der Karte an einer Stelle, mit Rueckfall auf die Bandfarbe.
  readonly property color textColor: Color.foreground
  readonly property color faintColor: Util.alpha(Color.foreground, 0.55)
  readonly property color lineColor: Util.alpha(Color.foreground, 0.14)
  readonly property int inset: 14
  readonly property int cardRadius: Style.cornerRadius > 0 ? Style.cornerRadius : 16

  readonly property string coverPath: host ? String(host.artPath || "") : ""
  readonly property string title: (host && host.song && host.song.title) ? String(host.song.title) : "Nothing playing"
  readonly property string artist: (host && host.song && (host.song.artist || host.song.albumartist)) ? String(host.song.artist || host.song.albumartist) : ""

  BorderSurface {
    id: frame
    anchors.fill: parent
    radius: card.cardRadius
    color: Util.alpha(Color.background, 0.86)
    borderSpec: Border.flat(card.lineColor, Style.normalBorderWidth)

    // Cover: eigener, leicht eingelassener Rahmen.
    BorderSurface {
      id: coverFrame
      anchors {
        top: parent.top
        left: parent.left
        right: parent.right
        margins: card.inset
      }
      height: width
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

        // clip:true plus radius rundet in dieser Laufzeit NICHT (am Vinyl-Look
        // gemessen). Die Maske ist der Weg, der wirklich rundet.
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

      // Rueckfall, solange (oder weil) kein Cover da ist: ein stilles Zeichen.
      Text {
        anchors.centerIn: parent
        visible: card.coverPath === ""
        text: "\u266b"
        color: card.faintColor
        font.pixelSize: Math.round(parent.width * 0.28)
        font.family: Style.font.family
      }
    }

    // Titel und Interpret unter dem Cover (Haeeppchen 1 endet hier).
    Column {
      anchors {
        top: coverFrame.bottom
        left: parent.left
        right: parent.right
        topMargin: card.inset
        leftMargin: card.inset
        rightMargin: card.inset
      }
      spacing: 4

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
  }
}
