# Roadmap — full ODM feature parity

The upstream ONVIF Device Manager exposed a broad surface: network, device,
user, certificates, maintenance, imaging, video, audio, PTZ, analytics,
metadata, events, live preview. This doc maps each of those features to
its phase in the rewrite.

Every phase ships behind both interfaces the app already has — **CLI**
(`onvifcfg <cmd>`) and the local web UI (`onvifcfg serve` →
`http://localhost:8080/`).

## Phase 1 — DONE

Shipped in the initial rewrite.

- WS-Discovery (`onvifcfg discover`)
- Authenticated session
- Network configuration: IP / subnet / gateway / DNS / NTP / hostname /
  HTTP-HTTPS-RTSP protocols / zero-config / discovery-mode
- Pre-apply validation + diff preview + reachability probe + bounded reboot
- All 11 reliability/compatibility fixes from the upstream ODM review
  (see `docs/RELIABILITY_FIXES.md`)

## Phase 2 — device basics

Small, low-risk, pure SOAP passthrough. Same pattern as `network.py`.

- **Device info** — Manufacturer / Model / Firmware / Serial / HardwareId
  via `GetDeviceInformation`, `GetSystemDateAndTime`
- **Time settings** — local / NTP-synced / posix timezone via
  `SetSystemDateAndTime`
- **Maintenance** — `SystemReboot`, `SetSystemFactoryDefault`, firmware
  upgrade (`UpgradeSystemFirmware` with MTOM/HTTP fallback — fix #18 from
  our review applies: binary payload handling varies by firmware)
- **Users** — `GetUsers`, `CreateUsers`, `DeleteUsers`, `SetUser`; enforce
  non-empty admin on delete, validate password complexity where the device
  advertises a security policy

## Phase 3 — media plane read / edit

- **Profiles** — `GetProfiles`, add/delete, rename
- **Video sources** — `GetVideoSources`, `GetVideoSourceConfigurations`,
  `SetVideoSourceConfiguration`
- **Video encoder** — `GetVideoEncoderConfigurations`,
  `SetVideoEncoderConfiguration` (resolution, bitrate, GOP, H264/H265
  profile)
- **Audio encoder** — same pattern
- **Imaging** — `GetImagingSettings`, `SetImagingSettings` (brightness,
  contrast, saturation, sharpness, WDR, backlight, focus)
- **Stream URIs** — `GetStreamUri` per profile (RTSP, unicast, TCP preferred)

## Phase 4 — live video preview

The hard one. Upstream ODM used a native C++ player (ffmpeg + live555) for
this. In the Python tool:

- **CLI**: `onvifcfg preview <host>` spawns `ffplay` as a subprocess with
  the RTSP URI from `GetStreamUri`. Requires ffmpeg on PATH; packages
  (`.deb` / `.msi`) will declare an optional dependency.
- **Web UI**: `/device/<host>/preview` — options, easiest to hardest:
  1. Server-side transcode to HLS with ffmpeg subprocess, serve via
     StaticFiles. Adds 1–2 s latency. Works in every browser.
  2. WebRTC via mediamtx / Janus as a sidecar service. Sub-second
     latency but adds infrastructure.
  3. MJPEG fallback via `GetSnapshotUri` + meta-refresh — crude but
     works without transcode.

Ship option (1) first; (3) as a low-tech fallback.

## Phase 5 — PTZ

- `GetConfigurations`, `GetConfigurationOptions`
- **ContinuousMove** / **RelativeMove** / **AbsoluteMove** / **Stop**
- **Presets** — `GetPresets`, `GotoPreset`, `SetPreset`, `RemovePreset`
- **Home** — `GotoHomePosition`, `SetHomePosition`
- **Status** — `GetStatus` (position + moving-state indicator)
- CLI: `onvifcfg ptz move <host> --pan +0.5 --tilt 0 --zoom 0.2`
- Web UI: virtual joystick (8-direction buttons + pan/tilt sliders) +
  preset grid, posts to `/ptz/...` with the session token

## Phase 6 — events, analytics, metadata

Lower priority; most users don't configure these interactively.

- **Events** — `CreatePullPointSubscription` + `PullMessages` loop,
  show event types and filter
- **Analytics** — list analytics modules on a profile, enable / disable
- **Metadata** — `GetMetadataConfigurations`, stream metadata on the
  same RTSP multiplex

## Phase 7 — certificates, advanced security

- **Certificates** — `GetCertificates`, `CreateCertificate`,
  `LoadCertificates`, `DeleteCertificates`
- **IEEE 802.1X** if the device advertises it
- **IP filter** — read/write `GetIPAddressFilter` /
  `SetIPAddressFilter` (allow/deny lists)

## Cross-cutting enhancements

- **Cross-subnet discovery** — most ONVIF cameras ship with a default IP
  on `192.168.1.0/24`. If the host doing discovery sits on a different
  subnet, WS-Discovery multicast won't reach them. Approaches under
  investigation:
  - **Unicast Probe sweep** over a user-supplied CIDR: send a WS-Discovery
    `Probe` as UDP unicast to each candidate IP on port 3702
  - **TCP probe sweep** — open port 80/8080/443 and try
    `GetDeviceInformation`
  - **ARP sniff** — passively watch ARP broadcasts on the local wire,
    match OUI against known camera vendors (Axis, Hikvision, Dahua,
    Uniview, Bosch, Hanwha) — requires `scapy` + libpcap/npcap
  - **Temporary secondary IP** — CLI helper to add a 192.168.1.x alias to
    a local interface, run discovery, remove the alias
  - **Broadcast Probe** — send to directed broadcast
    (e.g. `192.168.1.255`) — only works where the gateway forwards UDP
    broadcasts, which is rare
- **Multi-NIC / IPv6** UI — currently the network-settings code assumes
  the first enabled NIC and only edits IPv4. Dual-NIC cameras and
  IPv6-only deployments need a NIC picker and an IPv6 form. (Carried
  from upstream review item #10.)
- **Auth-scheme fallback ladder** — try WS-UsernameToken → HTTP Digest →
  HTTP Basic and cache the last-working scheme per endpoint.
  (Upstream review #19.)
- **WSDL regeneration** — the onvif-zeep package ships a 2.2-era WSDL
  bundle. Newer fields (`PrefixedIPv6Address`, extended
  `NetworkInterfaceExtension2`) may not round-trip. Track the package
  version and pin to a known-good.
- **i18n** — the upstream ODM shipped English / Russian / Traditional
  Chinese strings. Use Babel + .po files when / if that matters.
