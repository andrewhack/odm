"""Pre-apply validation for NetworkPatch.

Every check here fires BEFORE any SetX call hits the camera. The upstream ODM
review catalogued a number of ways the user can brick their own camera with a
careless Apply click; each of those scenarios is caught here with a loud
ValidationError instead of silently proceeding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from .exceptions import ValidationError
from .models import NetworkPatch, NetworkState, ProtocolName


@dataclass(frozen=True)
class Warning_:  # noqa: N801  # trailing underscore avoids shadowing builtins.Warning
    message: str


def _effective_ports(
    state: NetworkState, patch: NetworkPatch
) -> dict[ProtocolName, tuple[bool, tuple[int, ...]]]:
    """Merge current state with patch - returns (enabled, ports) per protocol."""
    current = {p.name: (p.enabled, p.port) for p in state.protocols}
    result: dict[ProtocolName, tuple[bool, tuple[int, ...]]] = {}

    def _merge(
        name: ProtocolName, port_override: int | None, enabled_override: bool | None
    ) -> None:
        enabled, ports = current.get(name, (False, ()))
        if port_override is not None:
            ports = (port_override,)
        if enabled_override is not None:
            enabled = enabled_override
        result[name] = (enabled, ports)

    _merge(ProtocolName.HTTP, patch.http_port, patch.http_enabled)
    _merge(ProtocolName.HTTPS, patch.https_port, patch.https_enabled)
    _merge(ProtocolName.RTSP, patch.rtsp_port, patch.rtsp_enabled)
    return result


def _is_contiguous_mask(mask: IPv4Address) -> bool:
    """Return True if mask is a valid contiguous IPv4 subnet mask (1s then 0s)."""
    n = int(mask)
    # invert bits, add 1 - if result is a power of two (or zero) the mask is contiguous
    inv = (~n) & 0xFFFFFFFF
    return (inv + 1) & inv == 0


def validate(
    state: NetworkState,
    patch: NetworkPatch,
    *,
    client_ip: IPv4Address | None = None,
) -> list[Warning_]:
    """Run all pre-apply validation.

    Raises ValidationError on any hard failure. Returns a list of Warning_
    objects the caller should surface but not block on. `client_ip` is the
    machine running this tool - used for reachability warnings.
    """

    warnings: list[Warning_] = []

    # ----- protocol ports ---------------------------------------------------
    ports_by_proto = _effective_ports(state, patch)

    # every enabled port must be 1..65535
    for proto, (enabled, ports) in ports_by_proto.items():
        if not enabled:
            continue
        for p in ports:
            if not 1 <= p <= 65535:
                raise ValidationError(f"port {p} for {proto.value} out of range 1..65535")

    # ports unique across all enabled protocols
    seen: dict[int, ProtocolName] = {}
    for proto, (enabled, ports) in ports_by_proto.items():
        if not enabled:
            continue
        for p in ports:
            if p in seen and seen[p] != proto:
                raise ValidationError(
                    f"port {p} assigned to both {seen[p].value} and {proto.value}"
                )
            seen[p] = proto

    # lockout guard - if origin had HTTP or HTTPS enabled, at least one must stay enabled
    origin_mgmt = any(
        p.enabled for p in state.protocols if p.name in (ProtocolName.HTTP, ProtocolName.HTTPS)
    )
    target_mgmt = any(
        enabled
        for proto, (enabled, _) in ports_by_proto.items()
        if proto in (ProtocolName.HTTP, ProtocolName.HTTPS)
    )
    if origin_mgmt and not target_mgmt:
        raise ValidationError(
            "disabling both HTTP and HTTPS would make the camera unreachable via ONVIF"
        )

    # ----- subnet mask contiguity ------------------------------------------
    if patch.subnet_mask is not None and not _is_contiguous_mask(patch.subnet_mask):
        raise ValidationError(f"subnet mask {patch.subnet_mask} is not a valid contiguous netmask")

    # ----- gateway plausibility --------------------------------------------
    effective_ip = (
        patch.ip
        if patch.ip is not None
        else (
            state.primary_interface.ipv4.address
            if state.primary_interface and state.primary_interface.ipv4
            else None
        )
    )
    effective_mask = patch.subnet_mask
    if (
        effective_mask is None
        and state.primary_interface
        and state.primary_interface.ipv4
        and state.primary_interface.ipv4.prefix_length is not None
    ):
        effective_mask = IPv4Address(
            IPv4Network(f"0.0.0.0/{state.primary_interface.ipv4.prefix_length}").netmask
        )

    if patch.gateway is not None and effective_ip is not None and effective_mask is not None:
        network = IPv4Network(f"{effective_ip}/{effective_mask}", strict=False)
        for gw in patch.gateway:
            if isinstance(gw, IPv4Address) and gw not in network:
                warnings.append(
                    Warning_(
                        f"gateway {gw} is not on the device's subnet "
                        f"{network} - device may lose outbound connectivity"
                    )
                )

    # ----- reachability warning for the managing PC ------------------------
    if client_ip is not None and effective_ip is not None and effective_mask is not None:
        network = IPv4Network(f"{effective_ip}/{effective_mask}", strict=False)
        if client_ip not in network:
            warnings.append(
                Warning_(
                    f"your PC's IP {client_ip} is NOT on the camera's new subnet "
                    f"{network} - after the camera reboots you will not be able to "
                    f"reach it without changing your network setup"
                )
            )

    return warnings


def require_confirmation(warnings: Iterable[Warning_]) -> bool:
    """True if the warnings should trigger an interactive confirmation."""
    return any(True for _ in warnings)
