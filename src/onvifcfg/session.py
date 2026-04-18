"""Thin ONVIF session wrapper.

Builds a zeep-backed ONVIFCamera and exposes the three services the rest of
the package uses: device, media, ptz.  All methods are sync; if an async
context is added later the calls are cheap to wrap with ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from onvif import ONVIFCamera  # type: ignore[import-untyped]

from .exceptions import SessionError

log = logging.getLogger(__name__)


def _resolve_wsdl_dir() -> str:
    """Locate the onvif-zeep WSDL directory in both dev and frozen runtimes.

    PyInstaller onefile extracts data files under ``sys._MEIPASS``. The
    collected ``onvif/wsdl`` tree lives there. In a regular install,
    ``importlib.resources`` returns the on-disk path.
    """
    try:
        from importlib.resources import files
        candidate = str(files("onvif") / "wsdl")
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass
    # Frozen fallback - pyinstaller onefile _MEIPASS layout
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, "onvif", "wsdl")
        if os.path.isdir(candidate):
            return candidate
    # Last resort - let onvif-zeep try its own resolution
    import onvif as _onvif
    pkg_dir = os.path.dirname(os.path.abspath(_onvif.__file__))
    candidate = os.path.join(pkg_dir, "wsdl")
    if os.path.isdir(candidate):
        return candidate
    raise RuntimeError(
        "could not locate onvif-zeep WSDL directory - is the package installed correctly?"
    )


@dataclass(slots=True)
class Credentials:
    user: str
    password: str


class DeviceSession:
    """Wraps an ONVIFCamera with device/media/ptz services lazily created."""

    def __init__(
        self,
        host: str,
        port: int,
        creds: Credentials,
        *,
        wsdl_dir: str | None = None,
    ) -> None:
        try:
            self._cam = ONVIFCamera(
                host, port, creds.user, creds.password,
                wsdl_dir or _resolve_wsdl_dir(),
            )
        except Exception as e:
            raise SessionError(f"failed to open ONVIF session to {host}:{port}: {e}") from e
        self.host = host
        self.port = port
        self._device = self._cam.create_devicemgmt_service()
        self._media: Any | None = None
        self._ptz: Any | None = None

    # ---- services ----------------------------------------------------

    @property
    def device(self) -> Any:
        return self._device

    @property
    def media(self) -> Any:
        if self._media is None:
            self._media = self._cam.create_media_service()
        return self._media

    @property
    def ptz(self) -> Any:
        if self._ptz is None:
            self._ptz = self._cam.create_ptz_service()
        return self._ptz

    # ---- generic call helpers ----------------------------------------

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._device, method)
        # onvif-zeep's service_wrapper takes a single positional dict,
        # not loose kwargs. Repack kwargs into a dict when the caller
        # used keyword-argument style.
        if kwargs and not args:
            return fn(dict(kwargs))
        return fn(*args, **kwargs)

    def safe_call(self, method: str, *args: Any, **kwargs: Any) -> Any | None:
        """Call a device op, return None on fault.

        Used for capability-advisory ops (GetZeroConfiguration, GetDiscoveryMode,
        SetHostnameFromDHCP) where a fault should not abort the surrounding flow.
        """
        try:
            return self.call(method, *args, **kwargs)
        except Exception as e:
            log.debug("safe_call %s swallowed: %s", method, e)
            return None

    def safe_service_call(self, service: Any, method: str, *args: Any, **kwargs: Any) -> Any | None:
        try:
            return getattr(service, method)(*args, **kwargs)
        except Exception as e:
            log.debug("safe_service_call %s.%s swallowed: %s", service, method, e)
            return None
