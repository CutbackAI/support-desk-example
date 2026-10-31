"""Optional Cutback observation; the application remains usable without Cutback."""

import os
import re
from contextlib import contextmanager, nullcontext

_observer = None


def start():
    global _observer
    if os.getenv("CUTBACK_ENABLED", "false").lower() != "true":
        return
    from cutback import init

    _observer = init(
        enabled=True,
        service_name="example-support-desk",
        environment="staging",
        providers=("openai",),
        endpoint=os.environ["CUTBACK_ENDPOINT"].rstrip("/") + "/v1/ingest/events",
        project_id=os.environ["CUTBACK_PROJECT_ID"],
        capture_content=False,
    )


@contextmanager
def request_scope():
    if _observer is None:
        with nullcontext():
            yield
        return
    from cutback.core.observation import observation_scope

    with observation_scope("simulation"):
        yield


def close():
    global _observer
    if _observer is not None:
        _observer.close(timeout_seconds=1)
        _observer = None


def enabled():
    return _observer is not None


def collected_summary():
    """Read this project's simulation totals without sending keys to the browser."""
    if _observer is None or not os.getenv("CUTBACK_VIEWER_TOKEN"):
        return {"status": "not_connected"}
    import httpx

    try:
        from cutback.agent_control import Control

        with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
            control = Control(
                os.environ["CUTBACK_ENDPOINT"], os.environ["CUTBACK_VIEWER_TOKEN"], client=client
            )
            result = control(
                "GET",
                "/v1/projects/"
                + os.environ["CUTBACK_PROJECT_ID"]
                + "/usage?group_by=model&traffic_kind=simulation",
            )["summary"]
        if not isinstance(result, dict) or any(
            type(result.get(field)) is not int or not 0 <= result[field] <= 10**12
            for field in ("observed_requests", "missing_usage_count")
        ):
            return {"status": "unavailable"}
        if any(
            result.get(field) is not None
            and (
                type(result[field]) is not str
                or not re.fullmatch(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,12})?", result[field])
            )
            for field in ("modeled_cost_usd", "known_modeled_cost_subtotal_usd")
        ):
            return {"status": "unavailable"}
        return {
            "status": "available",
            **{
                field: result[field]
                for field in (
                    "observed_requests",
                    "missing_usage_count",
                    "modeled_cost_usd",
                    "known_modeled_cost_subtotal_usd",
                )
            },
            "evidence": "local_fixture_not_real_model_quality_or_invoice",
        }
    except (ValueError, KeyError, TypeError, httpx.HTTPError):
        return {"status": "unavailable"}


def delivery():
    if _observer is None:
        return {"enabled": False}
    health = _observer.health()
    return {
        "enabled": True,
        **{
            key: health.get(key, 0)
            for key in (
                "observed",
                "exported",
                "dropped",
                "rejected",
                "export_failed",
                "normalization_failed",
                "queue_depth",
            )
        },
    }
