import QtQuick
import qs.Commons

// The player band, look "split": the artwork as a full-height column on the left
// rather than a square centred in the row -- a fixed-width slab, not a thumbnail.
// Everything else sits beside it (BandChrome.qml).
//
// Sits between "hero" (cover as the whole card's background) and "anker" (cover as
// the only picture, band grown tall to fit it): here the cover is a structural
// block, not a backdrop and not the point on its own. The panel stays plain for
// this look too (see Panel.qml, backdropMode) -- a second picture behind a band
// that already carries one full-height would be artwork twice over.
BandChrome {
  cover: "column"
  coverSize: Style.space(108)
}
