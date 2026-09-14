# Contributing to kokko.mpd

What goes where: the [README](README.md) is for people using the plugin,
[docs/internals.md](docs/internals.md) for how it works inside, and the
[issue tracker](https://git.m2control.de/bm/kokko.mpd/issues) for what is open.

## Tests

Everything that can be checked without a click runs in one call:

```sh
tests/run.sh            # everything, including a smoke test against a running MPD
tests/run.sh --fast     # without MPD -- that is what the pre-commit hook uses
tests/install-hooks.sh  # once per clone: activates the hook
```

The hook is the actual reason the tests exist: **a QML syntax error is invisible
here** — the shell starts, the widget is simply gone, without a message. `qmllint`
finds it (`omarchy plugin validate` does not), which is why it runs before every
commit. In an emergency: `git commit --no-verify`.

Two things are checked. Without MPD: the pure Python parts of the bridge — cover
picking with its ranking and size limit, the filter expression with both escaping
layers, the cache key, the image type, `music_directory` from `mpd.conf`. Plus
`qmllint` and `omarchy plugin validate`. With a running MPD: that the bridge
answers, fetches a cover, and that titles with special characters (`#1's …`,
`( O )( O )( O ), cl-018`) find themselves through the filter expression.

What was **not** possible automatically was filed as an issue in the repo (mouse
paths, `crop`) — both have since been checked by hand on the running desktop: the
clicks pass through to the row buttons and the cards, and `crop` keeps the playing
track as expected.

## Deliberately not planned

Deliberately **not** planned: splitting `bin/mpd-bridge` into modules or rewriting
it to `with_cmd`. The file is a maintained copy of omajam (see `NOTICE.md`); a
module split would destroy the upstream comparison and cost more than the
structure brings in.
