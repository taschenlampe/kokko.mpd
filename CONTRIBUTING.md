# Contributing to kokko.mpd

What goes where: the [README](README.md) is for people using the plugin,
[docs/internals.md](docs/internals.md) for how it works inside, and the
[issue tracker](https://github.com/taschenlampe/kokko.mpd/issues) for what is open.

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

## The bridge migration

The bridge is being rewritten as an independent package (`kokko_mpd/`) next to the
old `bin/mpd-bridge`, which is frozen until the switch. What both must do is written
down in [docs/bridge-contract.md](docs/bridge-contract.md); the contract tests check
it against a fake MPD, never against a real one:

```sh
python3 tests/contract/run.py                 # the bridge the widget starts today
python3 tests/contract/run.py --bridge <path> # any other bridge executable
python3 tests/contract/run.py -k Supersede    # only the tests matching a name
```

They take about a minute, so `tests/run.sh` runs them and `--fast` (the pre-commit
hook) does not. The launcher refuses every connection except loopback ports other
than 6600 and unix sockets in the test's scratch home, so a bridge under test cannot
reach a real MPD even when it tries.
