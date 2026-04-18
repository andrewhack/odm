"""Model unit tests — shape and behaviour checks."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address

import pytest

from onvifcfg.models import Gateway, IPv4Config, NetworkProtocol, ProtocolName


class TestIPv4Config:
    def test_subnet_mask_derived_from_prefix(self) -> None:
        cfg = IPv4Config(dhcp=False, address=IPv4Address("10.0.0.5"), prefix_length=24)
        assert cfg.subnet_mask == IPv4Address("255.255.255.0")

    def test_subnet_mask_none_when_prefix_missing(self) -> None:
        cfg = IPv4Config(dhcp=True)
        assert cfg.subnet_mask is None


class TestGatewayParse:
    def test_mixed_v4_and_v6(self) -> None:
        gw = Gateway.parse(["192.168.1.1", "fe80::1", "10.0.0.1"])
        assert gw.ipv4 == (IPv4Address("192.168.1.1"), IPv4Address("10.0.0.1"))
        assert gw.ipv6 == (IPv6Address("fe80::1"),)

    def test_empty(self) -> None:
        assert Gateway.parse([]) == Gateway()


class TestNetworkProtocol:
    def test_port_range_validation(self) -> None:
        NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(80,))
        NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(1, 65535))

    def test_port_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(0,))

    def test_port_too_high_rejected(self) -> None:
        with pytest.raises(Exception):
            NetworkProtocol(name=ProtocolName.HTTP, enabled=True, port=(70000,))
