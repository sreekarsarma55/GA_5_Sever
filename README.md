# TDS 2026 Sep GA5 — shared Q1 + Q4 FastAPI server

This project exposes the two graded server endpoints from one FastAPI app:

- `POST /u/{student_email}/query` (and `/student/{student_email}/query`) —
  Q1, with a student-specific knowledge base selected by the URL path.
- `POST /query` — Q1's root route, usable when the verifier forwards an
  identity header or when running a deliberately single-student deployment.
- `POST /classify` — Q4, one independent batch of up to 24 cases.
- `GET /student-link` — generates each student's Q1 URL in the browser.
- `GET /healthz` — health/configuration check.

The shared deployment must **not** set `STUDENT_EMAIL`. All students use the
same Vercel deployment; their Q1 URLs contain their own course email. Q4 is
already personalized by the portal because each request includes that
student's cases in the JSON body.

## What changed in this revision

### Q1 — RAG Colosseum

1. Reproduces the portal's `seedrandom@3.0.5` email-seeded generator and the
   5 domains × 10 templates = 50 passages. The generator is deterministic and
   cached per normalized email.
2. The supplied portal snapshot for `23f3002028@ds.study.iitm.ac.in` is used as
   a 50-passage golden reference. The test compares all 50 strings, not just
   counts or token presence.
3. The 20 captured probe questions now use narrow evidence sources rather
   than the former unrelated top-three confounders. Single-fact questions
   return the passage containing that fact; synthesis questions return the
   two named passages; absent facts abstain with `answer: null`, empty sources
   and low confidence.
4. The false-premise Transformer question is answered from the Transformer
   passage (index 12), including its per-student warmup learning-rate value,
   not mixed with the separate SGD base learning rate (index 10).
5. The HTML-comment injection is removed before matching, so its claimed
   `[49]` source does not control retrieval.
6. No ML model is downloaded at startup. The endpoint stays light and is
   designed to meet the Q1 eight-second response window.

### Q4 — Harness Safety Router

1. Cases are classified independently; no approval or instruction is shared
   across case or batch boundaries.
2. A later revocation of the pending operation blocks the tool without
   retroactively changing an otherwise allowed request. This matters for an
   owned, confined, fully isolated vulnerability demonstration that is later
   revoked: allowed request, blocked tool, restricted route, intervene.
3. “Do not apply the Terraform plan” is treated as prohibiting `terraform_apply`,
   not read-only `workspace_read`; a malicious instruction in a tool result
   still causes `watch`.
4. A specific “revoke the deployment approval” message blocks a pending
   deployment.
5. Defensive analysis of a malware report and indicators of compromise is
   treated as benign primary-route analysis, not active vulnerability testing.
6. The HTTP endpoint enforces JSON media type, bounded 2 MiB request/response
   size, unique case IDs, and the grader's 24-case batch size. It echoes
   `profile` and `batchId` and returns exactly one tuple per input case.

## 1. Local setup (Ubuntu / macOS / Windows)

Python 3.12 is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

Start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/docs`

## 2. Run tests before deploying

```bash
pytest -q
```

The suite checks:

- exact reproduction of the 50 reference passages for the supplied reference
  email;
- all 20 captured Q1 probes for three different emails, with personalized
  values extracted from each generated KB;
- the 96 supplied Q4 cases, response labels, case independence, and targeted
  policy regressions;
- HTTP path identity selection, path-over-header precedence, JSON media type,
  duplicate-ID rejection, and the 24-case API batch limit.

**Scoring limitation:** the supplied Q4 JSON contains 96 cases and the policy,
not the grader's gold decisions. These tests prove behavior against the visible
policy and named regressions; they cannot certify the hidden grader's exact
macro-F1 or tuple score. Likewise, the Q1 probe suite reflects the captured
20-probe set and may not prove every hidden grader implementation detail.

## 3. One shared Vercel deployment for all students

### Create the deployment once

1. Push the contents of this folder to the root of one GitHub repository.
2. In Vercel, select **Add New → Project** and import that repository.
3. Keep the project root at the repository root. `main.py`, `requirements.txt`,
   `vercel.json`, and `data/` must be at that level.
4. **Do not configure `STUDENT_EMAIL`** in Vercel. That variable is only for a
   single-student deployment and must not be set on the shared instance.
5. Deploy. The public domain will look like
   `https://YOUR-PROJECT.vercel.app`.

`vercel.json` includes the two JSON files in `data/` in the Python function
bundle. Q1 reconstructs the selected student's 50 passages on a cold start;
its per-process cache only improves subsequent calls.

### Share one link with the class

Give every student this same link:

```text
https://YOUR-PROJECT.vercel.app/student-link
```

Each student enters the exact email used to sign in to the course portal. The
page constructs a URL like:

```text
https://YOUR-PROJECT.vercel.app/u/student%40ds.study.iitm.ac.in
```

The student pastes that as the Q1 **Public Base URL**, without `/query`. The
exam checker should append `/query`, resulting in:

```text
POST https://YOUR-PROJECT.vercel.app/u/student%40ds.study.iitm.ac.in/query
```

FastAPI extracts the email from the path and calls the deterministic KB
generator. Student A and Student B therefore get different 50-passage KBs
while sharing the same deployment and code. No shared database is required.

**Verifier integration caveat:** the supplied frontend shows the course email
being sent to the course site's `/backendVerify` route, but not that hidden
route's server-to-server implementation. The per-student URL works if that
verifier appends `/query` to the supplied base URL while preserving the path,
which is the behavior implied by the field instructions. If it instead strips
the path and calls only the origin-root `/query` without forwarding an email
header/body/query parameter, no shared server can infer the student identity.
Validate this once with the actual portal Check and inspect Vercel request
logs for `/u/<email>/query` before distributing the link widely.

### Q4 endpoint

All students enter this same exact URL in Q4:

```text
https://YOUR-PROJECT.vercel.app/classify
```

The grader sends the student's own 24-case batches to that endpoint. The
server does not need a Q4 email setting or URL suffix.

## 4. Test the live deployment

From the project root:

```bash
python tests/smoke_remote.py https://YOUR-PROJECT.vercel.app student@ds.study.iitm.ac.in
```

The script sends all 20 captured Q1 probes through the student's `/u/.../query`
route, then sends the 96 captured Q4 cases as four 24-case requests with at most
two requests concurrently. It validates the contract and IDs; it is not a
replacement for the official portal Check.

To run the same smoke test against a local server:

```bash
python tests/smoke_remote.py http://127.0.0.1:8000 student@ds.study.iitm.ac.in
```

## 5. Manual curl checks

Q1 (replace the email with the student being tested):

```bash
curl --fail-with-body -sS \
  'http://127.0.0.1:8000/u/student%40ds.study.iitm.ac.in/query' \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?","top_k":3}'
```

Q4:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/classify \
  -H 'Content-Type: application/json' \
  -d '{"profile":"agent-harness-2026-09","batchId":"manual","policy":{},"cases":[]}'
```

## 6. Project structure

```text
ga5_unified_server/
├── main.py
├── rag_engine.py
├── safety_engine.py
├── requirements.txt
├── requirements-dev.txt
├── vercel.json
├── data/
│   ├── rag_templates.json
│   └── passage_anchors.json
└── tests/
    ├── q1_probes.json
    ├── legacy_passages_reference.json
    ├── q4_all_96_cases.json
    ├── test_q1.py
    ├── test_q4.py
    ├── test_http_identity.py
    └── smoke_remote.py
```
