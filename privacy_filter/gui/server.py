"""Flask server for the Privacy Filter GUI desktop application.

Stripped-down reimplementation of privacy_filter/app/main.py endpoints.
No auth, no GCS, no Celery, no Redis, no session logger, no metrics.
Runs entirely on localhost with temp directory storage.
"""
from __future__ import annotations

import gc
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request, send_file, Response

from ..pipeline.engine import MedDeIDEngine

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("privacy_filter.gui")

MAX_FILE_SIZE_MB = 75
_PAGE_RENDER_DPI = 150
_DICOM_MAX_PREVIEW_PX = 2048

_TMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "pf_gui_uploads"
_TMP_REDACTED_DIR = Path(tempfile.gettempdir()) / "pf_gui_redacted"
_PAGE_RENDER_DIR = Path(tempfile.gettempdir()) / "pf_gui_pages"
_CLEANUP_INTERVAL_S = 600
_CLEANUP_MAX_AGE_S = 1800


def _cleanup_old_files():
    """Remove temp files older than 30 minutes, runs every 10 minutes."""
    while True:
        time.sleep(_CLEANUP_INTERVAL_S)
        now = time.time()
        for tmp_dir in [_TMP_UPLOAD_DIR, _TMP_REDACTED_DIR]:
            if not tmp_dir.exists():
                continue
            for f in tmp_dir.iterdir():
                try:
                    if now - f.stat().st_mtime > _CLEANUP_MAX_AGE_S:
                        f.unlink(missing_ok=True)
                except OSError:
                    pass
        if _PAGE_RENDER_DIR.exists():
            for d in _PAGE_RENDER_DIR.iterdir():
                try:
                    if d.is_dir() and now - d.stat().st_mtime > _CLEANUP_MAX_AGE_S:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass

_SUPPORTED_SUFFIXES = {
    ".dcm", ".dicom",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    ".nii", ".pdf",
}

_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".dcm": "application/dicom",
    ".dicom": "application/dicom",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".nii": "application/octet-stream",
    ".json": "application/json",
}


def _guess_content_type(key: str) -> str:
    ext = Path(key).suffix.lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def supported_extensions() -> List[str]:
    return sorted(_SUPPORTED_SUFFIXES | {".nii.gz"})


def is_supported(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return True
    return Path(name).suffix.lower() in _SUPPORTED_SUFFIXES


def out_extension(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    return Path(filename).suffix.lower()


# Engine singleton
_engine: MedDeIDEngine | None = None


def _get_engine() -> MedDeIDEngine:
    global _engine
    if _engine is None:
        logger.info("Initialising MedDeIDEngine (tesseract/mask)")
        _engine = MedDeIDEngine(ocr_backend="tesseract", redaction_method="mask")
    return _engine


def _phi_to_entity(phi) -> Dict[str, Any]:
    word = getattr(phi, "text", None) or getattr(phi, "metadata_value", None)
    if not word:
        word = getattr(phi, "metadata_key", None)

    bbox = getattr(phi, "bbox", None)
    bbox_dict = None
    if bbox is not None:
        bbox_dict = {
            "x1": int(getattr(bbox, "x1", 0)),
            "y1": int(getattr(bbox, "y1", 0)),
            "x2": int(getattr(bbox, "x2", 0)),
            "y2": int(getattr(bbox, "y2", 0)),
            "page": int(getattr(bbox, "page", 0) or 0),
        }

    return {
        "entity_group": getattr(phi, "label", "PHI") or "PHI",
        "score": float(getattr(phi, "confidence", 1.0) or 1.0),
        "word": word,
        "start": None,
        "end": None,
        "bbox": bbox_dict,
    }


def _run_deidentification(input_path: Path, output_path: Path):
    engine = _get_engine()
    result = engine.process(input_path, output_path)

    entities: List[Dict[str, Any]] = []
    seen = set()

    pdf_entities = result.get("pdf_entities")
    if pdf_entities is not None:
        for ent in pdf_entities:
            bb = ent.get("bbox") or {}
            key = (ent["entity_group"], ent.get("word"),
                   (bb.get("x1"), bb.get("y1"), bb.get("x2"), bb.get("y2"), bb.get("page")))
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)
    else:
        metadata_phi = result.get("metadata_phi", []) or []
        pixel_phi = result.get("pixel_phi", []) or []
        for phi in list(metadata_phi) + list(pixel_phi):
            ent = _phi_to_entity(phi)
            bbox = getattr(phi, "bbox", None)
            key = (
                ent["entity_group"],
                ent["word"],
                (bbox.x1, bbox.y1, bbox.x2, bbox.y2) if bbox is not None else None,
            )
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)

    counts: Dict[str, int] = {}
    for e in entities:
        counts[e["entity_group"]] = counts.get(e["entity_group"], 0) + 1

    validation = result.get("validation")
    meta = {
        "validation_passed": bool(getattr(validation, "passed", False)),
        "risk_score": float(getattr(validation, "risk_score", 0.0)),
        "notes": getattr(validation, "notes", None),
        "phi_count": int(result.get("phi_count", 0)),
        "overlay_count": int(result.get("overlay_count", 0)),
    }

    return entities, counts, meta


def _find_stored_file(kind: str, key: str) -> Path | None:
    for tmp_base in [_TMP_UPLOAD_DIR, _TMP_REDACTED_DIR]:
        p = tmp_base / key
        if p.exists():
            return p
    return None


def _render_document_pages(file_path: Path, key: str) -> List[Dict[str, Any]]:
    out_dir = _PAGE_RENDER_DIR / key
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(out_dir.glob("page_*.png"))
    if existing:
        from PIL import Image as PILImage
        pages_info = []
        for png in existing:
            idx = int(png.stem.split("_", 1)[1])
            with PILImage.open(png) as img:
                pages_info.append({
                    "page": idx,
                    "url": f"/api/page-image/{key}/{idx}",
                    "width": img.width,
                    "height": img.height,
                })
        return pages_info

    suffix = file_path.suffix.lower()
    pages_info: List[Dict[str, Any]] = []

    if suffix == ".pdf":
        import fitz
        with fitz.open(file_path) as doc:
            for i, page in enumerate(doc):
                zoom = _PAGE_RENDER_DPI / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_path = out_dir / f"page_{i}.png"
                pix.save(str(img_path))
                pages_info.append({
                    "page": i,
                    "url": f"/api/page-image/{key}/{i}",
                    "width": pix.width,
                    "height": pix.height,
                })

    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        from PIL import Image as PILImage
        img = PILImage.open(file_path).convert("RGB")
        img_path = out_dir / "page_0.png"
        img.save(img_path, "PNG")
        pages_info.append({
            "page": 0,
            "url": f"/api/page-image/{key}/0",
            "width": img.width,
            "height": img.height,
        })

    elif suffix in {".dcm", ".dicom"}:
        import pydicom
        from pydicom.uid import ImplicitVRLittleEndian
        from PIL import Image as PILImage
        import numpy as np
        ds = pydicom.dcmread(str(file_path), force=True)
        if not hasattr(ds.file_meta, "TransferSyntaxUID") or ds.file_meta.TransferSyntaxUID is None:
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
        try:
            arr = ds.pixel_array
            if arr.ndim == 2:
                norm = ((arr - arr.min()) / (arr.max() - arr.min() + 1e-9) * 255).astype(np.uint8)
                img = PILImage.fromarray(norm, "L").convert("RGB")
            else:
                img = PILImage.fromarray(arr).convert("RGB")
            max_dim = max(img.width, img.height)
            if max_dim > _DICOM_MAX_PREVIEW_PX:
                scale = _DICOM_MAX_PREVIEW_PX / max_dim
                img = img.resize((int(img.width * scale), int(img.height * scale)), PILImage.LANCZOS)
            img_path = out_dir / "page_0.png"
            img.save(img_path, "PNG")
            pages_info.append({
                "page": 0,
                "url": f"/api/page-image/{key}/0",
                "width": img.width,
                "height": img.height,
            })
        except Exception:
            logger.exception("DICOM pixel_array failed for preview of %s", key)

    elif suffix == ".nii" or str(file_path).lower().endswith(".nii.gz"):
        try:
            import nibabel as nib
            from PIL import Image as PILImage
            import numpy as np
            nii = nib.load(str(file_path))
            data = np.asanyarray(nii.dataobj)
            if data.ndim >= 3:
                mid_slice = data[:, :, data.shape[2] // 2]
            else:
                mid_slice = data
            norm = ((mid_slice - mid_slice.min()) / (mid_slice.max() - mid_slice.min() + 1e-9) * 255).astype(np.uint8)
            img = PILImage.fromarray(norm, "L").convert("RGB")
            img_path = out_dir / "page_0.png"
            img.save(img_path, "PNG")
            pages_info.append({
                "page": 0,
                "url": f"/api/page-image/{key}/0",
                "width": img.width,
                "height": img.height,
            })
        except Exception:
            logger.warning("NIfTI preview failed")

    return pages_info


def _apply_boxes_pdf(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path):
    import fitz
    doc = fitz.open(src)
    for box in boxes:
        page_idx = int(box.get("page", 0))
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        sx, sy = pw / img_w, ph / img_h
        rect = fitz.Rect(
            box["x"] * sx, box["y"] * sy,
            (box["x"] + box["w"]) * sx, (box["y"] + box["h"]) * sy,
        )
        page.add_redact_annot(rect, fill=(0, 0, 0))
    for page in doc:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    doc.save(str(out), garbage=4, deflate=True, clean=True)
    doc.close()


def _apply_boxes_image(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path, suffix: str = ".png"):
    from PIL import Image as PILImage, ImageDraw
    img = PILImage.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    sx, sy = img.width / img_w, img.height / img_h
    for box in boxes:
        draw.rectangle(
            [box["x"] * sx, box["y"] * sy,
             (box["x"] + box["w"]) * sx, (box["y"] + box["h"]) * sy],
            fill=(0, 0, 0),
        )
    if suffix in {".jpg", ".jpeg"}:
        img.save(out, "JPEG", quality=95)
    elif suffix in {".tif", ".tiff"}:
        img.save(out, "TIFF")
    elif suffix == ".bmp":
        img.save(out, "BMP")
    else:
        img.save(out, "PNG")


def _apply_boxes_dicom(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path):
    import pydicom
    from pydicom.uid import ImplicitVRLittleEndian
    import numpy as np
    ds = pydicom.dcmread(str(src), force=True)
    if not hasattr(ds.file_meta, "TransferSyntaxUID") or ds.file_meta.TransferSyntaxUID is None:
        ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
    try:
        arr = ds.pixel_array.copy()
    except Exception:
        raise ValueError("DICOM has no pixel data")
    h_actual, w_actual = arr.shape[0], arr.shape[1] if arr.ndim >= 2 else 1
    sx, sy = w_actual / img_w, h_actual / img_h
    for box in boxes:
        y0 = max(0, int(box["y"] * sy))
        y1 = min(h_actual, int((box["y"] + box["h"]) * sy))
        x0 = max(0, int(box["x"] * sx))
        x1 = min(w_actual, int((box["x"] + box["w"]) * sx))
        arr[y0:y1, x0:x1, ...] = 0
    ds.PixelData = arr.tobytes()
    ds.save_as(str(out), write_like_original=False)


def create_app() -> Flask:
    """Create and configure the Flask app with all GUI API endpoints."""
    from .html_template import get_html

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_MB * 1024 * 1024

    _TMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _TMP_REDACTED_DIR.mkdir(parents=True, exist_ok=True)
    _PAGE_RENDER_DIR.mkdir(parents=True, exist_ok=True)

    threading.Thread(target=_cleanup_old_files, daemon=True).start()

    @app.route("/")
    def index():
        return Response(get_html(), content_type="text/html; charset=utf-8")

    @app.route("/api/health")
    def health():
        try:
            _get_engine()
            ready = True
        except Exception:
            ready = False
        return jsonify({
            "status": "ok" if ready else "initializing",
            "model": "Anonymizer",
            "device": "CPU",
            "model_loaded": ready,
        })

    @app.route("/api/supported-types")
    def supported_types():
        return jsonify({"extensions": supported_extensions()})

    @app.route("/api/redact", methods=["POST"])
    def redact_file():
        if "file" not in request.files:
            return jsonify({"detail": "No file uploaded"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"detail": "Missing filename"}), 400

        if not is_supported(file.filename):
            return jsonify({
                "detail": f"Unsupported file type. Supported: {', '.join(supported_extensions())}"
            }), 415

        job_id = uuid.uuid4().hex[:12]
        safe_name = Path(file.filename).name
        upload_key = f"{job_id}__{safe_name}"

        raw_bytes = file.read()
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            return jsonify({
                "detail": f"File is {size_mb:.1f} MB. Maximum allowed size is {MAX_FILE_SIZE_MB} MB."
            }), 413

        upload_path = _TMP_UPLOAD_DIR / upload_key
        upload_path.write_bytes(raw_bytes)
        del raw_bytes

        ext = out_extension(safe_name)
        stem = Path(safe_name).stem
        redacted_key = f"{job_id}__{stem}_redacted{ext}"
        redacted_path = _TMP_REDACTED_DIR / redacted_key

        try:
            entities_raw, counts, meta = _run_deidentification(upload_path, redacted_path)
        except Exception as e:
            logger.exception("De-identification failed: %s", e)
            return jsonify({"detail": f"De-identification failed: {e}"}), 500

        if not redacted_path.exists():
            return jsonify({"detail": "Engine completed but produced no output file."}), 500

        notes = None
        if not meta.get("validation_passed", False):
            notes = (
                f"Validation risk score {meta.get('risk_score', 0)}. "
                f"{meta.get('notes') or ''}".strip()
            )

        result = {
            "job_id": job_id,
            "filename": safe_name,
            "content_type": file.content_type or "application/octet-stream",
            "entities": entities_raw,
            "entity_counts": dict(Counter(counts)),
            "original_url": f"/api/files/uploads/{upload_key}",
            "redacted_url": f"/api/files/redacted/{redacted_key}",
            "text_preview_original": None,
            "text_preview_redacted": None,
            "notes": notes,
        }

        gc.collect()
        return jsonify(result)

    @app.route("/api/files/<kind>/<key>")
    def download_file(kind, key):
        if kind not in {"uploads", "redacted"}:
            return jsonify({"detail": "Unknown kind"}), 404
        p = _find_stored_file(kind, key)
        if p is None or not p.exists():
            return jsonify({"detail": "File not found"}), 404
        filename = key.split("__", 1)[-1] if "__" in key else key
        return send_file(p, as_attachment=True, download_name=filename)

    @app.route("/api/render-pages/<kind>/<key>")
    def render_pages(kind, key):
        if kind not in {"uploads", "redacted"}:
            return jsonify({"detail": "Unknown kind"}), 404
        file_path = _find_stored_file(kind, key)
        if file_path is None:
            return jsonify({"detail": "File not found"}), 404
        pages = _render_document_pages(file_path, key)
        return jsonify({"pages": pages, "text_only": False})

    @app.route("/api/page-image/<key>/<int:page_num>")
    def page_image(key, page_num):
        img_path = _PAGE_RENDER_DIR / key / f"page_{page_num}.png"
        if img_path.exists():
            return send_file(img_path, mimetype="image/png")
        return jsonify({"detail": "Page image not found"}), 404

    @app.route("/api/apply-redactions", methods=["POST"])
    def apply_redactions():
        body = request.get_json(force=True)
        job_id = body.get("job_id", "")
        source_key = body.get("source_key", "")
        boxes = body.get("boxes", [])
        image_width = body.get("image_width", 1)
        image_height = body.get("image_height", 1)

        tmp_upload = _find_stored_file("uploads", source_key)
        if tmp_upload is None:
            return jsonify({"detail": "Original file not found"}), 404

        suffix = tmp_upload.suffix.lower()
        original_name = source_key.split("__", 1)[-1] if "__" in source_key else source_key
        out_ext = Path(original_name).suffix.lower() or suffix
        stem = Path(original_name).stem

        redacted_key = f"{job_id}__{stem}_redacted{out_ext}"
        redacted_path = _TMP_REDACTED_DIR / redacted_key

        try:
            if suffix == ".pdf":
                _apply_boxes_pdf(tmp_upload, boxes, image_width, image_height, redacted_path)
            elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
                _apply_boxes_image(tmp_upload, boxes, image_width, image_height, redacted_path, suffix)
            elif suffix in {".dcm", ".dicom"}:
                _apply_boxes_dicom(tmp_upload, boxes, image_width, image_height, redacted_path)
            else:
                return jsonify({"detail": f"Editing not supported for {suffix}"}), 415
        except Exception as e:
            logger.exception("apply-redactions failed")
            return jsonify({"detail": str(e)}), 500

        page_cache = _PAGE_RENDER_DIR / redacted_key
        if page_cache.exists():
            import shutil
            shutil.rmtree(page_cache, ignore_errors=True)
        preview_pages = _render_document_pages(redacted_path, redacted_key)
        return jsonify({
            "redacted_key": redacted_key,
            "redacted_url": f"/api/files/redacted/{redacted_key}",
            "preview_pages": preview_pages,
        })

    return app
