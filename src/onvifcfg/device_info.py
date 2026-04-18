"""Device information and time settings.

Covers ODM's Identification + Time Settings panels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .session import DeviceSession


@dataclass(slots=True)
class DeviceInfo:
    manufacturer: str
    model: str
    firmware_version: str
    serial_number: str
    hardware_id: str


@dataclass(slots=True)
class SystemTime:
    utc_iso: str
    local_iso: str
    from_dhcp: bool
    daylight_savings: bool
    timezone: str | None


def get_device_info(sess: DeviceSession) -> DeviceInfo:
    d = sess.call("GetDeviceInformation")
    return DeviceInfo(
        manufacturer=getattr(d, "Manufacturer", "") or "",
        model=getattr(d, "Model", "") or "",
        firmware_version=getattr(d, "FirmwareVersion", "") or "",
        serial_number=getattr(d, "SerialNumber", "") or "",
        hardware_id=getattr(d, "HardwareId", "") or "",
    )


def get_system_time(sess: DeviceSession) -> SystemTime:
    t = sess.call("GetSystemDateAndTime")
    utc = _iso_from_onvif(getattr(t, "UTCDateTime", None))
    local = _iso_from_onvif(getattr(t, "LocalDateTime", None))
    tz = getattr(getattr(t, "TimeZone", None), "TZ", None) if getattr(t, "TimeZone", None) else None
    return SystemTime(
        utc_iso=utc,
        local_iso=local,
        from_dhcp=bool(getattr(t, "DateTimeType", "") == "NTP"),
        daylight_savings=bool(getattr(t, "DaylightSavings", False)),
        timezone=tz,
    )


def set_system_time(
    sess: DeviceSession,
    *,
    use_ntp: bool,
    timezone: str | None = None,
    utc_datetime: str | None = None,
) -> None:
    """Update date/time and timezone.

    Either turn on NTP sync (``use_ntp=True``) or push a fixed UTC datetime
    in ISO 8601 format. ``timezone`` is a POSIX TZ string like
    ``EET-2EEST,M3.5.0/3,M10.5.0/4``.
    """
    payload: dict[str, Any] = {
        "DateTimeType": "NTP" if use_ntp else "Manual",
        "DaylightSavings": False,
    }
    if timezone is not None:
        payload["TimeZone"] = {"TZ": timezone}
    if utc_datetime is not None and not use_ntp:
        # utc_datetime: 'YYYY-MM-DDTHH:MM:SSZ'
        y, mo, d = utc_datetime[:10].split("-")
        hh, mm, ss = utc_datetime[11:19].split(":")
        payload["UTCDateTime"] = {
            "Time": {"Hour": int(hh), "Minute": int(mm), "Second": int(ss)},
            "Date": {"Year": int(y), "Month": int(mo), "Day": int(d)},
        }
    sess.call("SetSystemDateAndTime", **payload)


def _iso_from_onvif(obj: Any) -> str:
    if obj is None:
        return ""
    d = obj.Date
    t = obj.Time
    return f"{d.Year:04d}-{d.Month:02d}-{d.Day:02d}T{t.Hour:02d}:{t.Minute:02d}:{t.Second:02d}"
