"""Application-owned behavioral checks; no external inference or collector is required."""

import pytest
from fastapi.testclient import TestClient

from example_supportdesk import business
from example_supportdesk.web import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CUTBACK_ENABLED", "false")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "text, expected",
    [
        ("I was charged twice for my subscription.", "billing"),
        ("Please send my invoice.", "billing"),
        ("Can I get a refund for yesterday's payment?", "billing"),
        ("I cannot sign into my account.", "access"),
        ("Please reset my password.", "access"),
        ("The service is down and requests return 502.", "incident"),
        ("Every request returns an error.", "incident"),
        ("The application is offline.", "incident"),
    ],
)
def test_ticket_reaches_the_expected_queue(client, text, expected):
    response = client.post("/api/route", json={"text": text})
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == expected
    assert data["mode"] == "synthetic"
    assert data["external_model_requests"] is False
    assert text not in response.text


def test_missing_usage_stays_unknown(client):
    response = client.post("/api/route", json={"text": "Wrong invoice. [usage unavailable]"})
    assert response.status_code == 200
    data = response.json()
    assert data["route"] == "billing"
    assert data["input_tokens"] is None
    assert data["output_tokens"] is None
    assert data["usage_origin"] == "unavailable"


def test_application_check_rejects_an_unsafe_token_cap(monkeypatch):
    native_create = business.client.responses.create

    def constrained(**kwargs):
        return native_create(**{**kwargs, "max_output_tokens": 16})

    monkeypatch.setattr(business.client.responses, "create", constrained)
    # This is a deliberately bad fixture alternative, not a real quality study.
    assert business.route_ticket("Please refund this payment.").output_text != "billing"


@pytest.mark.parametrize(
    "body", [{"text": ""}, {"text": "x" * 4001}, {"text": "Hi", "api_key": "not-accepted"}]
)
def test_invalid_inputs_are_rejected(client, body):
    response = client.post("/api/route", json=body)
    assert response.status_code == 422


def test_example_starts_without_cutback(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["cutback_enabled"] is False
    response = client.get("/")
    assert response.status_code == 200
    assert "Local simulation" in response.text
    assert '<html lang="en">' in response.text
    response = client.get("/api/observation")
    assert response.status_code == 200
    assert response.json() == {"status": "not_connected"}


@pytest.mark.parametrize("kind", ["outage", "malformed_counts", "malformed_money"])
def test_read_only_report_never_exposes_untrusted_error_or_receipt_content(monkeypatch, kind):
    pytest.importorskip(
        "cutback.agent_control", reason="Report qualification needs the optional cutback extra"
    )
    from example_supportdesk import observability

    monkeypatch.setattr(observability, "_observer", object())
    monkeypatch.setenv("CUTBACK_ENDPOINT", "http://127.0.0.1:8091")
    monkeypatch.setenv("CUTBACK_PROJECT_ID", "00000000-0000-4000-8000-000000000001")
    monkeypatch.setenv("CUTBACK_VIEWER_TOKEN", "synthetic-viewer-" + "x" * 40)
    canary = "SYNTHETIC_PRIVATE_RESPONSE_CANARY"

    class UntrustedCollector:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args):
            if kind == "outage":
                raise ValueError(canary)
            return {
                "summary": {
                    "observed_requests": canary if kind == "malformed_counts" else 2,
                    "missing_usage_count": 1,
                    "modeled_cost_usd": None,
                    "known_modeled_cost_subtotal_usd": canary
                    if kind == "malformed_money"
                    else "0.000432000000",
                }
            }

    monkeypatch.setattr("cutback.agent_control.Control", UntrustedCollector)
    # Call the read surface without application startup resetting the observer.
    from example_supportdesk.web import observation

    assert observation() == {"status": "unavailable"}
