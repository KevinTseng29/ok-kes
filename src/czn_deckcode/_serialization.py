"""The version 4 binary payload, independent of compression and obfuscation.

Integers use unsigned LEB128. Strings contain a LEB128 byte length followed by
UTF-8 bytes. Card flags select the optional fields in their wire order.
"""

from __future__ import annotations

import re

from .errors import InvalidCodeError, InvalidDeckError
from .models import Card, Deck, DecodeResult, DecodeWarning


_REMOVED = 0x01
_EPIPHANY = 0x02
_TALENTS = 0x04
_DIVINE = 0x40
_KNOWN_FLAGS = _REMOVED | _EPIPHANY | _TALENTS | _DIVINE
_REPLICATION = "TALENT_REPLICATION"
_UINT32_MAX = (1 << 32) - 1
_CARD_ID = re.compile(r"(?:c_[0-9]+_[a-z0-9_]+|(?:card|p)_[a-z0-9_]+)\Z")
_EPIPHANY_ID = re.compile(r"(?:c[0-9]+|c_[0-9]+_[0-9]+)\Z")
_DIVINE_ID = re.compile(r"(?:add|assault)_r_spark_([a-z]+)_[0-9]+(?:_[0-9]+)*\Z")
_VARIANT_RSP = re.compile(r"(.+)_rsp([0-9]+)\Z")
_SPARK_RSP = re.compile(r"rsp([0-9]+)_(.+)\Z")


def _write_uint(value: int, output: bytearray) -> None:
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)


def _write_string(value: str, output: bytearray) -> None:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidDeckError("Identifiers must contain valid Unicode") from error
    if len(encoded) > 255:
        raise InvalidDeckError("Identifiers must be at most 255 UTF-8 bytes")
    _write_uint(len(encoded), output)
    output.extend(encoded)


def _validate_card_id(value: str, field: str) -> None:
    if not _CARD_ID.fullmatch(value):
        raise InvalidDeckError(f"Invalid {field}: {value!r}")


def _card_fields(card: Card) -> tuple[str, int | None, str | None]:
    """Apply the site's lossy conversion from builder state to wire fields."""
    effective_id = card.card_id
    category: int | None = None
    spark_id: str | None = None
    variant = card.variant_card_id
    if variant:
        if variant.endswith(("_pot", "_lbk")):
            _validate_card_id(variant, "variantCardId")
            effective_id = variant
        else:
            match = _VARIANT_RSP.fullmatch(variant)
            if match:
                _validate_card_id(variant, "variantCardId")
                category = 1
                spark_id = f"rsp{match[2]}_{match[1]}"
    if spark_id is None and card.epiphany_id is not None:
        if not _EPIPHANY_ID.fullmatch(card.epiphany_id):
            raise InvalidDeckError(f"Invalid epiphanyId: {card.epiphany_id!r}")
        category = 3
        spark_id = card.epiphany_id
    if card.divine_id:
        if spark_id is None:
            raise InvalidDeckError("divineId requires an epiphany or an rsp variant")
        if not _DIVINE_ID.fullmatch(card.divine_id):
            raise InvalidDeckError(f"Invalid divineId: {card.divine_id!r}")
    return effective_id, category, spark_id


def serialize(deck: Deck) -> bytes:
    """Serialize a validated builder deck into a version 4 binary payload.

    The site stores ``_pot``/``_lbk`` variants as card IDs and ignores ``god``.
    An ``_rspN`` variant takes precedence over an ordinary epiphany. Character
    IDs must fit uint32; larger values would be silently truncated by the site.
    """
    if not isinstance(deck, Deck):
        raise InvalidDeckError("Expected a Deck")
    if not re.fullmatch(r"[0-9]+", deck.char_id):
        raise InvalidDeckError("charId must be a decimal uint32 string")
    # Check the digit count before int() to reject oversized untrusted strings.
    significant_id = deck.char_id.lstrip("0") or "0"
    if len(significant_id) > 10 or int(significant_id) > _UINT32_MAX:
        raise InvalidDeckError("charId must be between 0 and 4294967295")
    if deck.char_id != significant_id:
        raise InvalidDeckError("charId must not contain leading zeros")
    output = bytearray()
    _write_uint(int(significant_id), output)
    _write_uint(len(deck.cards), output)
    for index, card in enumerate(deck.cards):
        try:
            _validate_card_id(card.card_id, "cardId")
            # Generic card_/p_ cards are not owned by a particular character.
            if card.card_id.startswith("c_"):
                owner = card.card_id.split("_", 2)[1]
                if owner != deck.char_id:
                    raise InvalidDeckError("cardId belongs to a different character")
            card_id, category, spark_id = _card_fields(card)
            flags = (
                (_REMOVED if card.removed else 0)
                | (_EPIPHANY if spark_id is not None else 0)
                | (_TALENTS if card.duplicate else 0)
                | (_DIVINE if card.divine_id is not None else 0)
            )
            output.append(flags)
            _write_string(card_id, output)
            if spark_id is not None:
                assert category is not None
                output.append(category)
                _write_string(spark_id, output)
            if card.divine_id is not None:
                _write_string(card.divine_id, output)
            if card.duplicate:
                _write_uint(1, output)
                _write_string(_REPLICATION, output)
        except InvalidDeckError as error:
            raise InvalidDeckError(f"cards[{index}]: {error}") from error
    return bytes(output)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def byte(self) -> int:
        if self.offset == len(self.data):
            raise InvalidCodeError("Truncated binary payload")
        result = self.data[self.offset]
        self.offset += 1
        return result

    def uint(self) -> int:
        result = 0
        for index in range(5):
            byte = self.byte()
            if index == 4 and byte > 15:
                raise InvalidCodeError("Integer exceeds uint32")
            result |= (byte & 127) << (index * 7)
            if byte < 128:
                if index and byte == 0:
                    raise InvalidCodeError("Non-canonical LEB128 integer")
                return result
        raise InvalidCodeError("Invalid LEB128 integer")

    def string(self) -> str:
        length = self.uint()
        if not 1 <= length <= 255:
            raise InvalidCodeError("Identifier length must be between 1 and 255 bytes")
        end = self.offset + length
        if end > len(self.data):
            raise InvalidCodeError("Truncated identifier")
        value = self.data[self.offset:end]
        self.offset = end
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidCodeError("Invalid UTF-8 identifier") from error


def deserialize(data: bytes) -> Deck:
    """Decode a version 4 payload, refusing fields the SDK cannot preserve.

    This parses IDs without consulting a live card database, so unknown future
    card IDs and unavailable unique epiphanies can still be inspected offline.
    """
    if not isinstance(data, bytes):
        raise InvalidCodeError("Binary payload must be bytes")
    reader = _Reader(data)
    char_id = str(reader.uint())
    card_count = reader.uint()
    # Every card needs at least flags, a length, and one ID byte.
    if card_count > (len(data) - reader.offset) // 3:
        raise InvalidCodeError("Card count exceeds the binary payload")
    cards: list[Card] = []
    for index in range(card_count):
        flags = reader.byte()
        if flags & ~_KNOWN_FLAGS:
            raise InvalidCodeError(f"cards[{index}]: Unsupported flags 0x{flags:02x}")
        card_id = reader.string()
        variant_id = None
        epiphany_id = None
        divine_id = None
        god = None
        if flags & _EPIPHANY:
            category = reader.byte()
            spark_id = reader.string()
            if category == 1:
                match = _SPARK_RSP.fullmatch(spark_id)
                if not match:
                    raise InvalidCodeError("Malformed unique epiphany ID")
                variant_id = f"{match[2]}_rsp{match[1]}"
            elif category == 3:
                epiphany_id = spark_id
            else:
                raise InvalidCodeError(f"Unsupported epiphany category {category}")
        if flags & _DIVINE:
            if not flags & _EPIPHANY:
                raise InvalidCodeError("Divine field requires an epiphany")
            divine_id = reader.string()
            match = _DIVINE_ID.fullmatch(divine_id)
            if match:
                god = match[1].upper()
        duplicate = False
        if flags & _TALENTS:
            talent_count = reader.uint()
            if talent_count != 1 or reader.string() != _REPLICATION:
                raise InvalidCodeError("Unsupported card talent list")
            duplicate = True
        try:
            cards.append(Card(
                card_id=card_id,
                removed=bool(flags & _REMOVED),
                duplicate=duplicate,
                variant_card_id=variant_id,
                epiphany_id=epiphany_id,
                divine_id=divine_id,
                god=god,
            ))
        except InvalidDeckError as error:
            raise InvalidCodeError(f"cards[{index}]: {error}") from error
    if reader.offset != len(data):
        raise InvalidCodeError("Trailing bytes in binary payload")
    return Deck(char_id=char_id, cards=tuple(cards))


def deserialize_best_effort(data: bytes) -> DecodeResult:
    """Decode as many records as possible, reporting lossy fields.

    This parser is deliberately separate from :func:`deserialize`: the strict
    parser must continue rejecting data it cannot represent. Best effort mode
    only drops fields after their complete wire representation has been read;
    when a record boundary cannot be established it stops and returns the
    successfully decoded prefix.
    """
    if not isinstance(data, bytes):
        raise InvalidCodeError("Binary payload must be bytes")
    reader = _Reader(data)
    char_id = str(reader.uint())
    total_cards = reader.uint()
    cards: list[Card] = []
    warnings: list[DecodeWarning] = []
    complete = True

    def read_string(index: int, card_id: str | None, field: str) -> str | None:
        # Length prefixes give us an exact boundary even if the identifier's
        # contents cannot be represented. Consume it, then drop just that field.
        length = reader.uint()
        end = reader.offset + length
        if end > len(data):
            raise InvalidCodeError("Truncated identifier")
        raw = data[reader.offset:end]
        reader.offset = end
        try:
            if not 1 <= length <= 255:
                raise InvalidCodeError("Identifier length must be between 1 and 255 bytes")
            value = raw.decode("utf-8")
            if not value.strip():
                raise InvalidCodeError("Identifier must not be blank")
            return value
        except (UnicodeDecodeError, InvalidCodeError) as error:
            warnings.append(DecodeWarning(index, card_id, field,
                f"Invalid identifier was discarded: {error}",
                "skipped_card" if field == "cardId" else "dropped_option"))
            return None

    for index in range(total_cards):
        card_id: str | None = None
        try:
            flags = reader.byte()
            if flags & ~_KNOWN_FLAGS:
                warnings.append(DecodeWarning(index, None, "flags",
                    f"Unsupported flags 0x{flags:02x}; remaining records were not read",
                    "stopped"))
                complete = False
                break
            card_id = read_string(index, None, "cardId")
            variant_id = None
            epiphany_id = None
            divine_id = None
            god = None
            if flags & _EPIPHANY:
                category = reader.byte()
                spark_id = read_string(index, card_id, "epiphany")
                if spark_id is None:
                    pass
                elif category == 1:
                    match = _SPARK_RSP.fullmatch(spark_id)
                    if match and match[2] == card_id and _CARD_ID.fullmatch(f"{match[2]}_rsp{match[1]}"):
                        variant_id = f"{match[2]}_rsp{match[1]}"
                    else:
                        warnings.append(DecodeWarning(index, card_id, "epiphany",
                            "Malformed unique epiphany was discarded", "dropped_option"))
                elif category == 3:
                    if _EPIPHANY_ID.fullmatch(spark_id):
                        epiphany_id = spark_id
                    else:
                        warnings.append(DecodeWarning(index, card_id, "epiphany",
                            "Malformed ordinary epiphany was discarded", "dropped_option"))
                else:
                    warnings.append(DecodeWarning(index, card_id, "epiphany",
                        f"Unsupported epiphany category {category} was discarded",
                        "dropped_option"))
            if flags & _DIVINE:
                divine_id = read_string(index, card_id, "divine")
                if divine_id is None:
                    pass
                elif variant_id is None and epiphany_id is None:
                    warnings.append(DecodeWarning(index, card_id, "divine",
                        "Divine option without a supported epiphany was discarded", "dropped_option"))
                    divine_id = None
                else:
                    match = _DIVINE_ID.fullmatch(divine_id)
                    if match:
                        god = match[1].upper()
                    else:
                        warnings.append(DecodeWarning(index, card_id, "divine",
                            "Malformed divine option was discarded", "dropped_option"))
                        divine_id = None
            duplicate = False
            if flags & _TALENTS:
                talent_count = reader.uint()
                talents = [read_string(index, card_id, "talents") for _ in range(talent_count)]
                if talents == [_REPLICATION]:
                    duplicate = True
                else:
                    warnings.append(DecodeWarning(index, card_id, "talents",
                        f"Unsupported card talent list {talents!r} was normalized; only replication was retained if present",
                        "dropped_option"))
                    # Keep the known replication meaning if it is present with
                    # an additional unknown option.
                    duplicate = _REPLICATION in talents
            if card_id is None:
                continue
            _validate_card_id(card_id, "cardId")
            if card_id.startswith("c_") and card_id.split("_", 2)[1] != char_id:
                raise InvalidDeckError("cardId belongs to a different character")
            cards.append(Card(
                card_id=card_id,
                removed=bool(flags & _REMOVED),
                duplicate=duplicate,
                variant_card_id=variant_id,
                epiphany_id=epiphany_id,
                divine_id=divine_id,
                god=god,
            ))
        except InvalidCodeError as error:
            warnings.append(DecodeWarning(index, card_id, "record",
                f"Could not read this card completely: {error}", "stopped"))
            complete = False
            break
        except InvalidDeckError as error:
            warnings.append(DecodeWarning(index, card_id, "record", str(error), "skipped_card"))
            # Semantic validation failed after all fields were consumed, so the
            # following record remains aligned and can still be attempted.
            continue

    if reader.offset != len(data):
        complete = False
        if not warnings or warnings[-1].action != "stopped":
            warnings.append(DecodeWarning(None, None, "payload",
                "Trailing or unread payload bytes were discarded", "stopped"))
    return DecodeResult(Deck(char_id=char_id, cards=tuple(cards)), tuple(warnings), total_cards, complete)
