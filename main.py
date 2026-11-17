"""Unified FastAPI server for TDS 2026 Sep GA5 Questions 1 and 4.

Q1 identity resolution order:
  1. Explicit student email in a trusted verifier header (when the course
     verifier forwards one).
  2. Student-specific URL prefix: /u/{email}/query or /student/{email}/query.
  3. Optional email in the JSON body or query string (manual/API testing).
  4. STUDENT_EMAIL environment variable (single-student fallback only).

For a shared deployment, students can use the same Vercel project and submit
https://<deployment>/u/<url-encoded-course-email> as the Q1 Public Base URL.
The course page appends /query to that base URL.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from rag_engine import answer_question, normalize_email
from safety_engine import evaluate_case

app = FastAPI(
    title="TDS GA5 Unified Server",
    version="1.1.0",
    description=(
        "Shared personalized RAG endpoint for Q1 and deterministic "
        "safety router for Q4."
    ),
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
        "endpoints": {
            "q1_shared": "POST /query (requires identity via header/body/query/env)",
            "q1_student_specific": "POST /u/{email}/query",
            "student_link_generator": "GET /student-link",
            "q4": "POST /classify",
            "health": "GET /healthz",
        },
    }


@app.get("/student-link", response_class=HTMLResponse)
async def student_link_page() -> HTMLResponse:
    """A client-side helper that creates each student's Q1 base URL."""
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GA5 Student Endpoint Link</title>
  <style>
    body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#18212f}
    label{display:block;font-weight:650;margin:18px 0 6px}
    input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #aab4c2;border-radius:8px;font:inherit}
    button{margin-top:16px;padding:11px 16px;border:0;border-radius:8px;background:#155eef;color:white;font:inherit;cursor:pointer}
    .result{margin-top:20px;padding:16px;border:1px solid #d0d5dd;border-radius:10px;background:#f8fafc}
    .result[hidden]{display:none} .hint{color:#475467} code{overflow-wrap:anywhere}
  </style>
</head>
<body>
  <h1>GA5 — create your personal Q1 URL</h1>
  <p class="hint">Everyone uses the same deployment. Enter the exact email used to sign in to the course page. This page generates a personalized Q1 base URL in your browser; it does not save your email.</p>
  <form id="make-link">
    <label for="email">Course login email</label>
    <input id="email" type="email" autocomplete="email" placeholder="23f3002028@ds.study.iitm.ac.in" required>
    <button type="submit">Generate my URLs</button>
  </form>
  <section id="result" class="result" hidden>
    <h2>Q1 — Public Base URL</h2>
    <p class="hint">Paste this into the Q1 Public Base URL field. Do not add <code>/query</code>.</p>
    <input id="q1" readonly aria-label="Personal Q1 base URL">
    <button type="button" id="copy-q1">Copy Q1 URL</button>
    <h2>Q4 — POST endpoint</h2>
    <p class="hint">All students use this same endpoint.</p>
    <input id="q4" readonly aria-label="Shared Q4 endpoint">
    <button type="button" id="copy-q4">Copy Q4 URL</button>
  </section>
  <script>
    const form=document.getElementById('make-link');
    const result=document.getElementById('result');
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const email=document.getElementById('email').value.trim().toLowerCase();
      if(!email || !email.includes('@')) return;
      document.getElementById('q1').value=location.origin+'/u/'+encodeURIComponent(email);
      document.getElementById('q4').value=location.origin+'/classify';
      result.hidden=false;
    });
    for(const [buttonId,inputId] of [['copy-q1','q1'],['copy-q4','q4']]){
      document.getElementById(buttonId).addEventListener('click',async()=>{
        const input=document.getElementById(inputId);
        await navigator.clipboard.writeText(input.value);
        document.getElementById(buttonId).textContent='Copied';
      });
    }
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    configured_email = normalize_email(os.getenv("STUDENT_EMAIL", ""))
    return {
        "status": "ok",
        # Q1 can run without a global email because each request may supply
        # its identity in a header or its URL path.
        "q1_ready": True,
        "q1_identity_modes": [
            "X-Student-Email header",
            "/u/{email}/query path",
            "JSON body email (manual testing)",
            "email query parameter (manual testing)",
            "STUDENT_EMAIL environment fallback",
        ],
        "single_student_fallback_configured": bool(configured_email),
        "q4_ready": True,
    }


def _identity_from_request(
    request: Request,
    body: dict[str, Any],
    path_email: str | None,
) -> str:
    """Resolve the Q1 student's email without sharing mutable global state."""
    header_email = (
        request.headers.get("x-student-email")
        or request.headers.get("x-quiz-email")
        or request.headers.get("x-user-email")
        or request.headers.get("x-account-email")
        or request.headers.get("x-tds-email")
    )
    query_email = (
        request.query_params.get("student_email")
        or request.query_params.get("email")
    )
    env_email = os.getenv("STUDENT_EMAIL", "")

    # Request-specific identity must always take precedence over the
    # deployment-level fallback, which is intended only for a single user.
    candidates = (header_email, path_email, body.get("email"), query_email, env_email)
    for candidate in candidates:
        normalized = normalize_email(str(candidate or ""))
        if normalized:
            return normalized
    return ""


async def _handle_query(request: Request, path_email: str | None = None) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")

    question = str(body.get("question") or "").strip()
    email = _identity_from_request(request, body, path_email)
    if not email:
        raise HTTPException(
            status_code=400,
            detail=(
                "Q1 needs the student's course email. Use /u/{email}/query, "
                "send X-Student-Email, or configure STUDENT_EMAIL for a "
                "single-student deployment."
            ),
        )

    try:
        top_k = int(body.get("top_k", 3))
        result = answer_question(question, email, top_k)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(content=result)


@app.post("/query")
async def query_endpoint(request: Request) -> JSONResponse:
    return await _handle_query(request)


@app.post("/u/{student_email}/query")
@app.post("/student/{student_email}/query")
async def student_query_endpoint(student_email: str, request: Request) -> JSONResponse:
    return await _handle_query(request, path_email=student_email)


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
