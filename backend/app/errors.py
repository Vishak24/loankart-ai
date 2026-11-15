"""Domain errors. main.py maps each to one HTTP status, so services never import FastAPI."""


class NotFound(Exception):
    """404"""


class Conflict(Exception):
    """409: the request is valid but the case is not in a state that allows it."""


class Unauthorized(Exception):
    """401: no valid session for this request."""


class Forbidden(Exception):
    """403: signed in, but not allowed to see this."""


class BadInput(Exception):
    """422 for problems Pydantic cannot express (file type, size, unknown keys)."""
