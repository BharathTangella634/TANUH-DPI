"""
pdf_ocr_waterfall.py

Waterfall OCR for scanned PDF pages: docling → PaddleOCR → pytesseract.

Called by PDFRedactor._ocr_words() when a page has too few native text words
(scanned page). Returns words in PyMuPDF format so the rest of the redaction
pipeline works unchanged.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import fitz
import numpy as np

logger = logging.getLogger("privacy_filter.pdf_ocr_waterfall")

_RENDER_DPI = 300
_SCALE = 72.0 / _RENDER_DPI


def waterfall_ocr_words(page: "fitz.Page") -> list:
    """Try OCR engines in waterfall order; return first successful result.

    Returns list of tuples matching ``page.get_text("words")`` format:
    ``(x0, y0, x1, y1, word, block_no, line_no, word_no)``
    """
    pix = page.get_pixmap(matrix=fitz.Matrix(_RENDER_DPI / 72, _RENDER_DPI / 72))

    engines = [
        ("docling", _try_docling),
        ("paddleocr", _try_paddleocr),
        ("pytesseract", _try_pytesseract),
    ]

    for name, fn in engines:
        try:
            if name == "docling":
                result = fn(page)
            else:
                result = fn(pix)
            if result:
                logger.info(
                    "PDF OCR waterfall: %s succeeded (%d words)", name, len(result)
                )
                return result
            logger.info("PDF OCR waterfall: %s returned no words, trying next", name)
        except Exception as exc:
            logger.warning("PDF OCR waterfall: %s failed: %s", name, exc)

    logger.warning("PDF OCR waterfall: all engines failed")
    return []


# ---------------------------------------------------------------------------
# Engine: docling
# ---------------------------------------------------------------------------

def _try_docling(page: "fitz.Page") -> list | None:
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except Exception:
        logger.debug("docling not available")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = Path(tmp) / "page.pdf"
        src_doc = page.parent
        page_index = page.number

        single = fitz.open()
        single.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
        single.save(str(tmp_pdf))
        single.close()

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(str(tmp_pdf))

    doc = result.document
    page_width = page.rect.width
    page_height = page.rect.height

    docling_page_size = None
    if doc.pages:
        first_page = next(iter(doc.pages.values()))
        if first_page.size:
            docling_page_size = (first_page.size.width, first_page.size.height)

    words = []
    block_no = 0

    for item in doc.texts:
        text = item.text.strip() if item.text else ""
        if not text:
            continue

        bbox = None
        for prov in item.prov:
            bbox = prov.bbox
            break

        if bbox is None:
            continue

        x0, x1 = bbox.l, bbox.r

        from docling_core.types.doc.base import CoordOrigin
        if bbox.coord_origin == CoordOrigin.BOTTOMLEFT:
            y0 = docling_page_size[1] - bbox.t if docling_page_size else page_height - bbox.t
            y1 = docling_page_size[1] - bbox.b if docling_page_size else page_height - bbox.b
        else:
            y0, y1 = bbox.t, bbox.b

        if docling_page_size:
            sx = page_width / docling_page_size[0]
            sy = page_height / docling_page_size[1]
            x0 *= sx
            x1 *= sx
            y0 *= sy
            y1 *= sy

        words.extend(_split_words(text, x0, y0, x1, y1, block_no, 0))
        block_no += 1

    return words if words else None


# ---------------------------------------------------------------------------
# Engine: PaddleOCR
# ---------------------------------------------------------------------------

def _try_paddleocr(pix: "fitz.Pixmap") -> list | None:
    try:
        from paddleocr import PaddleOCR
    except Exception:
        logger.debug("paddleocr not available")
        return None

    image = _pixmap_to_numpy(pix)
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    result = ocr.ocr(image, cls=True)

    if not result:
        return None

    words = []
    block_no = 0

    for block in result:
        if not block:
            continue
        for line_no, line in enumerate(block):
            box_pts, (text, _conf) = line
            text = text.strip()
            if not text:
                continue

            xs = [p[0] for p in box_pts]
            ys = [p[1] for p in box_pts]
            x0 = min(xs) * _SCALE
            y0 = min(ys) * _SCALE
            x1 = max(xs) * _SCALE
            y1 = max(ys) * _SCALE

            words.extend(_split_words(text, x0, y0, x1, y1, block_no, line_no))
        block_no += 1

    return words if words else None


# ---------------------------------------------------------------------------
# Engine: pytesseract
# ---------------------------------------------------------------------------

def _try_pytesseract(pix: "fitz.Pixmap") -> list | None:
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        logger.debug("pytesseract not available")
        return None

    img_bytes = pix.tobytes("png")
    import io
    image = Image.open(io.BytesIO(img_bytes))

    data = pytesseract.image_to_data(
        image,
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )

    words = []
    n = len(data["text"])

    for i in range(n):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if conf < 10:
            continue

        x0 = int(data["left"][i]) * _SCALE
        y0 = int(data["top"][i]) * _SCALE
        x1 = (int(data["left"][i]) + int(data["width"][i])) * _SCALE
        y1 = (int(data["top"][i]) + int(data["height"][i])) * _SCALE

        block_num = int(data["block_num"][i])
        line_num = int(data["line_num"][i])
        word_num = int(data["word_num"][i])

        words.append((x0, y0, x1, y1, text, block_num, line_num, word_num))

    return words if words else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pixmap_to_numpy(pix: "fitz.Pixmap") -> np.ndarray:
    """Convert a PyMuPDF Pixmap to a numpy RGB array."""
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)


_SINGLE_LINE_HEIGHT = 18.0  # points — typical single text line height


def _split_words(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    block_no: int,
    line_no: int,
) -> list:
    """Split a text span into individual word tuples with proper coordinates.

    When the bbox height suggests the text spans multiple visual lines,
    words are distributed across estimated lines with correct per-line
    y-bands — not crammed into one horizontal strip.
    """
    tokens = text.split()
    if not tokens:
        return []
    if len(tokens) == 1:
        return [(x0, y0, x1, y1, tokens[0], block_no, line_no, 0)]

    height = y1 - y0
    width = x1 - x0
    total_chars = sum(len(t) for t in tokens)
    if total_chars == 0:
        return []

    estimated_lines = max(1, round(height / _SINGLE_LINE_HEIGHT))
    if estimated_lines <= 1 or width < 1:
        return _distribute_on_line(tokens, x0, y0, x1, y1, block_no, line_no)

    chars_per_line = max(1, total_chars // estimated_lines)
    lines: list[list[str]] = []
    current: list[str] = []
    current_len = 0

    for token in tokens:
        if current_len + len(token) > chars_per_line * 1.3 and current:
            lines.append(current)
            current = [token]
            current_len = len(token)
        else:
            current.append(token)
            current_len += len(token)
    if current:
        lines.append(current)

    n = len(lines)
    line_h = height / n
    result = []

    for i, line_tokens in enumerate(lines):
        ly0 = y0 + i * line_h
        ly1 = ly0 + line_h
        actual_line_no = line_no + i
        result.extend(
            _distribute_on_line(line_tokens, x0, ly0, x1, ly1, block_no, actual_line_no)
        )

    return result


def _distribute_on_line(
    tokens: list[str],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    block_no: int,
    line_no: int,
) -> list:
    """Distribute tokens proportionally along a single line."""
    if not tokens:
        return []
    if len(tokens) == 1:
        return [(x0, y0, x1, y1, tokens[0], block_no, line_no, 0)]

    total_chars = sum(len(t) for t in tokens)
    if total_chars == 0:
        return []

    width = x1 - x0
    result = []
    cur_x = x0

    for i, token in enumerate(tokens):
        token_width = (len(token) / total_chars) * width
        result.append((cur_x, y0, cur_x + token_width, y1, token, block_no, line_no, i))
        cur_x += token_width

    return result
