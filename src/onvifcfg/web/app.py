"""FastAPI app serving the onvifcfg browser UI.

Surface:
  GET  /                       landing page - auto-discovers and lists cams
  GET  /connect                try cached/default creds, fall back to form
  POST /device                 submit credentials manually
  POST /apply                  apply a NetworkPatch
  GET  /snapshot/{host}.jpg    JPEG snapshot using any cached credentials
"""

from __future__ import annotations

import socket
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import credentials_cache as _creds
from .. import device_info as _dev
from .. import media as _media
from ..discovery import discover as _discover
from ..exceptions import OnvifcfgError, ValidationError
from ..models import DiscoveryMode, NetworkPatch
from ..network import apply as _apply
from ..network import compute_diff, read_state
from ..session import Credentials, DeviceSession
from ..validation import validate as _validate

_here = Path(__file__).parent
templates = Jinja2Templates(directory=str(_here / "templates"))

# Inject build metadata so every template can render it in the footer.
from .. import __version__ as _pkg_version  # noqa: E402

try:
    from .._buildinfo import GIT_SHA as _git_sha  # noqa: N811
except Exception:
    _git_sha = "dev"
templates.env.globals["version"] = _pkg_version
templates.env.globals["git_sha"] = _git_sha


def _safe_profiles(sess: DeviceSession) -> list[Any]:
    """Phase 3 read-only profile listing for the device page.

    Wrapped in a try so a cranky media-service camera (no profiles, bad
    WSDL, auth only covers device_service) does not break the whole
    /device render path; the page degrades gracefully to "no profiles".
    """
    try:
        return list(_media.get_profiles(sess))
    except Exception as e:
        import logging

        logging.getLogger("onvifcfg.profiles").info("get_profiles failed: %s", e)
        return []


def create_app() -> FastAPI:
    app = FastAPI(title="onvifcfg", openapi_url=None, docs_url=None, redoc_url=None)

    @app.exception_handler(Exception)
    def _on_error(request, exc):  # type: ignore[no-untyped-def]
        import traceback

        tb = traceback.format_exc()
        return HTMLResponse(
            "<h2>onvifcfg internal error</h2><pre>" + tb.replace("<", "&lt;") + "</pre>",
            status_code=500,
        )

    app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, timeout: float = 3.0, no_discover: bool = False) -> Any:
        devices: list[dict] = []
        error: str | None = None
        if not no_discover:
            try:
                for d in _discover(timeout_s=timeout):
                    u = urlparse(d.best_xaddr())
                    hostname = u.hostname or ""
                    ip = _to_ipv4(hostname)
                    devices.append(
                        {
                            "host": ip,
                            "name": _reverse_dns(ip) or "",
                            "port": u.port or 80,
                            "xaddr": d.best_xaddr(),
                            "authed": _creds.known(ip),
                        }
                    )
            except Exception as e:
                error = f"discovery failed: {e}"
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "devices": devices, "error": error, "timeout": timeout},
        )

    @app.get("/connect", response_class=HTMLResponse)
    def connect_form(request: Request, host: str = "", port: int = 80) -> Any:
        for user, password in _creds.candidates(host):
            try:
                sess = DeviceSession(host, port, Credentials(user=user, password=password))
                state = read_state(sess)
            except Exception:
                continue
            _creds.remember(host, user, password)
            info = _dev.get_device_info(sess) if _dev else None
            profiles = _safe_profiles(sess)
            return templates.TemplateResponse(
                request=request,
                name="device.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "state": state,
                    "info": info,
                    "profiles": profiles,
                    "auto_login_note": f"auto-logged in as '{user or '(anonymous)'}'",
                },
            )
        return templates.TemplateResponse(
            request=request,
            name="connect.html",
            context={"request": request, "host": host, "port": port, "auto_failed": True},
        )

    @app.post("/device", response_class=HTMLResponse)
    def device(
        request: Request,
        host: str = Form(...),
        port: int = Form(80),
        user: str = Form(...),
        password: str = Form(...),
    ) -> Any:
        try:
            sess = DeviceSession(host, port, Credentials(user=user, password=password))
        except OnvifcfgError as e:
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "request": request,
                    "error": f"session error: {e}",
                    "devices": [],
                    "timeout": 3.0,
                },
            )
        # Session constructor succeeded - but read_state makes the first
        # real SOAP call which can still raise an auth fault.  If the auth
        # survives that first call, remember the creds even if something
        # further along fails, so a retry can pick them up from the cache.
        try:
            state = read_state(sess)
        except Exception as e:
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "request": request,
                    "error": f"session error: {e}",
                    "devices": [],
                    "timeout": 3.0,
                },
            )
        _creds.remember(host, user, password)
        info = _dev.get_device_info(sess) if _dev else None
        profiles = _safe_profiles(sess)
        return templates.TemplateResponse(
            request=request,
            name="device.html",
            context={
                "request": request,
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "state": state,
                "info": info,
                "profiles": profiles,
            },
        )

    @app.post("/apply", response_class=HTMLResponse)
    def apply(
        request: Request,
        host: str = Form(...),
        port: int = Form(80),
        user: str = Form(...),
        password: str = Form(...),
        dhcp: str | None = Form(None),
        ip: str | None = Form(None),
        subnet: str | None = Form(None),
        gateway: str | None = Form(None),
        dns: str | None = Form(None),
        ntp: str | None = Form(None),
        hostname: str | None = Form(None),
        hostname_from_dhcp: str | None = Form(None),
        http_port: int | None = Form(None),
        http_enabled: str | None = Form(None),
        https_port: int | None = Form(None),
        https_enabled: str | None = Form(None),
        rtsp_port: int | None = Form(None),
        rtsp_enabled: str | None = Form(None),
        zero_config_enabled: str | None = Form(None),
        discovery_mode: str | None = Form(None),
        client_ip: str | None = Form(None),
        confirm: str | None = Form(None),
    ) -> Any:
        patch = NetworkPatch(
            dhcp=_maybe_bool(dhcp),
            ip=IPv4Address(ip) if ip else None,
            subnet_mask=IPv4Address(subnet) if subnet else None,
            gateway=_csv_ips(gateway),
            dns=_csv_ips(dns),
            ntp_servers=_csv(ntp),
            hostname=hostname or None,
            use_hostname_from_dhcp=_maybe_bool(hostname_from_dhcp),
            http_port=http_port,
            http_enabled=_maybe_bool(http_enabled),
            https_port=https_port,
            https_enabled=_maybe_bool(https_enabled),
            rtsp_port=rtsp_port,
            rtsp_enabled=_maybe_bool(rtsp_enabled),
            zero_config_enabled=_maybe_bool(zero_config_enabled),
            discovery_mode=DiscoveryMode(discovery_mode) if discovery_mode else None,
        )
        try:
            sess = DeviceSession(host, port, Credentials(user=user, password=password))
            state = read_state(sess)
        except OnvifcfgError as e:
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={
                    "request": request,
                    "error": f"session error: {e}",
                    "devices": [],
                    "timeout": 3.0,
                },
            )

        diff = compute_diff(state, patch)
        if not diff.any:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={"request": request, "no_change": True, "host": host, "port": port},
            )

        try:
            warnings = _validate(
                state, patch, client_ip=IPv4Address(client_ip) if client_ip else None
            )
        except ValidationError as e:
            return templates.TemplateResponse(
                request=request,
                name="device.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "state": state,
                    "error": f"validation failed: {e}",
                },
            )

        if confirm != "yes":
            return templates.TemplateResponse(
                request=request,
                name="confirm.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "state": state,
                    "patch": patch,
                    "diff": diff,
                    "warnings": warnings,
                    "form_values": _form_dump(
                        ip=ip,
                        subnet=subnet,
                        gateway=gateway,
                        dns=dns,
                        ntp=ntp,
                        hostname=hostname,
                        hostname_from_dhcp=hostname_from_dhcp,
                        http_port=http_port,
                        http_enabled=http_enabled,
                        https_port=https_port,
                        https_enabled=https_enabled,
                        rtsp_port=rtsp_port,
                        rtsp_enabled=rtsp_enabled,
                        zero_config_enabled=zero_config_enabled,
                        discovery_mode=discovery_mode,
                        client_ip=client_ip,
                        dhcp=dhcp,
                    ),
                },
            )

        try:
            result = _apply(sess, state, patch, new_host_port=port)
        except OnvifcfgError as e:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={
                    "request": request,
                    "error": f"apply failed: {e}",
                    "host": host,
                    "port": port,
                },
            )
        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={"request": request, "host": host, "port": port, "result": result},
        )

    @app.get("/snapshot/{host}.jpg")
    def snapshot(host: str, port: int = 80) -> Response:
        import sys

        cands = _creds.candidates(host)
        print(
            f"[snapshot {host}:{port}] trying {len(cands)} candidate(s): "
            + ", ".join(u or "(anon)" for u, _ in cands),
            file=sys.stderr,
            flush=True,
        )
        """JPEG snapshot using cached creds with auth + no-auth + RTSP fallback.

        For each (user, password) candidate in the cache:
          1. Open an ONVIF session with those creds.
          2. Ask for the first profile's GetSnapshotUri.
          3. If the device returns one, fetch it with digest/basic auth,
             then retry anonymously if that returned 401.
        If no candidate produced a working HTTP snapshot AND at least one
        session authenticated successfully, fall back ONCE to an ffmpeg
        grab from the RTSP stream.  The fallback runs outside the
        per-credential loop on purpose: running it per-credential burned
        the camera's 10s RTSP timeout on every wrong cred, which made
        every snapshot look broken whenever the right cred was not the
        first one in the list.
        """
        import logging
        import urllib.error
        import urllib.request

        log = logging.getLogger("onvifcfg.snapshot")
        attempts: list[str] = []
        # First authenticated (user, password, profile_token) - for the
        # single ffmpeg fallback at the end.
        rtsp_fallback: tuple[str, str, str] | None = None
        for user, password in cands:
            label = user or "(anon)"
            try:
                sess = DeviceSession(host, port, Credentials(user=user, password=password))
                profs = _media.get_profiles(sess)
            except Exception as e:
                attempts.append(f"{label}: session/profiles failed ({e})")
                continue
            if not profs:
                attempts.append(f"{label}: device reports no media profiles")
                continue
            if rtsp_fallback is None:
                rtsp_fallback = (user, password, profs[0].token)
            try:
                uri = _media.get_snapshot_uri(sess, profs[0].token)
            except Exception as e:
                attempts.append(f"{label}: GetSnapshotUri threw ({e})")
                uri = None
            if not uri:
                attempts.append(f"{label}: device exposes no snapshot URI")
                continue
            # Two HTTP attempts: with digest/basic auth, then anonymous.
            for mode in ("auth", "anon"):
                try:
                    if mode == "auth":
                        pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                        pm.add_password(None, uri, user, password or "")
                        opener = urllib.request.build_opener(
                            urllib.request.HTTPBasicAuthHandler(pm),
                            urllib.request.HTTPDigestAuthHandler(pm),
                        )
                        src_opener: Any = opener
                    else:
                        src_opener = urllib.request
                    with src_opener.open(uri, timeout=6) as r:
                        ctype = r.headers.get("Content-Type", "?")
                        data = r.read()
                    # Some cameras share HTTP+ONVIF on the same port and route
                    # the snapshot path back to their SOAP/admin handler, so a
                    # 200 response can carry HTML or XML instead of a JPEG.
                    # Validate the JPEG magic before trusting it; on mismatch
                    # log what we actually got and fall through to ffmpeg.
                    if not (len(data) >= 3 and data[0] == 0xFF and data[1] == 0xD8):
                        head = data[:16].hex(" ")
                        attempts.append(
                            f"{label}/{mode}: not-jpeg from {uri} "
                            f"(ct={ctype!r} len={len(data)} head={head})"
                        )
                        break
                    _creds.remember(host, user, password)
                    return Response(
                        content=data,
                        media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"},
                    )
                except urllib.error.HTTPError as he:
                    attempts.append(f"{label}/{mode}: HTTP {he.code} from {uri}")
                    if he.code != 401:
                        break
                except Exception as e:
                    attempts.append(f"{label}/{mode}: {e}")
                    break
        # One-shot ffmpeg RTSP->JPEG fallback, using the first cred that
        # authenticated.  Runs at most ONCE per /snapshot request so a
        # camera without GetSnapshotUri still renders, without 10s-per-
        # wrong-credential stalls.
        if rtsp_fallback is not None:
            f_user, f_password, prof_token = rtsp_fallback
            import shutil
            import subprocess

            ffmpeg = None
            try:
                import imageio_ffmpeg as _iio

                ffmpeg = _iio.get_ffmpeg_exe()
                attempts.append(f"ffmpeg=imageio_ffmpeg:{ffmpeg}")
            except Exception as e:
                attempts.append(f"imageio_ffmpeg unavailable ({e})")
            if not ffmpeg:
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    attempts.append(f"ffmpeg=PATH:{ffmpeg}")
            if ffmpeg:
                rtsp = "<not resolved>"
                try:
                    sess = DeviceSession(
                        host,
                        port,
                        Credentials(user=f_user, password=f_password),
                    )
                    stream = _media.get_stream_uri(sess, prof_token)
                    rtsp = _media.uri_with_credentials(stream, f_user, f_password)
                    # Log the RTSP URI we are about to hand ffmpeg - without
                    # the password, so the stderr trace is safe to share.
                    from urllib.parse import urlparse, urlunparse

                    p = urlparse(rtsp)
                    safe_netloc = p.hostname or ""
                    if p.port:
                        safe_netloc = f"{safe_netloc}:{p.port}"
                    if p.username:
                        safe_netloc = f"{p.username}:***@{safe_netloc}"
                    attempts.append(
                        f"rtsp={urlunparse((p.scheme, safe_netloc, p.path, '', '', ''))}"
                    )
                    proc = subprocess.run(
                        [
                            ffmpeg,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-rtsp_transport",
                            "tcp",
                            "-i",
                            rtsp,
                            "-vframes",
                            "1",
                            "-f",
                            "mjpeg",
                            "-",
                        ],
                        capture_output=True,
                        timeout=15,
                    )
                    if proc.returncode == 0 and proc.stdout:
                        _creds.remember(host, f_user, f_password)
                        attempts.append(f"ffmpeg OK, {len(proc.stdout)} bytes")
                        print(
                            f"[snapshot {host}:{port}] OK via ffmpeg ({len(proc.stdout)} bytes)",
                            file=sys.stderr,
                            flush=True,
                        )
                        return Response(
                            content=proc.stdout,
                            media_type="image/jpeg",
                            headers={"Cache-Control": "no-store"},
                        )
                    tail = (proc.stderr or b"")[-400:].decode("utf-8", "replace").strip()
                    attempts.append(f"ffmpeg rc={proc.returncode} stderr={tail!r}")
                except subprocess.TimeoutExpired:
                    attempts.append(f"ffmpeg timed out after 15s on {rtsp[:80]}")
                except Exception as e:
                    attempts.append(f"ffmpeg path failed ({type(e).__name__}: {e})")
            else:
                attempts.append("no snapshot URI and ffmpeg not available")
        for a in attempts:
            log.info("snapshot %s: %s", host, a)
        diagnostic = f"[snapshot {host}:{port}] attempts: " + " | ".join(attempts)
        print(diagnostic, file=sys.stderr, flush=True)
        # Return the diagnostic as the response body so curl / DevTools
        # shows the reason inline without needing the server console.
        return Response(
            status_code=404,
            content=diagnostic.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/rtsp/{host}", response_class=HTMLResponse)
    def rtsp_link(request: Request, host: str, port: int = 80, profile: str = "") -> Any:
        """Return a page showing the RTSP stream URI for a camera.

        Uses cached credentials (same as the snapshot endpoint) to open an
        ONVIF session, fetch the requested (or first) profile's stream URI,
        and render it with a copy button and a VLC launch hint.
        404-equivalent page if no cached creds work.

        The ``profile`` query-string is an optional hint selecting which
        media profile to pull the RTSP URI from; falls back to the first
        profile when omitted, blank, or not found on this device.
        """
        import sys

        attempts: list[str] = []
        for user, password in _creds.candidates(host):
            label = user or "(anon)"
            try:
                sess = DeviceSession(host, port, Credentials(user=user, password=password))
                profs = _media.get_profiles(sess)
            except Exception as e:
                attempts.append(f"{label}: session/profiles failed ({e})")
                continue
            if not profs:
                attempts.append(f"{label}: device reports no media profiles")
                continue
            chosen = (
                next((p for p in profs if p.token == profile), profs[0]) if profile else profs[0]
            )
            try:
                uri = _media.get_stream_uri(sess, chosen.token)
            except Exception as e:
                attempts.append(f"{label}: GetStreamUri failed ({e})")
                continue
            with_creds = _media.uri_with_credentials(uri, user, password)
            _creds.remember(host, user, password)
            return templates.TemplateResponse(
                request=request,
                name="rtsp.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "profile_name": chosen.name or chosen.token,
                    "uri": uri,
                    "uri_with_creds": with_creds,
                },
            )
        print(
            f"[rtsp {host}:{port}] no cached cred worked; attempts: " + " | ".join(attempts),
            file=sys.stderr,
            flush=True,
        )
        return templates.TemplateResponse(
            request=request,
            name="rtsp.html",
            context={"request": request, "host": host, "port": port, "error": True},
        )

    @app.post("/action/reboot", response_class=HTMLResponse)
    def action_reboot(
        request: Request,
        host: str = Form(...),
        port: int = Form(80),
        user: str = Form(...),
        password: str = Form(...),
    ) -> Any:
        from .. import maintenance as _maint

        try:
            sess = DeviceSession(host, port, Credentials(user=user, password=password))
            came_back = _maint.reboot(sess, wait_s=90.0)
        except Exception as e:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "error": f"reboot failed: {e}",
                },
            )
        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "request": request,
                "host": host,
                "port": port,
                "result_msg": (
                    f"device came back on {host}:{port}"
                    if came_back
                    else "reboot requested - device did not answer within 90s"
                ),
            },
        )

    @app.post("/action/factory-reset", response_class=HTMLResponse)
    def action_factory_reset(
        request: Request,
        host: str = Form(...),
        port: int = Form(80),
        user: str = Form(...),
        password: str = Form(...),
        mode: str = Form("Soft"),
    ) -> Any:
        from .. import maintenance as _maint

        m = _maint.FactoryDefault.HARD if mode == "Hard" else _maint.FactoryDefault.SOFT
        try:
            sess = DeviceSession(host, port, Credentials(user=user, password=password))
            _maint.factory_default(sess, m)
        except Exception as e:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "error": f"factory reset failed: {e}",
                },
            )
        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "request": request,
                "host": host,
                "port": port,
                "result_msg": f"factory reset requested ({m.value})",
            },
        )

    return app


# ---------- helpers ----------


def _maybe_bool(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    return v in ("1", "true", "on", "yes", "True")


def _csv(v: str | None) -> tuple[str, ...] | None:
    if v is None:
        return None
    items = [s.strip() for s in v.replace(",", ";").split(";") if s.strip()]
    return tuple(items) if items else None


def _csv_ips(v: str | None) -> tuple[IPv4Address, ...] | None:
    raw = _csv(v)
    if raw is None:
        return None
    return tuple(ip_address(s) for s in raw)  # type: ignore[return-value]


def _form_dump(**kwargs: Any) -> dict[str, Any]:
    return {k: ("" if v is None else v) for k, v in kwargs.items()}


def _to_ipv4(host: str) -> str:
    if not host:
        return host
    try:
        import ipaddress

        ipaddress.IPv4Address(host)
        return host
    except ValueError:
        pass
    try:
        return socket.gethostbyname(host)
    except (socket.gaierror, socket.herror, OSError):
        return host


def _reverse_dns(ip: str) -> str | None:
    if not ip:
        return None
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.gaierror, socket.herror, OSError):
        return None
