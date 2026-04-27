"""onvifcfg — ONVIF network configuration CLI tool."""

from __future__ import annotations


def _resolve_version() -> str:
    """Resolve the package version once at import.

    Strategy:
    1. ``importlib.metadata.version("onvifcfg")`` — works for dev installs
       (``uv sync``) and any environment where the dist-info is present.
    2. Fall back to ``_buildinfo.VERSION`` — used by PyInstaller-frozen
       builds when ``--copy-metadata`` is not in effect; this constant is
       rewritten by ``scripts/write_buildinfo.{sh,ps1}`` from the
       ``pyproject.toml`` ``project.version`` field at build time.
    3. Final fallback string so we never raise from package import.
    """
    try:
        from importlib.metadata import version

        return version("onvifcfg")
    except Exception:
        pass
    try:
        from ._buildinfo import VERSION  # type: ignore[attr-defined]

        return str(VERSION)
    except Exception:
        return "0.0.0+unknown"


__version__ = _resolve_version()
