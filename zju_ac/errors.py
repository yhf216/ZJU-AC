"""Errors safe to display without exposing authentication data."""


class ZjuError(Exception):
    """An expected application error."""


class AuthenticationExpired(ZjuError):
    """The user must authenticate again."""


class ProtocolError(ZjuError):
    """The server response does not match the supported protocol."""


class TemporaryError(ZjuError):
    """A transient network or server failure."""
