# onvifcfg — ONVIF network configuration tool

Cross-platform ONVIF IP camera configuration tool.  Same feature scope as
the upstream ONVIF Device Manager — network configuration, device info,
user management, PTZ, live video preview — delivered as both a CLI
(`onvifcfg`) and a local browser UI (`onvifcfg serve` → localhost:3003).
The rewrite ships every reliability and compatibility fix identified in
the prior review of the legacy ODM source.

**Status**: Phase 1 (discovery + network configuration) shipped.  Phases
2–7 (device info, users, imaging, video encoder, live preview, PTZ,
events, certificates) tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

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

- **Linux (Debian/Ubuntu .deb)** — switch to branch [`linux`](../../tree/linux),
  run `bash packaging/deb/build-deb.sh` on a Linux host with `uv` and `nfpm`
- **Windows (MSI)** — switch to branch [`windows-msi`](../../tree/windows-msi),
  run `pwsh packaging/msi/build-msi.ps1` on a Windows host with `uv`
  and the WiX v4 toolset


## Windows (MSI / EXE)

Pre-built installers are attached to every GitHub release:

- `onvifcfg-<version>.msi` &mdash; classic Windows Installer (WiX).
- `onvifcfg-<version>-setup.exe` &mdash; Inno Setup alternative.

### SmartScreen warning

Windows will likely flag the first launch with
_"Microsoft Defender SmartScreen prevented an unrecognized app from starting"_.
**The installer is not malicious** &mdash; it is simply not code-signed.

I am not a Windows developer and do not intend to pay Microsoft (nor any
reseller) for a code-signing certificate just to ship a free tool that
configures ONVIF cameras on a local network. The signing-certificate
ecosystem is a rent extraction mechanism I am not interested in feeding.

Workarounds, in order of convenience:

1. **Elevated one-liner** (recommended &mdash; downloads via .NET
   `WebClient`, which does not tag the file with the Mark-of-the-Web
   flag SmartScreen checks, so it never triggers the prompt):

   ```powershell
   irm https://raw.githubusercontent.com/andrewhack/odm/main/packaging/msi/install.ps1 | iex
   ```

2. **Click through the warning** &mdash; on the SmartScreen dialog click
   _More info_ &rarr; _Run anyway_. Same binary, one extra click.

3. **Unblock the file manually** &mdash; right-click the downloaded
   `.msi` / `.exe` &rarr; Properties &rarr; check _Unblock_ &rarr; OK.

If your environment mandates signed binaries, build the MSI yourself from
source (`pwsh packaging/msi/build-msi.ps1` on the `windows-msi`
branch) and sign it with your own certificate.

## Usage — CLI

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

## Usage — web UI

```bash
onvifcfg serve            # binds 127.0.0.1:3003 by default
# then open http://localhost:3003/ in any browser
```

The web UI exposes the same discover / read / apply flow with a click-
through confirmation page.  Do **not** expose it on a network — it
reconfigures cameras and has no built-in access control.

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
