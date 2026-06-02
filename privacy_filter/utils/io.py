"""
io.py

Filesystem utilities.
"""

from __future__ import annotations

from pathlib import Path


def ensure_parent(
    path: str | Path,
) -> Path:
    """
    Ensure parent directory exists.
    """

    path = Path(path)

    path.parent.mkdir(

        parents=True,

        exist_ok=True,
    )

    return path