"""Five-out-of-five check for gap analysis and compare (M1 exit criterion, QA-005).

    python -m scripts.demo.check_ai --email demo.20261004@example.com [--runs 5]

It signs in (it asks for the password; nothing is stored), finds the two seeded validation
reports, then calls ``POST /gap-analysis`` on version 2.0 and ``POST /compare`` on both reports
``--runs`` times each. It prints one line per call: the HTTP status, the typed error code on a
failure, and how many gaps or differences came back. The exit code is 0 only if every call
succeeded.

The calls use the real providers, so run ``scripts/demo.sh preflight`` first. Each call spends a
little free-tier quota. Seed first (``scripts/demo.sh seed``).
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from scripts.demo.fixtures import REPORTS

CALL_TIMEOUT_S = 240.0


class CheckError(Exception):
    """A setup step failed in a way the presenter should read and act on."""


@dataclass(frozen=True)
class CallResult:
    """The outcome of one gap-analysis or compare call."""

    status: int
    seconds: float
    count: int | None  # gaps or differences returned; None on a failure
    code: str | None  # typed error code on a failure
    detail: str | None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.count is not None


def login(client: httpx.Client, email: str, password: str) -> None:
    """Signs in and stores the bearer token on the client."""
    response = client.post("/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise CheckError(f"Sign-in failed: HTTP {response.status_code}. Check the email and password.")
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def find_seeded_documents(client: httpx.Client) -> tuple[str, str]:
    """Returns the ids of the seeded version 1.0 and version 2.0 reports."""
    response = client.get("/documents")
    if response.status_code != 200:
        raise CheckError(f"Listing documents failed: HTTP {response.status_code}.")
    by_name = {d["filename"]: d["id"] for d in response.json().get("documents", []) if d.get("status") == "READY"}
    try:
        return by_name[REPORTS[0].filename], by_name[REPORTS[1].filename]
    except KeyError as exc:
        raise CheckError(
            f"The seeded report {exc.args[0]} was not found as a READY document. "
            "Run `scripts/demo.sh seed` first, and sign in as the account it created."
        ) from exc


def _call(client: httpx.Client, path: str, body: dict[str, str], key: str) -> CallResult:
    started = time.perf_counter()
    try:
        response = client.post(path, json=body, timeout=CALL_TIMEOUT_S)
    except httpx.TransportError as exc:
        return CallResult(0, time.perf_counter() - started, None, type(exc).__name__, "no response")
    seconds = time.perf_counter() - started
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code == 200 and isinstance(payload.get(key), list):
        return CallResult(200, seconds, len(payload[key]), None, None)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = payload.get("code") if isinstance(payload, dict) else None
    return CallResult(response.status_code, seconds, None, code, str(detail)[:120] if detail else None)


def run_checks(
    client: httpx.Client, *, runs: int, out: Callable[[str], None] = print
) -> bool:
    """Runs both checks; returns True only if every call succeeded."""
    v1_id, v2_id = find_seeded_documents(client)
    plans = (
        ("gap-analysis", "/gap-analysis", {"document_id": v2_id}, "gaps"),
        ("compare", "/compare", {"document_id_a": v1_id, "document_id_b": v2_id}, "differences"),
    )
    all_ok = True
    for name, path, body, key in plans:
        results = []
        for attempt in range(1, runs + 1):
            result = _call(client, path, body, key)
            results.append(result)
            if result.ok:
                out(f"  {name} {attempt}/{runs}: OK, HTTP 200, {result.count} {key} in {result.seconds:.1f} s")
            else:
                why = f"{result.code or 'error'}" + (f" ({result.detail})" if result.detail else "")
                out(f"  {name} {attempt}/{runs}: FAIL, HTTP {result.status}, {why}, {result.seconds:.1f} s")
        passed = sum(r.ok for r in results)
        out(f"{name}: {passed} of {runs} succeeded")
        out("")
        all_ok = all_ok and passed == runs
    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Five-out-of-five check for gap analysis and compare.")
    parser.add_argument("--api", default="http://localhost:8001", help="backend base URL")
    parser.add_argument("--email", required=True, help="the demo account's email (printed by `seed`)")
    parser.add_argument("--runs", type=int, default=5, help="calls per endpoint (default 5)")
    args = parser.parse_args(argv)

    password = getpass.getpass(f"Password for {args.email}: ")
    try:
        with httpx.Client(base_url=args.api, timeout=30.0) as client:
            login(client, args.email, password)
            ok = run_checks(client, runs=args.runs)
    except httpx.TransportError as exc:
        print(f"Cannot reach the backend at {args.api}: {type(exc).__name__}. Is it running?", file=sys.stderr)
        return 1
    except CheckError as exc:
        print(f"Check failed: {exc}", file=sys.stderr)
        return 1
    print("PASS: every call succeeded." if ok else "FAIL: at least one call failed. See the lines above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
