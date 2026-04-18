# onvifcfg — project instructions

Python 3.11+ CLI tool for ONVIF network configuration. Replaces a legacy
C#/F#/WPF ONVIF Device Manager fork.

## Architecture

- `src/onvifcfg/` — single package, sync API
- `tests/` — pytest, no real camera required for unit tests
- `docs/` — design + reliability-fix catalogue

## Conventions

- uv for package management (never pip directly)
- ruff check + ruff format
- pytest + pytest-asyncio (asyncio_mode = "auto")
- Pydantic v2 models for every config shape
- snake_case functions/vars, PascalCase classes, 4-space indent
- Type hints on all function signatures
- Imperative lowercase commits, scope-prefixed: `network: fix IPv6 DNS apply`
- Comments only when the WHY is non-obvious (hidden constraints, vendor
  quirks, upstream bug references). Don't explain WHAT the code does.

## Reliability fixes

Every behaviour cross-referenced as `fix #N` in code comments refers to
an entry in `docs/RELIABILITY_FIXES.md`. Preserve the cross-references
when refactoring — they make the code self-documenting for people
familiar with the upstream ODM review.

## Branches

- `main` — core Python source, no platform packaging
- `linux` — adds `debian/` and `build-deb.sh` for a Debian / Ubuntu `.deb`
- `windows-msi` — adds `wix/` and `build-msi.ps1` for a Windows MSI

## Testing locally

```bash
uv sync
uv run pytest
uv run onvifcfg --help
```
