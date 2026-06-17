"""
secrets.py — Resolve secrets from Google Secret Manager at process startup.

Goal: no plaintext credentials in .env or on disk. The .env file holds only
*pointers* to Secret Manager secret names; the real values live in Secret Manager
and are fetched into process memory at startup via the VM's attached service
account (Application Default Credentials).

Convention
──────────
An env var named ``<NAME>_SECRET`` holds a Secret Manager *secret name*. The
loader fetches that secret's latest value and sets ``os.environ[<NAME>]`` so all
existing code that reads the plain env var keeps working unchanged:

    .env:    MYSQL_PASSWORD_SECRET=mysql-password
    result:  os.environ["MYSQL_PASSWORD"] = <value from Secret Manager>

Redis AUTH
──────────
If ``REDIS_PASSWORD`` is resolved (via ``REDIS_PASSWORD_SECRET``) and ``REDIS_URL``
has no credentials, the password is injected into the URL so Celery / redis
clients authenticate transparently:

    redis://10.250.123.43:6379/0  ->  redis://:<password>@10.250.123.43:6379/0

Implementation notes
────────────────────
* Uses the Secret Manager REST API with an ADC OAuth token — only stdlib
  (urllib, json, base64) plus google.auth, both already present in every image.
  No google-cloud-secret-manager dependency required.
* Best-effort: failures are logged, never raised, so a transient Secret Manager
  hiccup degrades to whatever value is already in the environment instead of
  crashing the service. Call once, early, before config modules read env vars.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_SM_BASE = "https://secretmanager.googleapis.com/v1"
_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _get_adc_token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=[_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _access_secret(project: str, name: str, token: str) -> str:
    url = f"{_SM_BASE}/projects/{project}/secrets/{name}/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return base64.b64decode(data["payload"]["data"]).decode()


def _inject_redis_auth() -> None:
    """If a Redis password is present and REDIS_URL has no creds, inject it."""
    pwd = os.environ.get("REDIS_PASSWORD")
    url = os.environ.get("REDIS_URL")
    if not pwd or not url or "://" not in url:
        return
    scheme, rest = url.split("://", 1)
    if "@" in rest:  # already has credentials
        return
    os.environ["REDIS_URL"] = f"{scheme}://:{urllib.parse.quote(pwd, safe='')}@{rest}"
    logger.info("load_secrets: injected Redis AUTH into REDIS_URL")


def load_secrets(project: str | None = None) -> None:
    """
    Resolve every ``<NAME>_SECRET`` env var into ``os.environ[<NAME>]`` by
    fetching its value from Secret Manager. Idempotent and safe to call multiple
    times. Never raises.
    """
    pointers = {
        k: v for k, v in os.environ.items()
        if k.endswith("_SECRET") and v and not k.startswith("_")
    }
    if not pointers:
        return

    project = (
        project
        or os.getenv("PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    if not project:
        logger.warning("load_secrets: PROJECT_ID unset — skipping Secret Manager")
        return

    try:
        token = _get_adc_token()
    except Exception as exc:  # ADC unavailable (e.g. local dev without creds)
        logger.warning("load_secrets: ADC token unavailable (%s) — skipping", exc)
        return

    for ptr_key, secret_name in pointers.items():
        target = ptr_key[: -len("_SECRET")]  # MYSQL_PASSWORD_SECRET -> MYSQL_PASSWORD
        try:
            os.environ[target] = _access_secret(project, secret_name, token)
            logger.info("load_secrets: resolved %s from secret %r", target, secret_name)
        except Exception as exc:
            logger.warning(
                "load_secrets: failed to resolve %s from secret %r: %s",
                target, secret_name, exc,
            )

    _inject_redis_auth()
