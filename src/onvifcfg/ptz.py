"""PTZ control — move, stop, presets, status.

Speeds are ONVIF-normalised to [-1.0, 1.0]. The camera's own configuration
may restrict the practical range; clamp-at-device wins and we don't
pre-clamp here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .exceptions import ValidationError
from .session import DeviceSession


@dataclass(slots=True, frozen=True)
class Vector:
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0


@dataclass(slots=True, frozen=True)
class PTZStatus:
    pan: float | None
    tilt: float | None
    zoom: float | None
    moving_pan: bool
    moving_tilt: bool
    moving_zoom: bool


@dataclass(slots=True, frozen=True)
class Preset:
    token: str
    name: str


def _check_speed(v: Vector) -> None:
    for component in ("pan", "tilt", "zoom"):
        val = getattr(v, component)
        if val < -1.0 or val > 1.0:
            raise ValidationError(f"{component} speed {val} outside [-1.0, 1.0]")


def continuous_move(
    sess: DeviceSession,
    profile_token: str,
    velocity: Vector,
    *,
    duration_s: float | None = None,
) -> None:
    """Start a continuous move; if ``duration_s`` given, auto-stop after.

    Passing a zero vector is equivalent to ``stop()``.
    """
    _check_speed(velocity)
    sess.ptz.ContinuousMove(
        ProfileToken=profile_token,
        Velocity={
            "PanTilt": {"x": velocity.pan, "y": velocity.tilt},
            "Zoom": {"x": velocity.zoom},
        },
    )
    if duration_s is not None:
        time.sleep(duration_s)
        stop(sess, profile_token)


def relative_move(
    sess: DeviceSession,
    profile_token: str,
    translation: Vector,
    speed: Vector | None = None,
) -> None:
    _check_speed(translation)
    if speed is not None:
        _check_speed(speed)
    payload: dict = {
        "ProfileToken": profile_token,
        "Translation": {
            "PanTilt": {"x": translation.pan, "y": translation.tilt},
            "Zoom": {"x": translation.zoom},
        },
    }
    if speed is not None:
        payload["Speed"] = {
            "PanTilt": {"x": speed.pan, "y": speed.tilt},
            "Zoom": {"x": speed.zoom},
        }
    sess.ptz.RelativeMove(**payload)


def absolute_move(
    sess: DeviceSession,
    profile_token: str,
    position: Vector,
    speed: Vector | None = None,
) -> None:
    _check_speed(position)
    payload: dict = {
        "ProfileToken": profile_token,
        "Position": {
            "PanTilt": {"x": position.pan, "y": position.tilt},
            "Zoom": {"x": position.zoom},
        },
    }
    if speed is not None:
        payload["Speed"] = {
            "PanTilt": {"x": speed.pan, "y": speed.tilt},
            "Zoom": {"x": speed.zoom},
        }
    sess.ptz.AbsoluteMove(**payload)


def stop(sess: DeviceSession, profile_token: str) -> None:
    sess.ptz.Stop(ProfileToken=profile_token, PanTilt=True, Zoom=True)


def get_status(sess: DeviceSession, profile_token: str) -> PTZStatus:
    s = sess.ptz.GetStatus(ProfileToken=profile_token)
    pos = getattr(s, "Position", None)
    mov = getattr(s, "MoveStatus", None)
    pan = tilt = zoom = None
    if pos is not None:
        pt = getattr(pos, "PanTilt", None)
        zm = getattr(pos, "Zoom", None)
        if pt is not None:
            pan = float(pt.x)
            tilt = float(pt.y)
        if zm is not None:
            zoom = float(zm.x)
    moving_pt = str(getattr(mov, "PanTilt", "IDLE") if mov else "IDLE")
    moving_zm = str(getattr(mov, "Zoom", "IDLE") if mov else "IDLE")
    return PTZStatus(
        pan=pan,
        tilt=tilt,
        zoom=zoom,
        moving_pan=moving_pt == "MOVING",
        moving_tilt=moving_pt == "MOVING",
        moving_zoom=moving_zm == "MOVING",
    )


def get_presets(sess: DeviceSession, profile_token: str) -> list[Preset]:
    raw = sess.ptz.GetPresets(ProfileToken=profile_token) or []
    out: list[Preset] = []
    for p in raw:
        out.append(Preset(token=p.token, name=getattr(p, "Name", "") or p.token))
    return out


def goto_preset(
    sess: DeviceSession, profile_token: str, preset_token: str, speed: Vector | None = None
) -> None:
    payload: dict = {"ProfileToken": profile_token, "PresetToken": preset_token}
    if speed is not None:
        _check_speed(speed)
        payload["Speed"] = {
            "PanTilt": {"x": speed.pan, "y": speed.tilt},
            "Zoom": {"x": speed.zoom},
        }
    sess.ptz.GotoPreset(**payload)


def set_preset(
    sess: DeviceSession,
    profile_token: str,
    *,
    name: str | None = None,
    preset_token: str | None = None,
) -> str:
    """Create or overwrite a preset at the current position. Returns the token."""
    payload: dict = {"ProfileToken": profile_token}
    if name:
        payload["PresetName"] = name
    if preset_token:
        payload["PresetToken"] = preset_token
    resp = sess.ptz.SetPreset(**payload)
    return str(resp) if isinstance(resp, str) else str(getattr(resp, "PresetToken", ""))


def remove_preset(sess: DeviceSession, profile_token: str, preset_token: str) -> None:
    sess.ptz.RemovePreset(ProfileToken=profile_token, PresetToken=preset_token)


def goto_home(sess: DeviceSession, profile_token: str) -> None:
    sess.ptz.GotoHomePosition(ProfileToken=profile_token)


def set_home(sess: DeviceSession, profile_token: str) -> None:
    sess.ptz.SetHomePosition(ProfileToken=profile_token)
