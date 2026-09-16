import QtQuick

// The player band, look "classic": the artwork as a small square on the left,
// title and meta beside it, the progress line under them, then the spectrum and
// the controls on the right.
//
// The band itself -- title, meta line, clock, progress, transport, spectrum --
// lives in BandChrome.qml. What is left here is the look: which shape the cover
// has and how big it is. The two looks that keep this arrangement wrap this file
// (sharp: a bigger square, hero: the picture as the card's background).
BandChrome {
  id: band

  // hero: the artwork is the card's own background instead of sitting behind the
  // whole panel.
  property bool cardCover: false

  cover: band.cardCover ? "card" : "thumb"
}
