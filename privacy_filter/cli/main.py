"""
main.py

CLI entrypoint for MedDeID.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .. import registry as _  # noqa: F401 — bootstraps all loaders/savers/cleaners

from ..pipeline.engine import (
    MedDeIDEngine,
)

from ..utils.logging import (
    configure_logging,
)


def build_parser():

    parser = argparse.ArgumentParser(

        prog="meddeid",

        description=(
            "Universal Medical Imaging "
            "Deidentification Toolkit"
        ),
    )

    parser.add_argument(

        "input",

        help="Input file path",
    )

    parser.add_argument(

        "output",

        help="Output file path",
    )

    parser.add_argument(

        "--backend",

        default="paddle",

        choices=[
            "paddle",
            "tesseract",
        ],

        help="OCR backend",
    )

    parser.add_argument(

        "--redactor",

        default="mask",

        choices=[
            "mask",
            "crop",
            "inpaint",
        ],

        help="Redaction strategy",
    )

    parser.add_argument(

        "--json",

        dest="json_report",

        help=(
            "Optional JSON "
            "report output"
        ),
    )

    parser.add_argument(

        "--log-level",

        default="INFO",

        help="Logging level",
    )

    return parser


def main():

    parser = build_parser()

    args = parser.parse_args()

    configure_logging(
        args.log_level
    )

    logger = logging.getLogger(
        "meddeid.cli"
    )

    input_path = Path(
        args.input
    )

    output_path = Path(
        args.output
    )

    logger.info(
        "Starting MedDeID"
    )

    engine = MedDeIDEngine(

        ocr_backend=
        args.backend,

        redaction_method=
        args.redactor,
    )

    result = engine.process(

        input_path,

        output_path,
    )

    logger.info(
        "Processing completed."
    )

    print()

    print(
        "===== MEDDEID REPORT ====="
    )

    print(
        f"PHI Count: "
        f"{result['phi_count']}"
    )

    print(
        f"Overlay Count: "
        f"{result['overlay_count']}"
    )

    print(
        f"Validation Passed: "
        f"{result['validation'].passed}"
    )

    print(
        f"Risk Score: "
        f"{result['validation'].risk_score}"
    )

    if args.json_report:

        report_path = Path(
            args.json_report
        )

        payload = {

            "phi_count":
                result[
                    "phi_count"
                ],

            "overlay_count":
                result[
                    "overlay_count"
                ],

            "validation":

                {

                    "passed":

                        result[
                            "validation"
                        ].passed,

                    "risk_score":

                        result[
                            "validation"
                        ].risk_score,

                    "notes":

                        result[
                            "validation"
                        ].notes,
                },
        }

        report_path.write_text(

            json.dumps(

                payload,

                indent=2,
            )
        )

        logger.info(

            "JSON report saved → %s",

            report_path,
        )


if __name__ == "__main__":

    main()