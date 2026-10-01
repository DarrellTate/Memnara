"""Continuous-runtime errors. Separate from emulator adapter errors."""

from __future__ import annotations


class RuntimeLayerError(Exception):
    """Base class for continuous-runtime failures."""


class RuntimeStartupError(RuntimeLayerError):
    """The runtime owner thread could not reach a first published snapshot."""


class RuntimeStoppedError(RuntimeLayerError):
    """The runtime owner thread is no longer accepting work."""


class RuntimeBusyError(RuntimeLayerError):
    """A gameplay command is already pending. Memnara stays closed-loop."""


class RuntimeTimeoutError(RuntimeLayerError):
    """A command or frame wait did not complete in time."""


class RuntimeShutdownError(RuntimeLayerError):
    """The owner thread would not leave, so the emulator must not be freed."""
