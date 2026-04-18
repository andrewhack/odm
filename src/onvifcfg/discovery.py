"""WS-Discovery for ONVIF cameras on the local subnet."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    address: str
    types: tuple[str, ...]
    scopes: tuple[str, ...]

    def best_xaddr(self) -> str:
        """The first HTTP xAddr the device advertised."""
        return self.address


def discover(timeout_s: float = 3.0) -> list[DiscoveredDevice]:
    """Probe the local network for ONVIF devices.

    Uses the standard WS-Discovery multicast channel.  A single Probe is sent
    and responses are collected for ``timeout_s`` seconds.
    """
    # Imported lazily so the CLI can start without the discovery lib being
    # installed on a machine that only needs the show/apply commands.
    try:
        from wsdiscovery import QName  # type: ignore[import-untyped]
        from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "WS-Discovery requires the 'wsdiscovery' package (pip install wsdiscovery)"
        ) from e

    onvif_type = QName(
        "http://www.onvif.org/ver10/network/wsdl",
        "NetworkVideoTransmitter",
    )

    wsd = WSDiscovery()
    wsd.start()
    try:
        services = wsd.searchServices(types=[onvif_type], timeout=int(timeout_s))
    finally:
        wsd.stop()

    out: list[DiscoveredDevice] = []
    for svc in services:
        xaddrs = list(svc.getXAddrs())
        if not xaddrs:
            continue
        out.append(
            DiscoveredDevice(
                address=xaddrs[0],
                types=tuple(str(t) for t in svc.getTypes()),
                scopes=tuple(str(s) for s in svc.getScopes()),
            )
        )
    return out
