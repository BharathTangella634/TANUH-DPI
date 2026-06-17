"""
base.py

Abstract saver interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.core import (
    MedicalArtifact,
)


class BaseSaver(ABC):

    @abstractmethod
    def save(
        self,
        artifact: MedicalArtifact,
        output_path: str | Path,
    ) -> None:

        raise NotImplementedError

    def __call__(
        self,
        artifact: MedicalArtifact,
        output_path: str | Path,
    ):

        self.save(
            artifact,
            output_path,
        )