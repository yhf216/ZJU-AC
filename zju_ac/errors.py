"""Errors safe to display without exposing authentication data."""


class ZjuError(Exception):
    """An expected application error."""


class AuthenticationExpired(ZjuError):
    """The user must authenticate again."""


class ProtocolError(ZjuError):
    """The server response does not match the supported protocol."""


class TemporaryError(ZjuError):
    """A transient network or server failure."""


class PermissionDenied(ZjuError):
    """The authenticated user cannot access an endpoint."""


class CheckinRejected(ZjuError):
    """The server explicitly rejected a check-in submission."""


class SubmissionUncertain(ZjuError):
    """The write may have reached the server; verify instead of retrying."""
