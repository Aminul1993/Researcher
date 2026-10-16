"""Workflow errors whose messages are safe to show to API clients."""


class WorkflowError(Exception):
    """A workflow failure whose message is safe to show to API clients."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConfigurationError(WorkflowError):
    """Raised when required settings, such as the API key, are missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503)


class InvalidTeamError(WorkflowError, ValueError):
    """Raised when a supplied agent registry cannot be used.

    It is also a ValueError, so callers that caught the ValueError raised
    by earlier versions keep working.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)
