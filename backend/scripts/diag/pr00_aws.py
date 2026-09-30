"""PR-00 AWS side: read-only inspection and the one-off probe task.

Subcommands (all print JSON; none prints an env or secret *value*):

``inspect``
    Read-only. Master plan §2 steps 1, 2 and 5: the ECS services and their task
    definitions (env and secret **names** only), CloudWatch Logs Insights
    counts for the log patterns the plan lists, and the CloudTrail ``RunTask``
    history (was a seed or index one-off ever run?).
``probe-task``
    Builds the one-off ECS task that runs ``scripts/diag/pr00_probe.py`` inside
    the production container, pinned to a git commit and a SHA-256. It only
    prints the request unless ``--run`` is given; ``--run`` starts the task,
    waits for it and prints its ``PR00`` log lines. Needs owner approval.
``probe-logs``
    Prints the ``PR00`` lines of a probe task that already ran.

Needs ``boto3`` and AWS credentials for us-east-1 (``pip install boto3``).
``inspect`` and ``probe-logs`` need read access only; ``probe-task --run`` also
needs ``ecs:RunTask`` and ``iam:PassRole`` for the task's roles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from typing import Any

REGION = "us-east-1"
CLUSTER = "modelaudit-cluster"
PROD_SERVICE = "modelaudit-prod-service"
STAGING_SERVICE = "modelaudit-staging-service"
REPO_RAW = "https://raw.githubusercontent.com/Shakti8125/creditAudit/{sha}/backend/scripts/diag/pr00_probe.py"
LOG_WINDOW_DAYS = 7

# Master plan §2 step 2. One Insights query per group; each pattern becomes a
# 0/1 column that is summed per day, so the log is scanned once per group.
LOG_GROUPS_OF_PATTERNS: dict[str, dict[str, str]] = {
    "rate_limiter": {
        "rate_limit_error": "Rate limiting error",
        "script_load_failed": "Failed to load rate limiting scripts",
        "redis_init_failed": "Could not initialize Redis",
        "scripts_loaded": "Lua scripts successfully loaded",
    },
    "structured_output": {
        "gap_analysis_failed": "Failed to generate gap analysis",
        "compare_json_failed": "Failed to parse LLM comparison JSON",
        "json_decode_error": "JSONDecodeError",
    },
    "rerank_and_models": {
        "rerank_failed": "failed on 'rerank'",
        "gemini_rerank_error": "GeminiRerankError",
        "score_passage_failed": "Failed to score passage",
        "http_404": "404",
        "http_410": "410",
    },
    "corpus_scripts": {
        "dir_not_found": "Directory not found",
        "indexing_complete": "Indexing complete",
        "seeded_standard": "Seeded standard",
    },
    "egress": {
        "egress_violation": "EgressViolation",
        "egress_blocked": "Egress validation blocked",
    },
}
# Error lines whose text tells the plan's hypotheses apart (QA-005/006/007).
SAMPLE_PATTERNS = (
    "Rate limiting error",
    "Failed to load rate limiting scripts",
    "Could not initialize Redis",
    "Failed to generate gap analysis",
    "failed on 'rerank'",
)
CORPUS_SCRIPTS = ("seed_regulatory_standards", "index_regulatory_corpus")

_SCRUB = (
    re.compile(r"[a-z][a-z0-9+.\-]*://\S+"),
    re.compile(r"nvapi-[A-Za-z0-9_\-]+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"pcsk_[A-Za-z0-9_]+"),
    re.compile(r"(?i)(bearer|token|password|key)[=: ]+\S+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
)


def scrub(text: str, limit: int = 240) -> str:
    """Remove URLs, key-like strings and UUIDs (tenant and document IDs) from a log line."""
    for pattern in _SCRUB:
        text = pattern.sub("***", text)
    return text[:limit]


def secret_source_name(value_from: str) -> str:
    """Return the secret's own name from a ``valueFrom`` ARN, without account or region.

    Args:
        value_from: A Secrets Manager or SSM ARN, or a bare parameter name.

    Returns:
        For example ``secret:modelaudit/prod-AbCdEf:REDIS_URL`` or
        ``parameter:/modelaudit/prod/REDIS_URL``.
    """
    if not value_from.startswith("arn:"):
        return f"parameter:{value_from}"
    resource = value_from.split(":", 5)[5]
    if resource.startswith("secret:"):
        return resource.rstrip(":")
    if resource.startswith("parameter/"):
        return "parameter:/" + resource[len("parameter/") :]
    return resource


def summarise_task_definition(td: dict[str, Any]) -> dict[str, Any]:
    """Reduce a task definition to names: never an env value or a secret value.

    Args:
        td: ``describe_task_definition()["taskDefinition"]``.

    Returns:
        Family, revision, roles and, per container, the image repository and
        tag (registry host dropped), env names, secret names and the name of
        the secret each one is read from.
    """
    containers = []
    for c in td.get("containerDefinitions", []):
        image = c.get("image", "")
        log_options = (c.get("logConfiguration") or {}).get("options", {})
        containers.append(
            {
                "name": c.get("name"),
                "image": image.split("/", 1)[1] if "/" in image else image,
                "env_names": sorted(e["name"] for e in c.get("environment", [])),
                "secret_names": sorted(s["name"] for s in c.get("secrets", [])),
                "secret_sources": {s["name"]: secret_source_name(s["valueFrom"]) for s in c.get("secrets", [])},
                "command": c.get("command"),
                "log_group": log_options.get("awslogs-group"),
                "log_stream_prefix": log_options.get("awslogs-stream-prefix"),
            }
        )
    return {
        "task_definition": f"{td.get('family')}:{td.get('revision')}",
        "registered_at": str(td.get("registeredAt")),
        "cpu": td.get("cpu"),
        "memory": td.get("memory"),
        "task_role": (td.get("taskRoleArn") or "").rsplit("/", 1)[-1],
        "execution_role": (td.get("executionRoleArn") or "").rsplit("/", 1)[-1],
        "containers": containers,
    }


def compare_environments(prod: dict[str, Any], staging: dict[str, Any]) -> dict[str, Any]:
    """Say whether staging and prod share configuration (NEW-06), from two summaries."""
    p, s = prod["containers"][0], staging["containers"][0]
    shared = sorted(k for k in set(p["secret_sources"]) & set(s["secret_sources"]) if p["secret_sources"][k] == s["secret_sources"][k])
    return {
        "same_task_definition_revision": prod["task_definition"] == staging["task_definition"],
        "same_image": p["image"] == s["image"],
        "env_names_only_in_prod": sorted(set(p["env_names"]) - set(s["env_names"])),
        "env_names_only_in_staging": sorted(set(s["env_names"]) - set(p["env_names"])),
        "secrets_read_from_the_same_source": shared,
        "secrets_read_from_different_sources": sorted(
            k for k in set(p["secret_sources"]) & set(s["secret_sources"]) if k not in shared
        ),
    }


def summarise_run_task_event(event: dict[str, Any]) -> dict[str, Any]:
    """Reduce a CloudTrail ``RunTask`` event to who ran what, and flag corpus one-offs."""
    detail = json.loads(event.get("CloudTrailEvent") or "{}")
    params = detail.get("requestParameters") or {}
    overrides = (params.get("overrides") or {}).get("containerOverrides") or []
    commands = [o.get("command") for o in overrides if o.get("command")]
    flat = " ".join(" ".join(c) for c in commands)
    return {
        "time": str(event.get("EventTime")),
        "user": event.get("Username"),
        "task_definition": str(params.get("taskDefinition", "")).rsplit("/", 1)[-1],
        "started_by": params.get("startedBy"),
        "commands": [[scrub(part, 80) for part in c] for c in commands],
        "error_code": detail.get("errorCode"),
        "corpus_script": any(name in flat for name in CORPUS_SCRIPTS),
    }


def insights_regex(patterns: tuple[str, ...] | list[str]) -> str:
    """Join literal patterns into a Logs Insights regex, escaping only regex metacharacters."""
    return "|".join(re.sub(r"([.^$*+?()\[\]{}|\\/])", r"\\\1", p) for p in patterns)


def insights_query(patterns: dict[str, str]) -> str:
    """Build one Logs Insights query that counts each pattern per day."""
    columns = ", ".join(f'strcontains(@message, "{p}") as {k}' for k, p in patterns.items())
    sums = ", ".join(f"sum({k}) as n_{k}" for k in patterns)
    return f"filter @message like /{insights_regex(list(patterns.values()))}/ | fields {columns} | stats {sums} by bin(1d)"


def build_probe_command(sha: str, digest: str, sections: str) -> list[str]:
    """Return the container command that downloads, verifies and runs the probe.

    The script is fetched from the public repo at an exact commit and must
    match ``digest`` before it runs, so the task runs only the reviewed bytes.
    """
    url = REPO_RAW.format(sha=sha)
    code = (
        "import hashlib,urllib.request as u;"
        f"s=u.urlopen('{url}',timeout=30).read();"
        f"assert hashlib.sha256(s).hexdigest()=='{digest}','pr00_probe.py sha256 mismatch';"
        "exec(compile(s,'pr00_probe.py','exec'),{'__name__':'__main__'})"
    )
    return ["python", "-c", code, "--only", sections]


def _client(service: str) -> Any:
    import boto3

    return boto3.client(service, region_name=REGION)


def _describe(ecs: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    services = ecs.describe_services(cluster=CLUSTER, services=[PROD_SERVICE, STAGING_SERVICE])["services"]
    by_name = {s["serviceName"]: s for s in services}
    tds = {}
    for svc in services:
        arn = svc["taskDefinition"]
        if arn not in tds:
            tds[arn] = ecs.describe_task_definition(taskDefinition=arn)["taskDefinition"]
    return by_name, tds, {arn: summarise_task_definition(td) for arn, td in tds.items()}


def cmd_inspect(_: argparse.Namespace) -> dict[str, Any]:
    """Run master plan §2 steps 1, 2 and 5 (read-only)."""
    ecs, logs, trail = _client("ecs"), _client("logs"), _client("cloudtrail")
    services, _, summaries = _describe(ecs)
    out: dict[str, Any] = {
        "services": [
            {
                "service": name,
                "task_definition": svc["taskDefinition"].rsplit("/", 1)[-1],
                "desired": svc.get("desiredCount"),
                "running": svc.get("runningCount"),
                "launch_type": svc.get("launchType"),
                "network": (svc.get("networkConfiguration") or {}).get("awsvpcConfiguration"),
            }
            for name, svc in services.items()
        ],
        "task_definitions": list(summaries.values()),
        "families": ecs.list_task_definition_families(status="ACTIVE").get("families"),
    }
    if PROD_SERVICE in services and STAGING_SERVICE in services:
        out["staging_vs_prod"] = compare_environments(
            summaries[services[PROD_SERVICE]["taskDefinition"]],
            summaries[services[STAGING_SERVICE]["taskDefinition"]],
        )

    groups = sorted({c["log_group"] for s in summaries.values() for c in s["containers"] if c["log_group"]})
    out["log_groups"] = groups
    end = int(time.time())
    start = end - LOG_WINDOW_DAYS * 86400
    queries = {name: insights_query(p) for name, p in LOG_GROUPS_OF_PATTERNS.items()}
    queries["samples"] = (
        "filter @message like /" + insights_regex(SAMPLE_PATTERNS) + "/ "
        "| fields @timestamp, @message | sort @timestamp desc | limit 10"
    )
    results: dict[str, Any] = {}
    for name, query in queries.items():
        if not groups:
            break
        qid = logs.start_query(logGroupNames=groups, startTime=start, endTime=end, queryString=query)["queryId"]
        for _ in range(60):
            res = logs.get_query_results(queryId=qid)
            if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
                break
            time.sleep(2)
        rows = [{f["field"]: f["value"] for f in row if not f["field"].startswith("@ptr")} for row in res.get("results", [])]
        if name == "samples":
            rows = [{"t": r.get("@timestamp"), "msg": scrub(r.get("@message", ""))} for r in rows]
        results[name] = {"status": res["status"], "rows": rows}
    out["logs_insights_last_7_days"] = results

    events: list[dict[str, Any]] = []
    for page in trail.get_paginator("lookup_events").paginate(
        LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": "RunTask"}],
        PaginationConfig={"MaxItems": 200, "PageSize": 50},
    ):
        events += [summarise_run_task_event(e) for e in page.get("Events", [])]
    out["cloudtrail_run_task"] = {
        "events": len(events),
        "corpus_script_runs": [e for e in events if e["corpus_script"]],
        "distinct_commands": sorted({json.dumps(e["commands"]) for e in events}),
        "latest": events[:10],
    }
    return out


def cmd_probe_task(args: argparse.Namespace) -> dict[str, Any]:
    """Print, or with ``--run`` start, the one-off probe task in the prod service's network."""
    url = REPO_RAW.format(sha=args.sha)
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    digest = hashlib.sha256(body).hexdigest()
    if args.expect_sha256 and digest != args.expect_sha256:
        raise SystemExit(f"sha256 of {url} is {digest}, expected {args.expect_sha256}")
    ecs = _client("ecs")
    services, tds, _ = _describe(ecs)
    svc = services[PROD_SERVICE]
    container = tds[svc["taskDefinition"]]["containerDefinitions"][0]["name"]
    request = {
        "cluster": CLUSTER,
        "taskDefinition": svc["taskDefinition"].rsplit("/", 1)[-1],
        "launchType": svc.get("launchType") or "FARGATE",
        "networkConfiguration": svc["networkConfiguration"],
        "startedBy": "pr00-probe",
        "overrides": {"containerOverrides": [{"name": container, "command": build_probe_command(args.sha, digest, args.only)}]},
    }
    out: dict[str, Any] = {"script_url": url, "script_sha256": digest, "run_task_request": request, "started": False}
    if not args.run:
        out["note"] = "Dry run. Nothing was started. Re-run with --run after the owner approves."
        return out
    task_arn = ecs.run_task(**request)["tasks"][0]["taskArn"]
    out.update(started=True, task_arn=task_arn)
    ecs.get_waiter("tasks_stopped").wait(cluster=CLUSTER, tasks=[task_arn], WaiterConfig={"Delay": 15, "MaxAttempts": 80})
    task = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])["tasks"][0]
    out["stopped_reason"] = task.get("stoppedReason")
    out["exit_codes"] = {c["name"]: c.get("exitCode") for c in task.get("containers", [])}
    out["lines"] = _probe_lines(tds[svc["taskDefinition"]], task_arn.rsplit("/", 1)[-1])
    return out


def _probe_lines(td: dict[str, Any], task_id: str) -> list[Any]:
    c = td["containerDefinitions"][0]
    options = (c.get("logConfiguration") or {}).get("options", {})
    stream = f"{options.get('awslogs-stream-prefix')}/{c['name']}/{task_id}"
    logs = _client("logs")
    lines: list[Any] = []
    kwargs: dict[str, Any] = {"logGroupName": options.get("awslogs-group"), "logStreamName": stream, "startFromHead": True}
    while True:
        page = logs.get_log_events(**kwargs)
        for event in page.get("events", []):
            message = event.get("message", "")
            if message.startswith("PR00 "):
                lines.append(json.loads(message[5:]))
            elif "Traceback" in message or "Error" in message:
                lines.append({"s": "stderr", "msg": scrub(message)})
        if page.get("nextForwardToken") == kwargs.get("nextToken"):
            break
        kwargs["nextToken"] = page["nextForwardToken"]
    return lines


def cmd_probe_logs(args: argparse.Namespace) -> dict[str, Any]:
    """Print the ``PR00`` lines of a finished probe task."""
    ecs = _client("ecs")
    task = ecs.describe_tasks(cluster=CLUSTER, tasks=[args.task_id])["tasks"][0]
    td = ecs.describe_task_definition(taskDefinition=task["taskDefinitionArn"])["taskDefinition"]
    return {
        "exit_codes": {c["name"]: c.get("exitCode") for c in task.get("containers", [])},
        "lines": _probe_lines(td, args.task_id.rsplit("/", 1)[-1]),
    }


def main(argv: list[str]) -> int:
    """Parse the subcommand, run it and print its JSON result."""
    parser = argparse.ArgumentParser(description="PR-00 AWS inspection and probe task.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect", help="read-only: ECS names, Logs Insights counts, CloudTrail RunTask")
    probe = sub.add_parser("probe-task", help="print (default) or --run the one-off probe task")
    probe.add_argument("--sha", required=True, help="git commit that holds backend/scripts/diag/pr00_probe.py")
    probe.add_argument("--expect-sha256", default="", help="refuse to continue unless the script has this digest")
    probe.add_argument("--only", default="nvidia,gemini,pinecone,redis")
    probe.add_argument("--run", action="store_true", help="actually start the task (owner approval required)")
    logs = sub.add_parser("probe-logs", help="print the PR00 lines of a finished probe task")
    logs.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    handler = {"inspect": cmd_inspect, "probe-task": cmd_probe_task, "probe-logs": cmd_probe_logs}[args.cmd]
    print(json.dumps(handler(args), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
