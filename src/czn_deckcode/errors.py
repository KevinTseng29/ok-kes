"""Public exception types for deck validation and code parsing."""


class DeckCodeError(ValueError):
    """Base class for invalid decks or deck codes."""


class InvalidDeckError(DeckCodeError):
    """A deck or card does not match the public data model."""


class InvalidCodeError(DeckCodeError):
    """A deck code cannot be decoded."""


class UnsupportedVersionError(InvalidCodeError):
    """A deck code uses a version this SDK does not support."""
