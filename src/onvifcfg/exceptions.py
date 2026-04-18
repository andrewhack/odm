"""Custom exceptions for onvifcfg."""


class OnvifcfgError(Exception):
    """Base exception."""


class ValidationError(OnvifcfgError):
    """Raised when a NetworkPatch fails pre-apply validation."""


class ApplyError(OnvifcfgError):
    """Raised when applying a change step fails in a non-recoverable way."""


class SessionError(OnvifcfgError):
    """Raised when the device session cannot be established or re-established."""
