# Design notes

## Scope

MVP: ONVIF network configuration of a single camera at a time. Discovery,
read, validated apply, post-reboot reachability probe.

Intentionally out of scope:

- Live video preview (RTSP + codec — huge)
- PTZ
- User management (needs careful auth handling)
- Certificate management

These can be added as separate command groups later without rearchitecting
the existing code.

## Module layout

```
src/onvifcfg/
  cli.py            typer app, all user-facing I/O here
  discovery.py      WS-Discovery probe (uses wsdiscovery package)
  session.py        authenticated ONVIFCamera wrapper with safe_call helper
  network.py        read_state, compute_diff, apply — reliability fixes live here
  validation.py     pre-apply guards, warnings
  reachability.py   TCP probe + reconnect polling
  models.py         pydantic models for every config shape
  exceptions.py     onvifcfg-specific exception hierarchy
```

## Data flow

```
cli.apply
  │
  ├─► session.DeviceSession(host, port, creds)
  │
  ├─► network.read_state(sess)         ─► NetworkState
  │
  ├─► network.compute_diff(state, patch)
  │      └── Diff (per-field booleans + set[ProtocolName])
  │
  ├─► validation.validate(state, patch, client_ip)
  │      └── raises ValidationError | returns [Warning_]
  │
  ├─── CLI shows diff + warnings + confirms
  │
  └─► network.apply(sess, state, patch)
         ├── safe phase: NTP, DNS, gateway, zero-config, hostname, discovery
         ├── destructive: protocols (only changed ones)
         └── destructive: IP → SetNetworkInterfaces → SystemReboot → reachability.wait_for_port
```

## Why sync, not async

Per-session each apply is a single-user, single-device, short-lived flow.
Async buys nothing here and makes error handling harder to reason about.
If a web server mode is added later, the module API is cheap to wrap with
`asyncio.to_thread(read_state, sess)` etc.

## Testing

All units that don't need a real camera are tested directly with pytest:

- `test_validation.py` — port range, duplicates, lockout, masks, gateway warning, client reachability
- `test_models.py` — IPv4Config derivation, Gateway.parse, NetworkProtocol bounds
- `test_network_diff.py` — diff computation for various patches

Network-dependent integration tests (would hit a real camera) are deferred.

## Upstream-equivalence

The fixes catalogued in RELIABILITY_FIXES.md all cross-reference to specific
hunks in the original ODM F# source. The Python rewrite reimplements the
same apply state machine with those fixes baked in; a reader familiar with
`NetworkSettingsActivity.fs` should be able to map every concept 1:1.
