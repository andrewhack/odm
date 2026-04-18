"""CLI entry point (Typer + Rich)."""

from __future__ import annotations

import logging
from ipaddress import IPv4Address, ip_address
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from . import __version__
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
    help="ONVIF network configuration CLI.",
)
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


@app.command()
def version() -> None:
    """Print the installed onvifcfg version."""
    console.print(f"onvifcfg {__version__}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address. Stay on localhost unless you know what you're doing."),
    port: int = typer.Option(8080, "--port", "-P"),
) -> None:
    """Launch the local web UI (FastAPI + Jinja)."""
    import uvicorn

    from .web.app import create_app

    app_ = create_app()
    console.print(f"[green]onvifcfg web UI on http://{host}:{port}/[/]")
    uvicorn.run(app_, host=host, port=port, log_level="warning")


@app.command()
def discover(
    timeout: float = typer.Option(3.0, "--timeout", "-t", help="Probe timeout in seconds."),
) -> None:
    """Run WS-Discovery and list every ONVIF device on the local subnet."""

    devices = _discover(timeout_s=timeout)
    if not devices:
        console.print("[yellow]no ONVIF devices discovered[/]")
        raise typer.Exit(code=1)

    table = Table(title=f"discovered {len(devices)} device(s)")
    table.add_column("xAddr", style="cyan")
    table.add_column("scopes")
    for d in devices:
        table.add_row(d.best_xaddr(), "\n".join(d.scopes))
    console.print(table)


def _open_session(host: str, port: int, user: str, password: str) -> DeviceSession:
    try:
        return DeviceSession(host, port, Credentials(user=user, password=password))
    except OnvifcfgError as e:
        console.print(f"[red]session error:[/] {e}")
        raise typer.Exit(code=2)


@app.command()
def show(
    host: str = typer.Argument(..., help="Device hostname or IPv4."),
    port: int = typer.Option(80, "--port", help="ONVIF service port."),
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
            "ntp",
            f"fromDHCP={state.ntp.from_dhcp}  servers=[{', '.join(state.ntp.servers)}]",
        )
    for p in state.protocols:
        t.add_row(
            f"proto:{p.name.value.lower()}",
            f"enabled={p.enabled}  ports={list(p.port)}",
        )
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
    host: str = typer.Argument(..., help="Device hostname or IPv4."),
    port: int = typer.Option(80, "--port", help="ONVIF service port."),
    user: str = typer.Option(..., "--user", "-u", prompt=True),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    # patch fields
    dhcp: Optional[bool] = typer.Option(None, "--dhcp/--no-dhcp"),
    ip: Optional[str] = typer.Option(None, "--ip"),
    subnet: Optional[str] = typer.Option(None, "--subnet"),
    gateway: list[str] = typer.Option(None, "--gateway", help="One or more gateway IPs; repeat the flag."),
    dns: list[str] = typer.Option(None, "--dns", help="One or more DNS IPs; repeat the flag."),
    ntp: list[str] = typer.Option(None, "--ntp", help="One or more NTP servers (IP or hostname); repeat the flag."),
    hostname: Optional[str] = typer.Option(None, "--hostname"),
    hostname_from_dhcp: Optional[bool] = typer.Option(None, "--hostname-from-dhcp/--no-hostname-from-dhcp"),
    http: Optional[int] = typer.Option(None, "--http", help="HTTP port."),
    http_enabled: Optional[bool] = typer.Option(None, "--http-enabled/--no-http"),
    https: Optional[int] = typer.Option(None, "--https", help="HTTPS port."),
    https_enabled: Optional[bool] = typer.Option(None, "--https-enabled/--no-https"),
    rtsp: Optional[int] = typer.Option(None, "--rtsp", help="RTSP port."),
    rtsp_enabled: Optional[bool] = typer.Option(None, "--rtsp-enabled/--no-rtsp"),
    zero_config: Optional[bool] = typer.Option(None, "--zero-config/--no-zero-config"),
    discovery_mode: Optional[DiscoveryMode] = typer.Option(None, "--discovery-mode"),
    client_ip: Optional[str] = typer.Option(
        None,
        "--client-ip",
        help="Your PC's IP, used to warn about losing reachability after the change.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    reboot_wait: float = typer.Option(
        90.0,
        "--reboot-wait",
        help="Seconds to wait for the device to come back after an IP change.",
    ),
) -> None:
    """Apply a network configuration change set to a camera."""

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
        warnings = _validate(
            state,
            patch,
            client_ip=IPv4Address(client_ip) if client_ip else None,
        )
    except ValidationError as e:
        console.print(f"[red]validation failed:[/] {e}")
        raise typer.Exit(code=2)

    # Print diff
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
        raise typer.Exit(code=3)

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
        cur = f"{state.hostname.name} (fromDHCP={state.hostname.from_dhcp})"
        new = (
            f"{patch.hostname or state.hostname.name}"
            f" (fromDHCP={patch.use_hostname_from_dhcp if patch.use_hostname_from_dhcp is not None else state.hostname.from_dhcp})"
        )
        t.add_row("hostname", cur, new)
    for proto in diff.protocols_changed:
        cur = next((p for p in state.protocols if p.name == proto), None)
        if proto == ProtocolName.HTTP:
            new_enabled = patch.http_enabled if patch.http_enabled is not None else (cur.enabled if cur else False)
            new_port = patch.http_port if patch.http_port is not None else (cur.port[0] if cur and cur.port else None)
        elif proto == ProtocolName.HTTPS:
            new_enabled = patch.https_enabled if patch.https_enabled is not None else (cur.enabled if cur else False)
            new_port = patch.https_port if patch.https_port is not None else (cur.port[0] if cur and cur.port else None)
        else:
            new_enabled = patch.rtsp_enabled if patch.rtsp_enabled is not None else (cur.enabled if cur else False)
            new_port = patch.rtsp_port if patch.rtsp_port is not None else (cur.port[0] if cur and cur.port else None)
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
