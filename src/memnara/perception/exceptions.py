"""Perception-layer errors. Diagnosable; not swallowed into fake contexts."""


class PerceptionError(Exception):
    """Base perception/fusion error."""


class PerceptionFusionError(PerceptionError):
    """Fusion input was missing, malformed, or not a supported contract."""
