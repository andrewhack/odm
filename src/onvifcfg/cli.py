"""CLI entry point (Typer + Rich)."""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, ip_address
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from . import __version__
from . import device_info as _dev
from . import maintenance as _maint
from . import media as _media
from . import preview as _preview
from . import ptz as _ptz
from . import users as _users
from .discovery import discover as _discover
from .exceptions import OnvifcfgError, ValidationError
from .models import DiscoveryMode, NetworkPatch, NetworkState, ProtocolName
from .network import apply as _apply
from .network import compute_diff, prefix_to_mask, read_state
from .session import Credentials, DeviceSession
from .validation import validate as _validate

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="ONVIF camera configuration - network, device, users, media, PTZ, preview.",
)
ptz_app = typer.Typer(no_args_is_help=True, help="PTZ control.")
users_app = typer.Typer(no_args_is_help=True, help="User management.")
time_app = typer.Typer(no_args_is_help=True, help="System time.")
encoder_app = typer.Typer(no_args_is_help=True, help="Video encoder configuration.")
app.add_typer(ptz_app, name="ptz")
app.add_typer(users_app, name="users")
app.add_typer(time_app, name="time")
app.add_typer(encoder_app, name="encoder")

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@app.callback()
def _root(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    _setup_logging(verbose)


def _open_session(host: str, port: int, user: str, password: str) -> DeviceSession:
    try:
        return DeviceSession(host, port, Credentials(user=user, password=password))
    except OnvifcfgError as e:
        console.print(f"[red]session error:[/] {e}")
        raise typer.Exit(code=2) from None


# -------------------- top-level --------------------


@app.command()
def version() -> None:
    """Print the installed onvifcfg version."""
    console.print(f"onvifcfg {__version__}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(3003, "--port", "-P"),
) -> None:
    """Launch the local web UI (FastAPI + Jinja)."""
    import uvicorn

    from ._buildinfo import GIT_SHA as _git_sha  # noqa: N811
    from .web.app import create_app

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    app_ = create_app()
    console.print(f"[green]onvifcfg {__version__} ({_git_sha}) web UI on http://{host}:{port}/[/]")
    uvicorn.run(app_, host=host, port=port, log_level="info")


@app.command()
def discover(
    timeout: float = typer.Option(3.0, "--timeout", "-t"),
) -> None:
    """WS-Discovery scan the local subnet."""
    devices = _discover(timeout_s=timeout)
    if not devices:
        console.print("[yellow]no ONVIF devices discovered[/]")
        raise typer.Exit(code=1)
    t = Table(title=f"discovered {len(devices)} device(s)")
    t.add_column("xAddr", style="cyan")
    t.add_column("scopes")
    for d in devices:
        t.add_row(d.best_xaddr(), "\n".join(d.scopes))
    console.print(t)


@app.command()
def info(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    """Print device identification fields."""
    sess = _open_session(host, port, user, password)
    d = _dev.get_device_info(sess)
    t = Table(show_header=False, title="device info")
    for k, v in [
        ("manufacturer", d.manufacturer),
        ("model", d.model),
        ("firmware", d.firmware_version),
        ("serial", d.serial_number),
        ("hardware id", d.hardware_id),
    ]:
        t.add_row(k, v)
    console.print(t)


@app.command()
def reboot(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    wait: float = typer.Option(90.0, "--wait", help="Reachability probe window in seconds."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Ask the device to reboot, then wait for it to come back."""
    if not yes and not Confirm.ask(f"reboot {host}?", default=False):
        raise typer.Exit(code=1)
    sess = _open_session(host, port, user, password)
    ok = _maint.reboot(sess, wait_s=wait)
    if ok:
        console.print(f"[green]device answered on {host}:{port}[/]")
    else:
        console.print(f"[yellow]device did not answer within {wait}s[/]")
        raise typer.Exit(code=1)


@app.command("factory-reset")
def factory_reset(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    hard: bool = typer.Option(
        False, "--hard", help="Also wipe network settings - you will lose the device."
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Reset the device to factory defaults. SOFT keeps network, HARD wipes everything."""
    mode = _maint.FactoryDefault.HARD if hard else _maint.FactoryDefault.SOFT
    if not yes and not Confirm.ask(f"factory-reset {host} ({mode.value})?", default=False):
        raise typer.Exit(code=1)
    sess = _open_session(host, port, user, password)
    _maint.factory_default(sess, mode)
    console.print(f"[green]factory reset requested ({mode.value})[/]")


# -------------------- time --------------------


@time_app.command("show")
def time_show(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    sess = _open_session(host, port, user, password)
    t = _dev.get_system_time(sess)
    tbl = Table(show_header=False)
    tbl.add_row("utc", t.utc_iso)
    tbl.add_row("local", t.local_iso)
    tbl.add_row("timezone", t.timezone or "(none)")
    tbl.add_row("ntp", str(t.from_dhcp))
    tbl.add_row("dst", str(t.daylight_savings))
    console.print(tbl)


@time_app.command("set")
def time_set(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    ntp: bool = typer.Option(False, "--ntp", help="Enable NTP sync."),
    timezone: str | None = typer.Option(None, "--tz", help="POSIX TZ string."),
    utc: str | None = typer.Option(
        None, "--utc", help="UTC datetime (YYYY-MM-DDTHH:MM:SSZ). Only used if --ntp not set."
    ),
) -> None:
    """Set NTP sync and/or timezone and/or a manual UTC datetime."""
    sess = _open_session(host, port, user, password)
    _dev.set_system_time(sess, use_ntp=ntp, timezone=timezone, utc_datetime=utc)
    console.print("[green]time settings applied[/]")


# -------------------- users --------------------


@users_app.command("list")
def users_list(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    sess = _open_session(host, port, user, password)
    t = Table(title="users")
    t.add_column("username")
    t.add_column("level")
    for u in _users.get_users(sess):
        t.add_row(u.name, u.level.value)
    console.print(t)


@users_app.command("add")
def users_add(
    host: str = typer.Argument(...),
    new_user: str = typer.Argument(..., help="Username to create."),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    new_password: str = typer.Option(
        ..., "--new-password", prompt=True, hide_input=True, confirmation_prompt=True
    ),
    level: _users.UserLevel = typer.Option(_users.UserLevel.USER, "--level"),
) -> None:
    sess = _open_session(host, port, user, password)
    _users.create_user(sess, new_user, new_password, level)
    console.print(f"[green]created user {new_user} ({level.value})[/]")


@users_app.command("delete")
def users_delete(
    host: str = typer.Argument(...),
    target: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    if not yes and not Confirm.ask(f"delete user {target!r} on {host}?", default=False):
        raise typer.Exit(code=1)
    sess = _open_session(host, port, user, password)
    try:
        _users.delete_user(sess, target)
    except ValidationError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2) from None
    console.print(f"[green]deleted {target}[/]")


@users_app.command("passwd")
def users_passwd(
    host: str = typer.Argument(...),
    target: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    new_password: str = typer.Option(
        ..., "--new-password", prompt=True, hide_input=True, confirmation_prompt=True
    ),
) -> None:
    sess = _open_session(host, port, user, password)
    _users.set_user_password(sess, target, new_password)
    console.print(f"[green]password updated for {target}[/]")


# -------------------- media --------------------


@app.command()
def profiles(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    """List media profiles."""
    sess = _open_session(host, port, user, password)
    t = Table(title="media profiles")
    t.add_column("token")
    t.add_column("name")
    t.add_column("encoding")
    t.add_column("resolution")
    t.add_column("fps")
    t.add_column("kbps")
    t.add_column("ptz")
    for p in _media.get_profiles(sess):
        venc = p.video_encoder
        res = (
            f"{venc.resolution.width}x{venc.resolution.height}" if venc and venc.resolution else ""
        )
        t.add_row(
            p.token,
            p.name,
            venc.encoding if venc else "",
            res,
            str(venc.fps) if venc else "",
            str(venc.bitrate_kbps) if venc else "",
            p.ptz_token or "",
        )
    console.print(t)


@app.command()
def stream(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile", help="Profile token (default: first)."),
    with_creds: bool = typer.Option(False, "--with-creds", help="Inline user:pass into the URI."),
) -> None:
    """Print the RTSP stream URI for a profile."""
    sess = _open_session(host, port, user, password)
    profs = _media.get_profiles(sess)
    if not profs:
        console.print("[yellow]no profiles[/]")
        raise typer.Exit(code=1)
    p = next((x for x in profs if x.token == profile), profs[0])
    uri = _media.get_stream_uri(sess, p.token)
    if with_creds:
        uri = _media.uri_with_credentials(uri, user, password)
    console.print(uri)


@app.command()
def preview(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Open a live preview window via ffplay."""
    sess = _open_session(host, port, user, password)
    profs = _media.get_profiles(sess)
    p = next((x for x in profs if x.token == profile), profs[0] if profs else None)
    if p is None:
        console.print("[red]no profiles[/]")
        raise typer.Exit(code=1)
    uri = _media.uri_with_credentials(_media.get_stream_uri(sess, p.token), user, password)
    try:
        proc = _preview.spawn_ffplay(uri, title=f"{host} - {p.name}")
    except _preview.PreviewNotAvailable as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=2) from None
    console.print(f"[green]ffplay pid {proc.pid}[/] - close the window to exit")
    proc.wait()


@app.command()
def snapshot(
    host: str = typer.Argument(...),
    output: Path = typer.Argument(..., help="Output JPEG path."),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Fetch a single JPEG snapshot."""
    sess = _open_session(host, port, user, password)
    profs = _media.get_profiles(sess)
    p = next((x for x in profs if x.token == profile), profs[0] if profs else None)
    if p is None:
        console.print("[red]no profiles[/]")
        raise typer.Exit(code=1)
    uri = _media.get_snapshot_uri(sess, p.token)
    if not uri:
        console.print("[red]device does not expose a snapshot URI[/]")
        raise typer.Exit(code=2)
    _preview.save_snapshot(uri, output, user=user, password=password)
    console.print(f"[green]saved {output}[/]")


# -------------------- video encoder --------------------


@encoder_app.command("show")
def encoder_show(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile", help="Profile token (default: first)."),
) -> None:
    """Print the option space the encoder advertises for a profile."""
    sess = _open_session(host, port, user, password)
    profs = _media.get_profiles(sess)
    p = next((x for x in profs if x.token == profile), profs[0] if profs else None)
    if p is None or not p.encoder_config_token:
        console.print("[red]no profile with an encoder configuration[/]")
        raise typer.Exit(code=1)
    opts = _media.get_encoder_options(sess, p.encoder_config_token, p.token)
    if opts is None:
        console.print("[red]device refused GetVideoEncoderConfigurationOptions[/]")
        raise typer.Exit(code=2)
    t = Table(title=f"encoder options for profile {p.name} ({opts.encoding})")
    t.add_column("field")
    t.add_column("choices")
    t.add_row("config token", opts.token)
    t.add_row(
        "resolutions", ", ".join(f"{r.width}x{r.height}" for r in opts.resolutions) or "(none)"
    )
    t.add_row("fps", ", ".join(str(f) for f in opts.fps_choices) or "(none)")
    t.add_row(
        "bitrate kbps",
        f"{opts.bitrate_range_kbps[0]}-{opts.bitrate_range_kbps[1]}"
        if opts.bitrate_range_kbps
        else "(unspecified)",
    )
    t.add_row(
        "gov length",
        f"{opts.gov_length_range[0]}-{opts.gov_length_range[1]}"
        if opts.gov_length_range
        else "(unspecified)",
    )
    console.print(t)


@encoder_app.command("set")
def encoder_set(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile", help="Profile token (default: first)."),
    config_token: str | None = typer.Option(
        None, "--config-token", help="Override config token (default: from profile)."
    ),
    resolution: str | None = typer.Option(
        None, "--resolution", help="WxH e.g. 1920x1080. Must be one the device advertises."
    ),
    fps: int | None = typer.Option(None, "--fps"),
    bitrate: int | None = typer.Option(None, "--bitrate", help="kbps"),
    gov: int | None = typer.Option(None, "--gov", help="GOP length / GovLength"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Update one or more encoder fields on a profile."""
    sess = _open_session(host, port, user, password)
    profs = _media.get_profiles(sess)
    p = next((x for x in profs if x.token == profile), profs[0] if profs else None)
    if p is None:
        console.print("[red]no profiles[/]")
        raise typer.Exit(code=1)
    token = config_token or p.encoder_config_token
    if not token:
        console.print(f"[red]no encoder config token on profile {p.token!r}[/]")
        raise typer.Exit(code=1)
    res_obj = None
    if resolution:
        try:
            w, h = resolution.lower().split("x", 1)
            res_obj = _media.Resolution(int(w), int(h))
        except (ValueError, AttributeError) as e:
            console.print(f"[red]bad --resolution {resolution!r}: {e}[/]")
            raise typer.Exit(code=2) from None
    summary = ", ".join(
        f"{k}={v}"
        for k, v in {
            "resolution": resolution,
            "fps": fps,
            "bitrate": bitrate,
            "gov": gov,
        }.items()
        if v is not None
    )
    if not summary:
        console.print("[yellow]nothing to apply (no fields supplied)[/]")
        raise typer.Exit(code=1)
    if not yes and not Confirm.ask(
        f"apply encoder changes ({summary}) to {p.name}?", default=False
    ):
        raise typer.Exit(code=1)
    _media.set_video_encoder_configuration(
        sess,
        token,
        resolution=res_obj,
        fps=fps,
        bitrate_kbps=bitrate,
        gov_length=gov,
    )
    console.print(f"[green]encoder {token} updated ({summary})[/]")


# -------------------- PTZ --------------------


def _require_ptz_profile(sess: DeviceSession, profile: str | None) -> str:
    profs = _media.get_profiles(sess)
    ptz_profs = [p for p in profs if p.ptz_token]
    if not ptz_profs:
        console.print("[red]no PTZ-capable profiles[/]")
        raise typer.Exit(code=1)
    p = next((x for x in ptz_profs if x.token == profile), ptz_profs[0])
    return p.token


@ptz_app.command("status")
def ptz_status(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    s = _ptz.get_status(sess, tok)
    t = Table(show_header=False)
    t.add_row("pan", str(s.pan))
    t.add_row("tilt", str(s.tilt))
    t.add_row("zoom", str(s.zoom))
    t.add_row("moving", f"pan={s.moving_pan} tilt={s.moving_tilt} zoom={s.moving_zoom}")
    console.print(t)


@ptz_app.command("move")
def ptz_move(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    pan: float = typer.Option(0.0, "--pan", help="Pan speed -1.0..1.0"),
    tilt: float = typer.Option(0.0, "--tilt", help="Tilt speed -1.0..1.0"),
    zoom: float = typer.Option(0.0, "--zoom", help="Zoom speed -1.0..1.0"),
    duration: float | None = typer.Option(None, "--duration", help="Seconds, then auto-stop."),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    """Continuous move. Non-zero velocity + optional duration, then stop."""
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    _ptz.continuous_move(sess, tok, _ptz.Vector(pan=pan, tilt=tilt, zoom=zoom), duration_s=duration)


@ptz_app.command("stop")
def ptz_stop(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    _ptz.stop(sess, tok)


@ptz_app.command("presets")
def ptz_presets(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    t = Table(title="PTZ presets")
    t.add_column("token")
    t.add_column("name")
    for p in _ptz.get_presets(sess, tok):
        t.add_row(p.token, p.name)
    console.print(t)


@ptz_app.command("goto")
def ptz_goto(
    host: str = typer.Argument(...),
    preset: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    _ptz.goto_preset(sess, tok, preset)


@ptz_app.command("set-preset")
def ptz_set_preset(
    host: str = typer.Argument(...),
    name: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    out = _ptz.set_preset(sess, tok, name=name)
    console.print(f"[green]preset token: {out}[/]")


@ptz_app.command("remove-preset")
def ptz_remove_preset(
    host: str = typer.Argument(...),
    preset: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    profile: str | None = typer.Option(None, "--profile"),
) -> None:
    sess = _open_session(host, port, user, password)
    tok = _require_ptz_profile(sess, profile)
    _ptz.remove_preset(sess, tok, preset)


# -------------------- network (unchanged from Phase 1) --------------------


@app.command()
def show(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
) -> None:
    """Dump the current network configuration of a camera."""
    sess = _open_session(host, port, user, password)
    state = read_state(sess)
    _print_state(state)


def _print_state(state: NetworkState) -> None:
    nic = state.primary_interface
    t = Table(title="network state", show_header=False)
    t.add_column("key", style="bold")
    t.add_column("value")
    t.add_row("hostname", f"{state.hostname.name}  (fromDHCP={state.hostname.from_dhcp})")
    if nic and nic.ipv4:
        mask = nic.ipv4.subnet_mask
        t.add_row("interface", f"{nic.token}  mac={nic.mac}  enabled={nic.enabled}")
        t.add_row("dhcp", str(nic.ipv4.dhcp))
        t.add_row("ip", f"{nic.ipv4.address}/{nic.ipv4.prefix_length}  ({mask})")
    v4 = ", ".join(str(a) for a in state.gateway.ipv4)
    v6 = ", ".join(str(a) for a in state.gateway.ipv6)
    t.add_row("gateway", f"v4=[{v4}]  v6=[{v6}]")
    t.add_row(
        "dns",
        f"fromDHCP={state.dns.from_dhcp}  servers=[{', '.join(str(s) for s in state.dns.servers)}]  "
        f"search=[{', '.join(state.dns.search_domains)}]",
    )
    if state.ntp:
        t.add_row(
            "ntp", f"fromDHCP={state.ntp.from_dhcp}  servers=[{', '.join(state.ntp.servers)}]"
        )
    for p in state.protocols:
        t.add_row(f"proto:{p.name.value.lower()}", f"enabled={p.enabled}  ports={list(p.port)}")
    if state.zero_config:
        t.add_row(
            "zero-config",
            f"supported={state.zero_config.supported}  enabled={state.zero_config.enabled}  "
            f"addresses=[{', '.join(str(a) for a in state.zero_config.addresses)}]",
        )
    if state.discovery_mode is not None:
        t.add_row("discovery-mode", state.discovery_mode.value)
    console.print(t)


@app.command()
def apply(
    host: str = typer.Argument(...),
    port: int = typer.Option(80, "--port"),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    dhcp: bool | None = typer.Option(None, "--dhcp/--no-dhcp"),
    ip: str | None = typer.Option(None, "--ip"),
    subnet: str | None = typer.Option(None, "--subnet"),
    gateway: list[str] = typer.Option(None, "--gateway"),
    dns: list[str] = typer.Option(None, "--dns"),
    ntp: list[str] = typer.Option(None, "--ntp"),
    hostname: str | None = typer.Option(None, "--hostname"),
    hostname_from_dhcp: bool | None = typer.Option(
        None, "--hostname-from-dhcp/--no-hostname-from-dhcp"
    ),
    http: int | None = typer.Option(None, "--http"),
    http_enabled: bool | None = typer.Option(None, "--http-enabled/--no-http"),
    https: int | None = typer.Option(None, "--https"),
    https_enabled: bool | None = typer.Option(None, "--https-enabled/--no-https"),
    rtsp: int | None = typer.Option(None, "--rtsp"),
    rtsp_enabled: bool | None = typer.Option(None, "--rtsp-enabled/--no-rtsp"),
    zero_config: bool | None = typer.Option(None, "--zero-config/--no-zero-config"),
    discovery_mode: DiscoveryMode | None = typer.Option(None, "--discovery-mode"),
    client_ip: str | None = typer.Option(None, "--client-ip"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    reboot_wait: float = typer.Option(90.0, "--reboot-wait"),
) -> None:
    """Apply a network configuration change set."""

    patch = NetworkPatch(
        dhcp=dhcp,
        ip=IPv4Address(ip) if ip else None,
        subnet_mask=IPv4Address(subnet) if subnet else None,
        gateway=tuple(ip_address(g) for g in (gateway or [])) if gateway else None,
        dns=tuple(ip_address(d) for d in (dns or [])) if dns else None,
        ntp_servers=tuple(ntp) if ntp else None,
        hostname=hostname,
        use_hostname_from_dhcp=hostname_from_dhcp,
        http_port=http,
        http_enabled=http_enabled,
        https_port=https,
        https_enabled=https_enabled,
        rtsp_port=rtsp,
        rtsp_enabled=rtsp_enabled,
        zero_config_enabled=zero_config,
        discovery_mode=discovery_mode,
    )

    sess = _open_session(host, port, user, password)
    state = read_state(sess)

    diff = compute_diff(state, patch)
    if not diff.any:
        console.print("[green]no effective changes - nothing to apply[/]")
        return

    try:
        warnings = _validate(state, patch, client_ip=IPv4Address(client_ip) if client_ip else None)
    except ValidationError as e:
        console.print(f"[red]validation failed:[/] {e}")
        raise typer.Exit(code=2) from None

    _print_diff(state, patch, diff)
    for w in warnings:
        console.print(f"[yellow]warning:[/] {w.message}")

    if not yes and not Confirm.ask("apply these changes?", default=False):
        console.print("[yellow]aborted[/]")
        raise typer.Exit(code=1)

    try:
        result = _apply(sess, state, patch, new_host_port=port, reboot_wait_s=reboot_wait)
    except OnvifcfgError as e:
        console.print(f"[red]apply failed:[/] {e}")
        raise typer.Exit(code=3) from None

    if result.reboot_issued:
        if result.reconnected:
            console.print(f"[green]reconnected to {result.new_host}:{port}[/]")
        else:
            console.print(
                f"[yellow]reboot requested but device did not answer on "
                f"{result.new_host}:{port} within {reboot_wait}s[/]"
            )
    else:
        console.print("[green]done[/]")


def _print_diff(state: NetworkState, patch: NetworkPatch, diff) -> None:  # type: ignore[no-untyped-def]
    t = Table(title="changes")
    t.add_column("field")
    t.add_column("current")
    t.add_column("new", style="cyan")
    nic = state.primary_interface
    cur_ip = nic.ipv4.address if nic and nic.ipv4 else None
    cur_prefix = nic.ipv4.prefix_length if nic and nic.ipv4 else None
    cur_mask = prefix_to_mask(cur_prefix) if cur_prefix is not None else None
    if diff.dhcp_changed:
        t.add_row("dhcp", str(nic.ipv4.dhcp if nic and nic.ipv4 else None), str(patch.dhcp))
    if diff.ip_changed:
        t.add_row("ip", str(cur_ip), str(patch.ip))
    if diff.subnet_changed:
        t.add_row("subnet", str(cur_mask), str(patch.subnet_mask))
    if diff.gateway_changed:
        t.add_row(
            "gateway",
            ", ".join(str(a) for a in state.gateway.ipv4 + state.gateway.ipv6),
            ", ".join(str(a) for a in (patch.gateway or ())),
        )
    if diff.dns_changed:
        t.add_row(
            "dns",
            ", ".join(str(s) for s in state.dns.servers),
            ", ".join(str(s) for s in (patch.dns or ())),
        )
    if diff.ntp_changed:
        t.add_row(
            "ntp",
            ", ".join(state.ntp.servers) if state.ntp else "",
            ", ".join(patch.ntp_servers or ()),
        )
    if diff.hostname_changed:
        t.add_row(
            "hostname",
            f"{state.hostname.name} (fromDHCP={state.hostname.from_dhcp})",
            f"{patch.hostname or state.hostname.name}"
            f" (fromDHCP={patch.use_hostname_from_dhcp if patch.use_hostname_from_dhcp is not None else state.hostname.from_dhcp})",
        )
    for proto in diff.protocols_changed:
        cur = next((p for p in state.protocols if p.name == proto), None)
        if proto == ProtocolName.HTTP:
            new_enabled = (
                patch.http_enabled
                if patch.http_enabled is not None
                else (cur.enabled if cur else False)
            )
            new_port = (
                patch.http_port
                if patch.http_port is not None
                else (cur.port[0] if cur and cur.port else None)
            )
        elif proto == ProtocolName.HTTPS:
            new_enabled = (
                patch.https_enabled
                if patch.https_enabled is not None
                else (cur.enabled if cur else False)
            )
            new_port = (
                patch.https_port
                if patch.https_port is not None
                else (cur.port[0] if cur and cur.port else None)
            )
        else:
            new_enabled = (
                patch.rtsp_enabled
                if patch.rtsp_enabled is not None
                else (cur.enabled if cur else False)
            )
            new_port = (
                patch.rtsp_port
                if patch.rtsp_port is not None
                else (cur.port[0] if cur and cur.port else None)
            )
        t.add_row(
            f"proto:{proto.value.lower()}",
            f"enabled={cur.enabled if cur else False} port={cur.port[0] if cur and cur.port else None}",
            f"enabled={new_enabled} port={new_port}",
        )
    if diff.zero_config_changed:
        t.add_row(
            "zero-config",
            str(state.zero_config.enabled) if state.zero_config else "n/a",
            str(patch.zero_config_enabled),
        )
    if diff.discovery_mode_changed:
        t.add_row(
            "discovery-mode",
            state.discovery_mode.value if state.discovery_mode else "n/a",
            patch.discovery_mode.value if patch.discovery_mode else "",
        )
    console.print(t)
