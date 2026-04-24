"""Pydantic models for ONVIF network configuration."""

from __future__ import annotations

from enum import Enum
from ipaddress import IPv4Address, IPv4Network, IPv6Address, ip_address
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProtocolName(str, Enum):
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    RTSP = "RTSP"


class DiscoveryMode(str, Enum):
    DISCOVERABLE = "Discoverable"
    NON_DISCOVERABLE = "NonDiscoverable"


class NetworkProtocol(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ProtocolName
    enabled: bool
    port: tuple[int, ...]

    @field_validator("port")
    @classmethod
    def _ports_in_range(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        for p in v:
            if not 1 <= p <= 65535:
                raise ValueError(f"port {p} out of range 1..65535")
        return v


class IPv4Config(BaseModel):
    """Static or DHCP-derived IPv4 configuration for a NIC."""

    model_config = ConfigDict(frozen=True)

    dhcp: bool
    address: IPv4Address | None = None
    prefix_length: Annotated[int, Field(ge=0, le=32)] | None = None

    @property
    def subnet_mask(self) -> IPv4Address | None:
        if self.prefix_length is None:
            return None
        return IPv4Address(IPv4Network(f"0.0.0.0/{self.prefix_length}").netmask)


class NetworkInterface(BaseModel):
    """ONVIF NetworkInterface summary."""

    model_config = ConfigDict(frozen=True)

    token: str
    enabled: bool
    mac: str | None = None
    ipv4: IPv4Config | None = None


class Hostname(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    from_dhcp: bool


class NTPInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_dhcp: bool
    servers: tuple[str, ...]  # hostnames, IPv4, or IPv6


class DNSInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_dhcp: bool
    servers: tuple[IPv4Address | IPv6Address, ...]
    search_domains: tuple[str, ...] = ()


class Gateway(BaseModel):
    model_config = ConfigDict(frozen=True)

    ipv4: tuple[IPv4Address, ...] = ()
    ipv6: tuple[IPv6Address, ...] = ()

    @classmethod
    def parse(cls, addresses: list[str]) -> Gateway:
        v4: list[IPv4Address] = []
        v6: list[IPv6Address] = []
        for raw in addresses:
            addr = ip_address(raw.strip())
            if isinstance(addr, IPv4Address):
                v4.append(addr)
            else:
                v6.append(addr)
        return cls(ipv4=tuple(v4), ipv6=tuple(v6))


class ZeroConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    supported: bool
    enabled: bool
    interface_token: str | None = None
    addresses: tuple[IPv4Address, ...] = ()


class NetworkState(BaseModel):
    """Aggregate read of every network-related ONVIF property on a device."""

    interfaces: tuple[NetworkInterface, ...]
    hostname: Hostname
    gateway: Gateway
    dns: DNSInfo
    ntp: NTPInfo | None
    protocols: tuple[NetworkProtocol, ...]
    zero_config: ZeroConfig | None
    discovery_mode: DiscoveryMode | None

    @property
    def primary_interface(self) -> NetworkInterface | None:
        """First enabled NIC - the one every setter modifies."""
        return next((n for n in self.interfaces if n.enabled), None)


class NetworkPatch(BaseModel):
    """User-requested changes to apply on top of NetworkState.

    None means "leave alone"; any non-None value is a new setting.
    """

    model_config = ConfigDict(frozen=True)

    dhcp: bool | None = None
    ip: IPv4Address | None = None
    subnet_mask: IPv4Address | None = None
    gateway: tuple[IPv4Address | IPv6Address, ...] | None = None
    dns: tuple[IPv4Address | IPv6Address, ...] | None = None
    ntp_servers: tuple[str, ...] | None = None
    hostname: str | None = None
    use_hostname_from_dhcp: bool | None = None
    http_port: int | None = None
    http_enabled: bool | None = None
    https_port: int | None = None
    https_enabled: bool | None = None
    rtsp_port: int | None = None
    rtsp_enabled: bool | None = None
    zero_config_enabled: bool | None = None
    discovery_mode: DiscoveryMode | None = None
