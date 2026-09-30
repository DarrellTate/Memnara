"""Vision-layer errors. Diagnosable; not swallowed into fake observations."""


class VisionError(Exception):
    """Base vision error."""


class LocalOnlyEndpointError(VisionError):
    """Ollama host is not a permitted loopback address."""


class OllamaUnavailableError(VisionError):
    """Local Ollama HTTP server did not respond."""


class ModelUnavailableError(VisionError):
    """Required model is missing or is not vision-capable on the local server."""


class VisionParseError(VisionError):
    """Model response was missing, malformed, or failed schema validation."""


class VisionTimeoutError(VisionError):
    """Vision HTTP call exceeded the configured timeout."""
