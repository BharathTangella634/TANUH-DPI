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


def run_check():
    import sys
    checks = []
    checks.append(("Python", True, f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"))
    for mod, label in [("cv2", "OpenCV"), ("numpy", "NumPy"), ("PIL", "Pillow"),
                       ("pydicom", "pydicom"), ("nibabel", "NIfTI/nibabel"), ("fitz", "PyMuPDF")]:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", getattr(m, "version", "ok"))
            checks.append((label, True, str(ver)))
        except ImportError:
            checks.append((label, False, "NOT FOUND"))
    tess_ok = False
    try:
        import shutil, subprocess
        from ..detectors.ocr_detector import _find_bundled_tesseract
        tess_cmd = _find_bundled_tesseract() or shutil.which("tesseract")
        if tess_cmd:
            ver = subprocess.check_output([tess_cmd, "--version"], stderr=subprocess.STDOUT).decode().split("\n")[0]
            checks.append(("Tesseract", True, ver))
            tess_ok = True
        else:
            checks.append(("Tesseract", False, "NOT FOUND — install tesseract-ocr"))
    except Exception:
        checks.append(("Tesseract", False, "NOT FOUND — install tesseract-ocr"))
    print("===== pf-redact system check =====")
    all_ok = True
    for name, ok, info in checks:
        status = "OK" if ok else "MISSING"
        print(f"  {name:.<20s} {status:>7s}  ({info})")
        if not ok:
            all_ok = False
    print()
    if all_ok:
        print("All checks passed. Ready to process files.")
    else:
        print("Some checks failed. Install missing dependencies before processing.")
    sys.exit(0 if all_ok else 1)


def main():

    if len(__import__("sys").argv) == 2 and __import__("sys").argv[1] == "check":
        run_check()

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