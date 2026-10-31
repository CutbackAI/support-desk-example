"""Check the actual synthetic source lesson, no-replay behavior and read-only UI."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from example_supportdesk.optimize_demo import optimize


def check():
    from cutback.agent_control import connect
    from cutback.application_checks import ApplicationCheckContract, verify
    from cutback.core.workspace import read_private

    root = Path.cwd().resolve()
    value = optimize(root)
    assert value["status"] == "READY_FOR_HUMAN_REVIEW", "LESSON_NOT_READY"
    assert value["external_provider_calls"] == 0, "LIVE_TRANSPORT_NOT_PERMITTED"
    assert value["validation_run"] != value["confirmation_run"], "SEPARATE_CONFIRMATION_REQUIRED"
    assert value["source_applied_to_original"] is False, "ORIGINAL_SOURCE_CHANGED"
    assert value["real_model_quality_verified"] is False, "REAL_QUALITY_NOT_ESTABLISHED"
    assert len(value["candidates"]) == 5, "MISSING_EVALUATED_ALTERNATIVES"
    failed = [row for row in value["candidates"] if not row["quality_gate_passed"]]
    assert len(failed) == 2 and all(row["max_output_tokens"] == 16 for row in failed), (
        "NEGATIVE_CONTROLS_MISSING"
    )
    private = root / ".cutback/example-optimization"
    contract = ApplicationCheckContract.model_validate(
        read_private(private / "application-contract.json")
    )
    verify(
        contract,
        read_private(private / "application-checks.json"),
        private / "base",
        private / "proposed",
    )
    control, project = connect(root, local=True)
    identities = [value["validation_run"], value["confirmation_run"]]

    def counts():
        reports = [
            control("GET", f"/v1/projects/{project}/experiments/{identity}")
            for identity in identities
        ]
        assert all(row["results"]["billing_complete"] is True for row in reports), (
            "INCOMPLETE_FIXTURE_USAGE"
        )
        assert all(
            row["results"]["native_fixture"]["transport"] == "scripted_test_only" for row in reports
        ), "FIXTURE_MARKER_MISSING"
        return [row["requests"] for row in reports]

    before = counts()
    assert optimize(root) == value, "SAVED_RESULT_CHANGED_ON_RESUME"
    assert counts() == before, "RESUME_ISSUED_ANOTHER_MODEL_CALL"
    os.environ["CUTBACK_ENABLED"] = "false"
    from example_supportdesk.web import app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            for _ in range(100):
                try:
                    if client.get(f"http://127.0.0.1:{port}/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise ValueError("APPLICATION_NOT_READY")
        browser = subprocess.run(
            ["node", "scripts/browser.mjs"],
            cwd=root,
            env={
                **os.environ,
                "EXAMPLE_URL": f"http://127.0.0.1:{port}",
                "EXAMPLE_OPTIMIZATION": "true",
            },
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        assert browser.returncode == 0, "OPTIMIZATION_BROWSER_FAILED"
        evidence = json.loads(browser.stdout)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "fixture_requests": before,
                    "separate_confirmation": True,
                    "application_checks_both_trees": True,
                    "rollback_exact": True,
                    "no_new_calls_on_resume": True,
                    "paid_provider_calls": 0,
                    "real_model_quality_verified": False,
                    "browser": evidence,
                }
            )
        )
    finally:
        server.should_exit = True
        thread.join(10)
        assert not thread.is_alive(), "APPLICATION_DID_NOT_STOP"


if __name__ == "__main__":
    try:
        check()
    except Exception:  # noqa: BLE001 -- never expose credential-bearing API/database exceptions.
        sys.exit("EXAMPLE_OPTIMIZATION_ACCEPTANCE_FAILED: inspect the owned private lesson state.")
