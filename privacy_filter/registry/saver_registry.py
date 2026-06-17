"""
saver_registry.py
"""

from __future__ import annotations

from ..schemas.core import (
    FileFormat,
)


class SaverRegistry:

    _registry = {}

    @classmethod
    def register(
        cls,
        fmt: FileFormat,
        saver,
    ):

        cls._registry[
            fmt
        ] = saver

    @classmethod
    def get(
        cls,
        fmt: FileFormat,
    ):

        if fmt not in cls._registry:

            raise RuntimeError(

                f"No saver for "
                f"{fmt}"
            )

        return cls._registry[
            fmt
        ]