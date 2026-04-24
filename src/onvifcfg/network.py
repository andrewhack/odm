"""Read and apply ONVIF network configuration.

This module is where the reliability fixes from the upstream ODM review live.
Every fix is cross-referenced to its entry in docs/RELIABILITY_FIXES.md.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, ip_address

from .exceptions import ApplyError
from .models import (
    DiscoveryMode,
    DNSInfo,
    Gateway,
    Hostname,
    IPv4Config,
    NetworkInterface,
    NetworkPatch,
    NetworkProtocol,
    NetworkState,
    NTPInfo,
    ProtocolName,
    ZeroConfig,
)
from .reachability import wait_for_port
from .session import DeviceSession

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------


def read_state(sess: DeviceSession) -> NetworkState:
    """Pull every network-related property off the device into one snapshot."""

    nics_raw = sess.call("GetNetworkInterfaces")
    interfaces = tuple(_parse_interface(n) for n in (nics_raw or ()))

    hostname_raw = sess.call("GetHostname")
    hostname = Hostname(
        name=hostname_raw.Name or "",
        from_dhcp=bool(getattr(hostname_raw, "FromDHCP", False)),
    )

    gw_raw = sess.call("GetNetworkDefaultGateway")
    gateway = Gateway.parse(
        [
            *(getattr(gw_raw, "IPv4Address", None) or []),
            *(getattr(gw_raw, "IPv6Address", None) or []),
        ]
    )

    dns_raw = sess.call("GetDNS")
    dns = _parse_dns(dns_raw)

    ntp_raw = sess.safe_call("GetNTP")
    ntp = _parse_ntp(ntp_raw) if ntp_raw is not None else None

    protocols_raw = sess.call("GetNetworkProtocols")
    protocols = tuple(_parse_protocol(p) for p in (protocols_raw or ()))

    capabilities = sess.call("GetCapabilities")
    zc_supported = bool(
        getattr(getattr(capabilities, "Device", None), "Network", None)
        and getattr(capabilities.Device.Network, "ZeroConfiguration", False)
    )
    zero_config: ZeroConfig | None = None
    if zc_supported:
        # Capability flag is advisory (fix #12) - still wrap in safe_call.
        zc_raw = sess.safe_call("GetZeroConfiguration")
        if zc_raw is not None:
            zero_config = ZeroConfig(
                supported=True,
                enabled=bool(zc_raw.Enabled),
                interface_token=getattr(zc_raw, "InterfaceToken", None),
                addresses=tuple(
                    ip
                    for ip in (_parse_ipv4(a) for a in (getattr(zc_raw, "Addresses", None) or []))
                    if ip is not None
                ),
            )
        else:
            zero_config = ZeroConfig(supported=True, enabled=False)

    discovery_mode_raw = sess.safe_call("GetDiscoveryMode")
    discovery_mode = (
        DiscoveryMode(str(discovery_mode_raw)) if discovery_mode_raw is not None else None
    )

    return NetworkState(
        interfaces=interfaces,
        hostname=hostname,
        gateway=gateway,
        dns=dns,
        ntp=ntp,
        protocols=protocols,
        zero_config=zero_config,
        discovery_mode=discovery_mode,
    )


def _parse_ipv4(raw: str) -> IPv4Address | None:
    """Parse an IPv4 in dotted-decimal, or the occasional hex form.

    Some cameras return addresses as a packed 32-bit hex int
    (e.g. ``0x9605A8C0`` for 192.168.5.150 in little-endian byte order).
    Try dotted-decimal first, then big-endian 32-bit int, then
    little-endian.  Return None if all three fail so the caller can
    skip the entry instead of blowing up the session.
    """
    s = raw.strip()
    if not s:
        return None
    try:
        return IPv4Address(s)
    except (ValueError, TypeError):
        pass
    if s.lower().startswith("0x"):
        try:
            n = int(s, 16) & 0xFFFFFFFF
        except ValueError:
            return None
        for order in ("big", "little"):
            try:
                return IPv4Address(n.to_bytes(4, order))
            except (ValueError, OverflowError):
                continue
    return None


def _parse_interface(nic: object) -> NetworkInterface:
    info = getattr(nic, "Info", None)
    mac = getattr(info, "HwAddress", None) if info else None

    ipv4 = None
    ipv4_raw = getattr(nic, "IPv4", None)
    if ipv4_raw is not None:
        cfg = getattr(ipv4_raw, "Config", None)
        if cfg is not None:
            dhcp = bool(cfg.DHCP)
            manual = list(getattr(cfg, "Manual", None) or [])
            from_dhcp = getattr(cfg, "FromDHCP", None)
            if manual:
                ipv4 = IPv4Config(
                    dhcp=dhcp,
                    address=_parse_ipv4(manual[0].Address),
                    prefix_length=int(manual[0].PrefixLength),
                )
            elif from_dhcp is not None:
                ipv4 = IPv4Config(
                    dhcp=dhcp,
                    address=_parse_ipv4(from_dhcp.Address),
                    prefix_length=int(from_dhcp.PrefixLength),
                )
            else:
                ipv4 = IPv4Config(dhcp=dhcp)

    return NetworkInterface(
        token=nic.token,
        enabled=bool(getattr(nic, "Enabled", False)),
        mac=mac,
        ipv4=ipv4,
    )


def _parse_dns(dns_raw: object) -> DNSInfo:
    from_dhcp = bool(getattr(dns_raw, "FromDHCP", False))
    servers_raw = (
        getattr(dns_raw, "DNSFromDHCP", None) if from_dhcp else getattr(dns_raw, "DNSManual", None)
    ) or []
    servers: list[IPv4Address | IPv6Address] = []
    for s in servers_raw:
        addr = getattr(s, "IPv4Address", None) or getattr(s, "IPv6Address", None)
        if not addr:
            continue
        try:
            servers.append(ip_address(addr))
        except ValueError:
            ipv4 = _parse_ipv4(addr)
            if ipv4 is not None:
                servers.append(ipv4)
    return DNSInfo(
        from_dhcp=from_dhcp,
        servers=tuple(servers),
        search_domains=tuple(getattr(dns_raw, "SearchDomain", None) or []),
    )


def _parse_ntp(ntp_raw: object) -> NTPInfo:
    from_dhcp = bool(getattr(ntp_raw, "FromDHCP", False))
    src = (
        getattr(ntp_raw, "NTPFromDHCP", None) if from_dhcp else getattr(ntp_raw, "NTPManual", None)
    ) or []
    servers: list[str] = []
    for h in src:
        # Fix #1: NetworkHost may carry IPv4, IPv6 or a DNS name - route by type.
        t = str(getattr(h, "Type", "")).lower()
        if t == "ipv4":
            v = getattr(h, "IPv4Address", None)
        elif t == "ipv6":
            v = getattr(h, "IPv6Address", None)
        else:
            v = getattr(h, "DNSname", None)
        if v:
            servers.append(v)
    return NTPInfo(from_dhcp=from_dhcp, servers=tuple(servers))


def _parse_protocol(proto: object) -> NetworkProtocol:
    name_raw = str(proto.Name)
    return NetworkProtocol(
        name=ProtocolName(name_raw.upper() if name_raw in ("HTTP", "HTTPS", "RTSP") else name_raw),
        enabled=bool(proto.Enabled),
        port=tuple(int(p) for p in (getattr(proto, "Port", None) or [])),
    )


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Diff:
    """Structured diff of NetworkPatch against current NetworkState."""

    ip_changed: bool = False
    subnet_changed: bool = False
    dhcp_changed: bool = False
    gateway_changed: bool = False
    dns_changed: bool = False
    ntp_changed: bool = False
    hostname_changed: bool = False
    protocols_changed: set[ProtocolName] = None  # type: ignore[assignment]
    zero_config_changed: bool = False
    discovery_mode_changed: bool = False

    def __post_init__(self) -> None:
        if self.protocols_changed is None:
            self.protocols_changed = set()

    @property
    def any(self) -> bool:
        return any(
            (
                self.ip_changed,
                self.subnet_changed,
                self.dhcp_changed,
                self.gateway_changed,
                self.dns_changed,
                self.ntp_changed,
                self.hostname_changed,
                bool(self.protocols_changed),
                self.zero_config_changed,
                self.discovery_mode_changed,
            )
        )


def compute_diff(state: NetworkState, patch: NetworkPatch) -> Diff:
    d = Diff()
    nic = state.primary_interface
    cur_ipv4 = nic.ipv4 if nic else None

    if patch.ip is not None and (cur_ipv4 is None or cur_ipv4.address != patch.ip):
        d.ip_changed = True
    if patch.subnet_mask is not None and (
        cur_ipv4 is None or cur_ipv4.subnet_mask != patch.subnet_mask
    ):
        d.subnet_changed = True
    if patch.dhcp is not None and (cur_ipv4 is None or cur_ipv4.dhcp != patch.dhcp):
        d.dhcp_changed = True

    if patch.gateway is not None:
        cur_set: set[IPv4Address | IPv6Address] = set(state.gateway.ipv4) | set(state.gateway.ipv6)
        if cur_set != set(patch.gateway):
            d.gateway_changed = True

    if patch.dns is not None and tuple(patch.dns) != state.dns.servers:
        d.dns_changed = True

    if patch.ntp_servers is not None and (
        state.ntp is None or patch.ntp_servers != state.ntp.servers
    ):
        d.ntp_changed = True

    if patch.hostname is not None and patch.hostname != state.hostname.name:
        d.hostname_changed = True
    if (
        patch.use_hostname_from_dhcp is not None
        and patch.use_hostname_from_dhcp != state.hostname.from_dhcp
    ):
        d.hostname_changed = True

    # fix #13 - per-protocol change detection, only changed go in SetNetworkProtocols
    current_by_name = {p.name: p for p in state.protocols}
    for proto, port, enabled in (
        (ProtocolName.HTTP, patch.http_port, patch.http_enabled),
        (ProtocolName.HTTPS, patch.https_port, patch.https_enabled),
        (ProtocolName.RTSP, patch.rtsp_port, patch.rtsp_enabled),
    ):
        if port is None and enabled is None:
            continue
        cur = current_by_name.get(proto)
        new_enabled = enabled if enabled is not None else (cur.enabled if cur else False)
        new_ports = (port,) if port is not None else (cur.port if cur else ())
        if cur is None or cur.enabled != new_enabled or cur.port != new_ports:
            d.protocols_changed.add(proto)

    if (
        patch.zero_config_enabled is not None
        and state.zero_config is not None
        and state.zero_config.supported
        and state.zero_config.enabled != patch.zero_config_enabled
    ):
        d.zero_config_changed = True

    if (
        patch.discovery_mode is not None
        and state.discovery_mode is not None
        and state.discovery_mode != patch.discovery_mode
    ):
        d.discovery_mode_changed = True

    return d


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ApplyResult:
    reboot_issued: bool = False
    reconnected: bool = False
    new_host: str | None = None


def apply(
    sess: DeviceSession,
    state: NetworkState,
    patch: NetworkPatch,
    *,
    new_host_port: int = 80,
    reboot_wait_s: float = 90.0,
) -> ApplyResult:
    """Push a NetworkPatch to the device.

    Apply order rationale (fix #6): safe non-channel-affecting changes first
    (NTP, DNS, gateway, zero-config, hostname, discovery-mode), then protocols
    (may rotate HTTP/HTTPS/RTSP ports and kill the session), then IP last
    (always kills the session and requires a reboot).  The dangerous calls are
    wrapped in exception guards because the camera often drops the channel
    before acking the response.
    """

    diff = compute_diff(state, patch)
    result = ApplyResult()
    if not diff.any:
        log.info("no effective changes - nothing to apply")
        return result

    # --- safe-phase -----------------------------------------------------
    if diff.ntp_changed:
        _apply_ntp(sess, patch, state)
    if diff.dns_changed:
        _apply_dns(sess, patch, state)
    if diff.gateway_changed:
        _apply_gateway(sess, patch)
    if diff.zero_config_changed:
        _apply_zero_config(sess, state, patch)
    if diff.hostname_changed:
        _apply_hostname(sess, patch)
    if diff.discovery_mode_changed:
        _apply_discovery_mode(sess, patch)

    # --- destructive-phase ---------------------------------------------
    if diff.protocols_changed:
        _apply_protocols(sess, state, patch, diff)

    if diff.ip_changed or diff.subnet_changed or diff.dhcp_changed:
        reboot_needed = _apply_ip(sess, state, patch)
        if reboot_needed:
            _best_effort_reboot(sess)
            result.reboot_issued = True
            # Fix #20 - probe new IP until it answers, so the user knows when
            # the camera is back rather than staring at a blank progress bar.
            new_host = str(patch.ip) if patch.ip else sess.host
            if wait_for_port(new_host, new_host_port, timeout_s=reboot_wait_s):
                result.reconnected = True
                result.new_host = new_host

    return result


# --------------------------------------------------------------------------
# per-step helpers
# --------------------------------------------------------------------------


def _apply_ntp(sess: DeviceSession, patch: NetworkPatch, state: NetworkState) -> None:
    # fix #1 - route IPv6 NTP entries to iPv6Address, not iPv4Address.
    hosts = []
    for raw in patch.ntp_servers or ():
        s = raw.strip()
        if not s:
            continue
        try:
            addr = ip_address(s)
        except ValueError:
            hosts.append({"Type": "DNS", "DNSname": s})
            continue
        if isinstance(addr, IPv4Address):
            hosts.append({"Type": "IPv4", "IPv4Address": s})
        else:
            hosts.append({"Type": "IPv6", "IPv6Address": s})

    use_dhcp = bool(patch.dhcp and state.ntp and state.ntp.from_dhcp)
    sess.call("SetNTP", FromDHCP=use_dhcp, NTPManual=hosts)


def _apply_dns(sess: DeviceSession, patch: NetworkPatch, state: NetworkState) -> None:
    # fix #2 - branch per AddressFamily, fix #4 - round-trip SearchDomain.
    dns_manual = []
    for a in patch.dns or ():
        if isinstance(a, IPv4Address):
            dns_manual.append({"Type": "IPv4", "IPv4Address": str(a)})
        else:
            dns_manual.append({"Type": "IPv6", "IPv6Address": str(a)})

    use_dhcp = bool(patch.dhcp and state.dns.from_dhcp)
    sess.call(
        "SetDNS",
        FromDHCP=use_dhcp,
        SearchDomain=list(state.dns.search_domains),
        DNSManual=dns_manual,
    )


def _apply_gateway(sess: DeviceSession, patch: NetworkPatch) -> None:
    ipv4 = [str(g) for g in (patch.gateway or ()) if isinstance(g, IPv4Address)]
    ipv6 = [str(g) for g in (patch.gateway or ()) if isinstance(g, IPv6Address)]
    sess.call("SetNetworkDefaultGateway", IPv4Address=ipv4, IPv6Address=ipv6)


def _apply_zero_config(sess: DeviceSession, state: NetworkState, patch: NetworkPatch) -> None:
    # fix #12 - capability flag is advisory, tolerate ActionNotSupported.
    if not state.zero_config or not state.zero_config.interface_token:
        return
    sess.safe_call(
        "SetZeroConfiguration",
        InterfaceToken=state.zero_config.interface_token,
        Enabled=bool(patch.zero_config_enabled),
    )


def _apply_hostname(sess: DeviceSession, patch: NetworkPatch) -> None:
    # fix #3 - prefer SetHostnameFromDHCP when opting in to DHCP hostname.
    if patch.use_hostname_from_dhcp is True:
        ok = sess.safe_call("SetHostnameFromDHCP", FromDHCP=True)
        if ok is None:
            # fall back for ONVIF 1.x devices that don't implement the newer op
            sess.call("SetHostname", Name="")
        return
    if patch.hostname is not None:
        sess.call("SetHostname", Name=patch.hostname)


def _apply_discovery_mode(sess: DeviceSession, patch: NetworkPatch) -> None:
    sess.call("SetDiscoveryMode", DiscoveryMode=patch.discovery_mode.value)


def _apply_protocols(
    sess: DeviceSession, state: NetworkState, patch: NetworkPatch, diff: Diff
) -> None:
    """SetNetworkProtocols - only send the entries that actually changed.

    Strict firmware (some Uniview/Dahua) rejects a batch that includes an
    https entry on a device without TLS provisioning, even if that entry is
    unchanged - so don't include unchanged protocols at all.  (fix #13)
    """
    by_name = {p.name: p for p in state.protocols}

    def _build(name: ProtocolName, port: int | None, enabled: bool | None) -> dict | None:
        if name not in diff.protocols_changed:
            return None
        cur = by_name.get(name)
        new_enabled = enabled if enabled is not None else (cur.enabled if cur else False)
        new_port = port if port is not None else (cur.port[0] if cur and cur.port else None)
        if new_port is None:
            return None
        return {"Name": name.value, "Enabled": new_enabled, "Port": [new_port]}

    payload = [
        p
        for p in (
            _build(ProtocolName.HTTP, patch.http_port, patch.http_enabled),
            _build(ProtocolName.HTTPS, patch.https_port, patch.https_enabled),
            _build(ProtocolName.RTSP, patch.rtsp_port, patch.rtsp_enabled),
        )
        if p is not None
    ]
    if not payload:
        return

    try:
        sess.call("SetNetworkProtocols", NetworkProtocols=payload)
    except Exception as e:
        # The camera often drops the channel the moment it applies the port
        # change, raising a transport-level fault.  That's effectively
        # "succeeded, connection lost".  Log and continue - subsequent calls
        # in this apply() will fail fast anyway.
        log.warning("SetNetworkProtocols raised during port rotation: %s", e)


def _apply_ip(sess: DeviceSession, state: NetworkState, patch: NetworkPatch) -> bool:
    """Return True if the device asked for a reboot."""

    nic = state.primary_interface
    if nic is None:
        raise ApplyError("no enabled NIC to reconfigure")

    dhcp = patch.dhcp if patch.dhcp is not None else (nic.ipv4.dhcp if nic.ipv4 else False)

    manual: list[dict] = []
    if not dhcp:
        ip = patch.ip or (nic.ipv4.address if nic.ipv4 else None)
        mask = patch.subnet_mask
        prefix = (
            _mask_to_prefix(mask)
            if mask is not None
            else (
                nic.ipv4.prefix_length if nic.ipv4 and nic.ipv4.prefix_length is not None else None
            )
        )
        if ip is not None and prefix is not None:
            manual.append({"Address": str(ip), "PrefixLength": prefix})

    config: dict = {
        "Enabled": True,
        "IPv4": {
            "Enabled": True,
            "DHCP": dhcp,
            "Manual": manual,
        },
    }

    response = sess.call("SetNetworkInterfaces", InterfaceToken=nic.token, NetworkInterface=config)
    # onvif-zeep returns RebootNeeded directly on some stacks, a response
    # object with .RebootNeeded on others.
    return bool(getattr(response, "RebootNeeded", response))


def _best_effort_reboot(sess: DeviceSession) -> None:
    """Fire SystemReboot with a short timeout; swallow the expected fault.

    Fix #7: most cameras apply the IP change before acking the reboot, so
    the call hangs or raises on a stale connection.  We don't care - by that
    point the device is already rebooting.
    """
    start = time.monotonic()
    try:
        sess.call("SystemReboot")
    except Exception as e:
        log.info(
            "SystemReboot returned/raised after %.1fs (expected): %s", time.monotonic() - start, e
        )


def _mask_to_prefix(mask: IPv4Address) -> int:
    return sum(bin(b).count("1") for b in mask.packed)


def prefix_to_mask(prefix: int) -> IPv4Address:
    return IPv4Address(IPv4Network(f"0.0.0.0/{prefix}").netmask)
