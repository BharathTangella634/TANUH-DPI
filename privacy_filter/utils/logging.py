"""
logging.py

Logging helpers.
"""

from __future__ import annotations

import logging


def configure_logging(
    level: str = "INFO",
):
    """
    Configure package logger.
    """

    logging.basicConfig(

        level=getattr(
            logging,

            level.upper(),
        ),

        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )