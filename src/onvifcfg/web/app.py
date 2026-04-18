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
                    devices.append({
                        "host": ip,
                        "name": _reverse_dns(ip) or "",
                        "port": u.port or 80,
                        "xaddr": d.best_xaddr(),
                        "authed": _creds.known(ip),
                    })
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
            return templates.TemplateResponse(
                request=request,
                name="device.html",
                context={
                    "request": request,
                    "host": host, "port": port, "user": user, "password": password,
                    "state": state,
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
                context={"request": request, "error": f"session error: {e}", "devices": [], "timeout": 3.0},
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
                context={"request": request, "error": f"session error: {e}", "devices": [], "timeout": 3.0},
            )
        _creds.remember(host, user, password)
        return templates.TemplateResponse(
            request=request,
            name="device.html",
            context={
                "request": request,
                "host": host, "port": port, "user": user, "password": password,
                "state": state,
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
                context={"request": request, "error": f"session error: {e}", "devices": [], "timeout": 3.0},
            )

        diff = compute_diff(state, patch)
        if not diff.any:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={"request": request, "no_change": True, "host": host, "port": port},
            )

        try:
            warnings = _validate(state, patch, client_ip=IPv4Address(client_ip) if client_ip else None)
        except ValidationError as e:
            return templates.TemplateResponse(
                request=request,
                name="device.html",
                context={
                    "request": request,
                    "host": host, "port": port, "user": user, "password": password,
                    "state": state, "error": f"validation failed: {e}",
                },
            )

        if confirm != "yes":
            return templates.TemplateResponse(
                request=request,
                name="confirm.html",
                context={
                    "request": request,
                    "host": host, "port": port, "user": user, "password": password,
                    "state": state, "patch": patch, "diff": diff, "warnings": warnings,
                    "form_values": _form_dump(
                        ip=ip, subnet=subnet, gateway=gateway, dns=dns, ntp=ntp,
                        hostname=hostname, hostname_from_dhcp=hostname_from_dhcp,
                        http_port=http_port, http_enabled=http_enabled,
                        https_port=https_port, https_enabled=https_enabled,
                        rtsp_port=rtsp_port, rtsp_enabled=rtsp_enabled,
                        zero_config_enabled=zero_config_enabled,
                        discovery_mode=discovery_mode, client_ip=client_ip, dhcp=dhcp,
                    ),
                },
            )

        try:
            result = _apply(sess, state, patch, new_host_port=port)
        except OnvifcfgError as e:
            return templates.TemplateResponse(
                request=request,
                name="result.html",
                context={"request": request, "error": f"apply failed: {e}", "host": host, "port": port},
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
            file=sys.stderr, flush=True,
        )
        """JPEG snapshot using cached credentials with auth + no-auth fallback.

        For each (user, password) candidate in the cache:
          1. Open an ONVIF session with those creds.
          2. Get the first profile's snapshot URI.
          3. Fetch the URI with digest/basic auth configured.
          4. If that returns 401, retry without any auth (many cameras
             serve snapshots anonymously on HTTP even when ONVIF is
             locked down).
          5. If the HTTP fetch still fails, try the RTSP fallback below.
        On every failure, log the reason so "onvifcfg serve" console
        shows why a given camera has no preview.
        """
        import logging, urllib.error, urllib.request
        log = logging.getLogger("onvifcfg.snapshot")
        attempts: list[str] = []
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
            try:
                uri = _media.get_snapshot_uri(sess, profs[0].token)
            except Exception as e:
                attempts.append(f"{label}: GetSnapshotUri threw ({e})")
                continue
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
                        src = opener
                    else:
                        src = urllib.request
                    with src.open(uri, timeout=6) as r:  # type: ignore[union-attr]
                        data = r.read()
                    _creds.remember(host, user, password)
                    return Response(content=data, media_type="image/jpeg")
                except urllib.error.HTTPError as he:
                    attempts.append(f"{label}/{mode}: HTTP {he.code} from {uri}")
                    if he.code != 401:
                        break  # non-auth error, no point trying anon
                except Exception as e:
                    attempts.append(f"{label}/{mode}: {e}")
                    break
        for a in attempts:
            log.info("snapshot %s: %s", host, a)
        return Response(status_code=404, content=b"", media_type="image/jpeg")

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
