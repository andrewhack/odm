"""Per-host credential cache for auto-login.

Stored as JSON in the user's config dir:
  Windows  %APPDATA%\\onvifcfg\\credentials.json
  POSIX    $XDG_CONFIG_HOME/onvifcfg/credentials.json (defaults to ~/.config)

Plaintext on purpose — this is a local convenience cache, not a secret
store. Don't run this tool as a shared service on untrusted hosts.

Each entry is a list of [user, password] pairs in most-recently-used
order; up to 10 per host are kept.  ``candidates(host)`` returns what to
try when opening a new session: anonymous first, then host-specific MRU,
then every pair ever seen on any host.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Iterable
from pathlib import Path
from threading import Lock

_lock = Lock()

_DEFAULT_TRIES: tuple[tuple[str, str], ...] = (
    ("admin", ""),
    ("", ""),
)


def _cache_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "onvifcfg" / "credentials.json"


def _load() -> dict[str, list[list[str]]]:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data: dict[str, list[list[str]]]) -> None:
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        import sys

        print(f"[creds-cache] save failed to {p}: {e}", file=sys.stderr, flush=True)


def remember(host: str, user: str, password: str) -> None:
    """Record a working (user, password) pair for ``host`` at the MRU slot."""
    with _lock:
        data = _load()
        entries = data.get(host, [])
        pair = [user, password]
        entries = [e for e in entries if e != pair]
        entries.insert(0, pair)
        data[host] = entries[:10]
        _save(data)
    import sys

    print(
        f"[creds-cache] remember host={host} user={user or '(anon)'} (cache at {_cache_path()})",
        file=sys.stderr,
        flush=True,
    )


def candidates(host: str) -> list[tuple[str, str]]:
    """Return the (user, password) pairs to try for ``host``, in order.

    1. Default empty-password tries (admin/""  and ""/"") first so the UI
       opens the device with no typing when the camera allows it.
    2. Host-specific MRU next.
    3. Finally every pair ever seen on any other host, deduped.
    """
    data = _load()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    def add(pair: Iterable[str]) -> None:
        t = tuple(pair)  # type: ignore[arg-type]
        if t in seen:
            return
        seen.add(t)
        out.append(t)  # type: ignore[arg-type]

    for pair in _DEFAULT_TRIES:
        add(pair)
    for pair in data.get(host, []):
        add(pair)
    for h, entries in data.items():
        if h == host:
            continue
        for pair in entries:
            add(pair)
    return out


def forget(host: str | None = None) -> None:
    """Clear the cache for one host (or all hosts if ``host`` is None)."""
    with _lock:
        data = _load()
        if host is None:
            data = {}
        else:
            data.pop(host, None)
        _save(data)


def known(host: str) -> bool:
    """True if any (user, password) pair has ever been saved for ``host``.

    Previously this filtered out the (admin, "") / ("", "") defaults so the
    UI badge only lit up on "real" auth - but a camera that genuinely
    accepts admin/"" has nonetheless been authenticated from the user's
    perspective, and showing "locked" for a camera the user just opened is
    confusing.  Any cached entry now counts.
    """
    return bool(_load().get(host))
