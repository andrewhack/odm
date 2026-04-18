"""Live preview helpers.

CLI path: spawn ``ffplay`` against the camera's RTSP stream and forward
credentials via the URL's userinfo component.  ``ffplay`` is an ffmpeg
binary that ships with the same package; the build scripts declare it as
a runtime dependency.

Web UI path (Phase 4 follow-up): server-side transcode to HLS via an
``ffmpeg`` subprocess and serve the resulting ``.m3u8`` / ``.ts`` fragments
from a temporary directory. Browsers play HLS natively on Safari and via
hls.js elsewhere; latency is typically 1-3 s.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .exceptions import OnvifcfgError

log = logging.getLogger(__name__)


class PreviewNotAvailable(OnvifcfgError):
    pass


def spawn_ffplay(stream_uri: str, *, title: str | None = None) -> subprocess.Popen:
    """Open a local viewer window on the given RTSP URI. Non-blocking."""
    binary = shutil.which("ffplay")
    if not binary:
        raise PreviewNotAvailable(
            "ffplay not found on PATH - install ffmpeg "
            "(Debian: 'apt install ffmpeg'; Windows: bundle in installer)"
        )
    cmd = [
        binary,
        "-loglevel", "warning",
        "-fflags", "nobuffer",
        "-rtsp_transport", "tcp",
        "-window_title", title or "onvifcfg preview",
        stream_uri,
    ]
    log.info("launching ffplay: %s", " ".join(cmd[:3] + ["..."]))
    return subprocess.Popen(cmd)


def save_snapshot(snapshot_uri: str, output_path: Path, *, user: str | None = None, password: str | None = None) -> Path:
    """Download a single JPEG snapshot to disk. Returns the output path.

    Uses urllib with basic auth; some cameras allow anonymous snapshots,
    others require the same digest used for ONVIF itself.
    """
    import urllib.request

    req = urllib.request.Request(snapshot_uri)
    opener: urllib.request.OpenerDirector | None = None
    if user is not None:
        pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        pm.add_password(None, snapshot_uri, user, password or "")
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(pm),
            urllib.request.HTTPDigestAuthHandler(pm),
        )
    with (opener.open(req) if opener else urllib.request.urlopen(req)) as r, output_path.open("wb") as out:
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return output_path
