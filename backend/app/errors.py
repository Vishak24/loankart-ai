"""Domain errors. main.py maps each to one HTTP status, so services never import FastAPI."""


class NotFound(Exception):
    """404"""


class Conflict(Exception):
    """409: the request is valid but the case is not in a state that allows it."""


class Forbidden(Exception):
    """403"""


class BadInput(Exception):
    """422 for problems Pydantic cannot express (file type, size, unknown keys)."""
