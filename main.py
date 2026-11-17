"""Unified FastAPI server for TDS 2026 Sep GA5 Questions 1 and 4."""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rag_engine import answer_question
from safety_engine import evaluate_case

app = FastAPI(
    title="TDS GA5 Unified Server",
    version="1.0.0",
    description="Personalized RAG endpoint for Q1 and deterministic safety router for Q4.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "TDS GA5 unified server",
        "version": app.version,
        "endpoints": {"q1": "POST /query", "q4": "POST /classify", "health": "GET /healthz"},
    }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    email_is_configured = bool(os.getenv("STUDENT_EMAIL", "").strip())
    return {
        "status": "ok",
        "q1_ready": email_is_configured,
        "q4_ready": True,
        "note": "Set STUDENT_EMAIL in the deployment environment to enable /query.",
    }


@app.post("/query")
async def query_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")

    question = str(body.get("question") or "")
    # The course's grading payload specifies only question/top_k. A per-call
    # email is also accepted for manual testing; otherwise use the deploy-time
    # STUDENT_EMAIL variable associated with this student's submission.
    email = str(body.get("email") or os.getenv("STUDENT_EMAIL", "")).strip().lower()
    if not email:
        raise HTTPException(
            status_code=503,
            detail="Q1 is not configured. Set STUDENT_EMAIL to the email used on the course page.",
        )
    try:
        top_k = int(body.get("top_k", 3))
        result = answer_question(question, email, top_k)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(content=result)


@app.post("/classify")
async def classify_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")

    cases = body.get("cases") or []
    if not isinstance(cases, list):
        raise HTTPException(status_code=400, detail="'cases' must be a JSON array.")
    if len(cases) > 100:
        raise HTTPException(status_code=413, detail="Too many cases in one request.")

    results = [evaluate_case(case if isinstance(case, dict) else {}) for case in cases]
    return JSONResponse(
        content={
            "profile": body.get("profile", "agent-harness-2026-09"),
            "batchId": body.get("batchId", ""),
            "results": results,
        }
    )
