"""Offline encoding and decoding of BP version 4 deck codes."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
import re
from typing import Any

from ._compression import compress, decompress
from ._obfuscation import transform
from ._serialization import deserialize, deserialize_best_effort, serialize
from .errors import InvalidCodeError, InvalidDeckError, UnsupportedVersionError
from .models import Deck, DecodeResult

FORMAT_VERSION = 4
_MAGIC = b"BP"
_HEADER = _MAGIC + bytes([FORMAT_VERSION])
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_CODE_CHARACTERS = 2 * 1024 * 1024
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}\Z", re.ASCII)


def encode(deck: Deck | Mapping[str, Any]) -> str:
    """Encode a character's deck without network access or a card database.

    Accepts a :class:`Deck` or the site's camelCase JSON object. The result is
    an unpadded Base64url string in the BP4 format. Card order is significant.
    """
    if not isinstance(deck, Deck):
        deck = Deck.from_dict(deck)
    payload = serialize(deck)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise InvalidDeckError("Serialized deck exceeds the 1 MiB limit")
    return base64.urlsafe_b64encode(transform(_HEADER + compress(payload))).decode("ascii").rstrip("=")


def decode(code: str) -> Deck:
    """Decode a BP4 deck code locally, returning normalized card fields.

    Surrounding whitespace and correctly padded Base64url are accepted. Raises
    :class:`InvalidCodeError` for malformed data, and
    :class:`UnsupportedVersionError` for an unsupported BP version.
    """
    payload = _decode_payload(code)
    try:
        return deserialize(payload)
    except InvalidDeckError as error:
        raise InvalidCodeError(str(error)) from error


def decode_best_effort(code: str) -> DecodeResult:
    """Recover supported cards/options and explicitly report any data loss.

    Base64, BP header and compression errors remain fatal. Unsupported options
    with known byte boundaries are discarded; unknown record boundaries stop
    parsing and preserve only preceding cards. This operation can be lossy.
    """
    return deserialize_best_effort(_decode_payload(code))


def _decode_payload(code: str) -> bytes:
    if not isinstance(code, str):
        raise InvalidCodeError("Deck code must be a string")
    if len(code) > MAX_CODE_CHARACTERS:
        raise InvalidCodeError("Deck code exceeds the 2 MiB character limit")
    code = code.strip()
    if not _BASE64URL.fullmatch(code):
        raise InvalidCodeError("Deck code must contain Base64url characters")
    unpadded = code.rstrip("=")
    if len(unpadded) % 4 == 1:
        raise InvalidCodeError("Invalid Base64url length")
    padding = "=" * (-len(unpadded) % 4)
    if "=" in code and code != unpadded + padding:
        raise InvalidCodeError("Invalid Base64url padding")
    try:
        wire = base64.b64decode(unpadded + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise InvalidCodeError("Invalid Base64url data") from error
    if base64.urlsafe_b64encode(wire).decode("ascii").rstrip("=") != unpadded:
        raise InvalidCodeError("Nonzero Base64url padding bits")
    message = transform(wire)
    if len(message) < 3 or message[:2] != _MAGIC:
        raise InvalidCodeError("Invalid BP deck-code header")
    if message[2] != FORMAT_VERSION:
        raise UnsupportedVersionError(f"Unsupported BP version: {message[2]} (supported: 4)")
    return decompress(message[3:], max_output=MAX_PAYLOAD_BYTES)
