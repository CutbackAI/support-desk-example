"""The synthetic lesson cannot silently accept edited or private application data."""

import shutil
from pathlib import Path

import pytest

from example_supportdesk.optimize_demo import INPUTS, choose_candidate, fixture_key, verify_inputs


def test_only_the_exact_public_fixture_inputs_are_permitted(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in INPUTS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    verify_inputs(tmp_path)
    (tmp_path / "fixtures/tickets.jsonl").write_text("edited application data", encoding="utf-8")
    with pytest.raises(ValueError, match="EXAMPLE_REQUIRES_UNCHANGED_PUBLIC_FIXTURES"):
        verify_inputs(tmp_path)


def test_candidate_selection_uses_gates_complete_usage_and_decimal_cost():
    def row(key, value, *, quality=True):
        return {
            "candidate": {"key": key},
            "quality_gate_passed": quality,
            "cheaper_on_sample": True,
            "sample_modeled_cost_difference_usd": value,
        }

    report = {
        "billing_complete": True,
        "recommendations": [
            row("unsafe", "100", quality=False),
            row("b", "0.10000000000000000001"),
            row("a", "0.1"),
            row("zero", "0"),
        ],
    }
    assert choose_candidate(report) == "b"
    report["billing_complete"] = False
    with pytest.raises(ValueError, match="EXAMPLE_REQUIRES_COMPLETE_FIXTURE_USAGE"):
        choose_candidate(report)


def test_no_qualified_candidate_stops_instead_of_creating_a_patch():
    with pytest.raises(ValueError, match="EXAMPLE_NO_CANDIDATE_PASSED_NO_PATCH_CREATED"):
        choose_candidate({"billing_complete": True, "recommendations": []})


def test_fixture_executor_key_replaces_and_restores_shell_key(monkeypatch):
    import os

    monkeypatch.setenv("CUTBACK_EXPERIMENT_OPENAI_KEY", "owned-test-sentinel")
    with fixture_key():
        assert os.environ["CUTBACK_EXPERIMENT_OPENAI_KEY"] == "synthetic-fixture-only"
    assert os.environ["CUTBACK_EXPERIMENT_OPENAI_KEY"] == "owned-test-sentinel"
