"""Thin ONVIF session wrapper.

Builds a zeep-backed ONVIFCamera and exposes the three services the rest of
the package uses: device, media, ptz.  All methods are sync; if an async
context is added later the calls are cheap to wrap with ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from onvif import ONVIFCamera  # type: ignore[import-untyped]

from .exceptions import SessionError

log = logging.getLogger(__name__)


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
            self._cam = ONVIFCamera(host, port, creds.user, creds.password, wsdl_dir)
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
        return getattr(self._device, method)(*args, **kwargs)

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
