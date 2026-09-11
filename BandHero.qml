import QtQuick
import qs.Commons

// Look "hero": the classic row -- cover, text and one control row, everything
// where the other looks put it -- but the artwork is the player card's *own*
// background, so the picture is one surface instead of a backdrop plus a
// thumbnail. The panel stays plain in this look (see Panel.qml, backdropMode).
//
// The first attempt spread the parts into the corners (transport top right, levels
// under the cover, queue icons bottom right); that read as scattered, so the
// arrangement is deliberately the familiar one.
BandKlassisch {
  coverSize: Style.space(92)
  cardCover: true
}
