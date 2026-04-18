"""Pre-apply validation — unit tests."""

from __future__ import annotations

from ipaddress import IPv4Address

import pytest

from onvifcfg.exceptions import ValidationError
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
from onvifcfg.validation import _is_contiguous_mask, validate


def _state(
    *,
    ip: str = "192.168.1.100",
    prefix: int = 24,
    http: bool = True,
    https: bool = True,
    rtsp: bool = True,
) -> NetworkState:
    return NetworkState(
        interfaces=(
            NetworkInterface(
                token="eth0",
                enabled=True,
                ipv4=IPv4Config(dhcp=False, address=IPv4Address(ip), prefix_length=prefix),
            ),
        ),
        hostname=Hostname(name="cam", from_dhcp=False),
        gateway=Gateway(ipv4=(IPv4Address("192.168.1.1"),)),
        dns=DNSInfo(from_dhcp=False, servers=()),
        ntp=NTPInfo(from_dhcp=False, servers=()),
        protocols=(
            NetworkProtocol(name=ProtocolName.HTTP, enabled=http, port=(80,)),
            NetworkProtocol(name=ProtocolName.HTTPS, enabled=https, port=(443,)),
            NetworkProtocol(name=ProtocolName.RTSP, enabled=rtsp, port=(554,)),
        ),
        zero_config=None,
        discovery_mode=None,
    )


class TestPortValidation:
    def test_rejects_out_of_range(self) -> None:
        # Pydantic rejects at model construction - same layer as our validation.
        with pytest.raises(Exception):
            NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(70000,))

    def test_rejects_duplicate_ports(self) -> None:
        patch = NetworkPatch(rtsp_port=80)  # collide with HTTP default 80
        with pytest.raises(ValidationError, match="multiple protocols"):
            validate(_state(), patch)

    def test_allows_duplicate_port_if_only_one_protocol_enabled(self) -> None:
        patch = NetworkPatch(rtsp_port=80, http_enabled=False)
        # HTTPS is still enabled but on 443, so no conflict with 80.
        validate(_state(), patch)


class TestLockoutGuard:
    def test_refuses_disabling_both_management_protocols(self) -> None:
        patch = NetworkPatch(http_enabled=False, https_enabled=False)
        with pytest.raises(ValidationError, match="unreachable via ONVIF"):
            validate(_state(), patch)

    def test_allows_disabling_one_management_protocol(self) -> None:
        patch = NetworkPatch(https_enabled=False)
        validate(_state(), patch)

    def test_allows_rtsp_disable_when_management_stays_enabled(self) -> None:
        patch = NetworkPatch(rtsp_enabled=False)
        validate(_state(), patch)

    def test_no_lockout_guard_if_management_was_already_disabled(self) -> None:
        patch = NetworkPatch(rtsp_port=8554)
        validate(_state(http=False, https=False), patch)  # no crash


class TestSubnetMaskValidation:
    def test_contiguous_masks(self) -> None:
        for m in (
            "255.0.0.0",
            "255.255.0.0",
            "255.255.255.0",
            "255.255.255.192",
            "255.255.255.255",
            "0.0.0.0",
        ):
            assert _is_contiguous_mask(IPv4Address(m)), m

    def test_non_contiguous_mask(self) -> None:
        assert not _is_contiguous_mask(IPv4Address("255.0.255.0"))
        assert not _is_contiguous_mask(IPv4Address("255.255.0.1"))

    def test_rejects_invalid_mask(self) -> None:
        patch = NetworkPatch(subnet_mask=IPv4Address("255.0.255.0"))
        with pytest.raises(ValidationError, match="contiguous"):
            validate(_state(), patch)


class TestGatewayWarning:
    def test_warns_when_gateway_out_of_subnet(self) -> None:
        patch = NetworkPatch(gateway=(IPv4Address("10.0.0.1"),))
        w = validate(_state(), patch)
        assert any("gateway 10.0.0.1" in x.message for x in w)

    def test_no_warning_for_gateway_in_subnet(self) -> None:
        patch = NetworkPatch(gateway=(IPv4Address("192.168.1.1"),))
        w = validate(_state(), patch)
        assert not any("gateway" in x.message for x in w)


class TestClientReachabilityWarning:
    def test_warns_when_pc_ip_not_in_new_subnet(self) -> None:
        patch = NetworkPatch(
            ip=IPv4Address("10.0.0.5"),
            subnet_mask=IPv4Address("255.255.255.0"),
        )
        w = validate(_state(), patch, client_ip=IPv4Address("192.168.1.50"))
        assert any("your PC" in x.message for x in w)

    def test_no_warning_when_pc_ip_on_new_subnet(self) -> None:
        patch = NetworkPatch(
            ip=IPv4Address("192.168.1.200"),
            subnet_mask=IPv4Address("255.255.255.0"),
        )
        w = validate(_state(), patch, client_ip=IPv4Address("192.168.1.50"))
        assert not any("your PC" in x.message for x in w)
