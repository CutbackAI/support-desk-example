"""Only bounded synthetic result metadata may reach the read-only local browser."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from example_supportdesk import business
from example_supportdesk.optimization_view import summary
from example_supportdesk.optimize_demo import CONTRACT, INPUTS
from example_supportdesk.web import app


@pytest.fixture
def saved_result(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in INPUTS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    path = tmp_path / ".cutback/example-optimization/report.json"
    path.parent.mkdir(parents=True)
    value = {
        "contract": CONTRACT,
        "transport": "scripted_test_only",
        "status": "READY_FOR_HUMAN_REVIEW",
        "application_checks": {"all_passed": True, "rollback_exact": True},
        "validation_run": "00000000-0000-4000-8000-000000000001",
        "confirmation_run": "00000000-0000-4000-8000-000000000002",
        "winner": "search-aaaaaaaaaaaa",
        "candidates": [
            {
                "candidate": "search-aaaaaaaaaaaa",
                "model": "gpt-4.1-mini",
                "max_output_tokens": 32,
                "quality_gate_passed": True,
                "cheaper_on_sample": True,
                "sample_modeled_cost_difference_usd": "0.002",
            }
        ],
        "token": "OWNED_SECRET_SENTINEL",
        "diff": "OWNED_SOURCE_SENTINEL",
        "real_model_quality_verified": True,
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return tmp_path, path, value


def test_missing_lesson_does_not_require_optional_cutback_or_a_collector(tmp_path):
    assert summary(tmp_path) == {"status": "not_run"}


def test_saved_view_is_read_only_and_cannot_reflect_source_or_credentials(
    saved_result, monkeypatch
):
    root, _, _ = saved_result
    monkeypatch.chdir(root)
    monkeypatch.setenv("CUTBACK_ENABLED", "false")
    monkeypatch.setattr(business.client.responses, "create", lambda **kw: pytest.fail("NO_CALLS"))
    with TestClient(app) as client:
        response = client.get("/api/optimization")
        assert response.status_code == 200
        assert client.post("/api/optimization", json={"run": True}).status_code == 405
    value = response.json()
    assert value["status"] == "available"
    assert value["real_model_quality_verified"] is False
    assert value["real_customer_savings_verified"] is False
    assert value["production_savings_usd"] is None
    assert "OWNED_SECRET_SENTINEL" not in response.text
    assert "OWNED_SOURCE_SENTINEL" not in response.text


@pytest.mark.parametrize(
    "change",
    ["invalid_json", "oversize", "model", "cost", "same_run", "source", "invalid_run_type"],
)
def test_invalid_or_stale_saved_result_is_unavailable_without_echo(saved_result, change):
    root, path, value = saved_result
    if change == "invalid_json":
        path.write_text("OWNED_SECRET_SENTINEL", encoding="utf-8")
    elif change == "oversize":
        path.write_text("x" * 65537, encoding="utf-8")
    elif change == "source":
        (root / "fixtures/tickets.jsonl").write_text("changed data", encoding="utf-8")
    else:
        if change == "model":
            value["candidates"][0]["model"] = "<script>OWNED_SECRET_SENTINEL</script>"
        elif change == "cost":
            value["candidates"][0]["sample_modeled_cost_difference_usd"] = "NaN"
        elif change == "invalid_run_type":
            value["confirmation_run"] = True
        else:
            value["confirmation_run"] = value["validation_run"]
        path.write_text(json.dumps(value), encoding="utf-8")
    assert summary(root) == {"status": "unavailable"}
