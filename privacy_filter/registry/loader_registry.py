"""
loader_registry.py

Loader registry.
"""

from __future__ import annotations

from pathlib import Path

from ..loaders.base import (
    BaseLoader,
)
    

class LoaderRegistry:

    _loaders = []

    @classmethod
    def register(
        cls,
        loader: BaseLoader,
    ):

        cls._loaders.append(
            loader
        )

    @classmethod
    def get(
        cls,
        path: str | Path,
    ) -> BaseLoader:

        for loader in cls._loaders:

            if loader.supports(
                path
            ):

                return loader

        raise RuntimeError(

            f"No loader for: "
            f"{path}"
        )

    @classmethod
    def clear(
        cls,
    ):

        cls._loaders.clear()