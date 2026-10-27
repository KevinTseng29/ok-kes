"""Offline Chaos Zero Nightmare deck codes. No network or runtime dependencies."""

from .codec import FORMAT_VERSION, decode, decode_best_effort, encode
from .errors import DeckCodeError, InvalidCodeError, InvalidDeckError, UnsupportedVersionError
from .models import Card, Deck, DecodeResult, DecodeWarning

__version__ = "0.1.0a3"

__all__ = [
    "Card", "Deck", "encode", "decode", "decode_best_effort", "DecodeResult", "DecodeWarning", "FORMAT_VERSION",
    "DeckCodeError", "InvalidCodeError", "InvalidDeckError", "UnsupportedVersionError",
    "__version__",
]
