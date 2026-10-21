"""Rate-limited JSON/HTML fetcher. No third-party packages. Safe to call from several threads: each host's pacing
is held under that host's own lock, so two threads never call one host closer together than its pace."""
import json, os, threading, time, urllib.request, urllib.error
from . import config

_last = {}
fails = {}          # consecutive failed calls per host; lets the scanner notice a source outage and stop calling it
extra = {}          # seconds added to a host's pacing after it said "too many requests", eased off as calls succeed
UA = "undertow-screener/0.1 (+research; contact via repo)"
_locks, _guard = {}, threading.Lock()


def _lock(host):
    with _guard:
        return _locks.setdefault(host, threading.Lock())


def _pace(host):
    gap = config.PACE.get(host, 1.0)
    if host == "jupiter" and os.environ.get("JUP_API_KEY"):
        gap /= 2                      # a free Jupiter key allows 1 request a second
    with _lock(host):
        gap += extra.get(host, 0.0)
        wait = _last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()


def fetch(host, url, as_json=True, tries=3, timeout=25, headers=None, data=None, quiet=False):
    """GET (or POST when data is given) with per-host pacing and backoff on 429/5xx. Returns None on a final failure.
    A 4xx other than 429 means the request itself was refused (for example, unknown token), not an outage. quiet: the
    call shares the host's pacing, but its failures do not count towards down() and a "too many requests" does not
    widen the pacing (the minute sampler's calls, which must not make the scan give up on a source or slow it down)."""
    for i in range(tries):
        _pace(host)
        hdrs = {"User-Agent": UA, "Accept": "application/json,text/html", **(headers or {})}
        body_out = None
        if data is not None:
            body_out = json.dumps(data).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body_out, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                if not quiet:
                    fails[host] = 0
                extra[host] = max(0.0, extra.get(host, 0.0) - 0.1)
                return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504):
                # GeckoTerminal's free tier turns away single calls even at its published pace, and the next call a few
                # seconds later usually goes through: a short wait that doubles beats a long fixed one, and the host's
                # pacing widens a little so the run settles below its limit instead of hitting it again and again
                if e.code == 429 and not quiet:   # the sampler's rare calls leave the scan's pacing alone
                    extra[host] = min(4.0, extra.get(host, 0.0) + 0.5)
                ra = e.headers.get("Retry-After", "0") or "0"
                wait = int(ra) if ra.isdigit() and int(ra) > 0 else 4 * 2 ** i
                if i < tries - 1:                 # no point waiting after the last try
                    time.sleep(min(wait, 65))
                continue
            if not quiet:
                fails[host] = 0
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
            if i < tries - 1:
                time.sleep(3 * (i + 1))
    if not quiet:
        fails[host] = fails.get(host, 0) + 1
    return None


def down(host, after=3):
    """True once `after` calls in a row to this host have failed outright."""
    return fails.get(host, 0) >= after
