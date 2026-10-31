"""Run the owned synthetic optimization lesson; never use a live model transport.

The normal Cutback collector, PostgreSQL worker, evaluation gates, source patcher
and application-check runner do the work. This command only orchestrates those
components for the three exact public fixture files below.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

INPUTS = {
    "src/example_supportdesk/business.py": "f032866abf0599312a38425114cc0061d44d714fe38c73d004e50003889c28f0",
    "src/example_supportdesk/fixture_provider.py": "deba4ac746537d409ae72d3b71cf67a132c524b870c8484320f51f716b162694",
    "fixtures/tickets.jsonl": "f96b9146f9fa14d5f852fe91464f008ef1bfdb00ed9834b1b8a455b1fe053be6",
}
CONTRACT = "support-desk-synthetic-optimization-v1"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def verify_inputs(root):
    root = root.resolve(strict=True)
    for name, expected in INPUTS.items():
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("EXAMPLE_INPUT_REDIRECTED")
        if digest(path.read_bytes()) != expected:
            raise ValueError("EXAMPLE_REQUIRES_UNCHANGED_PUBLIC_FIXTURES")


def choose_candidate(results):
    if results.get("billing_complete") is not True:
        raise ValueError("EXAMPLE_REQUIRES_COMPLETE_FIXTURE_USAGE")
    choices = []
    for row in results.get("recommendations", []):
        if row.get("quality_gate_passed") is True and row.get("cheaper_on_sample") is True:
            value = Decimal(str(row["sample_modeled_cost_difference_usd"]))
            if value.is_finite() and value > 0:
                choices.append((value, row["candidate"]["key"]))
    if not choices:
        raise ValueError("EXAMPLE_NO_CANDIDATE_PASSED_NO_PATCH_CREATED")
    return min(choices, key=lambda pair: (-pair[0], pair[1]))[1]


@contextmanager
def fixture_environment():
    # Even if the shell has a real key, this executor receives only a fake key.
    name = "CUTBACK_EXPERIMENT_OPENAI_KEY"
    prior = os.environ.get(name)
    payload_name = "CUTBACK_ALLOW_PAYLOADS"
    prior_payloads = os.environ.get(payload_name)
    os.environ[name] = "synthetic-fixture-only"
    os.environ[payload_name] = "true"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior
        if prior_payloads is None:
            os.environ.pop(payload_name, None)
        else:
            os.environ[payload_name] = prior_payloads


def ticket_workflow(inventory):
    from cutback.core.inventory import workflow_identity

    workflows = {
        workflow_identity(entry["file"], entry["symbol"])[0]
        for site in inventory["call_sites"]
        if site["source_file"] == "src/example_supportdesk/business.py"
        for entry in site["entry_points"]
        if entry["file"] == "src/example_supportdesk/web.py" and entry["kind"] == "http_route"
    }
    if len(workflows) != 1:
        raise ValueError("EXAMPLE_REQUIRES_ONE_SCANNED_TICKET_ROUTE")
    return workflows.pop()


def execute_saved(root, control):
    verify_inputs(root)
    import httpx
    from cutback.agent import advance, load_session
    from cutback.evals.artifacts import EncryptedFileStore
    from cutback.evals.executors import OpenAIExecutor
    from cutback.local_stack import configured, database_url
    from cutback.server.api import create_app
    from cutback.server.worker import run_one

    # Imported only after the independent application's exact public inputs and
    # explicit native fixture plan have been checked.
    from .fixture_provider import transport

    state = load_session(root)
    fixture = state.get("plan", {}).get("native_fixture", {})
    if fixture.get("transport") != "scripted_test_only":
        raise ValueError("EXAMPLE_REQUIRES_FROZEN_NATIVE_FIXTURE_PLAN")
    if state["phase"] == "PLAN_READY":
        state = advance(
            root,
            control,
            plan_hash=state["plan"]["plan_hash"],
            approval_ref="owned-public-fixtures-only",
        )
    elif state["phase"] in {"APPROVING", "QUEUEING"}:
        state = advance(root, control)
    if state["phase"] in {"COMPLETED", "PROPOSAL_READY"}:
        return state
    if state["phase"] not in {"QUEUED", "RUNNING"} or not state.get("run_id"):
        raise ValueError("EXAMPLE_SAVED_RUN_REQUIRES_RECONCILIATION")
    current = control("GET", f"/v1/projects/{state['project_id']}/experiments/{state['run_id']}")
    if current["status"] == "COMPLETED":
        return advance(root, control)
    if current["status"] != "QUEUED":
        # In particular, never re-execute crashed, running, failed or blocked work.
        raise ValueError("EXAMPLE_RUN_NOT_QUEUED_INSPECT_SAVED_EVIDENCE")
    location, configuration = configured(root)
    if configuration["allow_payloads"] is not True:
        raise ValueError("EXAMPLE_OWNED_ENCRYPTED_FIXTURE_STORE_REQUIRED")
    app = create_app(
        database_url=database_url(location, configuration),
        admin_token=configuration["admin"],
        allow_insecure_http=True,
    )
    store = EncryptedFileStore(
        location / "encrypted", base64.b64decode(configuration["payload_key"])
    )
    calls = 0

    def closed_transport(request):
        nonlocal calls
        calls += 1
        return transport(request)

    class FixtureExecutor:
        synthetic_transport = True

        def execute(self, model, text, timeout_seconds):
            if model.provider != "openai" or model.model not in {"gpt-4.1", "gpt-4.1-mini"}:
                raise ValueError("EXAMPLE_UNSUPPORTED_FIXTURE_MODEL")
            return native.execute(model, text, timeout_seconds)

    try:
        with fixture_environment():
            native = OpenAIExecutor(
                http_client=httpx.Client(
                    transport=httpx.MockTransport(closed_transport), trust_env=False
                )
            )
            try:
                result = run_one(
                    app.state.sessions,
                    store,
                    executor=FixtureExecutor(),
                    execution_enabled=True,
                    only_run_id=state["run_id"],
                )
            finally:
                native.close()
        if result["status"] != "COMPLETED" or calls == 0:
            raise ValueError("EXAMPLE_FIXTURE_RUN_NOT_COMPLETED_INSPECT_SAVED_EVIDENCE")
        return advance(root, control)
    finally:
        app.state.engine.dispose()


def apply_diff(root, patch):
    # The only permitted patch was generated for the pinned synthetic application.
    # No shell, hooks, filters, interactive credential helper or network is used.
    executable = shutil.which("git")
    if not executable or not patch:
        raise ValueError("EXAMPLE_SOURCE_DIFF_REQUIRED")
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    for arguments in (("apply", "--check", "-"), ("apply", "-")):
        result = subprocess.run(
            [executable, "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *arguments],
            input=patch.encode(),
            capture_output=True,
            env=env,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise ValueError("EXAMPLE_SOURCE_DIFF_NOT_APPLICABLE")


def check_proposal(root, directory, artifact):
    from cutback.application_checks import ApplicationCommand, git, prepare, run_checks
    from cutback.core.workspace import write_private

    if artifact["source_file"] != "src/example_supportdesk/business.py":
        raise ValueError("EXAMPLE_PATCH_OUTSIDE_PUBLIC_BUSINESS_FILE")
    if digest(artifact["diff"].encode()) != artifact["diff_sha256"]:
        raise ValueError("EXAMPLE_PATCH_DIGEST_MISMATCH")
    base = directory / "base"
    proposed = directory / "proposed"
    # A partially created review workspace is evidence to inspect, not permission
    # to erase a user's edits or start a second execution.
    if base.exists() or proposed.exists():
        raise ValueError("EXAMPLE_PARTIAL_REVIEW_WORKSPACES_REQUIRE_INSPECTION")
    git(root, "worktree", "add", "--detach", str(base), artifact["source_commit"])
    git(root, "worktree", "add", "--detach", str(proposed), artifact["source_commit"])
    apply_diff(proposed, artifact["diff"])
    source = artifact["source_file"]
    after = proposed / source
    if digest(after.read_bytes()) != artifact["verification"]["after_sha256"]:
        raise ValueError("EXAMPLE_PROPOSED_SOURCE_MISMATCH")
    git(proposed, "add", "--", source)
    git(
        proposed,
        "-c",
        "user.name=Cutback synthetic example",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Review synthetic source candidate locally",
    )
    contract = prepare(
        base,
        proposed,
        [
            ApplicationCommand(
                key="application-contract",
                runtime="python",
                arguments=[
                    "-m",
                    "pytest",
                    "tests/test_application.py",
                    "-q",
                    "--tb=short",
                    "--no-showlocals",
                ],
                timeout_seconds=120,
            )
        ],
    )
    write_private(
        directory / "application-contract.json", contract.model_dump(mode="json"), exclusive=True
    )
    receipt = run_checks(contract, base, proposed, execute_local=True)
    write_private(directory / "application-checks.json", receipt, exclusive=True)
    if not receipt["all_passed"]:
        raise ValueError("EXAMPLE_APPLICATION_CHECKS_FAILED_NO_SOURCE_CHANGE_ACCEPTED")
    apply_diff(proposed, artifact["rollback_diff"])
    if after.read_bytes() != (base / source).read_bytes():
        raise ValueError("EXAMPLE_ROLLBACK_DID_NOT_RESTORE_EXACT_SOURCE")
    apply_diff(proposed, artifact["diff"])
    if git(proposed, "status", "--porcelain"):
        raise ValueError("EXAMPLE_REVIEW_TREE_CHANGED")
    return {
        "all_passed": True,
        "receipt_hash": receipt["receipt_hash"],
        "contract_hash": receipt["contract_hash"],
        "rollback_exact": True,
        "base_commit": contract.base.commit,
        "proposed_commit": contract.proposed.commit,
        "customer_quality": "not_established",
    }


def optimize(root, *, port=8091):
    from cutback.agent import analyze, confirm, gate, load_session, prepare, proposal
    from cutback.agent_control import connect
    from cutback.application_checks import git, source_root
    from cutback.core.native_fixture import NATIVE_FIXTURE_CONTRACT
    from cutback.core.workspace import (
        private_directory,
        read_private,
        workspace_lock,
        write_private,
    )
    from cutback.local_stack import configured, down, status, up
    from cutback.scanner import scan

    if NATIVE_FIXTURE_CONTRACT != "native-source-fixture-v1":
        raise ValueError("EXAMPLE_REQUIRES_NATIVE_FIXTURE_CAPABLE_CUTBACK")
    verify_inputs(root)
    if source_root(root) != root or git(root, "status", "--porcelain"):
        raise ValueError("EXAMPLE_CLEAN_REPOSITORY_ROOT_REQUIRED")
    directory = private_directory(root, ".cutback/example-optimization")
    with workspace_lock(directory):
        journal_path = directory / "journal.json"
        commit = git(root, "rev-parse", "HEAD").decode().strip()
        if journal_path.exists():
            journal = read_private(journal_path)
            if journal.get("contract") != CONTRACT or journal.get("source_commit") != commit:
                raise ValueError("EXAMPLE_SAVED_SOURCE_IDENTITY_CHANGED")
            if journal.get("phase") == "COMPLETED":
                return read_private(directory / "report.json")
        else:
            session_file = root / ".cutback/agent/session.json"
            if session_file.exists() and read_private(session_file)["phase"] != "ANALYZED":
                raise ValueError("EXAMPLE_EXISTING_AGENT_WORK_REQUIRES_INSPECTION")
            journal = {"contract": CONTRACT, "source_commit": commit, "phase": "PREPARING"}
            write_private(journal_path, journal, exclusive=True)
        running = status(root)
        if running["status"] == "READY":
            _, configuration = configured(root)
            if configuration["endpoint"] != f"http://127.0.0.1:{port}":
                raise ValueError("EXAMPLE_EXISTING_COLLECTOR_DESTINATION_CHANGED")
            if not configuration["allow_payloads"]:
                down(root)
        up(root, port=port, allow_payloads=True)
        control, project = connect(root, local=True)
        workflow = ticket_workflow(scan(root))
        if journal["phase"] == "PREPARING":
            state = analyze(root, workflow=workflow)
            if state["phase"] in {"ANALYZED", "SOURCE_CHANGED"}:
                state = prepare(
                    root,
                    control,
                    project,
                    files=["fixtures/tickets.jsonl"],
                    rights_basis="synthetic",
                    rights_ref="owned-public-support-desk-fixtures",
                    max_usd="5",
                    max_requests=1000,
                    workflow=workflow,
                    minimum=1,
                    independent_labels=True,
                    representative=False,
                    min_test_samples=6,
                    automatic=True,
                    fixture_transport=True,
                )
            if state["phase"] != "PLAN_READY":
                raise ValueError("EXAMPLE_PREPARATION_REQUIRES_INSPECTION")
            journal.update(phase="EVALUATING", session_id=load_session(root)["id"])
            write_private(journal_path, journal)
        state = load_session(root)
        if state["id"] != journal["session_id"]:
            raise ValueError("EXAMPLE_SAVED_SESSION_IDENTITY_CHANGED")
        if journal["phase"] == "EVALUATING":
            state = execute_saved(root, control)
            if not state.get("confirmation"):
                report = control("GET", f"/v1/projects/{project}/experiments/{state['run_id']}")
                winner = choose_candidate(report["results"])
                journal.update(
                    winner=winner,
                    validation_run=state["run_id"],
                    validation_rows=decision_rows(report["results"]),
                )
                write_private(journal_path, journal)
                confirm(
                    root,
                    control,
                    candidate=winner,
                    max_usd="5",
                    max_requests=1000,
                    purpose="owned-synthetic-independent-confirmation",
                )
            state = execute_saved(root, control)
            if not gate(root, control, candidate=journal["winner"], sample_only=True)["passed"]:
                raise ValueError("EXAMPLE_INDEPENDENT_FIXTURE_CONFIRMATION_FAILED")
            if gate(root, control, candidate=journal["winner"])["passed"]:
                raise ValueError("EXAMPLE_SYNTHETIC_EVIDENCE_MUST_NOT_PASS_REAL_QUALITY_GATE")
            artifact = proposal(
                root, control, purpose="owned-synthetic-source-review", candidate=journal["winner"]
            )
            write_private(directory / "proposal.json", artifact)
            journal.update(phase="REVIEWING", confirmation_run=state["run_id"])
            write_private(journal_path, journal)
        artifact = read_private(directory / "proposal.json")
        checks = check_proposal(root, directory, artifact)
        result = {
            "contract": CONTRACT,
            "status": "READY_FOR_HUMAN_REVIEW",
            "transport": "scripted_test_only",
            "external_provider_calls": 0,
            "validation_run": journal["validation_run"],
            "confirmation_run": journal["confirmation_run"],
            "candidates": journal["validation_rows"],
            "winner": journal["winner"],
            "application_checks": checks,
            "source_applied_to_original": False,
            "proposal": ".cutback/example-optimization/proposal.json",
            "review_worktree": ".cutback/example-optimization/proposed",
            "real_model_quality_verified": False,
            "real_customer_savings_verified": False,
            "production_savings_usd": None,
            "invoice_verified_cost_usd": None,
        }
        write_private(directory / "report.json", result)
        journal["phase"] = "COMPLETED"
        write_private(journal_path, journal)
        return result


def decision_rows(results):
    return [
        {
            "candidate": row["candidate"]["key"],
            "model": row["candidate"]["model"],
            "max_output_tokens": row["candidate"]["max_output_tokens"],
            "quality_gate_passed": row.get("quality_gate_passed") is True,
            "cheaper_on_sample": row.get("cheaper_on_sample") is True,
            "sample_modeled_cost_difference_usd": row.get("sample_modeled_cost_difference_usd"),
        }
        for row in results.get("recommendations", [])
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "report"))
    parser.add_argument("--collector-port", type=int, default=8091)
    args = parser.parse_args()
    try:
        root = Path.cwd().resolve()
        if args.action == "run":
            result = optimize(root, port=args.collector_port)
        else:
            verify_inputs(root)
            from cutback.core.workspace import read_private

            result = read_private(root / ".cutback/example-optimization/report.json")
    except (ImportError, ValueError, OSError, KeyError):
        # Only owned fixed uppercase codes can leave this process. Raw errors may
        # contain source, collector bodies, database URLs or credentials.
        import sys

        error = sys.exc_info()[1]
        code = str(error) if type(error) is ValueError else "EXAMPLE_OPTIMIZATION_FAILED"
        if not re.fullmatch(r"[A-Z][A-Z_]{1,119}", code):
            code = "EXAMPLE_OPTIMIZATION_FAILED"
        parser.exit(1, code + ": inspect saved private state; no automatic billable retry.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
