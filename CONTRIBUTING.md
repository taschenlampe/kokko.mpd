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

### What the suite covers, by what it needs

Three layers, and the point is that each one skips itself when its prerequisite is
missing — that is what lets CI and a desktop run the *same* file:

| Needs | Checks |
| --- | --- |
| nothing but Python | `py_compile`, the bridge's unit tests, `tests/check_consistency.py` (manifest complete, every setting the panel offers exists in the schema, `defaults` agrees with it, `\u` escapes carry exactly four hex digits) |
| Qt and the Omarchy shell | `qmllint`, `omarchy plugin validate` |
| the running desktop | `tests/smoke_mpd.py`, `tests/smoke_ui.py` |

`tests/smoke_ui.py` opens the panel, walks all eight tabs over the widget's own
`state` channel and checks what a human would otherwise have to look at: the tab
really switched, the selection sits inside the visible window, the footer hint still
fits, and the log has no load failure. It waits on **observable changes** instead of
a guessed number of seconds — the shell needs ten to fifteen seconds on this
machine, and the queue scrolls the playing row into view a moment *after* the tab
appears. Both were false alarms before the waits went in.

It is deliberately **not** part of `--fast`: it opens the panel, and a panel
flashing open on every commit is worse than the check is worth.

### CI

`.gitea/workflows/checks.yml` runs `tests/run.sh --fast` on every push to `main`
and on every pull request, in a container. There `qmllint`, `plugin validate` and
both smoke tests skip themselves, so CI covers the bridge, the manifest and the
seams between the files. **Everything QML-semantic stays a check on the machine the
plugin runs on** — a container has no panel, and pretending otherwise would be the
wrong kind of green.

The workflow needs a runner on the Gitea host; without one every run sits in
"waiting" forever. Registration, if the runner ever has to be rebuilt:

```sh
# token (plaintext in the answer -- reset it in the Gitea UI afterwards)
curl -s -X POST -H "Authorization: token <api-token>" \
  https://git.m2control.de/api/v1/repos/bm/kokko.mpd/actions/runners/registration-token

docker run --rm -v /opt/act-runner:/data docker.gitea.com/act_runner:latest \
  act_runner register --no-interactive --instance https://git.m2control.de \
  --token <token> --name vserver --labels ubuntu-latest:docker://node:20-bookworm
```

Then run it as a service with `restart: unless-stopped` and
`/var/run/docker.sock:/var/run/docker.sock`; `node:20-bookworm` is the image
because `actions/checkout` needs Node and `python3` comes in per `apt-get`.

## Deliberately not planned

Deliberately **not** planned: splitting `bin/mpd-bridge` into modules or rewriting
it to `with_cmd`. The file is a maintained copy of omajam (see `NOTICE.md`); a
module split would destroy the upstream comparison and cost more than the
structure brings in.
