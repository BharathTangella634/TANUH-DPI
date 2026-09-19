"""
Shared serialization helpers for the forgensic API and Celery tasks.

Extracted from main.py so neither main.py nor tasks.py imports each other
(avoiding circular dependencies).
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import REVIEW_MIN_REGIONS
from .pipeline import (
    DetectedRegion,
    DocumentPage,
    PageAnalysisResult,
    _merge_boxes,
    _scaled_merge_gap,
)


def merged_regions_for(
    result: PageAnalysisResult,
    page: Optional[DocumentPage],
) -> List[Dict[str, Any]]:
    """Per-category merged boxes for a page, using the same gap as the findings.

    The findings list and the "View area" crop are built from merged clusters
    (build_findings_summary), while the page overlay used to be drawn from the
    raw, unmerged regions -- so a finding's box frequently had no matching box
    on the document. Serving the merged boxes here lets the overlay draw the
    same rectangles the findings refer to.
    """
    if page is None or not page.image_width or not page.image_height:
        return []
    gap = _scaled_merge_gap(page.image_width, page.image_height)
    boxes_by_category: Dict[str, List[tuple]] = {}
    for region in result.detected_regions:
        boxes_by_category.setdefault(region.category_id, []).append(
            (region.x, region.y, region.x + region.w, region.y + region.h)
        )
    merged: List[Dict[str, Any]] = []
    for category_id, boxes in boxes_by_category.items():
        for cluster in _merge_boxes(boxes, gap):
            x1, y1, x2, y2 = cluster["box"]
            merged.append({
                "x": int(x1),
                "y": int(y1),
                "w": int(x2 - x1),
                "h": int(y2 - y1),
                "category_id": category_id,
                "count": int(cluster.get("count", 1)),
            })
    return merged


def build_verdict(results: List[PageAnalysisResult]) -> Dict[str, Any]:
    """Collapse a whole document down to one call: PASS or REVIEW.

    Counts the detected regions that survived the npv_focus filter across every
    page. At or above REVIEW_MIN_REGIONS the document goes to a human; below it
    the document is cleared without manual verification.

    This is the document-level rule behind the NHA pilot report: with a
    threshold of 4 it reproduced that report's 51 PASS / 93 FAIL split over the
    144-document batch exactly. The threshold now sits at 3, which sends
    slightly more documents to review than the report did.
    """
    # A document that produced no analysable page was never actually examined
    # -- an unsupported or corrupt file, a render failure, a PDF with no
    # extractable pages. Counting regions would score that zero and clear it as
    # "requires no manual review", which is the one thing this verdict must
    # never do: PASS has to mean "looked at and found nothing", not "could not
    # look". Anything unexamined goes to a human.
    if not results:
        return {
            "verdict": "REVIEW",
            "requires_manual_review": True,
            "total_regions": 0,
            "review_min_regions": REVIEW_MIN_REGIONS,
            "unlocalized_categories": [],
            "verdict_reason": "no_pages_analysed",
        }

    total_regions = sum(len(r.detected_regions) for r in results)

    # Safety net for page-level categories. Counting regions alone silently
    # clears any category that fires without localising: C8 (fully
    # AI-generated document) is classified per page and has no branch in
    # localize_tampered_regions_sync, so a C8 page yields zero regions and
    # would score as PASS -- "requires no manual review" on a document the
    # pipeline just called machine-generated. A category that flagged a page
    # but could not draw a box still means a human should look.
    unlocalized: List[str] = []
    for r in results:
        flagged = [c for c in r.predicted_categories if c != "C10"]
        if flagged and not r.detected_regions:
            unlocalized.extend(flagged)
    unlocalized = sorted(set(unlocalized))

    if unlocalized:
        reason = "unlocalized_detection"
    elif total_regions >= REVIEW_MIN_REGIONS:
        reason = "region_threshold"
    else:
        reason = "below_threshold"

    review = total_regions >= REVIEW_MIN_REGIONS or bool(unlocalized)
    return {
        "verdict": "REVIEW" if review else "PASS",
        "requires_manual_review": review,
        "total_regions": total_regions,
        "review_min_regions": REVIEW_MIN_REGIONS,
        "unlocalized_categories": unlocalized,
        "verdict_reason": reason,
    }


def region_to_dict(region: DetectedRegion) -> Dict[str, Any]:
    return {
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
        "category_id": region.category_id,
        "type": region.type,
        "stretch_factor": region.stretch_factor,
        "header_source": region.header_source,
        "body_source": region.body_source,
    }


def result_to_dict(
    result: PageAnalysisResult,
    page: Optional[DocumentPage],
    image_url: Optional[str],
    preview_url: Optional[str],
) -> Dict[str, Any]:
    return {
        "page_id": f"{result.file_name}",
        "page_number": result.page_number,
        "file_name": result.file_name,
        "image_url": image_url,
        "preview_url": preview_url,
        "image_width": page.image_width if page else None,
        "image_height": page.image_height if page else None,
        "categories": result.predicted_categories,
        "regions": [region_to_dict(r) for r in result.detected_regions],
        "merged_regions": merged_regions_for(result, page),
        "notes": result.notes,
    }


def build_results_payload(
    job_id: str,
    file_name: str,
    pages: List[DocumentPage],
    results: List[PageAnalysisResult],
    export_info: Dict[str, Any],
    file_url_map: Dict[str, str],
    preview_url_map: Dict[str, str],
    pipeline_version: str,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    findings_summary: Optional[Dict[str, Any]] = None,
    inference_seconds: Optional[float] = None,
    avg_inference_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the full JSON-serializable result payload for a completed job."""
    page_map = {p.page_file_name: p for p in pages}
    payload_pages = []
    summary: Dict[str, int] = {}

    for res in results:
        page = page_map.get(res.file_name)
        image_url = file_url_map.get(res.file_name)
        preview_url = preview_url_map.get(res.file_name)
        payload_pages.append(result_to_dict(res, page, image_url, preview_url))
        for cat in res.predicted_categories:
            summary[cat] = summary.get(cat, 0) + 1

    export_urls: Dict[str, Any] = {
        "json": file_url_map.get("submission.json"),
        "excel": file_url_map.get("submission_preview.xlsx"),
        "yaml": [
            file_url_map.get(Path(p).name)
            for p in export_info.get("yaml_paths", [])
            if file_url_map.get(Path(p).name)
        ],
    }
    if not any([export_urls.get("json"), export_urls.get("excel"), export_urls.get("yaml")]):
        export_urls = {}

    verdict = build_verdict(results)

    return {
        "job_id": job_id,
        "status": "complete",
        "file_name": file_name,
        "pipeline_version": pipeline_version,
        "pages": payload_pages,
        "category_summary": summary,
        **verdict,
        "export_urls": export_urls,
        "findings_summary": findings_summary,
        "inference_seconds": inference_seconds,
        "avg_inference_seconds": avg_inference_seconds,
        "created_at": created_at,
        "updated_at": updated_at,
    }
