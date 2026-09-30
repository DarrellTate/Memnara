"""Generic Game Boy buttons. Names match PyBoy's documented set without importing PyBoy."""

from __future__ import annotations

from enum import Enum

from memnara.emulators.exceptions import InvalidButtonError


class Button(str, Enum):
    A = "a"
    B = "b"
    START = "start"
    SELECT = "select"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


VALID_BUTTONS: frozenset[str] = frozenset(b.value for b in Button)


def normalize_button(button: Button | str) -> str:
    if isinstance(button, Button):
        return button.value
    name = str(button).strip().lower()
    if name not in VALID_BUTTONS:
        raise InvalidButtonError(f"Invalid Game Boy button: {button!r}")
    return name
