"""
safe_harbor_detector.py

Content-based PHI detector for documents (PDF text), implementing the HIPAA
Safe Harbor de-identification standard — the 18 identifier categories.

Unlike the image pipeline (which scans modality-specific regions), this works
purely on TEXT CONTENT and is therefore position-independent: it finds patient
identifiers anywhere on a page — header, body, footer, repeated page banners —
without any hardcoded top/bottom assumptions.

It returns character spans within a line of text. The PDF redactor maps those
spans back to word rectangles and truly removes them (PyMuPDF redaction).

Design goals
------------
* High recall on identifiers (Safe Harbor demands removal of ALL of them).
* Preserve clinical content — test results, reference ranges, measurements,
  findings. Clinical values are short numbers near units / ranges and are NOT
  matched by the identifier rules below (which require labels, separators, or
  6+ digit runs that clinical counts do not reach in normal reports).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class Span:
    start: int
    end: int
    text: str
    label: str


# ── Honorifics → person names ────────────────────────────────────────────────
# "Mr RAJA SHETTY", "Dr MADHU SRINIVASARANGAN", "Dr. ARPITHA M R",
# "Dr.PALLAVI B R", "Dr. Jyothsana Harini Suma S P", "Smt / Shri ..."
_HONORIFIC_NAME = re.compile(
    r"\b(?i:Mr|Mrs|Ms|Miss|Master|Dr|Smt|Shri|Baby\s+of|B/O|S/O|D/O|W/O)\.?\s*"
    r"[A-Z][A-Za-z]*(?:[\s.]+[A-Z][A-Za-z]*){0,5}",
)

# ── Age / gender anchors ─────────────────────────────────────────────────────
# "69 Y/Male", "69Y / Female", "45 yrs / M", "23 years/Female"
_AGE_GENDER = re.compile(
    r"\b\d{1,3}\s*(?:Y|yr|yrs|year|years)\s*/\s*(?:Male|Female|M|F|Other)\b",
    re.IGNORECASE,
)
# Gender-first variant: "Male / 41 Y", "Female/45 Yrs"
_GENDER_AGE = re.compile(
    r"\b(?:Male|Female)\s*/\s*\d{1,3}\s*(?:Y|yr|yrs|year|years)\b",
    re.IGNORECASE,
)
_AGE_ONLY = re.compile(
    r"\b\d{1,3}\s*(?:years?|yrs?)\s*(?:old)?\b",
    re.IGNORECASE,
)
# Standalone demographic age notation: "41 Y", "69Y" (uppercase Y only)
_AGE_Y = re.compile(r"\b\d{1,3}\s*Y\b")

# ── Dates (all elements except a bare year) ─────────────────────────────────
# 18-03-2026, 18/03/2026, 18-03-26, 2026-03-18, 6/2/26
_DATE = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",
)
# 18 March 2026 / March 18, 2026 / 18-Mar-2026
_DATE_MONTHNAME = re.compile(
    r"\b(?:\d{1,2}[-\s])?"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"(?:[-\s]\d{1,2})?,?[-\s]\d{2,4}\b",
    re.IGNORECASE,
)

# ── Times (date elements indicative of an event) ────────────────────────────
_TIME = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b",
)

# ── Contact details ──────────────────────────────────────────────────────────
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
_IP = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/[^\s]*)?",
)
_URL = re.compile(
    r"\b(?:https?://[^\s]+|www\.[^\s]+|"
    r"[A-Za-z0-9.-]+\.(?:in|com|org|net|gov|edu|io|co|info)(?:/[^\s]*)?)\b",
)
# Indian + generic phone / fax: 0821-2335555, 0821 -2335555, +91 98765 43210
# Negative lookbehind for ; and : prevents matching journal citations (1995;302:1251-1256)
_PHONE = re.compile(
    r"(?<![\d;:])(?:\+?\d{1,3}[-\s]?)?(?:\(?\d{2,5}\)?[-\s]?)?\d{3,5}[-\s]?\d{4,8}(?!\d)",
)

# ── Organization / lab names ─────────────────────────────────────────────────
# "Sterling Accuris Pathology Laboratory", "City Hospital", "Medall Diagnostics"
_ORG_SUFFIX = re.compile(
    r"\b[A-Z][A-Za-z']+(?:[\s&]+[A-Z][A-Za-z']*)*\s+"
    r"(?:Laborator(?:y|ies)|Pathology|Diagnostics?|Hospital(?:s)?|Clinic(?:s)?|"
    r"Medical\s+Cent(?:re|er)|Healthcare|Health\s*Care|Institute|Foundation|"
    r"Imaging|Radiology|Pharmacy|College|University|Mission|Academy|"
    r"Medical\s+College|Nursing\s+Home)"
    r"(?:\s*&\s*[A-Za-z']+)*\b",
    re.IGNORECASE,
)

# ── Doctor credentials near names ───────────────────────────────────────────
# "Sanjeev Shah MD", "Pallavi B R MBBS", "Yash Shah M.D."
_CREDENTIAL_NAME = re.compile(
    r"\b[A-Z][A-Za-z]*(?:[\s.,]+[A-Z][A-Za-z]*)+\s*[.,]?\s*"
    r"(?i:MBBS|MD|MS|DNB|DM|MCh|M\.?D\.?|M\.?S\.?|FRCS|MRCP|DCH|DA|DGO|"
    r"FRCOG|FAIS|FRCPath|MRCPath|Ph\.?D|D\.?C\.?P\.?|D\.?O\.?|D\.?N\.?B\.?)\b",
)

# ── Department / section headers (identifiable org sub-units) ───────────
# "DEPARTMENT OF PATHOLOGY", "DEPT. OF HISTOPATHOLOGY"
_DEPT_HEADER = re.compile(
    r"\b(?:DEPARTMENT|DEPT\.?)\s+OF\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b",
    re.IGNORECASE,
)

# ── Standalone credentials (catch trailing "MD.,", "MBBS" after names) ──
_STANDALONE_CRED = re.compile(
    r"\b(?:MBBS|DNB|MCh|FRCS|MRCP|DCH|DGO|"
    r"FRCOG|FAIS|FRCPath|MRCPath|Ph\.?D|D\.?C\.?P\.?|D\.?O\.?|D\.?N\.?B\.?|"
    r"M\.D\.?|M\.S\.?)[.,]*\b",
    re.IGNORECASE,
)

# ── Identifiers ──────────────────────────────────────────────────────────────
# Indian PIN code: "570 004" / "570004"
_PIN = re.compile(r"\b\d{3}\s?\d{3}\b")
# Barcode-style markers: *4243169*
_BARCODE_NUM = re.compile(r"\*\s*\d{4,}\s*\*")
# Any long numeric run (registration/bill/request/account/MRN). Clinical counts
# in normal reports do not reach 6 digits, so this spares results.
_LONG_NUM = re.compile(r"(?<!\d)\d{6,}(?!\d)")
# Alphanumeric codes: OS0979, Os1181, ABC123456, MRN-00912
_ALNUM_CODE = re.compile(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z]{1,4}\d{3,}\b")
# Govt IDs
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# ── Label-anchored values ────────────────────────────────────────────────────
# Everything after one of these labels (up to the next label or end of line)
# is the identifier value and must be removed.
_LABELS = [
    "registration number", "registration no", "reg no", "reg number",
    "request number", "request no", "req no", "req number",
    "bill number", "bill no", "bill no / bill date",
    "mrn", "medical record", "uhid", "ip no", "op no", "ipd no", "opd no",
    "accession", "accession number", "account", "account number",
    "patient category", "category",
    "referred by", "referring", "requested by", "consultant", "physician",
    "ref by", "ref. by",
    "result entered by", "result verified by", "entered by", "verified by",
    "authorized by", "authorised by", "approved by", "checked by", "signed by",
    "name", "patient name", "patient", "mobile", "phone", "tel", "tel no",
    "fax", "email", "e-mail", "address", "specimen collected at",
    "health id", "abha", "insurance", "policy no", "member id", "beneficiary",
    "dob", "date of birth", "d.o.b", "birth date", "date",
    "sex", "gender", "age", "age/sex", "age / sex", "sex/age", "sex / age",
    "client", "client name", "client id",
    "lab", "lab name", "lab no", "lab no.", "laboratory",
    "centre", "center", "branch",
    "collected at", "reported at", "received at",
    "collected on", "received on", "reported on",
    "sample id", "sample no", "barcode no",
    "contact", "contact no", "website",
    "biopsy no", "biopsy no.", "biopsy. no", "biopsy number",
    "hospital no", "hospital no.", "hospital number",
    "reference no", "reference no.", "reference number",
    "bill no", "bill no.",
    "pathologist", "pathologists",
]
# A colon is REQUIRED after the label. This prevents a generic word like
# "Patient" inside a clinical sentence ("*Patient is not able to hold urine…")
# from being treated as a label and swallowing the finding text.
_LABEL_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(lbl) for lbl in sorted(_LABELS, key=len, reverse=True)) + r")\b\s*:\s*",
)

# Patient-category keywords sometimes appear standalone on their own line.
_CATEGORY_WORDS = {"general", "private", "corporate", "insurance", "camp", "staff", "vip"}

# Labels whose entire line-remainder is identifier data (no clinical content).
_FULL_LINE_LABELS = {
    "result entered by", "result verified by", "entered by", "verified by",
    "authorized by", "authorised by", "approved by", "checked by", "signed by",
    "referred by", "referring", "requested by", "consultant", "physician",
    "ref by", "ref. by",
    "address", "specimen collected at", "collected at",
    "client", "client name",
    "contact", "contact no", "website",
    "lab", "lab name", "laboratory",
    "centre", "center", "branch",
    "pathologist", "pathologists",
}


# ── Clinical allowlist (never redact these terms) ───────────────────────────
_CLINICAL_ALLOWLIST = {
    "haemoglobin", "hemoglobin", "haemoglobins", "hemoglobins",
    "platelet", "platelets", "lymphocyte", "lymphocytes",
    "neutrophil", "neutrophils", "monocyte", "monocytes",
    "eosinophil", "eosinophils", "basophil", "basophils",
    "erythrocyte", "erythrocytes", "leukocyte", "leukocytes",
    "creatinine", "bilirubin", "cholesterol", "triglyceride", "triglycerides",
    "glucose", "albumin", "globulin", "protein", "calcium",
    "sodium", "potassium", "chloride", "phosphorus", "magnesium",
    "urea", "uric", "insulin", "testosterone", "estrogen",
    "progesterone", "cortisol", "thyroxine", "triiodothyronine",
    "ferritin", "transferrin", "fibrinogen", "prothrombin",
    "hematocrit", "haematocrit", "reticulocyte", "reticulocytes",
    "immunoglobulin", "antibody", "antibodies", "antigen",
    "specimen", "reference", "normal", "abnormal", "positive",
    "negative", "reactive", "nonreactive", "testing", "tested",
    "method", "methodology", "technique", "analysis", "report",
    "result", "results", "finding", "findings", "impression",
    "conclusion", "recommendation", "comment", "comments",
    "note", "notes", "observation", "observations",
    "prostate", "kidney", "bladder", "liver", "pancreas",
    "thyroid", "pituitary", "adrenal", "serum", "plasma", "whole",
    "glycated", "glycosylated", "fasting", "random", "postprandial",
    "control", "controls", "quality", "poor", "good", "excellent",
    "diabetes", "diabetic", "diabetics", "prediabetes", "pre-diabetes",
    "screening", "biological", "interval", "target", "optimal",
    "hypertension", "hypotension", "hyperglycemia", "hypoglycemia",
    "anemia", "anaemia", "jaundice", "malaria", "dengue", "typhoid",
    "tuberculosis", "hepatitis", "cirrhosis", "pneumonia", "asthma",
    "cancer", "carcinoma", "melanoma", "lymphoma", "leukemia", "leukaemia",
    "benign", "malignant", "metastatic", "invasive", "noninvasive",
    "acute", "chronic", "severe", "moderate", "mild", "borderline",
    "elevated", "decreased", "increased", "reduced", "deficiency",
    "diagnosis", "diagnostic", "prognosis", "pathology", "pathological",
    "clinical", "subclinical", "asymptomatic", "symptomatic",
    "treatment", "therapy", "medication", "dosage", "dose",
    "surgery", "surgical", "procedure", "biopsy", "autopsy",
    "inflammation", "infection", "infectious", "bacterial", "viral",
    "congenital", "hereditary", "genetic", "autoimmune",
    "renal", "hepatic", "cardiac", "pulmonary", "cerebral", "vascular",
    "anterior", "posterior", "lateral", "medial", "proximal", "distal",
    "bilateral", "unilateral", "ipsilateral", "contralateral",
    "systolic", "diastolic", "pulse", "rhythm", "sinus",
    "volume", "count", "level", "ratio", "index", "value", "range",
    "total", "differential", "absolute", "relative", "mean", "average",
    "packed", "corpuscular", "sedimentation", "coagulation",
    "sensitivity", "specificity", "prevalence", "incidence",
    "complete", "partial", "preliminary", "final", "supplementary",
    "routine", "urgent", "stat", "repeat", "follow",
    "within", "above", "below", "high", "normal", "desirable",
    "acceptable", "unacceptable", "satisfactory", "unsatisfactory",
    "mellitus", "microalbuminuria", "albuminuria", "proteinuria",
    "nephropathy", "neuropathy", "retinopathy", "angiopathy",
    "hemoglobin", "haemoglobin", "glycosylated", "glycated",
    "insulin", "dependent", "independent", "resistant",
    "kidney", "renal", "glomerular", "filtration",
    "cardiovascular", "coronary", "arterial", "venous",
    "system", "testing", "variant", "biorad", "method",
    "foundation", "national", "scientific", "advisory",
    "board", "committee", "council", "society", "association",
    "management", "recommendations", "guidelines",
}

# ── Clinical context detector (lab result lines) ───────────────────────────
_CLINICAL_CONTEXT = re.compile(
    r"(?:g/dL|mg/dL|mmol|µmol|ng/mL|pg/mL|IU/L|U/L|mEq/L|cells/µL|"
    r"×10|x10|lakhs?|million|thou|/cumm|/cu\.?\s*mm|fl|fL|"
    r"reference|ref\.?\s*range|normal\s*range|biological\s*ref|"
    r"\d+\.?\d*\s*-\s*\d+\.?\d*\s*(?:g|mg|ng|µg|mmol|U|IU|%))",
    re.IGNORECASE,
)


def _is_clinical_line(text: str) -> bool:
    return bool(_CLINICAL_CONTEXT.search(text))


class SafeHarborDetector:
    """Detects HIPAA Safe Harbor identifiers in a line of document text."""

    def detect_spans(self, text: str) -> List[Span]:
        """Return all PHI character spans found in ``text`` (one line)."""
        spans: List[Span] = []

        def add(m: re.Match, label: str):
            s, e = m.start(), m.end()
            val = text[s:e].strip()
            if val:
                # Trim trailing/leading whitespace offsets
                lead = len(text[s:e]) - len(text[s:e].lstrip())
                trail = len(text[s:e]) - len(text[s:e].rstrip())
                spans.append(Span(s + lead, e - trail, text[s + lead:e - trail], label))

        # ── Strong, unambiguous patterns first ──────────────────────────────
        clinical = _is_clinical_line(text)

        for m in _EMAIL.finditer(text):        add(m, "EMAIL")
        for m in _URL.finditer(text):          add(m, "URL")
        for m in _IP.finditer(text):           add(m, "IP_ADDRESS")
        for m in _AADHAAR.finditer(text):      add(m, "AADHAAR")
        for m in _PAN.finditer(text):          add(m, "PAN")
        for m in _SSN.finditer(text):          add(m, "SSN")
        for m in _BARCODE_NUM.finditer(text):  add(m, "BARCODE")
        for m in _DATE.finditer(text):         add(m, "DATE")
        for m in _DATE_MONTHNAME.finditer(text): add(m, "DATE")
        for m in _TIME.finditer(text):         add(m, "TIME")
        for m in _AGE_GENDER.finditer(text):   add(m, "AGE_GENDER")
        for m in _GENDER_AGE.finditer(text):   add(m, "AGE_GENDER")
        for m in _AGE_Y.finditer(text):
            if not clinical:
                add(m, "AGE")
        for m in _AGE_ONLY.finditer(text):
            if not clinical:
                add(m, "AGE")
        for m in _HONORIFIC_NAME.finditer(text): add(m, "PERSON_NAME")
        for m in _ORG_SUFFIX.finditer(text):   add(m, "ORG_NAME")
        for m in _DEPT_HEADER.finditer(text):  add(m, "ORG_NAME")
        for m in _CREDENTIAL_NAME.finditer(text): add(m, "PERSON_NAME")
        for m in _STANDALONE_CRED.finditer(text):
            if not _overlaps(m.start(), m.end(), spans):
                add(m, "PERSON_NAME")
        for m in _LONG_NUM.finditer(text):
            if not clinical:
                add(m, "IDENTIFIER")
        for m in _ALNUM_CODE.finditer(text):   add(m, "IDENTIFIER")
        for m in _PIN.finditer(text):
            if not clinical:
                add(m, "ZIP")

        # ── Phone numbers (after the above, to avoid double-spanning dates) ──
        for m in _PHONE.finditer(text):
            # Skip if this run is already inside a date/id span
            if not _overlaps(m.start(), m.end(), spans):
                # Require at least 8 digits total to be a phone (not a 6-digit id)
                digits = sum(c.isdigit() for c in m.group())
                if digits >= 8 and not clinical:
                    add(m, "PHONE")

        # ── Label-anchored values (staff codes, category, names on same line) ─
        spans.extend(self._label_anchored(text))

        # ── Standalone patient-category line ────────────────────────────────
        stripped = text.strip()
        if stripped.lower() in _CATEGORY_WORDS:
            i = text.lower().index(stripped.lower())
            spans.append(Span(i, i + len(stripped), stripped, "PATIENT_CATEGORY"))

        return _merge_overlaps(spans)

    # ------------------------------------------------------------------

    def _label_anchored(self, text: str) -> List[Span]:
        """Capture the value following each PHI label up to the next label/EOL."""
        out: List[Span] = []
        matches = list(_LABEL_RE.finditer(text))
        for i, m in enumerate(matches):
            label_text = m.group(1).lower().strip()
            value_start = m.end()
            value_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            value = text[value_start:value_end]
            # Strip surrounding whitespace/punctuation
            lead = len(value) - len(value.lstrip(" :-\t"))
            stripped = value.strip(" :-\t")
            if not stripped:
                continue
            vs = value_start + lead
            ve = vs + len(stripped)
            # For "always-PHI" labels (staff codes, referrer, requester) the
            # entire remainder of the line is identifier data — capture it all.
            # For generic labels, cap the value length so we never swallow a
            # clinical sentence that may follow a label like "Patient".
            if label_text in _FULL_LINE_LABELS or len(stripped) <= 60:
                out.append(Span(vs, ve, stripped, "LABELED_PHI"))
        return out


# ── span helpers ─────────────────────────────────────────────────────────────

def _overlaps(s: int, e: int, spans: List[Span]) -> bool:
    return any(not (e <= sp.start or s >= sp.end) for sp in spans)


def _merge_overlaps(spans: List[Span]) -> List[Span]:
    """Merge overlapping/adjacent spans, keeping the most specific label."""
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    merged: List[Span] = [spans[0]]
    for sp in spans[1:]:
        last = merged[-1]
        if sp.start <= last.end:  # overlap or touch
            new_end = max(last.end, sp.end)
            label = last.label if last.label != "LABELED_PHI" else sp.label
            text = last.text if len(last.text) >= len(sp.text) else sp.text
            merged[-1] = Span(last.start, new_end, text, label)
        else:
            merged.append(sp)
    return merged
