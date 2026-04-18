# onvifcfg — ONVIF network configuration tool

Cross-platform command-line tool for configuring ONVIF-compliant IP cameras.
Focused on the **network configuration** workflow (IP address, DNS, NTP,
gateway, hostname, discovery protocols) with reliability and compatibility
fixes derived from a prior analysis of the upstream ONVIF Device Manager.

## Lineage

This repository is a **rewrite** of the original ONVIF Device Manager (ODM),
a 2013-era C# / F# / C++ WPF application available at:

  **https://svn.code.sf.net/p/onvifdm/code/trunk onvifdm-code**

The earlier commit history of this repository contained a fork of that SVN
source tree plus a long series of attempts to get it to build on modern
Visual Studio 2022. The legacy tooling chain (MarkupCompilePass + .NET
Framework 4.x ReflectionOnly loading of transitively-unsigned assemblies)
ultimately proved unreliable on current Windows SDKs. Rather than continue
that port, this repo has been reset to a Python rewrite that delivers
**the functionality we actually cared about** — the network-settings
apply workflow — with every reliability and compatibility fix we identified
during the code review baked in from day one.

## Features

- WS-Discovery to find ONVIF cameras on the local network
- Read full network configuration from a camera
- Apply network configuration changes with:
  - Pre-apply validation (port ranges, lockout prevention, subnet sanity,
    IP-in-subnet gateway check)
  - Safe apply order — NTP, DNS, gateway, hostname, discovery-mode first;
    protocols and IP last to avoid breaking the session mid-apply
  - `SetHostnameFromDHCP` preferred over `SetHostname("")` (ONVIF 2.x)
  - IPv6 DNS / NTP entries correctly routed to `iPv6Address` fields
  - Round-trip of existing `SearchDomain` list on `SetDNS`
  - Capability-advisory guards around optional features
    (`GetZeroConfiguration`, `GetDiscoveryMode`)
  - Only-changed protocols sent via `SetNetworkProtocols`
  - Bounded 30-second timeout on `SystemReboot` best-effort call
  - Post-reboot TCP reachability probe on the new IP
  - Confirmation + diff preview before destructive apply

See [docs/RELIABILITY_FIXES.md](docs/RELIABILITY_FIXES.md) for the full
catalogue of issues fixed relative to upstream ODM's behaviour.

## Install

```bash
# development install
uv sync
uv run onvifcfg --help
```

Per-platform packaged installs:

- **Linux (Debian/Ubuntu .deb)**: switch to branch `linux`, see its README
- **Windows (MSI)**: switch to branch `windows-msi`, see its README

## Usage

```bash
# discover cameras on the local subnet
onvifcfg discover

# show current network config
onvifcfg show 192.168.1.100 --user admin --password secret

# apply a new IP (prompts for confirmation, shows diff)
onvifcfg apply 192.168.1.100 --user admin --password secret \
    --ip 192.168.1.200 --subnet 255.255.255.0 --gateway 192.168.1.1

# change only the RTSP port
onvifcfg apply 192.168.1.100 -u admin -p secret --rtsp 8554
```

## Layout

```
src/onvifcfg/
  cli.py            # typer entrypoint
  discovery.py      # WS-Discovery scan
  session.py        # authenticated ONVIF session
  network.py        # read + apply network settings
  validation.py     # pre-apply guards
  reachability.py   # post-reboot TCP probe
  models.py         # pydantic models

tests/              # pytest suite
docs/               # design notes and fix catalogue
```

## License

The upstream ODM codebase was BSD-licensed; this rewrite uses the same terms.
See [LICENSE](LICENSE).
