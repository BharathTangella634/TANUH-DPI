"""
cleaner_registry.py
"""

from __future__ import annotations

from ..schemas.core import (
    FileFormat,
)


class CleanerRegistry:

    _registry = {}

    @classmethod
    def register(
        cls,
        fmt: FileFormat,
        cleaner,
    ):

        cls._registry[
            fmt
        ] = cleaner

    @classmethod
    def get(
        cls,
        fmt: FileFormat,
    ):

        return cls._registry.get(
            fmt
        )