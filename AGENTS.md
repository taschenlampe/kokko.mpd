# Working on kokko.mpd

An Omarchy shell plugin: a Quickshell bar widget, a panel, and a long-running Python
bridge. `README.md` is for the people using it, `docs/internals.md` says how it works
inside, `CONTRIBUTING.md` covers the test setup.

## Language

Everything in this repo is English — code, comments, UI strings, README, manifest,
tests. There is no translation layer; the shell loads no Qt translations, so German in
the source would be German on screen for everyone.

## Check before claiming anything

```sh
qmllint -I /tmp/qslint <file>     # expect 0 lines containing error] or syntax]
bash tests/run.sh --fast          # bridge unit tests, state tests, lint, manifest
omarchy plugin validate
```

A QML syntax error is invisible at runtime: the shell starts and the widget is simply
gone, with no message. `qmllint` is the only thing here that catches it.

## Rules

- **Never change the user's state to prove something.** The MPD queue and the
  `favorites` playlist are user data: no `shuffle`, `clear`, `crop`, no keypresses that
  add or delete tracks, no setting stars for evidence. Use unit tests and
  `omarchy-shell kokko.mpd state` — it reports widget, panel and band state as JSON.
- **Leave `main` clean in the directory the shell loads from.** Work on a branch or in
  a git worktree (`git worktree add ../kmpd-<topic> -b <topic> main`); the running
  plugin is the working copy, not scratch space.
- **One checkout per agent.** Do not touch other clones of this repo.
- **Commit before a long verification.** A run that dies mid-check should leave a
  commit behind, not an uncommitted tree.
- **Report honestly.** "Compiles" is not "checked", and a visual change without a
  screenshot is not evidence. Say which parts you verified, which you did not, and what
  you left open on purpose.

## Where things live

`Panel.qml` — the panel: tabs, frames, key handling. `BarWidget.qml` — the bar label,
owns the bridge connection and the favorites set. `bin/mpd-bridge` — Python, one
long-lived process speaking JSON lines. `tests/` — one driver per state machine plus the
bridge unit tests. `docs/` — internals and mockups.

## Deliberately not planned

Splitting `bin/mpd-bridge` into modules: it is a maintained copy of omajam (see
`NOTICE.md`), and a module split would destroy that comparison.
