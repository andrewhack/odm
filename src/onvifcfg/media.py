"""Media plane — profiles, stream URIs, snapshot URIs, encoder configs.

Minimum viable read surface: enough to drive the live preview and show the
user what video profiles the camera exposes. Setters (SetVideoEncoderConfiguration,
imaging adjust) are staged for Phase 3 continuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from .session import DeviceSession


@dataclass(slots=True, frozen=True)
class Resolution:
    width: int
    height: int


@dataclass(slots=True, frozen=True)
class VideoEncoder:
    name: str
    encoding: str
    resolution: Resolution | None
    fps: int | None
    bitrate_kbps: int | None


@dataclass(slots=True, frozen=True)
class Profile:
    token: str
    name: str
    video_source_token: str | None
    video_encoder: VideoEncoder | None
    ptz_token: str | None


def get_profiles(sess: DeviceSession) -> list[Profile]:
    raw = sess.media.GetProfiles() or []
    out: list[Profile] = []
    for p in raw:
        vec = getattr(p, "VideoEncoderConfiguration", None)
        venc = None
        if vec is not None:
            res = getattr(vec, "Resolution", None)
            rate = getattr(vec, "RateControl", None)
            venc = VideoEncoder(
                name=getattr(vec, "Name", "") or "",
                encoding=str(getattr(vec, "Encoding", "") or ""),
                resolution=Resolution(int(res.Width), int(res.Height)) if res else None,
                fps=int(rate.FrameRateLimit) if rate else None,
                bitrate_kbps=int(rate.BitrateLimit) if rate else None,
            )
        vsc = getattr(p, "VideoSourceConfiguration", None)
        ptz = getattr(p, "PTZConfiguration", None)
        out.append(
            Profile(
                token=p.token,
                name=getattr(p, "Name", "") or "",
                video_source_token=getattr(vsc, "SourceToken", None) if vsc else None,
                video_encoder=venc,
                ptz_token=ptz.token if ptz else None,
            )
        )
    return out


def get_stream_uri(
    sess: DeviceSession,
    profile_token: str,
    *,
    protocol: str = "RTSP",
    stream: str = "RTP-Unicast",
) -> str:
    """Return the RTSP URI for a given profile token."""
    resp = sess.media.GetStreamUri({
        "StreamSetup": {"Stream": stream, "Transport": {"Protocol": protocol}},
        "ProfileToken": profile_token,
    })
    return str(resp.Uri)


def get_snapshot_uri(sess: DeviceSession, profile_token: str) -> str | None:
    """Return the HTTP snapshot URI for a profile, or None if the device
    does not expose one (not every vendor implements GetSnapshotUri even
    when it implements GetStreamUri).
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        resp = sess.media.GetSnapshotUri({"ProfileToken": profile_token})
    except Exception as e:
        log.info("GetSnapshotUri failed: %s", e)
        return None
    if resp is None:
        return None
    uri = getattr(resp, "Uri", None) or str(resp)
    return str(uri) if uri else None


def uri_with_credentials(uri: str, user: str, password: str) -> str:
    """Inject user:pass into a URI - some players expect them inline.

    Works for rtsp://host/path and http://host/path, including when the URI
    already has a userinfo component (it is replaced).
    """
    p = urlparse(uri)
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    if not host:
        return uri
    userinfo = f"{quote(user, safe='')}:{quote(password, safe='')}"
    netloc = f"{userinfo}@{host}"
    return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
