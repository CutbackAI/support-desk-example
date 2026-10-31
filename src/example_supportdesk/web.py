"""A small business surface around native SDK calls; all model responses are local fixtures."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from . import business, observability


class Ticket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


@asynccontextmanager
async def lifespan(app):
    observability.start()
    try:
        yield
    finally:
        observability.close()


app = FastAPI(title="Example Support Desk", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def home():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {
        "status": "ready",
        "mode": "synthetic",
        "external_model_requests": False,
        "cutback_enabled": observability.enabled(),
        "delivery": observability.delivery(),
    }


@app.post("/api/route")
def route(ticket: Ticket):
    with observability.request_scope():
        result = business.route_ticket(ticket.text)
    label = result.output_text.strip()
    if label not in {"access", "billing", "incident"}:
        raise HTTPException(502, "LOCAL_FIXTURE_RESPONSE_INVALID")
    usage = result.usage
    return {
        "route": label,
        "mode": "synthetic",
        "model": result.model,
        "input_tokens": usage.input_tokens if usage is not None else None,
        "output_tokens": usage.output_tokens if usage is not None else None,
        "usage_origin": "local_fixture" if usage is not None else "unavailable",
        "external_model_requests": False,
    }


@app.get("/api/observation")
def observation():
    return observability.collected_summary()
