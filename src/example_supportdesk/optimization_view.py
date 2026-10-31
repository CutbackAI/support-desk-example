"""Read-only, allowlisted projection of the saved synthetic lesson metadata."""

import json
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from .optimize_demo import CONTRACT, verify_inputs


def summary(root):
    path = root / ".cutback/example-optimization/report.json"
    if not path.exists():
        return {"status": "not_run"}
    try:
        for part in (root / ".cutback", path.parent, path):
            if part.is_symlink() or not part.resolve(strict=True).is_relative_to(root.resolve()):
                raise ValueError("UNSAFE_LOCAL_REPORT")
        if path.stat().st_size > 65536:
            raise ValueError("LOCAL_REPORT_TOO_LARGE")
        verify_inputs(root)
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["contract"] != CONTRACT or value["transport"] != "scripted_test_only":
            raise ValueError("UNSUPPORTED_LOCAL_REPORT")
        if value["status"] != "READY_FOR_HUMAN_REVIEW":
            raise ValueError("INCOMPLETE_LOCAL_REPORT")
        checks = value["application_checks"]
        if checks["all_passed"] is not True or checks["rollback_exact"] is not True:
            raise ValueError("INCOMPLETE_LOCAL_CHECKS")
        rows = value["candidates"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
            raise ValueError("INVALID_LOCAL_CANDIDATES")
        safe_rows = []
        for row in rows:
            if not re.fullmatch(r"search-[a-f0-9]{12}", row["candidate"]):
                raise ValueError("INVALID_LOCAL_CANDIDATE")
            if row["model"] not in {"gpt-4.1", "gpt-4.1-mini"}:
                raise ValueError("INVALID_LOCAL_MODEL")
            cap = row["max_output_tokens"]
            if type(cap) is not int or not 1 <= cap <= 64:
                raise ValueError("INVALID_LOCAL_OUTPUT_CAP")
            if any(
                type(row[key]) is not bool for key in ("quality_gate_passed", "cheaper_on_sample")
            ):
                raise ValueError("INVALID_LOCAL_GATE")
            cost = row["sample_modeled_cost_difference_usd"]
            if not isinstance(cost, str) or len(cost) > 48 or not Decimal(cost).is_finite():
                raise ValueError("INVALID_LOCAL_COST")
            safe_rows.append(
                {
                    key: row[key]
                    for key in (
                        "candidate",
                        "model",
                        "max_output_tokens",
                        "quality_gate_passed",
                        "cheaper_on_sample",
                        "sample_modeled_cost_difference_usd",
                    )
                }
            )
        winners = [row for row in safe_rows if row["candidate"] == value["winner"]]
        if (
            len(winners) != 1
            or not winners[0]["quality_gate_passed"]
            or not winners[0]["cheaper_on_sample"]
        ):
            raise ValueError("INVALID_LOCAL_WINNER")
        if any(
            not isinstance(value[key], str) or len(value[key]) != 36
            for key in ("validation_run", "confirmation_run")
        ):
            raise ValueError("INVALID_LOCAL_RUN_IDENTITY")
        runs = {key: str(UUID(value[key])) for key in ("validation_run", "confirmation_run")}
        if runs["validation_run"] == runs["confirmation_run"]:
            raise ValueError("CONFIRMATION_MUST_BE_SEPARATE")
        return {
            "status": "available",
            "evidence": "saved_local_scripted_fixture_result",
            "candidates": safe_rows,
            "winner": value["winner"],
            **runs,
            "application_checks_passed": True,
            "rollback_exact": True,
            "external_provider_calls": 0,
            "real_model_quality_verified": False,
            "real_customer_savings_verified": False,
            "production_savings_usd": None,
        }
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation):
        # No arbitrary saved field, exception, source diff, path or credential can
        # be reflected into a browser. This file is a local receipt, not proof of
        # independent CI authenticity or authority to execute another run.
        return {"status": "unavailable"}
