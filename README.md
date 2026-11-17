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

Set the email used to sign in to the TDS course page:

```bash
export STUDENT_EMAIL='your-student-email@ds.study.iitm.ac.in'  # Linux/macOS
# PowerShell: $env:STUDENT_EMAIL='your-student-email@ds.study.iitm.ac.in'
```

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

## 4. Deploy to Vercel

This version is intentionally light: the Q1 retrieval is deterministic and
uses no PyTorch, sentence-transformers, NumPy, or external embedding API. That
keeps it suitable for Vercel's Python Functions bundle and short request time.

1. Create a GitHub repository and upload the contents of this folder to its
   root (not the parent directory).
2. In Vercel, choose **Add New → Project**, import that GitHub repository, and
   keep the detected Python/FastAPI settings. The root should contain
   `main.py`, `requirements.txt`, and `vercel.json`.
3. Before deploying, open **Project → Settings → Environment Variables**.
   Add `STUDENT_EMAIL` with the exact email used on the TDS course page, for
   the **Production** environment. Do not put it in source code or commit a
   real `.env` file.
4. Deploy. After deployment, test:

   - `https://YOUR-PROJECT.vercel.app/`
   - `https://YOUR-PROJECT.vercel.app/healthz`
   - `POST https://YOUR-PROJECT.vercel.app/query`
   - `POST https://YOUR-PROJECT.vercel.app/classify`

5. For Q1, submit the **base URL only** in the assignment field, without
   `/query`: `https://YOUR-PROJECT.vercel.app`. The page adds `/query` itself.
6. For Q4, submit the exact route: `https://YOUR-PROJECT.vercel.app/classify`.
7. Keep the deployment available through both Check and Save. When you change
   an environment variable, redeploy so the new deployment receives it.

Vercel detects FastAPI from the root `main.py` app object. The supplied
`vercel.json` explicitly bundles `data/**` (the two JSON files required to
recreate the personalized knowledge base) and excludes the local test corpus.
No `/api` prefix or rewrite is required for this FastAPI entrypoint.

## 5. Verify the actual deployment

After Vercel finishes deploying, run this from the project folder:

```bash
python tests/smoke_remote.py https://YOUR-PROJECT.vercel.app
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

You can deploy without the dashboard too. From this project's root:

```bash
npm install --global vercel
vercel login
vercel
```

Follow the prompts to create/link the project. Add the production variable and
deploy:

```bash
vercel env add STUDENT_EMAIL production
vercel --prod
```

When prompted for the value, enter your course-login email. For environment
variable changes later, run `vercel env rm STUDENT_EMAIL production`, add it
again, and redeploy with `vercel --prod`.

## Important personalization note

The Q1 endpoint contract shown in the assignment sends `question` and `top_k`,
not the student's email. Therefore a shared deployment cannot infer which
student's personalized KB to use from the official request alone. Set
`STUDENT_EMAIL` to your own course-login email for your submission. For manual
multi-user testing, `/query` also accepts an optional `email` field, but the
course grader is not required to send it.
# GA_5_Sever
