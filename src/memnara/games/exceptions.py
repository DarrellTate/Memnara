"""Game-adapter exceptions. No title-specific addresses."""


class GameAdapterError(Exception):
    """Base game-adapter error."""


class UnsupportedRomError(GameAdapterError):
    """ROM identity is not compatible with this adapter's structured map."""


class StateParseError(GameAdapterError):
    """A field could not be decoded safely."""
