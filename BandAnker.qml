import QtQuick
import qs.Commons

// The player band, look "anchor": the artwork is the anchor -- big, with
// everything else reduced to text and one row of controls. The panel stays plain
// (Backdrop mode "off"), so the cover is the only picture on screen.
//
// Same band as "classic" (BandChrome.qml), only the picture is bigger -- which
// makes the band taller, so the list shows a couple of rows less.
BandChrome {
  cover: "big"
  coverSize: Style.space(104)
}
