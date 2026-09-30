"""Generic vision provider. No Ollama types, no title-specific RAM, no actions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from memnara.emulators.base import Framebuffer
from memnara.perception.vision.models import VisualObservation


class VisionProvider(ABC):
    @abstractmethod
    def observe(self, frame: Framebuffer) -> VisualObservation:
        """Structured visual observation. Must not execute gameplay actions."""
