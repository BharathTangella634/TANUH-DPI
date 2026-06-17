import json
import uuid
import operator
from typing import TypedDict, List, Dict, Annotated, Any
from langgraph.graph import StateGraph, END
# from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
import os
from datetime import datetime, timezone


# ---------------- STATE ----------------
class AgentState(TypedDict, total=False):
    text: str
    id_registry: Dict[str, Any]
    final_resources: Annotated[List[dict], operator.add]
    rulebook_paths: Dict[str, str]
    model: str           # frontend model selector value, propagated through the graph
    clinical_artifact: str  # which NHCX bundle type is being built

# ---------------- LLM ----------------
# llm = ChatOllama(model="qwen2.5:latest", temperature=0)
# llm = ChatOllama(model="deepseek-coder-v2", temperature=0)

# Dependency graph - what each resource needs
RESOURCE_DEPENDENCIES = {
    "Organization": [],
    "Patient": [],
    "Binary": [],
    "DocumentReference": ["Binary"],
    "InsurancePlan": ["Organization"],
    "HealthcareService": ["InsurancePlan"],
    "InsurancePlanBundle": ["InsurancePlan", "Organization"],
    "Claim": ["Organization", "Patient"],
    "ClaimBundle": ["Claim", "Organization", "Patient"],
    "ClaimResponse": ["Organization", "Patient"],
    "ClaimResponseBundle": ["ClaimResponse", "Organization", "Patient"],
    "CoverageEligibilityRequest": ["Organization", "Patient"],
    "CoverageEligibilityRequestBundle": ["CoverageEligibilityRequest", "Organization", "Patient"],
    "CoverageEligibilityResponse": ["Organization", "Patient"],
    "CoverageEligibilityResponseBundle": ["CoverageEligibilityResponse", "Organization", "Patient"],
    "Task": ["Organization"],
    "TaskBundle": ["Task", "Organization"],
}

# ── NHCX bundle-type constants (canonical source: nhcx_profiles.py) ──────────
from pdf2nhcx.utils.nhcx_profiles import (
    NHCX_BUNDLE_TYPES     as _NHCX_BUNDLE_TYPES,
    BUNDLE_PROFILES       as _BUNDLE_PROFILES,
    BUNDLE_PRIMARY_RESOURCE as _BUNDLE_PRIMARY_RESOURCE,
    BUNDLE_MUST_RESOURCES as _BUNDLE_MUST_RESOURCES,
    get_must_resources,
    get_allowed_supporting,
)
# Re-export get_must_resources so existing callers don't break
__all__ = ["get_must_resources"]


from dotenv import load_dotenv
import os

# Load .env for local development (Docker injects vars via env_file)
_here = os.path.dirname(__file__)
for _candidate in [
    os.path.join(_here, "../../.env"),
    os.path.join(_here, "../.env"),
    "/.env",
    "/app/.env",
]:
    if os.path.isfile(_candidate):
        load_dotenv(dotenv_path=_candidate)
        break
else:
    load_dotenv()

_PROJECT_ID = os.getenv("PROJECT_ID", "proj-dpi-shared")
_REGION     = os.getenv("REGION", "global")
_ENDPOINT   = os.getenv("ENDPOINT", "aiplatform.googleapis.com")

# ── Authentication ───────────────────────────────────────────────────────────
# Priority 1: Google Application Default Credentials (ADC)
#   - Works automatically on GCP VMs via metadata server
#   - Run 'gcloud auth application-default login' for local dev
# Priority 2: API_KEY from .env (for local/testing)

_cached_credentials = None

# ── LLM client cache (thread-safe, 55-min TTL) ───────────────────────────────
import threading as _threading
import time as _time
_llm_cache: dict = {}
_llm_cache_ts: dict = {}
_llm_cache_lock = _threading.Lock()
_LLM_CACHE_TTL = 3300  # 55 minutes

# ── Per-resource token limits ───────────────────────────────────────────────
_RESOURCE_TOKEN_LIMITS: dict = {
    "Patient": 2048, "Practitioner": 2048, "PractitionerRole": 1024,
    "Organization": 2048, "Appointment": 1024, "Specimen": 1024,
    "Encounter": 2048, "AllergyIntolerance": 1024, "Immunization": 1024,
    "FamilyMemberHistory": 1024, "MedicationRequest": 2048,
    "MedicationStatement": 2048, "Medication": 1024, "ServiceRequest": 1024,
    "Condition": 4096, "Procedure": 4096, "Observation": 4096,
    "DiagnosticReportLab": 4096, "DiagnosticReport": 4096, "ImagingStudy": 2048,
    "DocumentReference": 4096, "Binary": 1024, "Composition": 8192, "Bundle": 8192,
    "InsurancePlan": 8192, "InsurancePlanBundle": 8192,
    "Coverage": 4096, "Claim": 4096, "ClaimResponse": 4096,
    "Task": 2048, "Communication": 1024, "CommunicationRequest": 1024,
    "PaymentNotice": 1024, "PaymentReconciliation": 2048,
}

def _get_vertex_token() -> str:
    """Return a fresh OAuth2 access token via ADC, or fall back to API_KEY."""
    global _cached_credentials
    try:
        import google.auth
        import google.auth.transport.requests
        if _cached_credentials is None:
            _cached_credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        _cached_credentials.refresh(google.auth.transport.requests.Request())
        return _cached_credentials.token
    except Exception as e:
        fallback = os.getenv("API_KEY", "")
        print(f"⚠️  ADC unavailable ({e}), falling back to API_KEY env var")
        return fallback

# ── Model ─────────────────────────────────────────────────────────────────
MODEL_MAP = {
    "gemma4": "publishers/google/models/gemma-4-26b-a4b-it-maas",
}
_DEFAULT_MODEL = "gemma4"

def get_llm(model: str = _DEFAULT_MODEL, max_tokens: int = 4096):
    """
    Return a cached ChatGoogleGenerativeAI client (55-min TTL).
    Temperature 0.1 — faster + more reliable JSON than 0.7.
    """
    cache_key = (model, max_tokens)
    now = _time.monotonic()
    with _llm_cache_lock:
        if cache_key in _llm_cache and now - _llm_cache_ts[cache_key] < _LLM_CACHE_TTL:
            return _llm_cache[cache_key]
    _get_vertex_token()
    vertex_model = MODEL_MAP.get(model, MODEL_MAP[_DEFAULT_MODEL])
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=vertex_model,
        project=_PROJECT_ID,
        location="global",
        temperature=0.3,
        max_output_tokens=max_tokens,
        credentials=_cached_credentials,
    )
    with _llm_cache_lock:
        _llm_cache[cache_key] = llm
        _llm_cache_ts[cache_key] = now
    return llm

def check_llm_health():
    """Verify that we can at least get a token or the API_KEY is set."""
    token = _get_vertex_token()
    if token and len(token) > 10:
        return True, "ok"
    return False, "auth_failed"

# get_must_resources is imported from pdf2nhcx.utils.nhcx_profiles above
# ---------------- JSON EXTRACTION ----------------
def extract_json(text: str):
    if not text or not text.strip():
        return None
    
    # Remove markdown code blocks
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    decoder = json.JSONDecoder()
    idx = 0
    
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text[idx:])
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except:
                    pass
            return obj
        except json.JSONDecodeError:
            idx += 1
    return None

# ---------------- NORMALIZE FUNCTIONS ----------------
def ensure_id(resource):
    if not isinstance(resource, dict):
        return resource
    if "id" not in resource or not resource["id"]:
        resource["id"] = str(uuid.uuid4())
    return resource

def normalize_resource_output(res, resource_type):
    """Convert any input to single dict or list of dicts."""
    if isinstance(res, str):
        parsed = extract_json(res)
        if parsed:
            res = parsed
    
    if isinstance(res, dict):
        return [res]
    elif isinstance(res, list):
        return res
    else:
        # Create minimal resource
        return [{
            "resourceType": resource_type,
            "id": str(uuid.uuid4()),
            "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}
        }]

def get_single_resource(resources_list, resource_type):
    """Get first valid resource from list."""
    for res in resources_list:
        if isinstance(res, dict) and res.get("resourceType") == resource_type:
            return res
    # Return first item or create new
    if resources_list:
        res = resources_list
        if isinstance(res, dict):
            res["resourceType"] = resource_type
            return res
    return {
        "resourceType": resource_type,
        "id": str(uuid.uuid4()),
        "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}
    }

# ---------------- CORE AGENT FUNCTION ----------------
# ── Per-bundle LLM prompt prefix ─────────────────────────────────────────────
# These are prepended to the extraction prompt BEFORE the rulebook to give
# the LLM clear context about what it is extracting and what NOT to emit.
_BUNDLE_PROMPT_PREFIX = {
    "InsurancePlanBundle": (
        "You are extracting an insurance POLICY DOCUMENT — not a patient medical record "
        "and not a claim or eligibility workflow resource.\n"
        "Policy terms such as 'Congenital Anomaly', 'Pre-existing Disease', 'Acute Illness', "
        "'Waiting Period', and 'Exclusion' are POLICY DEFINITIONS. "
        "Encode them inside InsurancePlan.coverage.benefit, coverage.exclusion, or "
        "InsurancePlan.coverage.benefit.requirement — NEVER as Condition resources.\n"
        "Encode sum insured, limits, tiers, and costs strictly inside InsurancePlan.coverage.benefit.limit "
        "using 'value' (Quantity) and 'code' (CodeableConcept), or inside InsurancePlan.coverage.benefit.cost.\n"
        "DO NOT emit Condition, Claim, ClaimResponse, Task, CoverageEligibilityRequest, "
        "CoverageEligibilityResponse, PractitionerRole, or Patient resources.\n"
        "DO NOT nest a Bundle inside another Bundle. Emit InsurancePlan and Organization "
        "as flat top-level entries in a single collection Bundle."
    ),
    "ClaimBundle": (
        "You are extracting a CLAIM SUBMISSION document for a specific patient encounter.\n"
        "Include Condition ONLY if the source text contains a confirmed patient diagnosis "
        "that supports the claim (e.g. ICD-10 code or clinical description of the condition treated).\n"
        "DO NOT emit InsurancePlan, CoverageEligibilityResponse, or Task resources."
    ),
    "ClaimResponseBundle": (
        "You are extracting a CLAIM ADJUDICATION RESPONSE from a payer.\n"
        "Focus on ClaimResponse, adjudication details, payment notices, and reconciliation.\n"
        "DO NOT emit Condition, Procedure, InsurancePlan, CoverageEligibilityRequest, or Task resources."
    ),
    "CoverageEligibilityRequestBundle": (
        "You are extracting a COVERAGE ELIGIBILITY REQUEST to a payer.\n"
        "Include Coverage and InsurancePlan references only if explicitly present.\n"
        "DO NOT emit Claim, ClaimResponse, CoverageEligibilityResponse, Task, "
        "Condition, or Procedure resources."
    ),
    "CoverageEligibilityResponseBundle": (
        "You are extracting a COVERAGE ELIGIBILITY RESPONSE from a payer.\n"
        "Focus on CoverageEligibilityResponse, benefit details, coverage, and InsurancePlan.\n"
        "DO NOT emit Claim, ClaimResponse, Task, Condition, or Procedure resources."
    ),
    "TaskBundle": (
        "You are extracting a WORKFLOW TASK document (e.g. document request, payment status check).\n"
        "Task.focus should reference the relevant Claim or eligibility resource.\n"
        "DO NOT emit InsurancePlan, Condition, or Procedure resources."
    ),
}

def run_extraction_agent(state: AgentState, resource_type: str,
                         model: str = _DEFAULT_MODEL,
                         fhir_type: str = None):
    """
    resource_type : key used for rulebook lookup (e.g. "ClaimBundle")
    fhir_type     : FHIR resourceType written into the prompt (e.g. "Bundle");
                    defaults to resource_type when not provided.
    """
    rulebook_path = state['rulebook_paths'].get(resource_type)
    rulebook_content = ""
    if rulebook_path and os.path.exists(rulebook_path):
        with open(rulebook_path, 'r', encoding='utf-8') as f:
            rulebook_content = f.read()

    prompt_type = fhir_type if fhir_type else resource_type

    # Bundle-type-specific context prefix (drives what the LLM should and should NOT emit)
    clinical_artifact = state.get("clinical_artifact", "")
    _prefix = _BUNDLE_PROMPT_PREFIX.get(clinical_artifact, "")
    _prefix_block = f"BUNDLE CONTEXT:\n{_prefix}\n\n" if _prefix else ""

    prompt = f'''
    ACT AS an expert NHCX FHIR Data Architect. 

{_prefix_block}EXTRACT ONLY a valid HL7 FHIR R4 {prompt_type} resource (or a Bundle containing multiple resources) from the provided technical insurance text.

RULEBOOK (STRUCTURE GUIDANCE):
{rulebook_content}

INSURANCE POLICY TEXT (DISTILLED):
{state["text"]}

STRICT REQUIREMENTS (NON-NEGOTIABLE):
• Output MUST be valid JSON only.
• Output MUST start with "{{" or "[".
• DO NOT output markdown code fences (e.g., no ```json), no preamble, no comments, and no explanations.
• DO NOT hallucinate or infer missing data. If a field (like TPA name or specific Co-pay) is not in the text, OMIT IT.
• Extract ONLY information explicitly present in the provided text.
• Omit any field whose value is not clearly present.

NHCX + ABDM CONSTRAINTS:
• Conform to NHCX (National Health Claims Exchange) and ABDM profiling expectations.
• Resource Type: If extracting multiple linked resources, wrap them in a Bundle of type "collection".
• Identifiers: Every resource MUST contain an "id" as a UUID string (RFC-4122 format).
• Use the Product UIN (e.g., ADIHLGP22023V032122) as the business 'identifier' for the InsurancePlan resource.
• DO NOT include empty objects, empty arrays, or null values.
• DO NOT nest a Bundle inside another Bundle.

TERMINOLOGY & CODING RULES:
• Use IRDAI Standard Exclusion Codes (e.g., Excl03, Excl04) for exclusions.
• Use SNOMED CT for clinical conditions (e.g., Cancer, Myocardial Infarction) if coding is required.
• System URLs:
  - IRDAI Exclusions -> [https://irdai.gov.in/exclusions](https://irdai.gov.in/exclusions)
  - SNOMED CT -> [http://snomed.info/sct](http://snomed.info/sct)
• If no explicit code exists in the text, use only the "text" attribute within the CodeableConcept.
• NEVER fabricate codes.
• The string "collection" is ONLY valid as Bundle.type — never use it as a code, display, or text in a CodeableConcept.

REFERENCE & LINKING RULES:
• Use URN UUID references for internal Bundle linking: "reference": "urn:uuid:<uuid-here>".
• The InsurancePlan resource MUST reference the 'Organization' (Payer) via the .ownedBy element.
• The InsurancePlan resource SHOULD reference 'Location' resources for network/excluded hospitals if data is present.
• Only create references explicitly justified by the text.

DATA ACCURACY RULES:
• Preserve numeric precision exactly (e.g., 7.5 dioptres, 150% pay-out).
• Preserve all currency values (INR) and time-based limits (Waiting Periods) exactly.
• Ensure "Exclusions" are mapped correctly to either the general plan level or specific benefit level.

OUTPUT FORMAT:
Return ONLY the JSON resource(s) for {prompt_type}.
'''

    try:
        _max_tok = _RESOURCE_TOKEN_LIMITS.get(resource_type, 4096)
        fresh_llm = get_llm(state.get('model', _DEFAULT_MODEL), max_tokens=_max_tok)
        response = fresh_llm.invoke([HumanMessage(content=prompt)])
        raw_output = response.content.strip()
        print(f"\n🔍 Raw output for {resource_type}:\n{raw_output[:500]}...")

        parsed = extract_json(raw_output)
        if parsed:
            return parsed

        print(f"⚠️ Could not parse JSON for {resource_type}")

    except Exception as e:
        print(f"❌ Error for {resource_type}: {e}")

    # Fallback minimal resource
    return [{
        "resourceType": prompt_type,
        "id": str(uuid.uuid4()),
        "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}
    }]



_node_cache = {}

def create_insurance_node(resource_type: str):
    """
    Factory for NHCX graph nodes.
    All bundle types in _NHCX_BUNDLE_TYPES are extracted as a FHIR Bundle
    with the correct NHCX profile; individual resources are extracted as-is.
    """
    if resource_type in _node_cache:
        return _node_cache[resource_type]

    def node(state: AgentState):
        model = state.get('model', _DEFAULT_MODEL)
        is_bundle_type = resource_type in _NHCX_BUNDLE_TYPES

        if is_bundle_type:
            actual_resource_type = "Bundle"
            bundle_profile = _BUNDLE_PROFILES[resource_type]
        else:
            actual_resource_type = resource_type
            bundle_profile = None

        # Pass resource_type for rulebook lookup; fhir_type drives the prompt
        resources = run_extraction_agent(
            state, resource_type, model,
            fhir_type=actual_resource_type if is_bundle_type else None
        )
        resources = normalize_resource_output(resources, actual_resource_type)

        if isinstance(resources, list):
            safe_resources = []
            max_items = 1 if is_bundle_type else 15
            for res in resources[:max_items]:
                if isinstance(res, dict):
                    if res.get("resourceType") != actual_resource_type:
                        res["resourceType"] = actual_resource_type
                    if is_bundle_type:
                        res.setdefault('meta', {})['profile'] = [bundle_profile]
                        res['type'] = 'collection'
                    res = ensure_id(res)
                    payer_id = state['id_registry'].get('organization_id')
                    if payer_id and resource_type == "InsurancePlan":
                        res['ownedBy'] = {'reference': f'urn:uuid:{payer_id}'}
                    safe_resources.append(res)
            result = safe_resources
        else:
            result = get_single_resource([resources], actual_resource_type)
            result = ensure_id(result)
            if is_bundle_type:
                result.setdefault('meta', {})['profile'] = [bundle_profile]
                result['type'] = 'collection'
            payer_id = state['id_registry'].get('organization_id')
            if payer_id and resource_type == "InsurancePlan":
                result['ownedBy'] = {'reference': f'urn:uuid:{payer_id}'}

        # ID registration
        if isinstance(result, list):
            state['id_registry'][f'{resource_type.lower()}_refs'] = [
                {'reference': f'urn:uuid:{r["id"]}'} for r in result
            ]
            if resource_type == "Organization" and result:
                state['id_registry']['organization_id'] = result[0]['id']
        else:
            state['id_registry'][f'{resource_type.lower()}_id'] = result['id']
            if resource_type == "Organization":
                state['id_registry']['organization_id'] = result['id']

        count = len(result) if isinstance(result, list) else 1
        print(f"✅ {resource_type}: {count} {'Bundle' if is_bundle_type else resource_type}")
        return {"final_resources": [result] if isinstance(result, list) else [result]}

    node.__name__ = f"{resource_type.lower()}_node"
    _node_cache[resource_type] = node
    return node

# ✅ CLEAR CACHE BETWEEN WORKFLOWS (if needed)
def clear_node_cache():
    global _node_cache
    _node_cache = {}



def insurance_assembly_node(state):
    """
    Assembles the final NHCX bundle.
    Order: primary anchor resource FIRST, supporting resources MIDDLE, DocumentReference/Binary LAST.
    Works generically for all NHCX bundle types (ClaimBundle, TaskBundle, etc.).
    """
    import uuid
    from datetime import datetime, timezone

    # Determine bundle type from state (defaults to InsurancePlanBundle for backward compat)
    clinical_artifact = state.get("clinical_artifact", "InsurancePlanBundle")
    bundle_profile = _BUNDLE_PROFILES.get(
        clinical_artifact,
        _BUNDLE_PROFILES["InsurancePlanBundle"]
    )
    # The primary anchor resource type that should appear first in entries
    primary_resource_type = _BUNDLE_PRIMARY_RESOURCE.get(clinical_artifact, "InsurancePlan")

    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"profile": [bundle_profile]},
        "type": "collection",   # All NHCX bundles must be type=collection
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": []
    }

    # STEP 1: Find and add the primary anchor resource FIRST
    primary_found = False
    seen_ids = set()

    for resources_list in state["final_resources"]:
        if isinstance(resources_list, list):
            for res in resources_list:
                if isinstance(res, dict) and res.get('resourceType') == primary_resource_type:
                    bundle["entry"].insert(0, {
                        "fullUrl": f"urn:uuid:{res['id']}",
                        "resource": res
                    })
                    seen_ids.add(res['id'])
                    primary_found = True
                    print(f"✅ {primary_resource_type} ({res['id']}) added FIRST")
                    break
        if primary_found:
            break

    # STEP 2: Categorize remaining resources
    supporting_entries = []
    attachment_entries = []

    for resources_list in state["final_resources"]:
        if not isinstance(resources_list, list):
            resources_list = [resources_list]
        for r in resources_list:
            if not isinstance(r, dict) or r.get('id') in seen_ids:
                continue
            resource_type = r.get('resourceType')
            entry = {"fullUrl": f"urn:uuid:{r['id']}", "resource": r}
            if resource_type in ['DocumentReference', 'Binary']:
                attachment_entries.append(entry)
            else:
                supporting_entries.append(entry)
            seen_ids.add(r['id'])

    # STEP 3: Assemble in order
    bundle["entry"].extend(supporting_entries)
    bundle["entry"].extend(attachment_entries)

    print(f"✅ {clinical_artifact} assembled: {len(bundle['entry'])} total resources.")
    print(f"📊 1 {primary_resource_type}, {len(supporting_entries)} supporting, {len(attachment_entries)} attachments.")

    return {"final_resources": [bundle]}
def build_insurance_workflow(clinical_artifact: str, selected_other_resources: List[str], rulebook_paths: Dict[str, str]):
    # 1. Get mandatory resources for InsurancePlanBundle (Organization, InsurancePlan, etc.)
    must_resources = get_must_resources(clinical_artifact)
    
    # 2. Filter out duplicates
    selected_other_resources = [res for res in selected_other_resources if res not in must_resources]
    all_resources = list(set(must_resources + selected_other_resources))
    
    # Ensure the main artifact (InsurancePlanBundle) is included if not already
    if clinical_artifact not in all_resources:
        all_resources.append(clinical_artifact)
    
    print(f"📋 NHCX Workflow for {clinical_artifact}: {all_resources}")
    
    workflow = StateGraph(AgentState)
    
    # ✅ CREATE NODES
    created_nodes = set()
    for resource in all_resources:
        node_name = resource.lower()
        if node_name not in created_nodes:
            # Using the insurance factory function we created earlier
            node_func = create_insurance_node(resource) 
            workflow.add_node(node_name, node_func)
            created_nodes.add(node_name)
            print(f"✅ Added node: {node_name}")
    
    # 3. Topological sort (Uses your RESOURCE_DEPENDENCIES)
    def topological_sort(resources):
        visited = set()
        order = []
        def visit(resource):
            if resource in visited: return
            visited.add(resource)
            for dep in RESOURCE_DEPENDENCIES.get(resource, []):
                if dep in resources:
                    visit(dep)
            order.append(resource)
        for resource in resources:
            visit(resource)
        return order
    
    resource_order = topological_sort(all_resources)
    print(f"📊 Execution order: {[r.lower() for r in resource_order]}")
    
    # 4. Create Edges
    for i in range(len(resource_order) - 1):
        current = resource_order[i].lower()
        next_node = resource_order[i + 1].lower()
        workflow.add_edge(current, next_node)
        print(f"➡️  Edge: {current} → {next_node}")
    
    # 5. Assembly Node (Using the insurance_assembly_node created earlier)
    workflow.add_node("assembly", insurance_assembly_node)
    last_node = resource_order[-1].lower()
    workflow.add_edge(last_node, "assembly")
    workflow.add_edge("assembly", END)
    
    # ✅ FIX: Dynamic Entry Point
    # In NHCX, 'organization' (the Payer) is usually the best starting point
    if "organization" in created_nodes:
        workflow.set_entry_point("organization")
    else:
        # Fallback to the first resource in the sorted order
        workflow.set_entry_point(resource_order[0].lower())
    
    return workflow.compile(), all_resources

import json

def sanitize_fhir_resource(resource):
    res_type = resource.get("resourceType")
    if not res_type: return

    # Recurse into nested Bundles
    if res_type == "Bundle":
        for entry in resource.get("entry", []):
            if "resource" in entry:
                sanitize_fhir_resource(entry["resource"])
        return

    # Recurse into contained resources
    if "contained" in resource and isinstance(resource["contained"], list):
        for contained_res in resource["contained"]:
            sanitize_fhir_resource(contained_res)

    # 1. 'entry' is ONLY valid on Bundle
    if res_type != "Bundle" and "entry" in resource:
        del resource["entry"]
        
    # Remove hallucinated fields
    if "entity" in resource: del resource["entity"]
    if "permission" in resource: del resource["permission"]

    # ── Guard: "collection" must never appear as a coding code, display, or text ──
    # Bundle.type = "collection" sometimes leaks into CodeableConcept codings
    # and also into bare "display" fields on references or resources.
    _INVALID_CODING_CODES = {"collection", "document", "transaction", "batch", "history",
                              "searchset", "message"}

    def _clean_codeable_concept(cc):
        """Remove 'collection' (and other Bundle.type strings) from CodeableConcept."""
        if not isinstance(cc, dict):
            return
        for coding in cc.get("coding", []):
            if isinstance(coding, dict):
                if coding.get("code") in _INVALID_CODING_CODES:
                    coding.pop("code", None)
                if coding.get("display") in _INVALID_CODING_CODES:
                    coding.pop("display", None)
        if isinstance(cc.get("text"), str) and cc["text"].lower() in _INVALID_CODING_CODES:
            cc.pop("text", None)

    def _deep_clean_codings(obj, _parent_key=None):
        """Walk all dict values, scrub 'collection' from CodeableConcept shapes AND bare display fields."""
        if isinstance(obj, dict):
            # If this dict itself is a CodeableConcept, clean it
            if "coding" in obj or "text" in obj:
                _clean_codeable_concept(obj)
            # Bare "display" field containing a Bundle.type string (common on references)
            if "display" in obj and isinstance(obj["display"], str) and obj["display"].lower() in _INVALID_CODING_CODES:
                obj.pop("display", None)
            for k, v in list(obj.items()):
                _deep_clean_codings(v, _parent_key=k)
        elif isinstance(obj, list):
            for item in obj:
                _deep_clean_codings(item, _parent_key=_parent_key)

    _deep_clean_codings(resource)

    # ── Guard: placeholder names on InsurancePlan / Organization ─────────────
    _PLACEHOLDERS = {
        "Unknown InsurancePlan", "Unknown Organization", "Unknown Patient",
        "Unknown Practitioner", "Unknown Condition", "Unknown Procedure",
    }
    if res_type in {"InsurancePlan", "Organization"} and resource.get("name") in _PLACEHOLDERS:
        # If we also have no identifier, remove the placeholder name entirely
        if not resource.get("identifier"):
            resource.pop("name", None)
            print(f"⚠️  Removed placeholder name from {res_type} (no real data available)")
        
    # 2. 'type' formatting
    if res_type in ["Organization", "InsurancePlan"] and "type" in resource:
        system_url = "http://terminology.hl7.org/CodeSystem/organization-type" if res_type == "Organization" else "http://terminology.hl7.org/CodeSystem/insurance-plan-type"
        if isinstance(resource["type"], str):
            code = "pay" if res_type == "Organization" else "medical"
            resource["type"] = [{"coding": [{"system": system_url, "code": code, "display": resource["type"]}]}]
        elif isinstance(resource["type"], dict):
            resource["type"] = [resource["type"]]
        elif isinstance(resource["type"], list):
            # Fix hallucinated 'insurance' code for Organization
            for t in resource["type"]:
                if "coding" in t and isinstance(t["coding"], list):
                    for c in t["coding"]:
                        if res_type == "Organization" and c.get("code") == "insurance":
                            c["code"] = "pay"
                            c["system"] = system_url
                        elif res_type == "InsurancePlan" and c.get("code") == "medical":
                            c["system"] = system_url
            
    if res_type == "DocumentReference":
        if resource.get("status") not in ["current", "superseded", "entered-in-error"]:
            resource["status"] = "current"
        # DocumentReference.type must be a valid CodeableConcept, not bare text
        doc_type = resource.get("type")
        if not isinstance(doc_type, dict) or ("coding" not in doc_type and "text" not in doc_type):
            resource["type"] = {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "419891008",
                    "display": "Record artifact",
                }],
                "text": "Insurance Document",
            }
        elif isinstance(doc_type, dict) and "text" in doc_type and "coding" not in doc_type:
            # Has text but no coding — add the SNOMED coding
            doc_type["coding"] = [{
                "system": "http://snomed.info/sct",
                "code": "419891008",
                "display": "Record artifact",
            }]
        if isinstance(resource.get("type"), list):
            resource["type"] = resource["type"][0] if len(resource["type"]) > 0 else {}
        # docStatus — ReferredDocumentStatus value set
        # Valid codes: preliminary | final | amended | entered-in-error
        if "docStatus" in resource:
            _DOC_STATUS_MAP = {
                "completed": "final",
                "complete":  "final",
                "done":      "final",
                "approved":  "final",
                "draft":     "preliminary",
                "active":    "preliminary",
                "pending":   "preliminary",
                "revised":   "amended",
                "updated":   "amended",
                "cancelled": "entered-in-error",
                "error":     "entered-in-error",
            }
            _VALID_DOC_STATUS = {"preliminary", "final", "amended", "entered-in-error"}
            ds = resource["docStatus"]
            if ds not in _VALID_DOC_STATUS:
                resource["docStatus"] = _DOC_STATUS_MAP.get(ds, "final")

    # 3. 'ownedBy' in InsurancePlan must be a Reference (an object), not an array.
    if res_type == "InsurancePlan" and "ownedBy" in resource:
        if isinstance(resource["ownedBy"], list):
            resource["ownedBy"] = resource["ownedBy"][0] if len(resource["ownedBy"]) > 0 else {}

    # 4. Clean up InsurancePlan hallucinations and enforce FHIR R4 schema
    if res_type == "InsurancePlan":
        if "benefit" in resource: del resource["benefit"]
        if "note" in resource: del resource["note"]

        # ── Move top-level 'exclusion' and coverage.exclusion into NRCeS Claim-Exclusion extension ──
        # InsurancePlan.coverage.exclusion does not exist in FHIR R4.
        # NRCeS defines Claim-Exclusion extension: https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim-Exclusion
        _CLAIM_EXCLUSION_URL = "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim-Exclusion"

        def _exclusion_to_extension(exclusion_item) -> dict:
            """Convert one exclusion item (dict or str) to a Claim-Exclusion extension."""
            ext = {"url": _CLAIM_EXCLUSION_URL, "extension": []}
            if isinstance(exclusion_item, dict):
                text = exclusion_item.get("text") or exclusion_item.get("description") or ""
                code = exclusion_item.get("code") or exclusion_item.get("type")
                if text:
                    ext["extension"].append({"url": "statement", "valueString": str(text)})
                if isinstance(code, dict):
                    ext["extension"].append({"url": "item", "valueCodeableConcept": code})
                elif isinstance(code, str):
                    ext["extension"].append({"url": "item", "valueCodeableConcept": {"text": code}})
                elif text and not code:
                    ext["extension"].append({"url": "item", "valueCodeableConcept": {"text": str(text)}})
            elif isinstance(exclusion_item, str):
                ext["extension"].append({"url": "statement", "valueString": exclusion_item})
                ext["extension"].append({"url": "item", "valueCodeableConcept": {"text": exclusion_item}})
            return ext if ext["extension"] else None

        all_exclusions = []

        # Collect from top-level 'exclusion' (hallucinated)
        if "exclusion" in resource:
            excls = resource.pop("exclusion")
            if isinstance(excls, list):
                all_exclusions.extend(excls)
            elif isinstance(excls, (dict, str)):
                all_exclusions.append(excls)

        # Collect from coverage[].exclusion (also not FHIR R4)
        for cov in resource.get("coverage", []):
            if "exclusion" in cov:
                excls = cov.pop("exclusion")
                if isinstance(excls, list):
                    all_exclusions.extend(excls)
                elif isinstance(excls, (dict, str)):
                    all_exclusions.append(excls)

        # Convert to NRCeS Claim-Exclusion extensions
        if all_exclusions:
            resource.setdefault("extension", [])
            for excl in all_exclusions:
                ext = _exclusion_to_extension(excl)
                if ext:
                    resource["extension"].append(ext)
            print(f"✅ Moved {len(all_exclusions)} exclusion(s) to NRCeS Claim-Exclusion extensions")

        # ── Fix coverage[].benefit[] fields ──
        for cov in resource.get("coverage", []):
            if "description" in cov: del cov["description"]
            if "type" not in cov:
                cov["type"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/insurance-plan-type", "code": "medical"}]}
            if "benefit" not in cov or not isinstance(cov["benefit"], list) or len(cov["benefit"]) == 0:
                cov["benefit"] = [{"type": {"coding": [{"code": "benefit"}]}}]
            if isinstance(cov["benefit"], list):
                for ben in cov["benefit"]:
                    # claimable does not exist in FHIR R4
                    ben.pop("claimable", None)
                    # description is not a valid field on benefit
                    ben.pop("description", None)

                    # Ensure limit has correct structure if it exists
                    if "limit" in ben and not isinstance(ben["limit"], list):
                        ben["limit"] = [ben["limit"]]
                    
                    if "limit" in ben:
                        valid_limits = []
                        for limit_item in ben["limit"]:
                            if isinstance(limit_item, dict):
                                # Must have value (Quantity) or code (CodeableConcept)
                                if "value" in limit_item or "code" in limit_item:
                                    valid_limits.append(limit_item)
                        if valid_limits:
                            ben["limit"] = valid_limits
                        else:
                            ben.pop("limit", None)

                    # requirement must be a string, not an array of objects
                    req = ben.get("requirement")
                    if isinstance(req, list):
                        # Extract text from array-of-objects: [{"text": "..."}] -> "..."
                        texts = []
                        for item in req:
                            if isinstance(item, dict):
                                t = item.get("text") or item.get("description") or str(item)
                                texts.append(str(t))
                            elif isinstance(item, str):
                                texts.append(item)
                        ben["requirement"] = "; ".join(texts) if texts else None
                        if not ben["requirement"]:
                            ben.pop("requirement", None)
                    elif isinstance(req, dict):
                        # Single object -> extract text
                        ben["requirement"] = req.get("text") or req.get("description") or str(req)

        if "identifier" in resource and isinstance(resource["identifier"], list):
            for ident in resource["identifier"]:
                if ident.get("system") == "uin":
                    ident["system"] = "https://irdai.gov.in/uin"

    # 5. Fix missing required fields using 'display' instead of 'reference' to bypass resolution errors
    if res_type == "Procedure":
        if "status" not in resource: resource["status"] = "completed"
        if "subject" not in resource: resource["subject"] = {"display": "Unknown Patient"}
            
    if res_type == "ImagingStudy":
        if resource.get("status") not in ["registered", "available", "cancelled", "entered-in-error", "unknown"]:
            resource["status"] = "available"
            
    if res_type == "Coverage":
        if "status" not in resource: resource["status"] = "active"
        if "beneficiary" not in resource: resource["beneficiary"] = {"display": "Unknown Patient"}
        if "payor" not in resource: resource["payor"] = [{"display": "Unknown Organization"}]
            
    if res_type in ["Organization", "InsurancePlan"]:
        if "name" not in resource and "identifier" not in resource:
            resource["name"] = "Unknown " + res_type
            
    # 6. Composition fields
    if res_type == "Composition":
        if "author" not in resource or resource["author"] is None:
            resource["author"] = [{"display": "Unknown Author"}]
        elif not isinstance(resource["author"], list):
            resource["author"] = [resource["author"]]
            
        for sec in resource.get("section", []):
            if "status" in sec: del sec["status"]
            if "text" in sec and isinstance(sec["text"], str):
                sec["text"] = {"status": "generated", "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{sec['text']}</div>"}
            elif "text" not in sec and "entry" not in sec:
                sec["text"] = {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">No content</div>"}

    # 7. Practitioner qualification
    if res_type == "Practitioner":
        for qual in resource.get("qualification", []):
            if "text" in qual:
                if "code" not in qual: qual["code"] = {"text": qual["text"]}
                del qual["text"]
            if "code" not in qual: qual["code"] = {"text": "Unknown Qualification"}
            
    # 8. Encounter fields
    if res_type == "Encounter":
        if "serviceType" in resource and isinstance(resource["serviceType"], list):
            resource["serviceType"] = resource["serviceType"][0] if resource["serviceType"] else {}
        for loc in resource.get("location", []):
            if "display" in loc:
                loc["location"] = {"display": loc["display"]}
                del loc["display"]
        if "period" in resource and "start" in resource["period"]:
            if "T" in resource["period"]["start"] and "Z" not in resource["period"]["start"] and "+" not in resource["period"]["start"]:
                resource["period"]["start"] += "Z"
                
    # 9. ImagingStudy fields
    if res_type == "ImagingStudy":
        for series in resource.get("series", []):
            if "role" in series: del series["role"]
            if "modality" not in series: series["modality"] = {"system": "http://dicom.nema.org/resources/ontology/DCM", "code": "UNKNOWN"}
        if "started" in resource and "T" in resource["started"] and "Z" not in resource["started"] and "+" not in resource["started"]:
            resource["started"] += "Z"
            
    if res_type == "Appointment":
        valid_statuses = ["proposed", "pending", "booked", "arrived", "fulfilled", "cancelled", "noshow", "entered-in-error", "checked-in", "waitlist"]
        if resource.get("status") not in valid_statuses:
            resource["status"] = "fulfilled" if resource.get("status") in ["completed", "finished", "done"] else "booked"

    # 10. DiagnosticReport & Observation Date fields
    if res_type == "DiagnosticReport":
        if "issued" in resource and "T" in resource["issued"] and "Z" not in resource["issued"] and "+" not in resource["issued"]:
            resource["issued"] += "Z"
        if "effectiveDateTime" in resource and "T" in resource["effectiveDateTime"] and "Z" not in resource["effectiveDateTime"] and "+" not in resource["effectiveDateTime"]:
            resource["effectiveDateTime"] += "Z"
        if "result" in resource:
            resource["result"] = [r for r in resource["result"] if not r.get("reference", "").startswith("Practitioner/")]
            
    if res_type == "Observation":
        if "procedure" in resource: del resource["procedure"]
        if "effectiveDateTime" in resource and "T" in resource["effectiveDateTime"] and "Z" not in resource["effectiveDateTime"] and "+" not in resource["effectiveDateTime"]:
            resource["effectiveDateTime"] += "Z"
            
    # 11. Condition category codes
    if res_type == "Condition" and "category" in resource and isinstance(resource["category"], list):
        for cat in resource["category"]:
            if "coding" in cat and isinstance(cat["coding"], list):
                for coding in cat["coding"]:
                    if coding.get("system") == "http://terminology.hl7.org/CodeSystem/condition-category" and coding.get("code") == "encounter-related":
                        coding["code"] = "encounter-diagnosis"

    # 12. ClaimResponse.outcome — RemittanceOutcome value set
    #     Valid codes: queued | complete | error | partial
    #     LLMs commonly hallucinate: pending, approved, denied, partially-approved
    if res_type == "ClaimResponse" and "outcome" in resource:
        _OUTCOME_MAP = {
            "pending":            "queued",
            "in-progress":        "queued",
            "processing":         "queued",
            "approved":           "complete",
            "accepted":           "complete",
            "paid":               "complete",
            "denied":             "error",
            "rejected":           "error",
            "partially-approved": "partial",
            "partial-approval":   "partial",
        }
        _VALID_OUTCOMES = {"queued", "complete", "error", "partial"}
        outcome = resource["outcome"]
        if outcome not in _VALID_OUTCOMES:
            resource["outcome"] = _OUTCOME_MAP.get(outcome, "queued")

    # 13. Claim.use — valid: claim | preauthorization | predetermination
    if res_type == "Claim" and "use" in resource:
        if resource["use"] not in {"claim", "preauthorization", "predetermination"}:
            resource["use"] = "claim"

    # 14. Claim/ClaimResponse.status — valid: active | cancelled | draft | entered-in-error
    if res_type in {"Claim", "ClaimResponse"} and "status" in resource:
        if resource["status"] not in {"active", "cancelled", "draft", "entered-in-error"}:
            resource["status"] = "active"

    # ── NHCX-specific guards ──────────────────────────────────────────────────

    # 15. Task.status — valid FHIR TaskStatus value set
    if res_type == "Task":
        _VALID_TASK_STATUS = {
            "draft", "requested", "received", "accepted", "rejected",
            "ready", "cancelled", "in-progress", "on-hold", "failed",
            "completed", "entered-in-error",
        }
        if resource.get("status") not in _VALID_TASK_STATUS:
            resource["status"] = "requested"

        # Task.intent — valid: unknown | proposal | plan | order |
        # original-order | reflex-order | filler-order | instance-order | option
        _VALID_TASK_INTENT = {
            "unknown", "proposal", "plan", "order",
            "original-order", "reflex-order", "filler-order",
            "instance-order", "option",
        }
        if resource.get("intent") not in _VALID_TASK_INTENT:
            resource["intent"] = "order"

        # Strip non-FHIR top-level fields sometimes hallucinated on Task
        for _f in ("entity", "permission", "note", "input_data"):
            resource.pop(_f, None)

    # 16. Claim.type — system must be hl7 claim-type; reject hallucinated URLs
    if res_type == "Claim" and "type" in resource:
        _VALID_CLAIM_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/claim-type"
        _VALID_CLAIM_TYPE_CODES  = {"institutional", "oral", "pharmacy", "professional", "vision"}
        ct = resource["type"]
        if isinstance(ct, dict) and "coding" in ct:
            for coding in ct["coding"]:
                # Reject obviously wrong systems (e.g. Arabic-character URLs)
                sys_url = coding.get("system", "")
                if sys_url and sys_url != _VALID_CLAIM_TYPE_SYSTEM:
                    coding["system"] = _VALID_CLAIM_TYPE_SYSTEM
                if coding.get("code") not in _VALID_CLAIM_TYPE_CODES:
                    coding["code"] = "professional"

        # Strip non-FHIR fields on Claim
        for _f in ("entity", "permission"):
            resource.pop(_f, None)

    # 17. CoverageEligibilityRequest.purpose — valid: auth-requirements | benefits | discovery | validation
    if res_type == "CoverageEligibilityRequest" and "purpose" in resource:
        _VALID_PURPOSE = {"auth-requirements", "benefits", "discovery", "validation"}
        purpose = resource["purpose"]
        if isinstance(purpose, list):
            resource["purpose"] = [p for p in purpose if p in _VALID_PURPOSE] or ["benefits"]
        elif isinstance(purpose, str) and purpose not in _VALID_PURPOSE:
            resource["purpose"] = ["benefits"]

    # 18. Organization.type — ensure correct system URL and code
    if res_type == "Organization" and "type" in resource:
        _ORG_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/organization-type"
        for t in (resource["type"] if isinstance(resource["type"], list) else [resource["type"]]):
            if isinstance(t, dict) and "coding" in t:
                for c in t["coding"]:
                    # Normalise the system URL regardless of what the LLM produced
                    c["system"] = _ORG_TYPE_SYSTEM
                    # "insurance" is not a valid code — correct to "pay" (payer)
                    if c.get("code") == "insurance":
                        c["code"] = "pay"

# assemble_nhcx_collection_bundle and document_reference_node are implemented in
# nhcx_assembler.py (no LangGraph dependency) and re-exported here so all existing
# call sites in run_nhcx_insurance_pipeline continue to work.
from pdf2nhcx.utils.nhcx_assembler import (
    assemble_nhcx_collection_bundle,
    document_reference_node,
)
def run_nhcx_insurance_pipeline(
    distilled_text: str,
    clinical_artifact: str,
    selected_other_resources: List[str],
    output_dir=None,
    pdf_base64=None,
    idx=None,
    model: str = _DEFAULT_MODEL,
):
    # Complete rulebook paths (add all your paths)

    # ── Anchor rulebook paths relative to THIS file, not the cwd. ────────────
    # This makes paths work both locally (run from pdf2nhcx/) AND inside Docker
    # where WORKDIR=/app but rulebooks land at /app/pdf2nhcx/rulebooks_updated/.
    _rb_dir = os.path.join(os.path.dirname(__file__), "..", "rulebooks_updated")
    _rb_dir = os.path.abspath(_rb_dir)

    def _rb(name: str) -> str:
        return os.path.join(_rb_dir, f"StructureDefinition-{name}_updated.json")

    # Mandatory resource paths (always included regardless of selection)
    must_resources = get_must_resources(clinical_artifact)
    must_paths = {res: _rb(res) for res in must_resources}

    # Dynamic paths for LLM-selected optional resources
    optional_paths = {
        res: _rb(res)
        for res in selected_other_resources
        if res not in must_paths
    }

    rulebook_paths = {
        **must_paths,
        **optional_paths,
        # No "Bundle" alias needed: run_extraction_agent uses resource_type (e.g. "ClaimBundle")
        # for rulebook lookup and fhir_type="Bundle" only for the LLM prompt.
    }

    initial_state = {
        "text": distilled_text,
        "clinical_artifact": clinical_artifact,
        "id_registry": {},
        "final_resources": [],
        "rulebook_paths": rulebook_paths,
        "model": model,  # propagate model selection through the LangGraph state
    }

    # Build and run dynamic workflow
    app, used_resources = build_insurance_workflow(clinical_artifact, selected_other_resources, rulebook_paths)

    print(f"🚀 Starting FHIR Bundle Generation for Patient {idx}...")
    final_output = app.invoke(initial_state)
    bundle = final_output['final_resources'][-1]

    # ── NHCX-only post-processing (replaces clean_and_reorder_bundle) ─────────
    # assemble_nhcx_collection_bundle strips ABDM artefacts, validates structure,
    # and enforces the correct NRCES profile URL for this bundle type.
    bundle = assemble_nhcx_collection_bundle(bundle, clinical_artifact)
    bundle = document_reference_node(bundle, pdf_base64=pdf_base64)

    from pdf2nhcx.utils.nhcx_assembler import strip_binary_data
    bundle = strip_binary_data(bundle)

    print(f"FHIR Bundle generated — resources: {used_resources}, entries: {len(bundle.get('entry', []))}")

    return bundle
