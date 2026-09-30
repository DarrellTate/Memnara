from pathlib import Path

import pytest

from memnara.emulators.buttons import Button, normalize_button
from memnara.emulators.exceptions import InvalidButtonError


def test_normalize_enum() -> None:
    assert normalize_button(Button.A) == "a"


def test_normalize_string_case() -> None:
    assert normalize_button("Start") == "start"


def test_invalid_button() -> None:
    with pytest.raises(InvalidButtonError):
        normalize_button("turbo")
