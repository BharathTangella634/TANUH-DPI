"""
redactor_registry.py
"""

from __future__ import annotations


class RedactorRegistry:

    _registry = {}

    @classmethod
    def register(
        cls,
        name: str,
        redactor,
    ):

        cls._registry[
            name.lower()
        ] = redactor

    @classmethod
    def get(
        cls,
        name: str,
    ):

        key = name.lower()

        if key not in cls._registry:

            raise RuntimeError(

                f"Unknown redactor: "
                f"{name}"
            )

        return cls._registry[
            key
        ]