"""Device maintenance — reboot, factory reset, firmware upgrade."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .exceptions import OnvifcfgError
from .reachability import wait_for_port
from .session import DeviceSession

log = logging.getLogger(__name__)


class FactoryDefault(str, Enum):
    SOFT = "Soft"  # keep network settings
    HARD = "Hard"  # wipe everything including network


def reboot(sess: DeviceSession, *, wait_s: float = 90.0) -> bool:
    """Best-effort SystemReboot + reachability probe.

    Returns True if the device came back within ``wait_s``. Transport
    exceptions during the SOAP call are swallowed because many cameras
    apply the reboot before ACKing the response.
    """
    try:
        sess.call("SystemReboot")
    except Exception as e:
        log.info("SystemReboot raised (expected): %s", e)
    return wait_for_port(sess.host, sess.port, timeout_s=wait_s)


def factory_default(sess: DeviceSession, mode: FactoryDefault = FactoryDefault.SOFT) -> None:
    """Reset the device to factory defaults.

    SOFT keeps network settings; HARD wipes IP, DNS, hostname and all auth
    (you will lose the device if you use HARD on a remote camera).
    """
    sess.call("SetSystemFactoryDefault", FactoryDefault=mode.value)


@dataclass(slots=True)
class FirmwareUpgradeResult:
    method: str  # "http-upload" | "inline-base64"
    came_back: bool
    message: str


def firmware_upgrade(
    sess: DeviceSession,
    firmware: bytes,
    *,
    user: str | None = None,
    password: str | None = None,
    wait_s: float = 180.0,
) -> FirmwareUpgradeResult:
    """Upload firmware to the device and wait for it to come back.

    Tries the HTTP-upload flow first (``StartFirmwareUpgrade`` returns an
    upload URL we POST the binary to), then falls back to the inline
    base64 ``UpgradeSystemFirmware`` SOAP call (fix #18 from the upstream
    ODM review: zeep does not implement MTOM, so binary firmware payloads
    must be base64-inlined or routed through HTTP-upload).

    Reuses the session credentials for HTTP digest/basic auth on the
    upload URL; ``user`` / ``password`` overrides are accepted in case
    the caller stores them separately.
    """
    import urllib.error
    import urllib.request

    # --- Path 1: StartFirmwareUpgrade -> HTTP POST to UploadUri ---------
    try:
        resp = sess.call("StartFirmwareUpgrade")
    except Exception as e:
        log.info("StartFirmwareUpgrade unsupported: %s", e)
        resp = None

    upload_uri = None
    if resp is not None:
        upload_uri = (
            getattr(resp, "UploadUri", None)
            or getattr(resp, "UploadURI", None)
            or getattr(resp, "Uri", None)
        )

    if upload_uri:
        try:
            req = urllib.request.Request(
                str(upload_uri),
                data=firmware,
                method="POST",
                headers={"Content-Type": "application/octet-stream"},
            )
            opener: urllib.request.OpenerDirector | None = None
            if user is not None:
                pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                pm.add_password(None, str(upload_uri), user, password or "")
                opener = urllib.request.build_opener(
                    urllib.request.HTTPBasicAuthHandler(pm),
                    urllib.request.HTTPDigestAuthHandler(pm),
                )
            with (
                opener.open(req, timeout=120)
                if opener
                else urllib.request.urlopen(req, timeout=120)
            ):
                pass
            came_back = wait_for_port(sess.host, sess.port, timeout_s=wait_s)
            return FirmwareUpgradeResult(
                method="http-upload",
                came_back=came_back,
                message=(
                    f"firmware uploaded ({len(firmware)} bytes) via HTTP; "
                    + ("device came back" if came_back else "device did not answer within window")
                ),
            )
        except urllib.error.HTTPError as he:
            raise OnvifcfgError(f"firmware HTTP upload to {upload_uri} returned {he.code}") from he
        except Exception as e:
            log.info("HTTP upload to %s failed (%s); will try inline base64", upload_uri, e)

    # --- Path 2: UpgradeSystemFirmware with inline base64 ---------------
    try:
        sess.call("UpgradeSystemFirmware", Firmware=firmware)
    except Exception as e:
        raise OnvifcfgError(
            f"firmware upgrade failed (no upload URI and inline UpgradeSystemFirmware threw: {e})"
        ) from e
    came_back = wait_for_port(sess.host, sess.port, timeout_s=wait_s)
    return FirmwareUpgradeResult(
        method="inline-base64",
        came_back=came_back,
        message=(
            f"firmware sent inline ({len(firmware)} bytes); "
            + ("device came back" if came_back else "device did not answer within window")
        ),
    )
