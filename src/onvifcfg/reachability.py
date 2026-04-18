"""TCP reachability probe - used post-reboot to confirm the device came back."""

from __future__ import annotations

import socket
import time
from ipaddress import IPv4Address, IPv6Address


def wait_for_port(
    host: str | IPv4Address | IPv6Address,
    port: int,
    *,
    timeout_s: float = 60.0,
    poll_interval_s: float = 2.0,
    connect_timeout_s: float = 3.0,
) -> bool:
    """Poll TCP port until it accepts a connection or timeout expires.

    Returns True on success, False on timeout. Never raises.
    """

    deadline = time.monotonic() + timeout_s
    host_str = str(host)
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host_str, port), timeout=connect_timeout_s):
                return True
        except (OSError, socket.timeout):
            pass
        time.sleep(poll_interval_s)
    return False
