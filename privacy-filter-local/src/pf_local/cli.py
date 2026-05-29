"""
cli.py -- Command-line interface for pf-redact (Privacy Filter).

Usage:
    pf-redact redact  document.png -o redacted.png
    pf-redact redact  scan.pdf -o redacted.pdf
    pf-redact check                                  # Verify models load OK
    pf-redact supported-types                        # List supported formats
"""

import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import click


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not verbose:
        for noisy in ["httpcore", "httpx", "urllib3", "PIL", "pytesseract"]:
            logging.getLogger(noisy).setLevel(logging.WARNING)


@click.group()
@click.version_option(version="1.0.0", prog_name="pf-redact")
def main():
    """
    Privacy Filter -- Redact PII from documents locally.

    All processing happens on YOUR machine. No data leaves your computer.

    \b
    Quick start:
      1. Redact an image:  pf-redact redact scan.png -o redacted.png
      2. Redact a PDF:     pf-redact redact report.pdf -o redacted.pdf
      3. Check models:     pf-redact check
    """
    pass


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def check(verbose):
    """Check that ML models can be downloaded and loaded."""
    setup_logging(verbose)

    click.echo("Checking Privacy Filter models...")
    click.echo("")

    from pf_local.model import PrivacyFilter

    click.echo("  [1/2] Loading privacy-filter model (openai/privacy-filter)...")
    click.echo("         This downloads ~2.8 GB on first run.")
    try:
        pf = PrivacyFilter.instance()
        pf.load()
        click.echo(click.style("         OK", fg="green"))
    except Exception as e:
        click.echo(click.style(f"         FAILED: {e}", fg="red"))
        sys.exit(1)

    click.echo("  [2/2] Loading NER model (dslim/bert-base-NER)...")
    click.echo("         This downloads ~433 MB on first run.")
    from pf_local.ner_model import NERModel
    try:
        ner = NERModel.instance()
        ner.load()
        if ner.loaded:
            click.echo(click.style("         OK", fg="green"))
        else:
            click.echo(click.style("         WARN: NER model did not load (non-fatal)", fg="yellow"))
    except Exception as e:
        click.echo(click.style(f"         WARN: {e} (non-fatal)", fg="yellow"))

    click.echo("")
    test_text = "John Doe lives at 123 Main St. His SSN is 123-45-6789."
    click.echo(f"  Quick test: \"{test_text}\"")
    entities = pf.detect(test_text)
    click.echo(f"  Detected {len(entities)} PII entities:")
    for ent in entities:
        click.echo(f"    - {ent['entity_group']}: \"{ent['word']}\" (score={ent['score']:.2f})")

    click.echo("")
    click.echo(click.style("  All checks passed!", fg="green", bold=True))


@main.command("supported-types")
def supported_types():
    """List all supported file formats."""
    from pf_local.redactor import supported_extensions

    click.echo("Supported file formats:")
    for ext in supported_extensions():
        click.echo(f"  {ext}")


@main.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, help="Output file path for the redacted document")
@click.option("--json-report", "-j", default=None, help="Optional: save detection report as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def redact(input_path, output, json_report, verbose):
    """Redact PII from a document.

    \b
    Supported formats: .txt, .md, .log, .csv, .pdf, .docx,
                       .png, .jpg, .jpeg, .tif, .tiff, .dcm, .dicom

    \b
    Examples:
      pf-redact redact scan.png -o redacted.png
      pf-redact redact report.pdf -o redacted.pdf
      pf-redact redact notes.docx -o redacted.docx -j report.json
    """
    setup_logging(verbose)
    input_file = Path(input_path)
    output_file = Path(output)

    click.echo(click.style("Privacy Filter -- Local Redaction", fg="cyan", bold=True))
    click.echo(f"  Input:  {input_file}")
    click.echo(f"  Output: {output_file}")
    click.echo("")

    start = time.perf_counter()

    # Step 1: Resolve format handler
    click.echo("[1/4] Detecting file format...")
    from pf_local.redactor import get_handler
    try:
        handler = get_handler(input_file.name)
    except ValueError as e:
        click.echo(click.style(f"  ERROR: {e}", fg="red"))
        sys.exit(1)
    click.echo(f"       Format: {handler.name} ({input_file.suffix})")

    # Step 2: Extract text
    click.echo("[2/4] Extracting text...")
    text = handler.extract(input_file)
    click.echo(f"       Extracted {len(text)} characters")

    if not text.strip():
        click.echo(click.style("       WARNING: No text extracted. The file may be empty or unreadable.", fg="yellow"))

    # Step 3: Detect PII
    click.echo("[3/4] Detecting PII entities...")
    click.echo("       Loading models (first run downloads ~3 GB)...")
    from pf_local.model import PrivacyFilter
    pf = PrivacyFilter.instance()
    entities = pf.detect(text)
    click.echo(f"       Found {len(entities)} PII entities")

    if entities:
        counts = Counter(e["entity_group"] for e in entities)
        for label, count in sorted(counts.items()):
            click.echo(f"         {label}: {count}")

    # Step 4: Redact
    click.echo("[4/4] Redacting...")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    handler.redact(input_file, entities, output_file)

    elapsed = round(time.perf_counter() - start, 1)

    click.echo("")
    click.echo(click.style(f"  Done! {len(entities)} entities redacted in {elapsed}s", fg="green", bold=True))
    click.echo(f"  Redacted file: {output_file}")

    # Optional JSON report
    if json_report:
        report = {
            "input": str(input_file),
            "output": str(output_file),
            "format": handler.name,
            "text_length": len(text),
            "entity_count": len(entities),
            "entities": [
                {
                    "entity_group": e.get("entity_group"),
                    "score": round(float(e.get("score", 0)), 4),
                    "word": e.get("word", ""),
                    "start": e.get("start"),
                    "end": e.get("end"),
                }
                for e in entities
            ],
            "elapsed_seconds": elapsed,
        }
        with open(json_report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        click.echo(f"  JSON report:   {json_report}")


if __name__ == "__main__":
    main()
