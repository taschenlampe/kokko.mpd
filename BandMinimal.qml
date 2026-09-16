import QtQuick

// The player band, look "minimal": no artwork at all, one thin line -- title,
// meta and progress, then prev/play/next. For people who leave `showArt` off in
// the bar and don't want a picture in the panel either, just the transport.
//
// The band's height is the whole point of this look (38 px: three more list rows
// than classic), so BandChrome.qml folds it down to a single line for
// `cover: "none"` -- title and meta share that line, and the options row and the
// two queue glyphs every other look carries stay out of it; they are one tap away
// in the hover card and the settings tab. If that trade-off turns out wrong in
// practice, the fix is a taller variant, not stuffing this one.
//
// The panel forces `backdropMode: "off"` for this look (see Panel.qml) -- a
// blurred cover behind a band that shows no cover of its own would be a picture
// appearing from nowhere.
BandChrome {
  cover: "none"
}
