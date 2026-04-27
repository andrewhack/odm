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

## Phase 2 — device basics — DONE (core), follow-ups open

Small, low-risk, pure SOAP passthrough. Same pattern as `network.py`.
Shipped in v0.1.x: device info panel on `/device`, reboot + soft/hard
factory-reset buttons wired to the existing maintenance module, new
POST `/action/reboot` and POST `/action/factory-reset` routes.

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

## Phase 2 follow-ups — DONE

Shipped in v0.1.2:

- **Time settings UI** — `/device` panel reads UTC / local / TZ /
  NTP-sync / DST and exposes a form posting to `/action/set-time`,
  wrapping `SetSystemDateAndTime` (NTP toggle, POSIX TZ string,
  manual UTC override).
- **Users UI** — `/device` table of users with per-row password +
  delete actions and an "add user" form, posting to
  `/action/user-create`, `/action/user-delete`,
  `/action/user-password`. Last-administrator deletion guard from
  the backend is preserved.
- **Firmware upgrade** — `/action/firmware-upgrade` accepts a
  `multipart/form-data` upload, tries `StartFirmwareUpgrade` HTTP
  upload first, falls back to inline base64 `UpgradeSystemFirmware`
  (fix #18 from the upstream review: zeep does not implement MTOM,
  binary payload handling varies by firmware). Reachability probe
  waits up to 180 s for the device to come back.

## Phase 3 — media plane read / edit

### Shipped in v0.1.x

- Read-only profile table on `/device` (name / token / encoding /
  resolution / fps / bitrate / GOV) with one RTSP link per profile.
- `get_encoder_options` helper exposing the device-advertised
  resolutions / fps range / bitrate range / GOV-length range per
  encoder configuration.

### Shipped in v0.1.4 — video encoder edit

- **Setter backend**: `media.set_video_encoder_configuration()` reads
  the existing config first and patches only the fields the caller
  supplied (round-trips Name / UseCount / Multicast / Quality so
  HIK and Dahua firmwares that fault on a partially-populated
  configuration accept the write).
- **Web UI**: per-profile edit form on `/device` posting to
  `POST /action/encoder-set`, with resolution / fps populated from
  the option space and bitrate / GOV-length validated against the
  range advertised by the device.
- **CLI**: `onvifcfg encoder show` prints the option space;
  `onvifcfg encoder set --resolution WxH --fps N --bitrate K --gov G`
  applies a delta in one shot.
- **Tests**: 5 round-trip tests in `tests/test_media_encoder.py`
  cover the most common firmware regressions (resolution-only
  patch preserves Encoding / Name, fps + bitrate route to
  RateControl, GOV-length routes to the H264 sub-block, force-
  persistence override, hard-fail when the device refuses
  GetVideoEncoderConfiguration).

### Phase 3 follow-ups

- **Profiles** — `GetProfiles`, add / delete, rename.
- **Video sources** — `GetVideoSources`, `GetVideoSourceConfigurations`,
  `SetVideoSourceConfiguration`.
- **Audio encoder** — same setter pattern as video encoder.
- **Imaging** — `GetImagingSettings`, `SetImagingSettings`
  (brightness, contrast, saturation, sharpness, WDR, backlight, focus).
- **Stream URIs** — extend `GetStreamUri` to surface RTSP-over-HTTP
  + multicast variants alongside the default unicast TCP URI.

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

## Phase 8 — vendor adapters (HIK / Dahua / Axis)

Most cameras expose ONVIF as a secondary, lowest-common-denominator
surface; their full feature set lives behind a vendor-proprietary HTTP
API (Hikvision **ISAPI**, Dahua **CGI**, Axis **VAPIX**). A vendor
adapter layer keeps ONVIF as the default but lets us route to the
native API where it does a better or more reliable job.

Architecture:

```
src/onvifcfg/vendors/
  __init__.py    # registry + auto-detect at session open
  hik.py         # Hikvision ISAPI client (httpx + digest)
  dahua.py       # Dahua CGI client
  axis.py        # Axis VAPIX client
```

Auto-detect probes `GET /ISAPI/System/deviceInfo` (HIK), `GET
/cgi-bin/magicBox.cgi?action=getSystemInfo` (Dahua), `GET
/axis-cgi/basicdeviceinfo.cgi` (Axis). On match, the session is
flagged with the vendor; otherwise it stays pure ONVIF. The adapter
is **additive** — never replaces ONVIF, only augments. ONVIF failure
still falls back to the standard path.

Highest-value wins per vendor:

- **HIK ISAPI**:
  - Reliable snapshot via `/ISAPI/Streaming/channels/<ch>01/picture`
    — bypasses the shared HTTP+ONVIF port collision that breaks
    `GetSnapshotUri` on some firmwares (the 192.168.5.57 class).
  - Firmware upgrade via `PUT /ISAPI/System/updateFirmware` —
    covers the Phase 2 follow-up cleanly; ONVIF firmware upgrade is
    patchy across vendors.
  - Smart events (line-crossing, intrusion zones, motion grids) that
    HIK does not surface over ONVIF.
  - Imaging (WDR / BLC / day-night) richer than ONVIF imaging.
- **Dahua CGI**: same shape — snapshot, smart events, imaging,
  storage management.
- **Axis VAPIX**: parameter list (`/axis-cgi/param.cgi`), event
  declarations, the action engine.

Stays ONVIF-only:

- Discovery (WS-Discovery is universal; SADP/Dahua-discover are
  chatty and vendor-specific).
- Network configuration (ONVIF `SetNetworkInterfaces` works on every
  vendor; no reason to reinvent).
- Stream URI (vendor ONVIF stacks all return the right RTSP URL).

Phasing:

1. Vendor detection + HIK ISAPI snapshot (kills the 5.57 class of
   bugs).
2. HIK firmware upgrade (closes the Phase 2 follow-up).
3. HIK smart events read-only display.
4. Dahua CGI parity for snapshot + firmware.
5. Imaging write surfaces per vendor.

Test fixtures use recorded XML / JSON responses; no live camera
required for unit tests.

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
