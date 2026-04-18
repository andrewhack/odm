"""Device maintenance — reboot, factory reset."""

from __future__ import annotations

import logging
from enum import Enum

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
