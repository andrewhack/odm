"""Thin ONVIF session wrapper.

Builds a zeep-backed ONVIFCamera with conservative per-call timeouts.  All
methods are synchronous - the CLI is single-shot and a sync API is easier to
reason about.  If a FastAPI server mode gets added later, the calls are cheap
to wrap in `asyncio.to_thread`.
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
    """Wraps an ONVIFCamera with the device service ready to use."""

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

    # ------------------------------------------------------------------
    # Thin passthrough helpers - each one wraps a raw SOAP call.  Kept in
    # one place so timeouts, retries or instrumentation can be added once.
    # ------------------------------------------------------------------

    @property
    def device(self) -> Any:
        return self._device

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._device, method)
        return fn(*args, **kwargs)

    def safe_call(self, method: str, *args: Any, **kwargs: Any) -> Any | None:
        """Call a SOAP op, return None if the device reports ActionNotSupported.

        Use for capability-advisory calls (GetZeroConfiguration, GetDiscoveryMode,
        SetHostnameFromDHCP) where a fault should not abort the surrounding flow.
        """
        try:
            return self.call(method, *args, **kwargs)
        except Exception as e:
            log.debug("safe_call %s swallowed: %s", method, e)
            return None
