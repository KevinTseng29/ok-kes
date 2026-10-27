"""Validated deck models with the site's camelCase JSON representation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import InvalidDeckError


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidDeckError(f"{field} must be a non-empty string")
    return value


def _optional_identifier(value: object, field: str) -> str | None:
    # Responses use both null and "" for an unset optional identifier.
    if value is None or value == "":
        return None
    return _identifier(value, field)


def _object(
    value: object, *, name: str, allowed: set[str], required: set[str]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidDeckError(f"{name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        fields = ", ".join(sorted(repr(key) for key in unknown))
        raise InvalidDeckError(f"Unknown {name} field(s): {fields}")
    missing = required - set(value)
    if missing:
        raise InvalidDeckError(f"Missing {name} field(s): {', '.join(sorted(missing))}")
    return value


@dataclass(frozen=True, slots=True)
class Card:
    """A card and its state; identifiers are opaque strings."""

    card_id: str
    removed: bool = False
    duplicate: bool = False
    variant_card_id: str | None = None
    epiphany_id: str | None = None
    divine_id: str | None = None
    god: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.card_id, "cardId")
        for field in ("removed", "duplicate"):
            if type(getattr(self, field)) is not bool:
                raise InvalidDeckError(f"{field} must be a boolean")
        for attribute, field in (
            ("variant_card_id", "variantCardId"),
            ("epiphany_id", "epiphanyId"),
            ("divine_id", "divineId"),
        ):
            object.__setattr__(
                self, attribute, _optional_identifier(getattr(self, attribute), field)
            )
        if self.god is not None and not isinstance(self.god, str):
            raise InvalidDeckError("god must be a string or null")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Card:
        data = _object(
            value,
            name="card",
            allowed={
                "cardId", "removed", "duplicate", "variantCardId",
                "epiphanyId", "divineId", "god",
            },
            required={"cardId"},
        )
        return cls(
            card_id=data["cardId"],
            removed=data.get("removed", False),
            duplicate=data.get("duplicate", False),
            variant_card_id=data.get("variantCardId"),
            epiphany_id=data.get("epiphanyId"),
            divine_id=data.get("divineId"),
            god=data.get("god"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready fields, omitting optional values that are unset."""
        result: dict[str, Any] = {
            "cardId": self.card_id,
            "removed": self.removed,
            "duplicate": self.duplicate,
        }
        for field, value in (
            ("variantCardId", self.variant_card_id),
            ("epiphanyId", self.epiphany_id),
            ("divineId", self.divine_id),
            ("god", self.god),
        ):
            if value is not None:
                result[field] = value
        return result


@dataclass(frozen=True, slots=True)
class Deck:
    """A character's cards, in caller-supplied order."""

    char_id: str
    cards: tuple[Card, ...]

    def __post_init__(self) -> None:
        _identifier(self.char_id, "charId")
        if not isinstance(self.cards, (list, tuple)):
            raise InvalidDeckError("cards must be a list or tuple of Card objects")
        for index, card in enumerate(self.cards):
            if not isinstance(card, Card):
                raise InvalidDeckError(f"cards[{index}] must be a Card")
        object.__setattr__(self, "cards", tuple(self.cards))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Deck:
        data = _object(
            value, name="deck", allowed={"charId", "cards"}, required={"charId", "cards"}
        )
        if not isinstance(data["cards"], (list, tuple)):
            raise InvalidDeckError("cards must be an array of card objects")
        cards = []
        for index, value in enumerate(data["cards"]):
            try:
                cards.append(Card.from_dict(value))
            except InvalidDeckError as error:
                raise InvalidDeckError(f"cards[{index}]: {error}") from error
        return cls(char_id=data["charId"], cards=tuple(cards))

    def to_dict(self) -> dict[str, Any]:
        return {"charId": self.char_id, "cards": [card.to_dict() for card in self.cards]}


@dataclass(frozen=True, slots=True)
class DecodeWarning:
    """Information discarded by a best-effort decode."""

    card_index: int | None
    card_id: str | None
    field: str
    message: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return {"card_index": self.card_index, "card_id": self.card_id,
                "field": self.field, "message": self.message, "action": self.action}


@dataclass(frozen=True, slots=True)
class DecodeResult:
    """Decoded deck plus non-fatal data-loss warnings."""

    deck: Deck
    warnings: tuple[DecodeWarning, ...] = ()
    total_cards: int = 0
    complete: bool = True

    @property
    def skipped_cards(self) -> int:
        return self.total_cards - len(self.deck.cards)

    def to_dict(self) -> dict[str, Any]:
        return {"deck": self.deck.to_dict(), "warnings": [w.to_dict() for w in self.warnings],
                "total_cards": self.total_cards, "skipped_cards": self.skipped_cards,
                "complete": self.complete}
