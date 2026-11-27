import QtQuick
import qs.Commons

// The player band, look "phosphor": the classic band with the cover standing in
// its own light -- an accent halo, a touch bigger than the picture itself and
// blurred, so it reads as light rather than as a second frame.
//
// The rest of this look is the panel's: scanlines over everything, the tab chips
// carrying their digits, and an accent wash under the row that plays. Glow and
// scanlines switch off on a light theme (Panel.phosphorGlow); the structure
// stays. It is the terminal player's screen, not its font: the names and columns
// are the plugin's own.
BandChrome {
  cover: "thumb"
  coverSize: Style.space(64)
  glow: true
}
