"""Verify native SDK → real HTTP collector → PostgreSQL → metadata report locally."""

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

from example_supportdesk.local import configure, connection, prepare, report


def check():
    root = Path.cwd().resolve()
    prepare(root, 8091)
    configure(root)
    from cutback.agent_control import Control
    from cutback.core.inventory import workflow_identity
    from cutback.scanner import scan

    from example_supportdesk.web import app

    before = report(root)["report"]["summary"]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            for _ in range(100):
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise ValueError("APPLICATION_NOT_READY")
            canary = "SYNTHETIC_PRIVATE_TICKET_CANARY"
            for text, route in [
                ("Please refund my invoice. " + canary, "billing"),
                ("The service is down. [usage unavailable] " + canary, "incident"),
            ]:
                response = client.post("/api/route", json={"text": text})
                assert response.status_code == 200, "APPLICATION_REQUEST_FAILED"
                assert response.json()["route"] == route, "APPLICATION_ROUTE_INCORRECT"
            for _ in range(100):
                health = client.get("/api/health").json()["delivery"]
                if health.get("exported", 0) == 2:
                    break
                if health.get("dropped", 0):
                    raise ValueError("METADATA_DELIVERY_LOSS")
                time.sleep(0.05)
            else:
                raise ValueError("METADATA_NOT_DELIVERED")
        expected_calls, expected_missing = 2, 1
        if os.getenv("EXAMPLE_CHECK_BROWSER") == "true":
            subprocess.run(
                ["node", "scripts/browser.mjs"],
                check=True,
                cwd=root,
                env={**os.environ, "EXAMPLE_URL": f"http://127.0.0.1:{port}/"},
                timeout=120,
            )
            expected_calls, expected_missing = 6, 3
            for _ in range(100):
                with httpx.Client(trust_env=False, timeout=5) as status_client:
                    health = status_client.get(f"http://127.0.0.1:{port}/api/health").json()[
                        "delivery"
                    ]
                if health.get("exported", 0) == expected_calls:
                    break
                time.sleep(0.05)
            else:
                raise ValueError("BROWSER_METADATA_NOT_DELIVERED")
        result = report(root)
        summary = result["report"]["summary"]
        assert summary["observed_requests"] == before["observed_requests"] + expected_calls
        assert summary["missing_usage_count"] == before["missing_usage_count"] + expected_missing
        assert summary["modeled_cost_usd"] is None
        assert summary["actual_billed_cost_usd"] is None
        assert result["report"]["coverage"]["population_coverage_percent"] is None
        inventory = scan(root)
        expected = {
            workflow_identity(entry["file"], entry["symbol"])[0]
            for site in inventory["call_sites"]
            for entry in site["entry_points"]
            if entry["file"] == "src/example_supportdesk/web.py"
        }
        assert len(expected) == 1
        assert any(
            group["key"] in expected and group["observed_requests"] >= 2
            for group in result["report"]["groups"]
        ), "WORKFLOW_ATTRIBUTION_MISSING"
        saved = connection(root)
        with httpx.Client(trust_env=False, timeout=5) as scoped:
            response = scoped.get(
                saved["endpoint"] + "/v1/projects/" + saved["project"] + "/usage",
                headers={"Authorization": "Bearer " + saved["ingest_token"]},
            )
            assert response.status_code == 403, "INGEST_READ_NOT_DENIED"
            response = scoped.post(
                saved["endpoint"] + "/v1/projects/" + saved["project"] + "/scans",
                headers={"Authorization": "Bearer " + saved["viewer_token"]},
                json=inventory,
            )
            assert response.status_code == 403, "VIEWER_WRITE_NOT_DENIED"
        control = Control(saved["endpoint"], saved["viewer_token"])
        events = control("GET", "/v1/projects/" + saved["project"] + "/events")
        assert canary not in json.dumps(events), "CONTENT_ENTERED_METADATA"
        assert saved["ingest_token"] not in json.dumps(events)
        assert saved["viewer_token"] not in json.dumps(events)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "native_calls": expected_calls,
                    "real_http_collection": True,
                    "postgresql_report": True,
                    "scanner_workflow_attributed": True,
                    "missing_usage_preserved": True,
                    "payload_capture": False,
                    "paid_provider_calls": 0,
                }
            )
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "APPLICATION_DID_NOT_STOP"


if __name__ == "__main__":
    try:
        check()
    except Exception as exc:  # noqa: BLE001 -- suppress arbitrary credential-bearing client exception text.
        # A fixed error avoids dumping credentials from arbitrary client exceptions.
        permitted = {
            "APPLICATION_NOT_READY",
            "APPLICATION_REQUEST_FAILED",
            "APPLICATION_ROUTE_INCORRECT",
            "METADATA_DELIVERY_LOSS",
            "METADATA_NOT_DELIVERED",
            "BROWSER_METADATA_NOT_DELIVERED",
            "WORKFLOW_ATTRIBUTION_MISSING",
            "CONTENT_ENTERED_METADATA",
            "APPLICATION_DID_NOT_STOP",
            "INGEST_READ_NOT_DENIED",
            "VIEWER_WRITE_NOT_DENIED",
        }
        code = str(exc) if str(exc) in permitted else "UNCLASSIFIED_ACCEPTANCE_FAILURE"
        sys.exit("EXAMPLE_COLLECTOR_ACCEPTANCE_FAILED: " + code)
