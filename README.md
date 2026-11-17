# TDS 2026 Sep GA5 — unified Q1 + Q4 server

This project exposes both graded endpoints from one small FastAPI app:

- `POST /query` — Q1 personalized 50-passage RAG service.
- `POST /classify` — Q4 deterministic safety/router classifier.
- `GET /` and `GET /healthz` — health checks.

The app does not download a transformer model on startup. It generates the 50
Q1 passages locally using the same email-seeded `seedrandom` 3.x algorithm and
the templates/tokens extracted from the assignment page. Q4 is a stateless,
per-case policy engine. No approval is shared across cases or batches.

## 1. Local run (Ubuntu / macOS / Windows)

Python 3.12 is recommended.

```bash
cd ga5_unified_server
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For a local one-student test, optionally set `STUDENT_EMAIL`. For testing
multiple students, leave it unset and use the student-specific URL path shown
below.

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/` and `http://127.0.0.1:8000/docs`.

## 2. Test Q1 locally

```bash
python tests/test_q1.py
```

The test runs the 20 unique Q1 questions captured from the provided request log.
It checks that answerable probes return the expected passage IDs and that the
known unanswerable probes abstain. It also checks that the generated KB matches
the previously supplied server's 50 passages when `GA5_REFERENCE_EMAIL` is set
to the matching reference account. The test identity is read from
`STUDENT_EMAIL` or `GA5_TEST_EMAIL`; otherwise a non-real placeholder is used.

## 3. Test Q4 locally

```bash
python tests/test_q4.py
```

This runs all 96 supplied cases through the classifier and checks response
shape, legal label values, stable case IDs, case independence, and key policy
invariants (revocation, path traversal, private-data transfer, preflight,
owned-isolated security tests, etc.). The supplied JSON contains cases and the
policy but no official expected labels, so this is a regression/invariant test,
not a claim of 96/96 official accuracy.

## 4. Deploy one shared service for multiple students on Vercel

This version supports a shared deployment. Students do **not** need their own
Vercel projects. Q1 must know which student's email seeded the 50 passages.
The visible course-page code uses `d.email` to generate the passages, but the
visible browser code sends that email to the course site's `/backendVerify`
endpoint; it does not put the email in the documented Q1 JSON body. The
server therefore supports several identity channels:

1. `X-Student-Email` (and common equivalent headers) if the course verifier
   forwards student identity to the submitted endpoint.
2. A per-student base URL path, which works even when the verifier does not
   forward a header, provided it appends `/query` to the submitted base URL.
3. JSON/query email for manual testing.
4. `STUDENT_EMAIL` as a single-student fallback.

### One-time owner deployment

1. Put the contents of this folder at the root of a GitHub repository.
2. Import that repository into Vercel (**Add New → Project**).
3. Do **not** set `STUDENT_EMAIL` for the shared deployment. That prevents a
   missing identity from silently falling back to the owner's KB.
4. Deploy once. The service URL will look like
   `https://YOUR-PROJECT.vercel.app`.
5. Test `GET https://YOUR-PROJECT.vercel.app/healthz`. It should report
   `q1_ready: true` because request-level identity is supported.

### Share this link with all students

Once deployed, share this single link with everyone:

```text
https://YOUR-PROJECT.vercel.app/student-link
```

Each student opens it, enters the exact email used on the TDS course page, and
clicks **Generate my URLs**. The page constructs the personal Q1 base URL in
their browser; it does not store the email. It also shows the common Q4 URL.

### What each student enters for Q1

Each student uses the same host, but appends their own URL-encoded email as a
path segment after `/u/`. For example, if the deployment is
`https://YOUR-PROJECT.vercel.app` and the student's course email is
`23f3002028@ds.study.iitm.ac.in`, that student enters this as the **Public
Base URL** (without `/query`):

```text
https://YOUR-PROJECT.vercel.app/u/23f3002028%40ds.study.iitm.ac.in
```

The grader should then call:

```text
POST https://YOUR-PROJECT.vercel.app/u/23f3002028%40ds.study.iitm.ac.in/query
```

The FastAPI route extracts the email from the path and generates the exact
50-passage KB for that student. Another student enters the same deployment
URL with their own email segment. No redeployment or code edit is needed. A
second alias is available at `/student/{email}/query`.

**Important verification caveat:** the supplied files include the browser code
that submits `response` and `email` to the course's `/backendVerify` endpoint,
but not the implementation of that backend endpoint. The browser code alone
therefore cannot prove whether it appends `/query` while preserving a path
prefix or forwards an identity header. The path-based URL is designed for the
normal base-URL-plus-`/query` behavior implied by the form. Before circulating
the link widely, do one Q1 Check with a second test account and inspect your
Vercel function logs: the request path should contain `/u/<that-email>/query`
or the request should include `X-Student-Email`. If the grader forces the path
to the origin-root `/query` and sends no identity header/body/query field, a
shared deployment cannot distinguish students; the grader would need to pass
identity in a header/body or allow a per-student URL path/subdomain.

### Q4 URL

Q4 already sends the selected student's personalized `cases` in every POST
body, so all students can use the same exact URL:

```text
https://YOUR-PROJECT.vercel.app/classify
```

No email setting or per-student Q4 URL is needed.

Vercel detects FastAPI from `main.py`. The supplied `vercel.json` bundles
`data/**`, the two JSON files needed to regenerate the personalized passages.

## 5. Verify the actual deployment

After Vercel finishes deploying, run this from the project folder:

```bash
python tests/smoke_remote.py https://YOUR-PROJECT.vercel.app your-course-email@ds.study.iitm.ac.in
```

It calls all 20 captured Q1 probes and sends the 96 supplied Q4 cases as four
24-case batches, with no more than two Q4 requests in flight. It checks the
response schema, IDs, known Q1 source rankings, and abstentions. It does not
claim to reproduce the hidden grader's official score.

## 6. Local endpoint smoke tests

Q1:

```bash
curl -sS http://127.0.0.1:8000/query \\
  -H 'Content-Type: application/json' \\
  -d '{"question":"What is the heartbeat interval in Raft?","top_k":3}' | python -m json.tool
```

Q4:

```bash
curl -sS http://127.0.0.1:8000/classify \\
  -H 'Content-Type: application/json' \\
  -d '{"profile":"agent-harness-2026-09","batchId":"smoke-test","policy":{},"cases":[]}' | python -m json.tool
```

## 7. Optional Vercel CLI deployment

You can deploy without the dashboard too. For the recommended shared deployment,
do not add `STUDENT_EMAIL`. Only add it when deliberately configuring a
single-student instance. From this project's root:

```bash
npm install --global vercel
vercel login
vercel
```

Follow the prompts to create/link the project, then deploy:

```bash
vercel --prod
```

For a single-student instance only, add `STUDENT_EMAIL` with `vercel env add
STUDENT_EMAIL production` and redeploy. Do not set it on the shared instance.

## Important personalization note

The visible Q1 browser code generates the personalized knowledge base from the
signed-in email, then posts the entered base URL plus that email to the course
site's `/backendVerify` endpoint. It does not show the hidden verifier's
server-to-server request implementation. The API contract displayed on the
page contains only `question` and `top_k`, so a shared endpoint needs another
identity channel. This project accepts a forwarded identity header and a
student-specific `/u/{email}/query` path. For a single student's own
deployment, `STUDENT_EMAIL` remains available as a fallback.
