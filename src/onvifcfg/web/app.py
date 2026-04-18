"""FastAPI app serving the onvifcfg browser UI.

This mirrors the CLI surface:
  GET  /                             -> landing page: discover + manual host entry
  POST /discover                     -> run WS-Discovery, list devices
  POST /device                       -> connect to a device, show current state + edit form
  POST /apply                        -> apply a patch, show result

The HTML is server-rendered with Jinja2. No JS framework: one ``fetch()``
in base.html handles the confirm-before-apply step.
"""

from __future__ import annotations

from ipaddress import IPv4Address, ip_address
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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

    app.mount(
        "/static",
        StaticFiles(directory=str(_here / "static")),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, timeout: float = 3.0, no_discover: bool = False) -> Any:
        """Landing page - runs WS-Discovery on load and lists cameras as links.

        Pass ?no_discover=1 to skip discovery (useful for fast page reloads);
        pass ?timeout=<s> to tune the probe window.
        """
        devices: list[dict] = []
        error: str | None = None
        if not no_discover:
            try:
                for d in _discover(timeout_s=timeout):
                    u = urlparse(d.best_xaddr())
                    devices.append({
                        "host": u.hostname or "",
                        "port": u.port or 80,
                        "xaddr": d.best_xaddr(),
                        "scopes": list(d.scopes),
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
        """Auto-login with a blank password; fall back to the form on failure.

        Many ONVIF cameras ship with a factory-default admin account and no
        password. Trying it first saves a click on fresh-out-of-the-box
        devices. We also try fully-anonymous (empty user + empty password)
        for the handful of firmwares that allow unauthenticated ONVIF access.
        """
        for user, password in [("admin", ""), ("", "")]:
            try:
                sess = DeviceSession(host, port, Credentials(user=user, password=password))
                state = read_state(sess)
            except Exception:
                continue
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
                    "auto_login_note": f"auto-logged in as '{user or '(anonymous)'}'",
                },
            )
        return templates.TemplateResponse(
            request=request,
            name="connect.html",
            context={
                "request": request,
                "host": host,
                "port": port,
                "auto_failed": True,
            },
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
            state = read_state(sess)
        except OnvifcfgError as e:
            return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "error": f"session error: {e}"})
        return templates.TemplateResponse(request=request, name="device.html", context={
                "request": request,
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "state": state,
            })

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
            return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "error": f"session error: {e}"})

        diff = compute_diff(state, patch)
        if not diff.any:
            return templates.TemplateResponse(request=request, name="result.html", context={
                    "request": request,
                    "no_change": True,
                    "host": host,
                    "port": port,
                })

        try:
            warnings = _validate(
                state,
                patch,
                client_ip=IPv4Address(client_ip) if client_ip else None,
            )
        except ValidationError as e:
            return templates.TemplateResponse(request=request, name="device.html", context={
                    "request": request,
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "state": state,
                    "error": f"validation failed: {e}",
                })

        if confirm != "yes":
            return templates.TemplateResponse(request=request, name="confirm.html", context={
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
                        ip=ip, subnet=subnet, gateway=gateway, dns=dns, ntp=ntp,
                        hostname=hostname, hostname_from_dhcp=hostname_from_dhcp,
                        http_port=http_port, http_enabled=http_enabled,
                        https_port=https_port, https_enabled=https_enabled,
                        rtsp_port=rtsp_port, rtsp_enabled=rtsp_enabled,
                        zero_config_enabled=zero_config_enabled,
                        discovery_mode=discovery_mode, client_ip=client_ip,
                        dhcp=dhcp,
                    ),
                })

        try:
            result = _apply(sess, state, patch, new_host_port=port)
        except OnvifcfgError as e:
            return templates.TemplateResponse(request=request, name="result.html", context={"request": request, "error": f"apply failed: {e}", "host": host, "port": port})

        return templates.TemplateResponse(request=request, name="result.html", context={
                "request": request,
                "host": host,
                "port": port,
                "result": result,
            })

    return app


# ---------- form helpers ----------


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
