"""Preflight for the local demo (L-01): is everything the demo calls reachable right now?

    python -m scripts.demo.preflight [--only nvidia,gemini,pinecone]

It runs the PR-00 probe (``scripts/diag/pr00_probe.py``) quietly and turns its records into
one line per capability: OK, WARN or FAIL. A FAIL means the demo will break (upload, chat);
a WARN means one feature is degraded. The exit code is 1 only when a required check fails.
Run it ten minutes before an interview, because model IDs change often (PR-01b).

It makes the probe's calls: a handful of small requests on the NVIDIA and Gemini free tiers.
Nothing is written to Postgres or Pinecone, and nothing secret is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from scripts.diag import pr00_probe

OK, WARN, FAIL = "ok", "warn", "fail"
DEFAULT_SECTIONS = "nvidia,gemini,pinecone"


@dataclass(frozen=True)
class Check:
    """One capability and whether it works right now."""

    name: str
    level: str
    detail: str
    required: bool


def _group(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record.get("s", "")].append(record)
    return grouped


def _statuses(rows: list[dict[str, Any]]) -> str:
    return ", ".join(f"{r.get('model', '?')}: {r.get('status')}" for r in rows) or "no response"


def _check_generate(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Primary LLM answers"
    if g["nvidia_skipped"]:
        return Check(name, FAIL, "NVIDIA_API_KEY is not set in backend/.env", True)
    rows = g["nvidia_generate"]
    answered = [r for r in rows if r.get("status") == 200]
    if answered:
        first = answered[0]
        return Check(name, OK, f"{first['model']} answered in {first.get('ms')} ms", True)
    return Check(name, FAIL, f"no NVIDIA generation model answered ({_statuses(rows)})", True)


def _check_embed(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Embeddings"
    if g["nvidia_skipped"]:
        return Check(name, FAIL, "NVIDIA_API_KEY is not set in backend/.env", True)
    rows = [r for r in g["nvidia_embed"] if r.get("requested_dimensions") is None]
    if rows and rows[0].get("status") == 200:
        return Check(name, OK, f"{rows[0]['model']} returns {rows[0].get('dimension')} dimensions", True)
    return Check(name, FAIL, f"the embedding call failed ({_statuses(rows)})", True)


def _check_index(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Pinecone index ready"
    if g["pinecone_skipped"]:
        return Check(name, FAIL, "PINECONE_API_KEY or PINECONE_INDEX_NAME is not set", True)
    rows = g["pinecone_index"]
    if not rows:
        return Check(name, FAIL, "the Pinecone check did not run", True)
    row = rows[0]
    if not row.get("ok"):
        return Check(name, FAIL, f"Pinecone call failed ({row.get('error_class')})", True)
    if not row.get("configured_index_listed"):
        return Check(name, FAIL, "PINECONE_INDEX_NAME is not among the account's indexes", True)
    if row.get("ready") is not True:
        return Check(name, FAIL, f"the index is not ready (state: {row.get('state')})", True)
    return Check(name, OK, f"ready, dimension {row.get('dimension')}, metric {row.get('metric')}", True)


def _check_dimensions(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Embedding size matches the index"
    rows = g["embed_vs_index"]
    if not rows:
        return Check(name, FAIL, "not compared, because the embedding or index check did not complete", True)
    row = rows[0]
    # The app pins the size (EMBEDDING_DIMENSIONS), so what it sends is the effective size.
    effective = row.get("effective_dimension", row.get("embed_dimension"))
    native = row.get("embed_dimension")
    if row.get("match"):
        note = f" (the model returns {native}; the app slices to the pinned size)" if effective != native else ""
        return Check(name, OK, f"both are {effective}{note}", True)
    return Check(
        name,
        FAIL,
        f"embeddings are {effective} wide but the index holds {row.get('index_dimension')}; "
        "uploads will fail. Set EMBEDDING_DIMENSIONS to the index size",
        True,
    )


def _configured_model_check(
    name: str, rows: list[dict[str, Any]], env_var: str, nothing_answered: str
) -> Check:
    """OK when the configured model answered; a warning that names a working candidate otherwise.

    The probe marks the row of the model the app is configured to call with ``configured``.
    A candidate that answers while the configured one does not is the model to set in
    ``env_var``. Without the marker (older records) any answer counts.
    """
    answered = [r for r in rows if r.get("status") == 200]
    configured = [r for r in rows if r.get("configured")]
    if configured and configured[0].get("status") != 200:
        bad = configured[0]
        if answered:
            alt = answered[0]["model"]
            detail = f"{bad['model']} returned {bad.get('status')}, but {alt} answers: set {env_var}={alt} in backend/.env"
            return Check(name, WARN, detail, False)
        return Check(name, WARN, nothing_answered.format(statuses=_statuses(rows)), False)
    if answered:
        return Check(name, OK, f"{answered[0]['model']} answered", False)
    return Check(name, WARN, nothing_answered.format(statuses=_statuses(rows)), False)


def _check_rerank(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Reranker"
    if g["nvidia_skipped"]:
        return Check(name, WARN, "skipped: no NVIDIA key", False)
    return _configured_model_check(
        name,
        g["nvidia_rerank"],
        "NVIDIA_RERANK_MODEL",
        "no reranker answered ({statuses}); retrieval keeps working in its fused order, "
        "but answer quality may suffer (QA-006)",
    )


def _nvidia_structured_valid(row: dict[str, Any]) -> bool:
    return row.get("status") == 200 and bool(row.get("schema_ok")) and row.get("finish_reason") == "stop"


def _thinking_word(thinking: Any) -> str:
    return "thinking off" if thinking is False else "thinking on"


def _nvidia_structured_problem(row: dict[str, Any]) -> str:
    """Why the configured NVIDIA structured request did not return valid JSON (names no secrets)."""
    status = row.get("status")
    if status != 200:
        return f"the NVIDIA API answered {status} to it"
    if row.get("finish_reason") == "length":
        spent = row.get("completion_tokens")
        used = f" after {spent} tokens" if spent else ""
        reasoning = " (the model also returned reasoning text)" if row.get("reasoning_len") or row.get("think_tag_in_content") else ""
        return f"the reply was cut off at the {row.get('max_tokens')}-token budget{used}{reasoning}"
    if row.get("thinking") is False and (row.get("reasoning_len") or row.get("think_tag_in_content")):
        return "the model returned reasoning text although thinking is off"
    return "the reply was not valid JSON for the schema"


def _check_structured(g: dict[str, list[dict[str, Any]]]) -> Check:
    """Does the CONFIGURED NVIDIA structured request (``NVIDIA_STRUCTURED_MODE`` plus the thinking
    setting) return valid JSON? If not, name a variant that does and the setting to change."""
    name = "Structured output (gap analysis, compare)"
    if g["nvidia_skipped"]:
        return Check(name, WARN, "skipped: no NVIDIA key", False)
    rows = [r for r in g["nvidia_structured"] if r.get("variant") != "deployed"]
    configured = next((r for r in rows if r.get("configured")), None)
    if configured is None:
        return Check(name, WARN, "the structured-output check did not run", False)
    label = f"NVIDIA_STRUCTURED_MODE={configured.get('variant')} ({_thinking_word(configured.get('thinking'))})"
    if _nvidia_structured_valid(configured):
        return Check(name, OK, f"{label} returns valid JSON", False)

    problem = _nvidia_structured_problem(configured)
    working = [r for r in rows if _nvidia_structured_valid(r)]
    # Prefer a variant that keeps the thinking choice, so only the mode changes.
    working.sort(key=lambda r: r.get("thinking") is not configured.get("thinking"))
    if not working:
        return Check(
            name,
            WARN,
            f"{label} fails ({problem}), and no other variant returned valid JSON; "
            "gap analysis and compare will use the Gemini backup or error",
            False,
        )
    best = working[0]
    change = f"set NVIDIA_STRUCTURED_MODE={best.get('variant')}"
    if best.get("thinking") is not configured.get("thinking"):
        change += f" and NVIDIA_STRUCTURED_DISABLE_THINKING={'true' if best.get('thinking') is False else 'false'}"
    return Check(
        name,
        WARN,
        f"{label} fails ({problem}), but {best.get('variant')} ({_thinking_word(best.get('thinking'))}) works: "
        f"{change} in backend/.env",
        False,
    )


_GEMINI_MODE_SETTING = {"responseJsonSchema": "response_json_schema", "responseSchema": "response_schema"}


def _check_gemini_structured(g: dict[str, list[dict[str, Any]]]) -> Check:
    """Does the Gemini backup return valid JSON for a structured request? The app tries
    ``responseJsonSchema`` and falls back to ``responseSchema`` by itself, so this only warns."""
    name = "Structured output on the Gemini backup"
    if g["gemini_skipped"]:
        return Check(name, WARN, "skipped: no Gemini key", False)
    rows = g["gemini_structured"]
    if not rows:
        return Check(name, WARN, "the Gemini structured-output check did not run", False)

    def valid(row: dict[str, Any]) -> bool:
        return row.get("status") == 200 and bool(row.get("schema_ok")) and row.get("finish_reason") == "STOP"

    first = rows[0]
    if valid(first):
        return Check(name, OK, f"{first.get('schema_field')} returns valid JSON", False)
    working = [r for r in rows if valid(r)]
    if working:
        mode = _GEMINI_MODE_SETTING.get(working[0].get("schema_field"), "")
        if first.get("status") == 200:
            # Accepted but the reply was not valid: the app does not switch on its own.
            detail = (
                f"{first.get('schema_field')} returned a reply that is not valid JSON, but "
                f"{working[0].get('schema_field')} works: set GEMINI_STRUCTURED_SCHEMA_MODE={mode} in backend/.env"
            )
        else:
            detail = (
                f"{first.get('schema_field')} was rejected (status {first.get('status')}), but "
                f"{working[0].get('schema_field')} works. The app falls back to it by itself; set "
                f"GEMINI_STRUCTURED_SCHEMA_MODE={mode} to skip the rejected call"
            )
        return Check(name, WARN, detail, False)
    if first.get("finish_reason") == "MAX_TOKENS":
        why = f"the reply was cut off at {first.get('max_output_tokens')} tokens; raise STRUCTURED_MAX_TOKENS"
    elif first.get("thinking_level"):
        why = f"GEMINI_STRUCTURED_THINKING_LEVEL={first.get('thinking_level')} may be rejected; clear it and re-run"
    else:
        why = "statuses " + ", ".join(f"{r.get('schema_field')}: {r.get('status')}" for r in rows)
    return Check(name, WARN, f"neither schema form returned valid JSON ({why}); failover for gap analysis will error", False)


def _check_gemini(g: dict[str, list[dict[str, Any]]]) -> Check:
    name = "Gemini backup (free tier)"
    if g["gemini_skipped"]:
        return Check(name, WARN, "GEMINI_API_KEY is not set; there is no backup if NVIDIA fails", False)
    return _configured_model_check(
        name, g["gemini_generate"], "GEMINI_GENERATION_MODEL", "no Gemini model answered ({statuses})"
    )


def evaluate(records: list[dict[str, Any]]) -> list[Check]:
    """Maps probe records to one check per capability the demo depends on."""
    g = _group(records)
    return [
        _check_generate(g),
        _check_embed(g),
        _check_index(g),
        _check_dimensions(g),
        _check_rerank(g),
        _check_structured(g),
        _check_gemini(g),
        _check_gemini_structured(g),
    ]


def verdict(checks: list[Check]) -> tuple[bool, str]:
    """Returns (ready, summary line)."""
    failed = [c for c in checks if c.required and c.level == FAIL]
    warned = [c for c in checks if c.level == WARN]
    if failed:
        return False, f"NOT READY: {len(failed)} required check(s) failed."
    suffix = f" with {len(warned)} warning(s)" if warned else ""
    return True, f"READY{suffix}."


def render(checks: list[Check], *, color: bool) -> str:
    """Formats the checks as aligned text, one per line, then the verdict."""
    paint = {OK: "32", WARN: "33", FAIL: "31"}
    label = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    width = max(len(c.name) for c in checks)
    lines = [f"Preflight at {datetime.now():%H:%M:%S}"]
    for check in checks:
        tag = label[check.level]
        if color:
            tag = f"\033[{paint[check.level]}m{tag}\033[0m"
        lines.append(f"  {tag}  {check.name.ljust(width)}  {check.detail}")
    _, summary = verdict(checks)
    lines.append("")
    lines.append(summary)
    return "\n".join(lines)


async def collect(cfg: pr00_probe.ProbeConfig, sections: set[str], client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Runs the probe with a silent sink and returns its records."""
    emit = pr00_probe.Emitter(cfg.secrets, sink=lambda _line: None)
    await pr00_probe.run(cfg, sections, emit, client)
    return [json.loads(line.removeprefix("PR00 ")) for line in emit.lines]


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check that the demo's providers work right now.")
    parser.add_argument("--only", default=DEFAULT_SECTIONS, help=f"probe sections (default: {DEFAULT_SECTIONS})")
    args = parser.parse_args(argv)
    sections = {s.strip() for s in args.only.split(",") if s.strip()}

    cfg = pr00_probe.ProbeConfig.from_app_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        records = await collect(cfg, sections, client)

    checks = evaluate(records)
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print(render(checks, color=color))
    return 0 if verdict(checks)[0] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
