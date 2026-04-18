"""Diff computation — does it spot exactly the fields that changed?"""

from __future__ import annotations

from ipaddress import IPv4Address

from onvifcfg.models import (
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
)
from onvifcfg.network import compute_diff


def _baseline() -> NetworkState:
    return NetworkState(
        interfaces=(
            NetworkInterface(
                token="eth0",
                enabled=True,
                ipv4=IPv4Config(
                    dhcp=False, address=IPv4Address("192.168.1.10"), prefix_length=24
                ),
            ),
        ),
        hostname=Hostname(name="cam01", from_dhcp=False),
        gateway=Gateway(ipv4=(IPv4Address("192.168.1.1"),)),
        dns=DNSInfo(from_dhcp=False, servers=(IPv4Address("8.8.8.8"),)),
        ntp=NTPInfo(from_dhcp=False, servers=("pool.ntp.org",)),
        protocols=(
            NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(80,)),
            NetworkProtocol(name=ProtocolName.HTTPS, enabled=True, port=(443,)),
            NetworkProtocol(name=ProtocolName.RTSP, enabled=True, port=(554,)),
        ),
        zero_config=None,
        discovery_mode=None,
    )


def test_no_diff_for_empty_patch() -> None:
    assert not compute_diff(_baseline(), NetworkPatch()).any


def test_ip_only_change() -> None:
    d = compute_diff(_baseline(), NetworkPatch(ip=IPv4Address("192.168.1.20")))
    assert d.ip_changed
    assert not d.subnet_changed
    assert not d.gateway_changed


def test_protocol_only_changed_protocols_in_diff() -> None:
    d = compute_diff(_baseline(), NetworkPatch(rtsp_port=8554))
    assert d.protocols_changed == {ProtocolName.RTSP}


def test_setting_same_port_is_not_a_change() -> None:
    d = compute_diff(_baseline(), NetworkPatch(rtsp_port=554))
    assert d.protocols_changed == set()


def test_hostname_change_vs_dhcp_flag() -> None:
    d = compute_diff(_baseline(), NetworkPatch(use_hostname_from_dhcp=True))
    assert d.hostname_changed
