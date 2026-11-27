"""kokko.mpd's bridge between the Quickshell widget and MPD.

Written against docs/bridge-contract.md, independently of the frozen
bin/mpd-bridge. Standard library only. Layers, bottom up:

    protocol   bytes <-> commands, replies, ACKs, binary (no sockets)
    filters    the widget's conditions -> MPD filter expressions
    records    replies -> the rows the widget reads
    (phase 3+) connection, session, state, queries, artwork, radio, bridge
"""
