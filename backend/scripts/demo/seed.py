"""Seeds a fresh local demo through the public API (L-01).

    python -m scripts.demo.seed [--api http://localhost:8001]

It registers ``demo.<date>@example.com`` with a random password, prints the sign-in once,
creates one synthetic PD model with two versions and uploads the two synthetic validation
reports (version 1 passes, version 2 breaches). Everything goes through the API, so the
seeded data is exactly what a user could create in the UI.

The upload runs the whole pipeline (extract, mask, embed, Pinecone), so it needs working
provider keys; run ``scripts/demo.sh preflight`` first. Without them the upload fails with
a generic 500 and nothing is stored for that document.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from collections.abc import Callable
from datetime import date

import httpx

from scripts.demo.fixtures import REPORTS, ReportSpec, build_report

MODEL_NAME = "Retail PD Scorecard (synthetic)"
TENANT_NAME = "Demo Tenant"
MAX_EMAIL_ATTEMPTS = 9
UPLOAD_TIMEOUT_S = 300.0


class SeedError(Exception):
    """A seed step failed in a way the presenter should read and act on."""


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail)[:300] if detail else response.reason_phrase


def _expect(response: httpx.Response, ok: int, step: str) -> dict:
    if response.status_code != ok:
        raise SeedError(f"{step} failed: HTTP {response.status_code}: {_detail(response)}")
    return response.json()


def _email_candidates(today: date) -> list[str]:
    base = f"demo.{today:%Y%m%d}"
    return [f"{base}@example.com"] + [
        f"{base}.{n}@example.com" for n in range(2, MAX_EMAIL_ATTEMPTS + 1)
    ]


def register(client: httpx.Client, today: date) -> tuple[str, str, str]:
    """Registers the demo user; returns (email, password, access token).

    If today's address is taken (a second seed without a reset), it tries ``.2``, ``.3``, ...
    """
    password = secrets.token_urlsafe(12)
    for email in _email_candidates(today):
        response = client.post(
            "/auth/register",
            json={"email": email, "password": password, "tenant_name": TENANT_NAME},
        )
        if response.status_code == 400 and "already registered" in _detail(response).lower():
            continue
        body = _expect(response, 200, "Registering the demo user")
        return email, password, body["access_token"]
    raise SeedError(
        "Every demo address for today is taken. Run `scripts/demo.sh reset` for a clean database."
    )


def upload(client: httpx.Client, version_id: str, spec: ReportSpec) -> tuple[dict, float]:
    """Uploads one report; returns (response body, seconds taken)."""
    started = time.perf_counter()
    response = client.post(
        "/documents/upload",
        data={"model_version_id": version_id},
        files={
            "file": (
                spec.filename,
                build_report(spec),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        timeout=UPLOAD_TIMEOUT_S,
    )
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        hint = (
            " Provider keys are missing or unreachable; run `scripts/demo.sh preflight`."
            if response.status_code == 500
            else ""
        )
        raise SeedError(
            f"Uploading {spec.filename} failed: HTTP {response.status_code}: "
            f"{_detail(response).rstrip('.')}.{hint}"
        )
    return response.json(), elapsed


def run(
    client: httpx.Client,
    *,
    app_url: str,
    today: date | None = None,
    out: Callable[[str], None] = print,
) -> None:
    """Seeds the demo. Raises ``SeedError`` on the first failing step."""
    today = today or date.today()

    health = client.get("/health")
    if health.status_code != 200:
        raise SeedError(f"The backend is not healthy: HTTP {health.status_code}.")
    if health.json().get("db") != "connected":
        raise SeedError("The backend is up but cannot reach its database.")

    email, password, token = register(client, today)
    client.headers["Authorization"] = f"Bearer {token}"
    # Printed before the uploads on purpose: if one fails, the account still exists.
    out("")
    out("Demo account created. This password is shown once and is not stored anywhere:")
    out(f"  URL:      {app_url}")
    out(f"  Email:    {email}")
    out(f"  Password: {password}")
    out("")

    model = _expect(
        client.post(
            "/models",
            json={
                "name": MODEL_NAME,
                "type": "PD",
                "description": "Synthetic retail PD scorecard for the demo. All data is fictional.",
                "portfolio": "Retail personal loans",
                "algorithm": "Logistic regression",
                "initial_version": REPORTS[0].version_label,
            },
        ),
        201,
        "Creating the model",
    )
    out(f"Created model '{MODEL_NAME}'.")

    version_id = model["current_version"]["id"]
    for index, spec in enumerate(REPORTS):
        if index > 0:
            version = _expect(
                client.post(f"/models/{model['id']}/versions", json={"version": spec.version_label}),
                201,
                f"Creating version {spec.version_label}",
            )
            version_id = version["id"]
        body, seconds = upload(client, version_id, spec)
        out(
            f"Uploaded {spec.filename} as version {spec.version_label}: "
            f"{body['chunk_count']} chunks in {seconds:.1f} s (expected {spec.expected_status})."
        )

    final = _expect(client.get(f"/models/{model['id']}"), 200, "Reading the model back")
    out(f"Model status is now {final.get('status')}. The demo is ready.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a fresh local demo through the API.")
    parser.add_argument("--api", default="http://localhost:8001", help="backend base URL")
    parser.add_argument("--app-url", default="http://localhost:5173", help="frontend URL to print")
    args = parser.parse_args(argv)

    try:
        with httpx.Client(base_url=args.api, timeout=30.0) as client:
            run(client, app_url=args.app_url)
    except httpx.TransportError as exc:
        print(f"Cannot reach the backend at {args.api}: {type(exc).__name__}. Is it running?", file=sys.stderr)
        return 1
    except SeedError as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
