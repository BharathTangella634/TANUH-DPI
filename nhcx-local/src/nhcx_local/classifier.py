"""
classifier.py -- Two-tier document validation gate.

Tier 1: keyword_screen()  -- Zero-cost heuristic, < 1 ms
Tier 2: LLM fallback      -- Only when keywords are ambiguous

Returns: "CLINICAL" | "INSURANCE" | "INVALID"
"""

import logging
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

_CLINICAL_KEYWORDS = [
    "discharge summary", "date of discharge", "date of admission",
    "hospital course", "chief complaint", "final diagnosis",
    "discharge diagnosis", "condition at discharge",
    "lab no", "collection date", "reference range", "haemoglobin",
    "platelet", "wbc", "rbc", "hba1c", "creatinine", "radiology",
    "x-ray", "mri", "ct scan", "ultrasound", "biopsy", "specimen",
    "impression", "pathology", "laboratory",
    "patient name", "age/sex", "diagnosis", "prescription",
    "medication", "allergy", "blood pressure", "pulse rate",
    "temperature", "oxygen saturation", "spo2",
    "doctor", "physician", "consultant", "ward", "opd", "ipd",
]

_INSURANCE_KEYWORDS = [
    "insurance", "insurer", "policy number", "sum insured",
    "premium", "deductible", "co-payment", "co-pay",
    "claim", "pre-authorization", "nhcx", "tpa",
    "waiting period", "exclusion", "benefit", "coverage",
    "insured member", "policyholder", "irdai", "uin",
    "room rent", "icu charges", "reimbursement",
    "network hospital", "cashless", "maternity benefit",
]

_KEYWORD_CONFIDENCE_THRESHOLD = 2


def keyword_screen(text: str) -> str:
    """Fast heuristic pre-screen. Returns CLINICAL / INSURANCE / UNKNOWN."""
    if not text or len(text.strip()) < 50:
        return "UNKNOWN"

    sample = text[:4000].lower()
    clinical_hits = sum(1 for kw in _CLINICAL_KEYWORDS if kw in sample)
    insurance_hits = sum(1 for kw in _INSURANCE_KEYWORDS if kw in sample)

    if clinical_hits >= _KEYWORD_CONFIDENCE_THRESHOLD and clinical_hits > insurance_hits:
        return "CLINICAL"
    if insurance_hits >= _KEYWORD_CONFIDENCE_THRESHOLD and insurance_hits > clinical_hits:
        return "INSURANCE"
    return "UNKNOWN"


_LLM_CLASSIFY_PROMPT = """
You are an expert medical document classifier.
Analyze the following text extracted from a PDF and classify it into one of these three categories:

1. "CLINICAL": The document is a medical record, such as a discharge summary, lab report, diagnostic report, or clinical note.
2. "INSURANCE": The document is an insurance policy, a claim form, a pre-authorization request, or an insurance-related benefit summary.
3. "INVALID": The document is neither a medical record nor an insurance document.

Return ONLY the category name in uppercase: "CLINICAL", "INSURANCE", or "INVALID".

TEXT:
{text}
"""


def _parse_llm_response(raw: str) -> str:
    category = raw.strip().upper()
    if category in ("CLINICAL", "INSURANCE", "INVALID"):
        return category
    if "CLINICAL" in category:
        return "CLINICAL"
    if "INSURANCE" in category:
        return "INSURANCE"
    return "INVALID"


def classify_document_text(text: str, llm=None) -> str:
    """
    Two-tier classifier (synchronous for local CLI use).

    1. Runs keyword_screen() (instant, free).
    2. Falls back to local LLM only when ambiguous.

    Returns "CLINICAL", "INSURANCE", or "INVALID".
    """
    if not text or len(text.strip()) < 50:
        return "INVALID"

    verdict = keyword_screen(text)
    if verdict != "UNKNOWN":
        logger.info("classify: keyword verdict = %s", verdict)
        return verdict

    # Ambiguous -- ask the local LLM
    if llm is None:
        from nhcx_local.llm import get_llm
        llm = get_llm(temperature=0.3, max_tokens=10)

    try:
        response = llm.invoke([HumanMessage(
            content=_LLM_CLASSIFY_PROMPT.format(text=text[:2000])
        )])
        verdict = _parse_llm_response(response.content)
        logger.info("classify: LLM verdict = %s", verdict)
        return verdict
    except Exception as exc:
        logger.error("LLM classification failed: %s", exc)
        return "INVALID"
