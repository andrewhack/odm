"""User management — list / add / delete / change password."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import ValidationError
from .session import DeviceSession


class UserLevel(str, Enum):
    ADMIN = "Administrator"
    OPERATOR = "Operator"
    USER = "User"
    ANON = "Anonymous"
    EXT = "Extended"


@dataclass(slots=True, frozen=True)
class User:
    name: str
    level: UserLevel


def get_users(sess: DeviceSession) -> list[User]:
    raw = sess.call("GetUsers") or []
    out: list[User] = []
    for u in raw:
        level_str = str(getattr(u, "UserLevel", UserLevel.USER.value))
        try:
            level = UserLevel(level_str)
        except ValueError:
            level = UserLevel.USER
        out.append(User(name=u.Username, level=level))
    return out


def create_user(
    sess: DeviceSession, name: str, password: str, level: UserLevel = UserLevel.USER
) -> None:
    if not name:
        raise ValidationError("username required")
    if not password:
        raise ValidationError("password required")
    sess.call(
        "CreateUsers",
        User=[{"Username": name, "Password": password, "UserLevel": level.value}],
    )


def delete_user(sess: DeviceSession, name: str) -> None:
    """Delete a user by name.

    Refuses to delete the last administrator - if that happens on a remote
    camera you will be locked out.
    """
    users = get_users(sess)
    admins_left = [u for u in users if u.level == UserLevel.ADMIN and u.name != name]
    target = next((u for u in users if u.name == name), None)
    if target is None:
        raise ValidationError(f"user {name!r} not found")
    if target.level == UserLevel.ADMIN and not admins_left:
        raise ValidationError("refusing to delete the last administrator")
    sess.call("DeleteUsers", Username=[name])


def set_user_password(sess: DeviceSession, name: str, password: str) -> None:
    if not password:
        raise ValidationError("password required")
    sess.call("SetUser", User=[{"Username": name, "Password": password}])
