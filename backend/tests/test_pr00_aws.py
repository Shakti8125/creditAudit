"""Tests for the PR-00 AWS helper (``scripts/diag/pr00_aws.py``).

Only the pure functions are tested; they decide what reaches the output, and
the rule is names only, never an env value or a secret value.
"""

from __future__ import annotations

import json

from scripts.diag import pr00_aws as aws

ACCOUNT = "123456789012"


def _task_definition(revision: int, env_value: str, secret_prefix: str) -> dict:
    return {
        "family": "modelaudit-backend-task",
        "revision": revision,
        "taskRoleArn": f"arn:aws:iam::{ACCOUNT}:role/modelaudit-task-role",
        "executionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/ecsTaskExecutionRole",
        "containerDefinitions": [
            {
                "name": "backend",
                "image": f"{ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/modelaudit-ai/backend:prod-latest",
                "environment": [
                    {"name": "RATE_LIMIT_ENABLED", "value": env_value},
                    {"name": "ALLOWED_ORIGINS", "value": "https://private.example"},
                ],
                "secrets": [
                    {"name": "REDIS_URL", "valueFrom": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:{secret_prefix}-AbC123:REDIS_URL::"},
                    {"name": "NVIDIA_API_KEY", "valueFrom": f"arn:aws:ssm:us-east-1:{ACCOUNT}:parameter/modelaudit/shared/NVIDIA_API_KEY"},
                ],
                "logConfiguration": {"options": {"awslogs-group": "/ecs/modelaudit", "awslogs-stream-prefix": "ecs"}},
            }
        ],
    }


def test_task_definition_summary_holds_names_only() -> None:
    summary = aws.summarise_task_definition(_task_definition(7, "false", "modelaudit/prod"))
    dumped = json.dumps(summary)
    assert ACCOUNT not in dumped
    assert "https://private.example" not in dumped
    assert '"false"' not in dumped
    container = summary["containers"][0]
    assert container["image"] == "modelaudit-ai/backend:prod-latest"
    assert container["env_names"] == ["ALLOWED_ORIGINS", "RATE_LIMIT_ENABLED"]
    assert container["secret_names"] == ["NVIDIA_API_KEY", "REDIS_URL"]
    assert container["secret_sources"] == {
        "REDIS_URL": "secret:modelaudit/prod-AbC123:REDIS_URL",
        "NVIDIA_API_KEY": "parameter:/modelaudit/shared/NVIDIA_API_KEY",
    }
    assert summary["task_definition"] == "modelaudit-backend-task:7"
    assert summary["task_role"] == "modelaudit-task-role"


def test_compare_environments_reports_shared_sources() -> None:
    prod = aws.summarise_task_definition(_task_definition(7, "true", "modelaudit/prod"))
    same = aws.compare_environments(prod, prod)
    assert same["same_task_definition_revision"] is True
    assert same["secrets_read_from_the_same_source"] == ["NVIDIA_API_KEY", "REDIS_URL"]

    staging = aws.summarise_task_definition(_task_definition(8, "true", "modelaudit/staging"))
    diff = aws.compare_environments(prod, staging)
    assert diff["same_task_definition_revision"] is False
    assert diff["secrets_read_from_the_same_source"] == ["NVIDIA_API_KEY"]
    assert diff["secrets_read_from_different_sources"] == ["REDIS_URL"]


def test_run_task_event_flags_corpus_scripts() -> None:
    def event(command: list[str]) -> dict:
        detail = {
            "requestParameters": {
                "taskDefinition": "arn:aws:ecs:us-east-1:1:task-definition/modelaudit-backend-task:7",
                "overrides": {"containerOverrides": [{"name": "backend", "command": command}]},
            }
        }
        return {"EventTime": "2026-09-28", "Username": "deployer", "CloudTrailEvent": json.dumps(detail)}

    migration = aws.summarise_run_task_event(event(["alembic", "upgrade", "head"]))
    assert migration["corpus_script"] is False and migration["task_definition"] == "modelaudit-backend-task:7"
    seed = aws.summarise_run_task_event(event(["python", "scripts/seed_regulatory_standards.py"]))
    assert seed["corpus_script"] is True


def test_insights_query_counts_each_pattern() -> None:
    query = aws.insights_query(aws.LOG_GROUPS_OF_PATTERNS["rerank_and_models"])
    assert query.startswith("filter @message like /")
    assert "\\ " not in query, "an escaped space is not valid in the Insights regex"
    assert "strcontains(@message, \"failed on 'rerank'\") as rerank_failed" in query
    assert "sum(rerank_failed) as n_rerank_failed" in query
    assert aws.insights_regex(["a.b/c"]) == "a\\.b\\/c"


def test_probe_command_is_pinned_to_commit_and_digest() -> None:
    command = aws.build_probe_command("abc1234", "f" * 64, "nvidia,gemini")
    assert command[:2] == ["python", "-c"]
    assert "/Shakti8125/creditAudit/abc1234/backend/scripts/diag/pr00_probe.py" in command[2]
    assert "=='" + "f" * 64 + "'" in command[2]
    assert command[3:] == ["--only", "nvidia,gemini"]
    assert len(json.dumps(command)) < 2000, "ECS caps container overrides at 8 KiB"


def test_scrub_removes_urls_keys_and_uuids() -> None:
    line = (
        "Rate limiting error: connect to https://host.upstash.io failed token=abc "
        "tenant 7d0c5a4e-1111-2222-3333-444455556666 nvapi-XYZ"
    )
    cleaned = aws.scrub(line)
    assert "upstash" not in cleaned and "abc" not in cleaned and "7d0c5a4e" not in cleaned and "nvapi" not in cleaned
    assert cleaned.startswith("Rate limiting error")
