"""Closed local HTTP fixture. It has no network client or real provider key."""

import json

import httpx


def transport(request: httpx.Request) -> httpx.Response:
    if request.method != "POST" or not request.url.path.endswith("/responses"):
        return httpx.Response(400, json={"error": {"message": "UNSUPPORTED_LOCAL_FIXTURE_REQUEST"}})
    body = json.loads(request.content)
    text = body["input"].casefold()
    if any(
        word in text
        for word in ("charge", "payment", "invoice", "refund", "billing", "receipt", "card", "paid")
    ):
        label = "billing"
    elif any(
        word in text
        for word in (
            "outage",
            "offline",
            "down",
            "error",
            "broken",
            "failing",
            "crash",
            "unavailable",
            "timeout",
            "502",
            "slow",
        )
    ):
        label = "incident"
    else:
        label = "access"
    # This deliberately bad bounded alternative lets application tests reject
    # an unsafe token-cap change. It says nothing about real model quality.
    if body.get("max_output_tokens", 64) <= 16:
        label = "access" if label != "access" else "billing"
    response = {
        "id": "resp_local_fixture",
        "object": "response",
        "created_at": 1,
        "model": body["model"],
        "status": "completed",
        "service_tier": "default",
        "output": [
            {
                "id": "msg_local_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": label, "annotations": []}],
            }
        ],
    }
    if "[usage unavailable]" not in text:
        response["usage"] = {
            "input_tokens": 100,
            "output_tokens": 2,
            "total_tokens": 102,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    return httpx.Response(200, json=response)
