from __future__ import annotations

import httpx
import pytest

from scripts.demo import check_ai
from scripts.demo.fixtures import REPORTS

V1, V2 = "doc-v1", "doc-v2"


def docs_payload(*, ready=True):
    status = "READY" if ready else "ERROR"
    return {
        "documents": [
            {"id": V1, "filename": REPORTS[0].filename, "status": status},
            {"id": V2, "filename": REPORTS[1].filename, "status": status},
        ]
    }


class FakeApi:
    def __init__(self, *, gap_failures=(), compare_status=200, ready=True, login_status=200):
        self.calls: list[tuple[str, str]] = []
        self.bodies: dict[str, dict] = {}
        self.gap_failures = list(gap_failures)  # (status, body) for the first N gap-analysis calls
        self.compare_status = compare_status
        self.ready = ready
        self.login_status = login_status

    def handle(self, request: httpx.Request) -> httpx.Response:
        import json

        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={"detail": "bad credentials"})
            return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref"})
        assert request.headers.get("Authorization") == "Bearer tok"
        if path == "/documents":
            return httpx.Response(200, json=docs_payload(ready=self.ready))
        self.bodies[path] = json.loads(request.content)
        if path == "/gap-analysis":
            if self.gap_failures:
                status, body = self.gap_failures.pop(0)
                return httpx.Response(status, json=body)
            return httpx.Response(200, json={"gaps": [{"x": 1}, {"x": 2}], "coverage_score": 0.4})
        if path == "/compare":
            if self.compare_status != 200:
                return httpx.Response(
                    self.compare_status,
                    json={"detail": "The AI returned an invalid response. Please retry.",
                          "code": "structured_output_invalid", "retryable": True},
                )
            return httpx.Response(200, json={"differences": [1, 2, 3], "summary": "s"})
        return httpx.Response(404, json={"detail": "not found"})


def run(api: FakeApi, runs=5):
    lines: list[str] = []
    with httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client:
        check_ai.login(client, "demo@example.com", "pw")
        ok = check_ai.run_checks(client, runs=runs, out=lines.append)
    return ok, lines


def test_all_calls_succeeding_passes_and_uses_the_seeded_documents():
    api = FakeApi()
    ok, lines = run(api)

    assert ok
    assert "gap-analysis: 5 of 5 succeeded" in lines and "compare: 5 of 5 succeeded" in lines
    assert api.bodies["/gap-analysis"] == {"document_id": V2}  # the breaching version
    assert api.bodies["/compare"] == {"document_id_a": V1, "document_id_b": V2}
    assert sum(1 for _, p in api.calls if p == "/gap-analysis") == 5
    assert sum(1 for _, p in api.calls if p == "/compare") == 5


def test_a_typed_error_is_reported_with_its_code_and_fails_the_check():
    ok, lines = run(FakeApi(compare_status=502), runs=2)

    assert not ok
    text = "\n".join(lines)
    assert "compare 1/2: FAIL, HTTP 502, structured_output_invalid" in text
    assert "compare: 0 of 2 succeeded" in text
    assert "gap-analysis: 2 of 2 succeeded" in text


def test_one_failure_among_five_is_not_a_pass():
    gap = [(503, {"detail": "down", "code": "provider_unavailable", "retryable": True})]
    ok, lines = run(FakeApi(gap_failures=gap))

    assert not ok
    assert "gap-analysis: 4 of 5 succeeded" in lines


def test_an_empty_gap_list_still_counts_as_a_successful_call():
    api = FakeApi(gap_failures=[(200, {"gaps": [], "coverage_score": 1.0})])
    ok, lines = run(api, runs=1)

    assert ok
    assert any("0 gaps" in line for line in lines)


def test_missing_seed_documents_explain_what_to_do():
    api = FakeApi(ready=False)
    with httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client:
        check_ai.login(client, "d@example.com", "pw")
        with pytest.raises(check_ai.CheckError, match="scripts/demo.sh seed"):
            check_ai.find_seeded_documents(client)


def test_a_wrong_password_is_a_clear_error():
    api = FakeApi(login_status=401)
    with (
        httpx.Client(base_url="http://backend", transport=httpx.MockTransport(api.handle)) as client,
        pytest.raises(check_ai.CheckError, match="Sign-in failed"),
    ):
        check_ai.login(client, "d@example.com", "wrong")


def test_main_asks_for_the_password_and_reports_an_unreachable_backend(monkeypatch, capsys):
    monkeypatch.setattr(check_ai.getpass, "getpass", lambda prompt: "pw")

    assert check_ai.main(["--api", "http://127.0.0.1:9", "--email", "d@example.com"]) == 1
    assert "Cannot reach the backend" in capsys.readouterr().err
