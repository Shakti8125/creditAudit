from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from scripts.demo import seed
from scripts.demo.fixtures import REPORTS

TODAY = date(2026, 10, 4)


class FakeApi:
    """A minimal stand-in for the backend that records what the seed calls."""

    def __init__(self, *, taken_emails=(), upload_status=200, db="connected"):
        self.calls: list[tuple[str, str]] = []
        self.auth_headers: dict[str, str | None] = {}
        self.upload_version_ids: list[str] = []
        self.registered: list[str] = []
        self.taken_emails = set(taken_emails)
        self.upload_status = upload_status
        self.db = db

    def handle(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        self.calls.append((request.method, request.url.path))
        self.auth_headers[key] = request.headers.get("Authorization")
        path = request.url.path

        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "db": self.db})
        if path == "/auth/register":
            email = json.loads(request.content)["email"]
            self.registered.append(email)
            if email in self.taken_emails:
                return httpx.Response(400, json={"detail": "Email already registered"})
            return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref"})
        if path == "/models" and request.method == "POST":
            return httpx.Response(
                201, json={"id": "model-1", "current_version": {"id": "version-1"}}
            )
        if path == "/models/model-1/versions":
            return httpx.Response(201, json={"id": "version-2"})
        if path == "/documents/upload":
            body = request.content.decode("latin-1")
            self.upload_version_ids.append(
                "version-2" if "version-2" in body else "version-1"
            )
            if self.upload_status != 200:
                return httpx.Response(
                    self.upload_status,
                    json={"detail": "Document processing failed. Please try again or contact support."},
                )
            return httpx.Response(200, json={"chunk_count": 7})
        if path == "/models/model-1":
            return httpx.Response(200, json={"status": "BREACH"})
        return httpx.Response(404, json={"detail": "not found"})


def run_seed(api: FakeApi) -> list[str]:
    lines: list[str] = []
    with httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client:
        seed.run(client, app_url="http://localhost:5173", today=TODAY, out=lines.append)
    return lines


def test_seeds_one_model_with_two_versions_and_both_reports():
    api = FakeApi()
    lines = run_seed(api)

    assert api.calls == [
        ("GET", "/health"),
        ("POST", "/auth/register"),
        ("POST", "/models"),
        ("POST", "/documents/upload"),
        ("POST", "/models/model-1/versions"),
        ("POST", "/documents/upload"),
        ("GET", "/models/model-1"),
    ]
    assert api.upload_version_ids == ["version-1", "version-2"]
    assert api.registered == ["demo.20261004@example.com"]
    assert any("Model status is now BREACH" in line for line in lines)


def test_every_call_after_registration_is_authenticated():
    api = FakeApi()
    run_seed(api)

    assert api.auth_headers["POST /auth/register"] is None
    for key in ("POST /models", "POST /documents/upload", "POST /models/model-1/versions"):
        assert api.auth_headers[key] == "Bearer tok"


def test_the_password_is_printed_exactly_once():
    lines = run_seed(FakeApi())
    text = "\n".join(lines)

    password_lines = [line for line in lines if line.strip().startswith("Password:")]
    assert len(password_lines) == 1
    password = password_lines[0].split("Password:")[1].strip()
    assert len(password) >= 12
    assert text.count(password) == 1


def test_a_taken_address_falls_back_to_a_numbered_one():
    api = FakeApi(taken_emails={"demo.20261004@example.com", "demo.20261004.2@example.com"})
    run_seed(api)

    assert api.registered == [
        "demo.20261004@example.com",
        "demo.20261004.2@example.com",
        "demo.20261004.3@example.com",
    ]


def test_a_failed_upload_explains_itself_and_the_password_was_already_shown():
    api = FakeApi(upload_status=500)
    lines: list[str] = []
    with (
        httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client,
        pytest.raises(seed.SeedError) as excinfo,
    ):
        seed.run(client, app_url="http://x", today=TODAY, out=lines.append)

    message = str(excinfo.value)
    assert REPORTS[0].filename in message
    assert "HTTP 500" in message
    assert "scripts/demo.sh preflight" in message
    assert any(line.strip().startswith("Password:") for line in lines)


def test_a_database_that_is_down_stops_the_seed_before_registering():
    api = FakeApi(db="disconnected")
    with (
        httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client,
        pytest.raises(seed.SeedError, match="database"),
    ):
        seed.run(client, app_url="http://x", today=TODAY, out=lambda _: None)
    assert api.calls == [("GET", "/health")]


def test_main_reports_an_unreachable_backend_and_exits_non_zero(capsys):
    assert seed.main(["--api", "http://127.0.0.1:9"]) == 1
    assert "Cannot reach the backend" in capsys.readouterr().err
