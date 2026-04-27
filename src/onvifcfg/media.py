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
    encoder_config_token: str | None
    encoder_gov_length: int | None
    ptz_token: str | None


def get_profiles(sess: DeviceSession) -> list[Profile]:
    raw = sess.media.GetProfiles() or []
    out: list[Profile] = []
    for p in raw:
        vec = getattr(p, "VideoEncoderConfiguration", None)
        venc = None
        enc_token: str | None = None
        gov: int | None = None
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
            enc_token = getattr(vec, "token", None) or getattr(vec, "Token", None)
            # GovLength sits on the H264 / H265 sub-block, not on the
            # configuration itself, so we read it from whichever is present.
            for sub in ("H264", "H265", "MPEG4"):
                blk = getattr(vec, sub, None)
                if blk is not None:
                    g = getattr(blk, "GovLength", None)
                    if g is not None:
                        gov = int(g)
                    break
        vsc = getattr(p, "VideoSourceConfiguration", None)
        ptz = getattr(p, "PTZConfiguration", None)
        out.append(
            Profile(
                token=p.token,
                name=getattr(p, "Name", "") or "",
                video_source_token=getattr(vsc, "SourceToken", None) if vsc else None,
                video_encoder=venc,
                encoder_config_token=enc_token,
                encoder_gov_length=gov,
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
    resp = sess.media.GetStreamUri(
        {
            "StreamSetup": {"Stream": stream, "Transport": {"Protocol": protocol}},
            "ProfileToken": profile_token,
        }
    )
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


@dataclass(slots=True, frozen=True)
class EncoderOptions:
    """Read-only summary of the tunable space on the primary encoder.

    Feeds the Phase 3 edit form so the UI can validate bitrate / resolution
    / fps choices against what the device actually advertises.
    """

    token: str
    encoding: str
    resolutions: tuple[Resolution, ...]
    fps_choices: tuple[int, ...]
    bitrate_range_kbps: tuple[int, int] | None
    gov_length_range: tuple[int, int] | None


def get_encoder_options(
    sess: DeviceSession, configuration_token: str, profile_token: str
) -> EncoderOptions | None:
    """Return the option space for a given encoder configuration.

    Wrapper around GetVideoEncoderConfigurationOptions.  Returns None if
    the device refuses or returns a malformed response.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        opts = sess.media.GetVideoEncoderConfigurationOptions(
            {
                "ConfigurationToken": configuration_token,
                "ProfileToken": profile_token,
            }
        )
    except Exception as e:
        log.info("GetVideoEncoderConfigurationOptions failed: %s", e)
        return None
    if opts is None:
        return None

    # onvif-zeep returns a union of H264 / JPEG / MPEG4 / H265 option
    # blocks; we surface whichever is populated, preferring H264.
    block = (
        getattr(opts, "H264", None)
        or getattr(opts, "H265", None)
        or getattr(opts, "JPEG", None)
        or getattr(opts, "MPEG4", None)
    )
    encoding = (
        "H264"
        if getattr(opts, "H264", None)
        else (
            "H265"
            if getattr(opts, "H265", None)
            else ("JPEG" if getattr(opts, "JPEG", None) else "MPEG4")
        )
    )
    resolutions: tuple[Resolution, ...] = ()
    fps_choices: tuple[int, ...] = ()
    gov_range: tuple[int, int] | None = None
    bitrate_range: tuple[int, int] | None = None
    if block is not None:
        rlist = getattr(block, "ResolutionsAvailable", None) or []
        resolutions = tuple(Resolution(int(r.Width), int(r.Height)) for r in rlist)
        fps_range = getattr(block, "FrameRateRange", None)
        if fps_range is not None:
            lo, hi = int(fps_range.Min), int(fps_range.Max)
            fps_choices = tuple(range(lo, hi + 1))
        gl = getattr(block, "GovLengthRange", None)
        if gl is not None:
            gov_range = (int(gl.Min), int(gl.Max))

    # Bitrate range lives on the Extension.BitrateRange element on newer
    # firmwares, or on RateControl of the profile-scoped Extension.
    ext = getattr(opts, "Extension", None)
    br = getattr(ext, "H264", None) if ext else None
    if br is not None:
        brr = getattr(br, "BitrateRange", None)
        if brr is not None:
            bitrate_range = (int(brr.Min), int(brr.Max))

    return EncoderOptions(
        token=configuration_token,
        encoding=encoding,
        resolutions=resolutions,
        fps_choices=fps_choices,
        bitrate_range_kbps=bitrate_range,
        gov_length_range=gov_range,
    )


def get_video_encoder_configuration(sess: DeviceSession, configuration_token: str) -> Any | None:
    """Read the raw VideoEncoderConfiguration object for a token.

    Handy for the edit form's pre-populate path: ``get_profiles`` only
    surfaces the slimmed-down ``VideoEncoder`` view. The setter below
    needs the unmodified fields it does not edit (Name, UseCount,
    Quality, Multicast, etc.) so the round-trip preserves them.
    """
    try:
        return sess.media.GetVideoEncoderConfiguration({"ConfigurationToken": configuration_token})
    except Exception:
        import logging

        logging.getLogger(__name__).info(
            "GetVideoEncoderConfiguration(%s) failed", configuration_token, exc_info=True
        )
        return None


def set_video_encoder_configuration(
    sess: DeviceSession,
    configuration_token: str,
    *,
    encoding: str | None = None,
    resolution: Resolution | None = None,
    fps: int | None = None,
    bitrate_kbps: int | None = None,
    encoding_interval: int | None = None,
    gov_length: int | None = None,
    quality: float | None = None,
    force_persistence: bool = True,
) -> None:
    """Apply a video encoder configuration change.

    Reads the current configuration first and patches only the fields
    the caller actually supplied, then writes it back.  This preserves
    Name / UseCount / Multicast / Quality on devices that reject a
    partially-populated configuration (some firmwares fault if Multicast
    is omitted on SetVideoEncoderConfiguration).

    Resolution / fps / bitrate / GovLength are validated against the
    options space the caller can fetch via ``get_encoder_options`` —
    this function does NOT re-validate, on purpose: the camera will
    reject anything illegal, and we want the form to surface the exact
    SOAP fault rather than a guess.
    """
    cfg = get_video_encoder_configuration(sess, configuration_token)
    if cfg is None:
        raise RuntimeError(
            f"could not read encoder configuration {configuration_token!r}; "
            "device refused GetVideoEncoderConfiguration"
        )

    # Build a plain-dict copy of the config so we can mutate it without
    # depending on zeep's element-mutability.  Round-trip through the
    # zeep helper that walks the object's attributes.
    payload = _zeep_to_dict(cfg)
    payload["token"] = configuration_token

    if encoding is not None:
        payload["Encoding"] = encoding
    if resolution is not None:
        payload["Resolution"] = {
            "Width": int(resolution.width),
            "Height": int(resolution.height),
        }
    rc = payload.get("RateControl") or {}
    if not isinstance(rc, dict):
        rc = _zeep_to_dict(rc)
    if fps is not None:
        rc["FrameRateLimit"] = int(fps)
    if bitrate_kbps is not None:
        rc["BitrateLimit"] = int(bitrate_kbps)
    if encoding_interval is not None:
        rc["EncodingInterval"] = int(encoding_interval)
    if rc:
        payload["RateControl"] = rc

    enc_name = (encoding or payload.get("Encoding") or "").upper()
    sub_key = {"H264": "H264", "H265": "H265", "MPEG4": "MPEG4"}.get(enc_name)
    if sub_key and (gov_length is not None or quality is not None):
        sub = payload.get(sub_key) or {}
        if not isinstance(sub, dict):
            sub = _zeep_to_dict(sub)
        if gov_length is not None:
            sub["GovLength"] = int(gov_length)
        payload[sub_key] = sub
    if quality is not None:
        payload["Quality"] = float(quality)

    sess.media.SetVideoEncoderConfiguration(
        {"Configuration": payload, "ForcePersistence": bool(force_persistence)}
    )


def _zeep_to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort flat dict from a zeep CompoundValue.

    Zeep's ``serialize_object`` would do this with full recursion, but it
    is not part of the stable public API and behaves differently across
    versions.  A plain attribute walk is enough for our shallow
    VideoEncoderConfiguration round-trip.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    out: dict[str, Any] = {}
    # zeep CompoundValue exposes attributes via __values__ on newer
    # versions and as plain attrs on older ones.
    src = getattr(obj, "__values__", None)
    if isinstance(src, dict):
        for k, v in src.items():
            out[k] = v
        return out
    for k in dir(obj):
        if k.startswith("_"):
            continue
        v = getattr(obj, k, None)
        if callable(v):
            continue
        out[k] = v
    return out


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
