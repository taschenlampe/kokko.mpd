import QtQuick
import qs.Commons

// Look "sharp": the same band as klassisch, with the artwork given more room --
// 88 px instead of 58. The other half of this look is the panel's backdrop, which
// stops blurring and keeps the cover as a photograph (see Backdrop.qml, mode
// "sharp").
BandKlassisch {
  coverSize: Style.space(88)
}
