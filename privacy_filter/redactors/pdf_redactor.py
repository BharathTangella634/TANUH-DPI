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

import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz

from ..detectors.safe_harbor_detector import SafeHarborDetector, _CLINICAL_ALLOWLIST

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

# Signature image heuristic: wider than tall, moderate height.
_SIG_MIN_AR = 1.5
_SIG_MAX_AR = 6.0
_SIG_MIN_H = 20.0  # PDF points
_SIG_MAX_H = 80.0  # PDF points

# Labels whose detected text is a discrete identifier worth searching for
# everywhere it repeats (names, codes, IDs). Dates/times/ages repeat too but
# are already caught per-line by the pattern detectors on every page.
_GLOBAL_LABELS = {
    "PERSON_NAME", "IDENTIFIER", "LABELED_PHI", "BARCODE", "AADHAAR",
    "PAN", "SSN", "EMAIL", "ORG_NAME",
}

# Stop-words never worth global searching (would over-match clinical text).
_TOKEN_STOPWORDS = {
    "dr", "mr", "mrs", "ms", "the", "of", "and", "unit", "male", "female",
    "general", "consultant", "professor", "resident", "by", "no", "id",
    "for", "with", "from", "into", "that", "this", "then", "than",
    "not", "but", "are", "was", "were", "been", "has", "have", "had",
    "its", "all", "any", "can", "may", "will", "also", "each", "per",
    "national", "international", "scientific", "advisory", "board",
    "committee", "council", "society", "association", "organization",
    "foundation", "system", "testing", "variant", "method", "type",
    "group", "class", "level", "grade", "stage", "phase", "part",
    "based", "using", "according", "between", "within", "after", "before",
    "about", "under", "over", "through", "during", "following",
    "management", "recommendations", "guidelines", "standards",
    "department", "division", "section", "service", "program",
    "journal", "report", "review", "study", "research", "article",
    "patients", "subjects", "individuals", "persons", "cases",
    "data", "information", "records", "files", "documents",
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

        is_scanned = len(words) < _MIN_WORDS_FOR_NATIVE
        if is_scanned:
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

        # ── Block-level detection ────────────────────────────────────────────
        redact_rects.extend(self._block_level_detect(lines, words))

        if is_scanned:
            # Scanned page: text lives in the page image, not as PDF glyphs.
            # Annotation-based redaction would destroy the entire page image.
            # Instead, modify the image pixels directly.
            return self._apply_scanned_redactions(
                page, page_index, redact_rects, global_tokens,
            )

        # ── Digital page: text-based redaction (true glyph removal) ──────────
        for rect, label, text in redact_rects:
            page.add_redact_annot(rect, fill=(0, 0, 0))
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

        if redact_rects or any(e["entity_group"] in ("QR_CODE", "BARCODE", "SIGNATURE") for e in entities):
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

        return entities

    # ------------------------------------------------------------------

    def _apply_scanned_redactions(
        self,
        page: "fitz.Page",
        page_index: int,
        redact_rects: List[tuple],
        global_tokens: set | None = None,
    ) -> List[Dict[str, Any]]:
        """Redact a scanned page by modifying the embedded image pixels.

        For scanned PDFs the visible content is a raster image, not PDF text
        glyphs.  Annotation-based ``apply_redactions`` with image removal would
        destroy the entire page.  Instead we:
          1. Extract the main page image.
          2. Draw filled black rectangles at every PHI bounding box.
          3. Detect and mask handwritten signatures.
          4. Replace the image in the PDF via ``page.replace_image``.
        """
        from PIL import Image, ImageDraw

        entities: List[Dict[str, Any]] = []
        doc = page.parent

        page_images = page.get_images(full=True)
        if not page_images:
            logger.warning("Scanned page %d: no extractable images", page_index)
            return entities

        # Pick the largest embedded image (the full-page scan).
        main_xref, main_rect = None, None
        max_area = 0.0
        for img_info in page_images:
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                r = rects[0]
                area = r.width * r.height
                if area > max_area:
                    max_area, main_xref, main_rect = area, xref, r
            except Exception:
                continue

        if main_xref is None:
            logger.warning("Scanned page %d: could not locate main image", page_index)
            return entities

        try:
            base_image = doc.extract_image(main_xref)
        except Exception as exc:
            logger.warning("Scanned page %d: extract_image failed: %s", page_index, exc)
            return entities

        pil_img = Image.open(io.BytesIO(base_image["image"]))
        if pil_img.mode not in ("RGB", "L"):
            pil_img = pil_img.convert("RGB")

        img_w, img_h = pil_img.size
        sx = img_w / main_rect.width
        sy = img_h / main_rect.height

        draw = ImageDraw.Draw(pil_img)
        _PAD_L = 6   # left/top padding (pixels)
        _PAD_R = 18  # right padding — OCR boxes consistently under-report width
        _PAD_T = 6
        _PAD_B = 10  # bottom — descenders extend below baseline

        for rect, label, text in redact_rects:
            px0 = max(0, int((rect.x0 - main_rect.x0) * sx) - _PAD_L)
            py0 = max(0, int((rect.y0 - main_rect.y0) * sy) - _PAD_T)
            px1 = min(img_w, int((rect.x1 - main_rect.x0) * sx) + _PAD_R)
            py1 = min(img_h, int((rect.y1 - main_rect.y0) * sy) + _PAD_B)
            draw.rectangle([px0, py0, px1, py1], fill="black")

            if global_tokens is not None and text and label in _GLOBAL_LABELS:
                global_tokens.add(text)
            entities.append({
                "entity_group": label,
                "score": 1.0,
                "word": text or None,
                "bbox": _px_bbox(rect, page_index),
            })

        # Detect and mask handwritten signatures.
        for sig_box in self._detect_signatures_in_image(pil_img):
            draw.rectangle(sig_box, fill="black")
            pg_rect = fitz.Rect(
                sig_box[0] / sx + main_rect.x0,
                sig_box[1] / sy + main_rect.y0,
                sig_box[2] / sx + main_rect.x0,
                sig_box[3] / sy + main_rect.y0,
            )
            entities.append({
                "entity_group": "SIGNATURE",
                "score": 0.9,
                "word": None,
                "bbox": _px_bbox(pg_rect, page_index),
            })

        # Save modified image and replace in the PDF.
        buf = io.BytesIO()
        ext = base_image.get("ext", "png").lower()
        if ext in ("jpeg", "jpg"):
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            pil_img.save(buf, format="JPEG", quality=95)
        else:
            pil_img.save(buf, format="PNG")

        try:
            new_pix = fitz.Pixmap(buf.getvalue())
            page.replace_image(main_xref, pixmap=new_pix)
        except Exception as exc:
            logger.warning(
                "Scanned page %d: replace_image failed (%s), "
                "falling back to page rebuild",
                page_index, exc,
            )
            self._rebuild_page_with_image(page, buf.getvalue())

        logger.info(
            "Scanned page %d: redacted %d regions + %d signatures",
            page_index,
            len(redact_rects),
            sum(1 for e in entities if e["entity_group"] == "SIGNATURE"),
        )
        return entities

    # ------------------------------------------------------------------

    @staticmethod
    def _rebuild_page_with_image(page: "fitz.Page", img_bytes: bytes):
        """Fallback: delete page and re-create with the redacted image."""
        doc = page.parent
        idx = page.number
        rect = page.rect
        doc.delete_page(idx)
        new_page = doc.new_page(pno=idx, width=rect.width, height=rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)

    # ------------------------------------------------------------------

    @staticmethod
    def _detect_signatures_in_image(pil_img) -> List[tuple]:
        """Detect handwritten signature regions in the bottom half of an image.

        Returns list of (x0, y0, x1, y1) pixel rectangles.
        """
        import numpy as np

        try:
            import cv2
        except ImportError:
            return []

        gray = np.array(pil_img.convert("L"))
        h, w = gray.shape

        # Signatures appear in the bottom 45% of the page.
        y_start = int(h * 0.55)
        bottom = gray[y_start:]
        bh = bottom.shape[0]

        # Otsu threshold: dark ink on light paper.
        _, binary = cv2.threshold(bottom, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Dilate to merge nearby pen strokes into connected regions.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 8))
        dilated = cv2.dilate(binary, kernel, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        sig_rects: List[tuple] = []
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            area = cw * ch
            if area < w * bh * 0.003 or area > w * bh * 0.08:
                continue
            ar = cw / max(ch, 1)
            if ar < 1.2 or ar > 10:
                continue
            # Must not span the full width (those are text lines, caught by OCR).
            if cw > w * 0.55:
                continue
            fill = cv2.contourArea(c) / max(area, 1)
            # Signatures are sparse strokes, not solid blocks.
            if fill > 0.7:
                continue
            sig_rects.append((x, y + y_start, x + cw, y + ch + y_start))

        return sig_rects

    # ------------------------------------------------------------------

    def _block_level_detect(
        self,
        lines: Dict[tuple, list],
        words: list,
    ) -> List[tuple]:
        """Re-run detection on block-level text to catch cross-line label-value pairs.
        """
        extra: List[tuple] = []
        blocks: Dict[int, list] = {}
        for key, line_words in lines.items():
            blocks.setdefault(key[0], []).append((key, line_words))

        _Y_TOL = 3.0  # points — lines within this tolerance are the same row

        for block_id, block_data in blocks.items():
            if len(block_data) <= 1:
                continue
            # Sort lines into visual reading order: group by y (with tolerance),
            # then left-to-right within each row.
            for item in block_data:
                item_words = item[1]
                item_words.sort(key=lambda w: w[0])
            block_data.sort(
                key=lambda x: (
                    round(min(w[1] for w in x[1]) / _Y_TOL) * _Y_TOL,
                    min(w[0] for w in x[1]),
                )
            )

            block_text = ""
            block_offsets = []
            for _key, lwords in block_data:
                for w in lwords:
                    start = len(block_text)
                    block_text += w[4]
                    block_offsets.append(
                        (start, len(block_text), fitz.Rect(w[0], w[1], w[2], w[3]))
                    )
                    block_text += " "

            for span in self.detector.detect_spans(block_text):
                rect = None
                span_words = []
                for cs, ce, r in block_offsets:
                    if not (ce <= span.start or cs >= span.end):
                        rect = r if rect is None else (rect | r)
                        span_words.append(block_text[cs:ce])
                if rect is not None:
                    text = span.text or " ".join(span_words)
                    extra.append((rect, span.label, text))
        return extra

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
                    elif _SIG_MIN_AR <= ar <= _SIG_MAX_AR and _SIG_MIN_H <= h <= _SIG_MAX_H:
                        out.append((rect, "SIGNATURE"))
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
                if t.lower() in _CLINICAL_ALLOWLIST:
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
        """OCR fallback for scanned pages — waterfall: docling → PaddleOCR → pytesseract."""
        from .pdf_ocr_waterfall import waterfall_ocr_words
        return waterfall_ocr_words(page)
