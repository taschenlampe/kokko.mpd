"""radio-browser.info: the one part of the bridge that leaves this machine.

No key, no account, one question: which stations match. Nothing here touches
MPD, so a search works while the player is down and can never change it.

Two ceilings, because a hang here would be a hang in the panel: the socket
timeout, and a wall-clock deadline around the whole request (getaddrinfo()
ignores socket timeouts, and a dead resolver parked one call for minutes once).
Anything the directory sends is somebody else's data: an address is followed
only if it is plain http(s) -- `urlopen` also speaks `file:`, and a hostile
station entry must not turn into a read of a local file.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from .tuning import T

UA = "kokko.mpd bridge (+https://github.com/taschenlampe/kokko.mpd)"
SEARCH_PATH = "/json/stations/search"
BYURL_PATH = "/json/stations/byurl"
MAX_BYTES = 4 * 1024 * 1024
LOGO_LIMIT = 512 * 1024
ROW_LIMIT = 200

HTTP_URL = re.compile(r"^https?://[^\x00-\x20\x7f]+$", re.IGNORECASE)


class RadioError(Exception):
    """The directory could not be asked, or did not answer with stations."""


def is_http_url(url) -> bool:
    return bool(HTTP_URL.match(str(url or "")))


def search_url(search: str, country: str = "", tag: str = "", limit: int = 50) -> str:
    """The search request. `name` only when there is one: an empty `name=` would
    read as "names containing nothing", which the directory has answered
    differently across releases."""
    params = [("limit", str(limit)), ("hidebroken", "true"),
              ("order", "votes"), ("reverse", "true")]
    if search:
        params.insert(0, ("name", search))
    if country:
        params.append(("countrycode", country))
    if tag:
        params.append(("tag", tag))
    return T.RADIO_API + SEARCH_PATH + "?" + urllib.parse.urlencode(params)


def byurl_url(stream: str) -> str:
    return T.RADIO_API + BYURL_PATH + "?" + urllib.parse.urlencode([("url", stream)])


def _body(url: str, timeout: float, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,image/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def get(url: str, timeout: float = None, limit: int = MAX_BYTES) -> bytes:
    """One GET, bounded in time even when the resolver is not."""
    timeout = T.RADIO_TIMEOUT if timeout is None else timeout
    outcome = {}

    def run():
        try:
            outcome["body"] = _body(url, timeout, limit)
        except BaseException as exc:      # carried across, not raised here
            outcome["error"] = exc

    worker = threading.Thread(target=run, name="radio_fetch", daemon=True)
    worker.start()
    worker.join(timeout + T.RADIO_GRACE)
    if worker.is_alive():
        raise RadioError("radio-browser did not answer within %gs" % (timeout + T.RADIO_GRACE))
    if "error" in outcome:
        exc = outcome["error"]
        if isinstance(exc, urllib.error.HTTPError):
            raise RadioError("radio-browser answered HTTP %s" % exc.code)
        raise RadioError(getattr(exc, "strerror", None) or str(exc) or type(exc).__name__)
    return outcome.get("body") or b""


def _number(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def stations(body, limit: int = ROW_LIMIT) -> list:
    """The usable half of an answer: checked stations on a playable address."""
    try:
        entries = json.loads(bytes(body).decode("utf-8", "replace"))
    except (ValueError, TypeError):
        raise RadioError("radio-browser answered something that is not JSON")
    if not isinstance(entries, list):
        raise RadioError("radio-browser answered something that is not a station list")
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if _number(entry.get("lastcheckok")) != 1:
            continue
        stream = str(entry.get("url_resolved") or "").strip()
        if not is_http_url(stream):
            continue
        rows.append({
            "name": str(entry.get("name") or ""),
            "url_resolved": stream,
            "codec": str(entry.get("codec") or ""),
            "bitrate": _number(entry.get("bitrate")),
            "country": str(entry.get("country") or ""),
            "countrycode": str(entry.get("countrycode") or ""),
            "lastcheckok": 1,
            "votes": _number(entry.get("votes")),
            "tags": str(entry.get("tags") or ""),
            "homepage": str(entry.get("homepage") or ""),
        })
        if len(rows) >= limit:
            break
    return rows


def search(conn, request, limit):
    """The `radio_search` query: no MPD connection is taken, nothing is written."""
    term = str(request.get("search") or request.get("term") or "").strip()
    country = str(request.get("country") or "").strip()
    tag = str(request.get("tag") or "").strip()
    if not term and not country and not tag:
        return []
    limit = max(1, min(ROW_LIMIT, limit))
    return stations(get(search_url(term, country, tag, limit)), limit)


# ------------------------------------------------------------ stream logos

def homepage_favicon(homepage: str) -> str:
    try:
        parts = urllib.parse.urlsplit((homepage or "").strip())
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return "%s://%s/favicon.ico" % (parts.scheme, parts.netloc)


def logo_candidates(body) -> list:
    """Every record's favicon, then each record's homepage /favicon.ico.

    The directory answers one stream address with several records that do not
    agree: measured, the first record's favicon was a 404 and the second's a
    30 KB PNG. So the answer is the chain, deduplicated.
    """
    try:
        entries = json.loads(bytes(body).decode("utf-8", "replace"))
    except (ValueError, TypeError):
        return []
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for url in (str(entry.get("favicon") or "").strip(),
                    homepage_favicon(str(entry.get("homepage") or ""))):
            if url and is_http_url(url) and url not in out:
                out.append(url)
    return out


def stream_logo(stream: str) -> tuple:
    """The station logo for a playing stream, or (b"", "")."""
    try:
        body = get(byurl_url(stream), limit=MAX_BYTES)
    except RadioError:
        return b"", ""
    for url in logo_candidates(body):
        try:
            data = get(url, limit=LOGO_LIMIT)
        except RadioError:
            continue
        if data and _is_image(data):
            return data, _mime(data)
    return b"", ""


def _is_image(data: bytes) -> bool:
    return (data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
            or data[:6] in (b"GIF87a", b"GIF89a"))


def _mime(data: bytes) -> str:
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/gif"


def install(bridge) -> None:
    bridge.queries.register("radio_search", search, local=True)
