from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader

from app.ledger import LedgerService
from app.models import (
    HealthResponse,
    LedgerLookupRequest,
    LedgerLookupResponse,
    LedgerMergeRequest,
    LedgerMergeResponse,
    OutreachEvent,
    OutreachEventResponse,
    OutreachValidationRequest,
    OutreachValidationResponse,
)
from app.outreach import validate_outreach
from app.storage import StorageError, build_store


app = FastAPI(
    title="Customs Buyer Intelligence Ledger",
    version="2.1.0",
    description="Persistent, auditable buyer evidence ledger and deterministic outreach firewall.",
    servers=[{"url": os.getenv("PUBLIC_BASE_URL", "https://YOUR-SERVICE.onrender.com")}],
)
service = LedgerService(build_store())
action_key_header = APIKeyHeader(name="X-Action-Key", auto_error=False)


@app.middleware("http")
async def basic_api_hardening(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 2_000_000:
        return JSONResponse(status_code=413, content={"detail": "request body exceeds 2 MB"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


def require_action_key(x_action_key: str | None = Security(action_key_header)) -> None:
    expected = os.getenv("ACTION_API_KEY", "")
    local_mode = os.getenv("STORE_MODE", "local").strip().lower() == "local"
    if not expected and local_mode:
        return
    if not expected:
        raise HTTPException(status_code=503, detail="ACTION_API_KEY is not configured")
    if not x_action_key:
        raise HTTPException(status_code=401, detail="missing X-Action-Key header")
    if not hmac.compare_digest(x_action_key, expected):
        raise HTTPException(status_code=401, detail="X-Action-Key value does not match ACTION_API_KEY")


@app.get("/health", operation_id="getHealth", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check whether the backend is awake. This does not inspect or modify buyer data."""
    return HealthResponse(
        **{
        "status": "ok",
        "service": "customs-buyer-intelligence-ledger",
        "version": "2.1.0",
        "store_mode": os.getenv("STORE_MODE", "local").strip().lower(),
        }
    )


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy() -> str:
    return """
    <!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
    <title>Privacy Policy - Customs Buyer Intelligence</title></head><body>
    <h1>Privacy Policy / 隐私政策</h1>
    <p>This private service stores only buyer research data intentionally submitted through its authenticated API.
    It does not sell data, run advertising trackers, or call an OpenAI API.</p>
    <p>本私有服务仅保存经身份验证接口主动提交的买家调查数据；不出售数据、不运行广告追踪，也不调用 OpenAI API。</p>
    <p>Repository access tokens and action keys are held only as hosting environment secrets and are never returned by the API.</p>
    <p>仓库令牌与 Action 密钥仅作为托管平台环境变量保存，接口不会返回这些密钥。</p>
    </body></html>
    """


@app.post(
    "/ledger/lookup",
    operation_id="lookupBuyerLedger",
    dependencies=[Depends(require_action_key)],
    response_model=LedgerLookupResponse,
)
async def lookup_buyer_ledger(request: LedgerLookupRequest) -> LedgerLookupResponse:
    """Load prior buyer, shipment, evidence, contact, and event data before starting a new investigation."""
    try:
        return await service.lookup(request)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/ledger/merge",
    operation_id="mergeBuyerLedger",
    dependencies=[Depends(require_action_key)],
    response_model=LedgerMergeResponse,
)
async def merge_buyer_ledger(request: LedgerMergeRequest) -> LedgerMergeResponse:
    """Append and deduplicate source-bound evidence, shipment records, and contacts after current research."""
    try:
        return await service.merge(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/outreach/events",
    operation_id="recordOutreachEvent",
    dependencies=[Depends(require_action_key)],
    response_model=OutreachEventResponse,
)
async def record_outreach_event(request: OutreachEvent) -> OutreachEventResponse:
    """Record a sent, bounce, reply, CRM, or rating event only from user confirmation, an upload, or a connector receipt."""
    try:
        return await service.record_event(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/outreach/validate",
    operation_id="validateOutreachDraft",
    dependencies=[Depends(require_action_key)],
    response_model=OutreachValidationResponse,
)
async def validate_outreach_draft(request: OutreachValidationRequest) -> OutreachValidationResponse:
    """Apply the deterministic recipient-union and safety firewall before presenting a mailto draft link."""
    return validate_outreach(request)
