# Reliability and compatibility fixes carried over from upstream ODM

Every numbered item below was a bug, surprising behaviour, or lockout risk
identified during the review of the original ONVIF Device Manager F# code
(`odm/odm.ui.activities/NetworkSettingsActivity.fs`,
`onvif/onvif.utils/OdmSession.fs`). The fixes are implemented from day one
in the Python rewrite — there is no toggle to disable them.

## Bug fixes

| # | Area | Fix |
|---|------|-----|
| 1 | `NetworkHost` serialisation | IPv6 NTP/host entries are written to `iPv6Address`, not `iPv4Address`. Upstream ODM silently corrupted IPv6 NTP server fields. See `network._apply_ntp`. |
| 2 | DNS apply | Each DNS entry is parsed and routed by `AddressFamily`; IPv6 servers go to `IPv6Address`, IPv4 to `IPv4Address`. Upstream force-cast everything to IPv4. See `network._apply_dns`. |
| 3 | Hostname from DHCP | Uses `SetHostnameFromDHCP(true)` (ONVIF 2.x) and falls back to `SetHostname("")` only if the device faults. Upstream relied on the ambiguous empty-string sentinel. See `network._apply_hostname`. |
| 4 | DNS apply | Existing `SearchDomain` list is read and round-tripped. Upstream passed `null` and wiped it. See `network._apply_dns`. |
| 5 | Load phase | Capability query deduplicated; a single `GetCapabilities` resolves every feature flag. See `network.read_state`. |
| 11 | Load phase | No `255.255.255.255` sentinel when there is no enabled NIC; the UI shows empty fields and refuses to apply nonsense. See `network._apply_ip`. |

## Reliability improvements

| # | Area | Fix |
|---|------|-----|
| 6 | Apply order | NTP / DNS / gateway / zero-config / hostname / discovery-mode first, then protocols (may rotate ports), then IP last. Dangerous calls are wrapped in exception guards because the camera often drops the channel before ACKing. See `network.apply`. |
| 7 | Post-IP reboot | `SystemReboot` runs best-effort with a bounded timeout; transport failures are treated as "already rebooting", not errors. See `network._best_effort_reboot`. |

## Compatibility improvements

| # | Area | Fix |
|---|------|-----|
| 12 | Zero-config | `SetZeroConfiguration` wrapped in capability-advisory `safe_call`; some vendors advertise the feature and then fault on Set. See `network._apply_zero_config`. |
| 13 | Protocol apply | Only protocols whose port list actually changed go into `SetNetworkProtocols`. Strict firmware on some Uniview / Dahua units rejects batches that include unsupported HTTPS entries. See `network._apply_protocols`. |

## Pre-apply validation

| # | Check |
|---|-------|
| 14 | Every enabled port must be in `1..65535`. |
| 14 | No port may be assigned to more than one enabled protocol. |
| 14 | If origin had HTTP or HTTPS enabled, target must keep at least one enabled — otherwise the camera becomes unreachable via ONVIF. |
| 15 | Full diff + warning preview before destructive apply (requires interactive confirm unless `--yes`). |
| — | Subnet mask must be a valid contiguous netmask. |
| — | Gateway plausibility warning if not on the device's subnet. |
| 20 | Client-PC reachability warning if your own IP is not on the camera's new subnet. |

## Post-apply

| # | Behaviour |
|---|-----------|
| 20 | After an IP change + reboot, poll the new address with bounded timeout and report `reconnected` / `timeout` explicitly instead of hanging silently. See `network.apply` and `reachability.wait_for_port`. |
