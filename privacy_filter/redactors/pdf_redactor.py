"""
pdf_redactor.py

Native-text PDF de-identification using true PyMuPDF redaction.

Why a dedicated PDF path (separate from the image pipeline)
-----------------------------------------------------------
DICOM / fundus / scan redaction works on PIXELS in modality-specific regions.
Documents are different: PHI is TEXT scattered anywhere (header banners repeated
on every page, body, signatures, footers). Rasterising a PDF and masking corner
strips would both miss PHI and destroy clinical text.

This redactor instead:
  1. Reads the PDF's native text WITH coordinates (word level).
  2. Runs the content-based Safe Harbor detector on each line.
  3. Adds true redaction annotations over the PHI word rectangles and applies
     them — PyMuPDF removes the underlying glyphs (not just draws a box), so the
     text cannot be recovered (anonymisation, not cosmetic masking).
  4. Removes QR codes and barcodes (they encode patient/visit identifiers).
  5. Scrubs PDF document metadata (author/title/creator/producer/dates).

Clinical content — test results, reference ranges, findings, measurements — is
preserved because the detector only matches identifier patterns, never plain
numbers near units or ranges.

If a page has no extractable text (scanned PDF), it falls back to Tesseract OCR
via PyMuPDF's OCR text page when available.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz

from ..detectors.safe_harbor_detector import SafeHarborDetector

logger = logging.getLogger("privacy_filter.pdf_redactor")


def _px_bbox(rect, page_index: int) -> dict:
    """Convert a PyMuPDF point-rect to a preview-pixel bbox dict for the UI."""
    return {
        "x1": float(rect.x0) * _PT_TO_PX, "y1": float(rect.y0) * _PT_TO_PX,
        "x2": float(rect.x1) * _PT_TO_PX, "y2": float(rect.y1) * _PT_TO_PX,
        "page": page_index,
    }

# Minimum native words on a page before we attempt OCR fallback.
_MIN_WORDS_FOR_NATIVE = 5

# Reported entity bounding boxes are emitted in the SAME pixel space the editor
# preview uses (the API renders PDF pages at this DPI). PyMuPDF page coords are
# in points (72/inch); multiply by this ratio so the UI overlay/edit boxes line
# up with the rendered preview image. Must match _PAGE_RENDER_DPI in app/main.py.
_PREVIEW_DPI = 150
_PT_TO_PX = _PREVIEW_DPI / 72.0

# QR-code image heuristic: near-square and not large.
_QR_AR_LO, _QR_AR_HI = 0.80, 1.25
_QR_MAX_SIDE = 160.0  # PDF points

# Barcode image heuristic: clearly wide and short.
_BARCODE_MIN_AR = 2.5
_BARCODE_MAX_H = 70.0  # PDF points — distinguishes barcodes from wide banners

# Labels whose detected text is a discrete identifier worth searching for
# everywhere it repeats (names, codes, IDs). Dates/times/ages repeat too but
# are already caught per-line by the pattern detectors on every page.
_GLOBAL_LABELS = {
    "PERSON_NAME", "IDENTIFIER", "LABELED_PHI", "BARCODE", "AADHAAR",
    "PAN", "SSN", "EMAIL",
}

# Stop-words never worth global searching (would over-match clinical text).
_TOKEN_STOPWORDS = {
    "dr", "mr", "mrs", "ms", "the", "of", "and", "unit", "male", "female",
    "general", "consultant", "professor", "resident", "by", "no", "id",
}


class PDFRedactor:
    """De-identify a PDF in place (input file → output file)."""

    def __init__(self) -> None:
        self.detector = SafeHarborDetector()

    # ------------------------------------------------------------------

    def redact(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """Redact ``input_path`` → ``output_path``.

        Returns (entities, counts) for the audit report.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(input_path))
        entities: List[Dict[str, Any]] = []

        # Collect distinct PHI token strings as we go, for a global second pass
        # that catches the same identifier wherever it repeats (e.g. a staff
        # code or patient name reprinted on every page banner).
        global_tokens: set[str] = set()

        for page_index in range(len(doc)):
            page = doc[page_index]
            entities.extend(self._redact_page(page, page_index, global_tokens))

        # ── Global pass: redact every occurrence of each known PHI token ───────
        # Splitting on whitespace lets search_for match individual identifiers
        # (codes, name parts) anywhere they reappear, regardless of position.
        search_tokens = self._expand_tokens(global_tokens)
        for page_index in range(len(doc)):
            page = doc[page_index]
            hit = False
            for tok in search_tokens:
                for rect in page.search_for(tok, quads=False):
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    hit = True
                    entities.append({
                        "entity_group": "REPEATED_PHI",
                        "score": 1.0,
                        "word": tok,
                        "bbox": _px_bbox(rect, page_index),
                    })
            if hit:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # Scrub document-level metadata (author, title, creator, producer, dates).
        try:
            doc.set_metadata({})
            # Remove XMP metadata too.
            doc.del_xml_metadata()
        except Exception as exc:
            logger.warning("PDF metadata scrub failed: %s", exc)

        # Save deflated + garbage-collected so removed content is truly gone.
        doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        doc.close()

        counts: Dict[str, int] = {}
        for e in entities:
            counts[e["entity_group"]] = counts.get(e["entity_group"], 0) + 1

        logger.info(
            "PDF redacted: %d entities across %d pages → %s",
            len(entities), len(entities and {e['bbox']['page'] for e in entities} or {}),
            output_path.name,
        )
        return entities, counts

    # ------------------------------------------------------------------

    def _redact_page(
        self,
        page: "fitz.Page",
        page_index: int,
        global_tokens: set | None = None,
    ) -> List[Dict[str, Any]]:
        """Detect + redact PHI on a single page; return entity dicts."""
        entities: List[Dict[str, Any]] = []

        words = page.get_text("words")  # [x0,y0,x1,y1, word, block, line, wordno]

        # Scanned page fallback → OCR text page (needs system tesseract).
        if len(words) < _MIN_WORDS_FOR_NATIVE:
            words = self._ocr_words(page)

        # Group words into visual lines by (block, line).
        lines: Dict[tuple, list] = {}
        for w in words:
            key = (w[5], w[6])
            lines.setdefault(key, []).append(w)

        redact_rects: List[tuple] = []  # (rect, label, text)

        for key, line_words in lines.items():
            # Order left→right and build the line string with char offsets.
            line_words.sort(key=lambda w: w[0])
            text = ""
            offsets = []  # (char_start, char_end, rect)
            for w in line_words:
                token = w[4]
                start = len(text)
                text += token
                offsets.append((start, len(text), fitz.Rect(w[0], w[1], w[2], w[3])))
                text += " "

            for span in self.detector.detect_spans(text):
                # Union the rects of every word overlapping this PHI span.
                rect = None
                for cs, ce, r in offsets:
                    if not (ce <= span.start or cs >= span.end):
                        rect = r if rect is None else (rect | r)
                if rect is not None:
                    redact_rects.append((rect, span.label, span.text))

        # Apply text redactions (true removal + black fill).
        for rect, label, text in redact_rects:
            page.add_redact_annot(rect, fill=(0, 0, 0))
            # Remember identifier-like tokens for the global repeat pass.
            if global_tokens is not None and text and label in _GLOBAL_LABELS:
                global_tokens.add(text)
            entities.append({
                "entity_group": label,
                "score": 1.0,
                "word": text or None,
                "bbox": _px_bbox(rect, page_index),
            })

        # Redact QR codes + barcodes (encode patient/visit identifiers).
        for rect, kind in self._identifier_images(page):
            page.add_redact_annot(rect, fill=(0, 0, 0))
            entities.append({
                "entity_group": kind,
                "score": 1.0,
                "word": None,
                "bbox": _px_bbox(rect, page_index),
            })

        if redact_rects or any(e["entity_group"] in ("QR_CODE", "BARCODE") for e in entities):
            # images=PDF_REDACT_IMAGE_NONE keeps unrelated images (logos, figures);
            # the QR/barcode rects are removed because their annots cover them and
            # we request pixel removal only where annots sit.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

        return entities

    # ------------------------------------------------------------------

    def _identifier_images(self, page: "fitz.Page") -> List[tuple]:
        """Return [(rect, kind)] for QR-code and barcode images on the page."""
        out: List[tuple] = []
        try:
            for img in page.get_images(full=True):
                xref = img[0]
                for rect in page.get_image_rects(xref):
                    w, h = rect.width, rect.height
                    if h <= 0:
                        continue
                    ar = w / h
                    if _QR_AR_LO <= ar <= _QR_AR_HI and max(w, h) <= _QR_MAX_SIDE:
                        out.append((rect, "QR_CODE"))
                    elif ar >= _BARCODE_MIN_AR and h <= _BARCODE_MAX_H:
                        out.append((rect, "BARCODE"))
        except Exception as exc:
            logger.warning("QR/barcode scan failed: %s", exc)
        return out

    # ------------------------------------------------------------------

    def _expand_tokens(self, tokens: set) -> List[str]:
        """Split collected PHI strings into discrete search tokens.

        E.g. "Mr RAJA SHETTY" → {"RAJA", "SHETTY"}; "59460 18-03-26" → {"59460"}.
        Tokens shorter than 4 chars or in the stop-word list are dropped so the
        global search never matches common clinical words.
        """
        out: set[str] = set()
        for phrase in tokens:
            for raw in phrase.replace("/", " ").replace(",", " ").split():
                t = raw.strip(".:-()[]*")
                if len(t) < 4 or t.lower() in _TOKEN_STOPWORDS:
                    continue
                # Only search for identifier-like tokens: those containing a
                # digit (codes/IDs) or that are capitalised/UPPER name parts.
                # All-lowercase words are clinical prose (e.g. "urine") and must
                # never be globally redacted.
                has_digit = any(c.isdigit() for c in t)
                is_namecase = t[0].isupper()
                if has_digit or is_namecase:
                    out.add(t)
        # Longer tokens first so multi-word identifiers redact before fragments.
        return sorted(out, key=len, reverse=True)

    def _ocr_words(self, page: "fitz.Page") -> list:
        """OCR fallback for scanned pages (best-effort; needs tesseract)."""
        try:
            tp = page.get_textpage_ocr(flags=0, full=True)
            return page.get_text("words", textpage=tp)
        except Exception as exc:
            logger.warning("PDF OCR fallback unavailable: %s", exc)
            return []
