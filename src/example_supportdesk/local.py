"""Owned loopback collector setup. Credentials remain in the ignored private workspace."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def location(root):
    from cutback.core.workspace import private_directory

    return private_directory(root, ".cutback/example")


def connection(root):
    from cutback.core.workspace import read_private

    value = read_private(location(root) / "connection.json")
    if value.get("phase") != "READY":
        raise ValueError("EXAMPLE_SETUP_UNCERTAIN_RECONCILE_OWNED_PROJECT_BEFORE_RETRY")
    if datetime.fromisoformat(value["expires_at"]) <= datetime.now(UTC):
        raise ValueError("EXAMPLE_CREDENTIAL_EXPIRED_REAUTHORIZE_OWNED_PROJECT")
    return value


def prepare(root, port):
    from cutback.agent_control import Control
    from cutback.core.workspace import read_private, workspace_lock, write_private
    from cutback.instrumentation.attribution import build_source_map
    from cutback.local_stack import configured, up
    from cutback.scanner import scan

    private = location(root)
    with workspace_lock(private):
        path = private / "connection.json"
        if path.exists():
            existing = connection(root)
            if existing["endpoint"] != f"http://127.0.0.1:{port}":
                raise ValueError("EXAMPLE_COLLECTOR_DESTINATION_CHANGED")
            collector = up(root, port=port, allow_payloads=False)
            inventory = scan(root)
            source_map = build_source_map(root, inventory)
            map_path = root / ".cutback/source-map.json"
            if source_map != read_private(map_path):
                _, configuration = configured(root)
                control = Control(collector["endpoint"], configuration["admin"])
                existing["phase"] = "UPDATING_SOURCE"
                write_private(path, existing)
                control("POST", "/v1/projects/" + existing["project"] + "/scans", inventory)
                write_private(map_path, source_map)
                existing["phase"] = "READY"
                write_private(path, existing)
            return {"status": "READY", "endpoint": existing["endpoint"], "reused": True}
        collector = up(root, port=port, allow_payloads=False)
        _, configuration = configured(root)
        if configuration["allow_payloads"]:
            raise ValueError("EXAMPLE_REQUIRES_METADATA_ONLY_COLLECTOR")
        control = Control(collector["endpoint"], configuration["admin"])
        inventory = scan(root)
        if len(inventory["call_sites"]) != 1:
            raise ValueError("EXAMPLE_EXPECTS_EXACTLY_ONE_NATIVE_CALL_SITE")
        # Before any non-idempotent credential writes, retain a crash marker.
        # An uncertain setup stops; it never silently mints replacement keys.
        value = {
            "phase": "SETTING_UP",
            "endpoint": collector["endpoint"],
            "slug": "example-support-" + uuid4().hex[:12],
        }
        write_private(path, value, exclusive=True)
        project = control("POST", "/v1/projects", {"slug": value["slug"], "environment": "staging"})
        value["project"] = project["id"]
        write_private(path, value)
        base = "/v1/projects/" + value["project"]
        control("POST", base + "/scans", inventory)
        for role in ("ingest", "viewer"):
            key = control(
                "POST",
                base + "/keys",
                {"role": role, "environment": "staging", "expires_in_days": 1},
            )
            value[role + "_token"] = key["token"]
            value[role + "_key_id"] = key["key_id"]
            value["expires_at"] = min(value.get("expires_at", key["expires_at"]), key["expires_at"])
            write_private(path, value)
        write_private(root / ".cutback/source-map.json", build_source_map(root, inventory))
        value["phase"] = "READY"
        write_private(path, value)
        assert read_private(path)["phase"] == "READY"
        return {
            "status": "READY",
            "endpoint": collector["endpoint"],
            "call_sites": 1,
            "payload_storage_enabled": False,
            "provider_calls": 0,
        }


def configure(root):
    from cutback.core.workspace import read_private
    from cutback.instrumentation.attribution import build_source_map
    from cutback.scanner import scan

    value = connection(root)
    if build_source_map(root, scan(root)) != read_private(root / ".cutback/source-map.json"):
        raise ValueError("EXAMPLE_SOURCE_CHANGED_RUN_PREPARE_FIRST")
    os.environ.update(
        {
            "CUTBACK_ENABLED": "true",
            "CUTBACK_ENDPOINT": value["endpoint"],
            "CUTBACK_PROJECT_ID": value["project"],
            "CUTBACK_PROJECT_TOKEN": value["ingest_token"],
            "CUTBACK_VIEWER_TOKEN": value["viewer_token"],
            "CUTBACK_SOURCE_MAP": str(root / ".cutback/source-map.json"),
        }
    )


def report(root):
    from cutback.agent_control import Control

    value = connection(root)
    control = Control(value["endpoint"], value["viewer_token"])
    body = control(
        "GET",
        "/v1/projects/" + value["project"] + "/usage?group_by=workflow&traffic_kind=simulation",
    )
    return {"evidence": "local_synthetic_metadata", "invoice_verified": False, "report": body}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "serve", "report", "down"))
    parser.add_argument("--collector-port", type=int, default=8091)
    parser.add_argument("--app-port", type=int, default=8010)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if not (root / "src/example_supportdesk/business.py").is_file():
        parser.error("Run from the example repository root.")
    try:
        if args.action == "prepare":
            result = prepare(root, args.collector_port)
        elif args.action == "report":
            result = report(root)
        elif args.action == "down":
            from cutback.local_stack import down

            result = down(root)
        else:
            configure(root)
            import uvicorn

            uvicorn.run(
                "example_supportdesk.web:app",
                host="127.0.0.1",
                port=args.app_port,
                access_log=False,
                log_level="warning",
            )
            return
    except (ValueError, OSError, KeyError):
        # Never emit arbitrary exception bodies, credentials or collector payloads.
        parser.exit(
            1,
            "EXAMPLE_LOCAL_OPERATION_FAILED: inspect the owned local collector and private setup phase. No credentials were printed.\n",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
