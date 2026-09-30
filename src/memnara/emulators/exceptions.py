"""Emulator harness errors. Diagnosable; not swallowed."""


class EmulatorError(Exception):
    """Base error for the emulator harness."""


class RomNotFoundError(EmulatorError):
    """ROM path does not exist."""


class RomUnreadableError(EmulatorError):
    """ROM path exists but cannot be read as a usable dump."""


class EmulatorStartupError(EmulatorError):
    """Emulator process/library failed to start."""


class InvalidButtonError(EmulatorError):
    """Button name is not a valid Game Boy control."""


class CaptureUnavailableError(EmulatorError):
    """Framebuffer capture requested when the emulator is not ready."""


class SaveStateError(EmulatorError):
    """Save-state path or write failed."""


class LoadStateError(EmulatorError):
    """Load-state path missing or restore failed."""


class AdapterClosedError(EmulatorError):
    """Operation attempted after the adapter was closed."""


class MemoryReadError(EmulatorError):
    """Read-only memory access failed (bounds, length, or backend)."""
