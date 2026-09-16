import QtQuick
import qs.Commons

// The player band, look "vinyl": the artwork sits inside a spinning disc instead
// of a square -- a circular clip, a rim line and a spindle dot at the centre.
// Everything around it (title, meta, progress, spectrum, controls) is the band
// from BandChrome.qml, so this look differs only in the shape of the picture.
//
// The disc turns while playing and holds its angle when paused, which is the
// rotation animation's own doing (see BandChrome.qml). Duration is decorative,
// not a reproduction of 33/45 RPM: slow enough to read as a record, fast enough
// that it doesn't look stuck at a glance.
BandChrome {
  cover: "disc"
  coverSize: Style.space(72)
}
