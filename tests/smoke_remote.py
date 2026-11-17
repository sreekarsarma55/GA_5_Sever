"""End-to-end smoke test for a deployed GA5 server.

Usage: python tests/smoke_remote.py https://your-project.vercel.app

This checks all 20 captured Q1 probes and the 96 supplied Q4 cases in four
24-case batches, with no more than two Q4 requests in flight.
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (sys.argv[1] if len(sys.argv) > 1 else "").rstrip("/")
LOCAL_HTTP = BASE.startswith("http://127.0.0.1") or BASE.startswith("http://localhost")
if not BASE.startswith("https://") and not LOCAL_HTTP:
    raise SystemExit("Pass an HTTPS deployment URL (or http://127.0.0.1 for local testing).")


def post_json(url: str, payload: dict, timeout: int = 55) -> tuple[dict, str]:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            if "application/json" not in content_type.lower():
                raise RuntimeError(f"{url} returned non-JSON Content-Type: {content_type}")
            return json.loads(response.read().decode("utf-8")), content_type
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"{url}: HTTP {exc.code}: {detail}") from exc


# Q1: the grader contract sends question/top_k only; the service reads the
# student email from the deployment's STUDENT_EMAIL setting.
probes = json.loads((ROOT / "tests/q1_probes.json").read_text(encoding="utf-8"))
q1_expected = {
    0: [0, 1, 3], 1: [10, 11, 19], 2: [20, 21, 25], 3: [40, 41, 37],
    4: None, 5: None, 6: None, 7: None,
    8: [0, 1, 3], 9: [10, 11, 19], 10: [20, 21, 25], 11: [40, 41, 37],
    12: [0, 1, 3], 13: [0, 1, 3], 14: [12, 10, 19], 15: None,
    16: [4, 5, 2], 17: [48, 40, 49], 18: [16, 17, 18], 19: [21, 20, 25],
}
for index, question in enumerate(probes):
    result, _ = post_json(BASE + "/query", {"question": question, "top_k": 3})
    expected = q1_expected[index]
    assert set(("answer", "sources", "scores", "confidence")) <= result.keys(), (index, result)
    assert result["sources"] == (expected or []), (index, expected, result)
    assert len(result["sources"]) == len(result["scores"])
print(f"Q1 PASS: all {len(probes)} captured probes responded with expected source IDs / abstentions")

# Q4: run all 96 sample cases as the page does: four batches of 24, maximum two
# requests at once. Labels are schema-checked; this is not official hidden-score validation.
payload = json.loads((ROOT / "tests/q4_all_96_cases.json").read_text(encoding="utf-8"))
cases = payload["cases"]
batches = [cases[i:i + 24] for i in range(0, len(cases), 24)]

def send_batch(index: int, batch: list[dict]) -> list[dict]:
    batch_id = f"remote-smoke-{index}"
    response, _ = post_json(
        BASE + "/classify",
        {
            "profile": "agent-harness-2026-09",
            "batchId": batch_id,
            "policy": payload["policy"],
            "cases": batch,
        },
    )
    assert response.get("profile") == "agent-harness-2026-09"
    assert response.get("batchId") == batch_id
    results = response.get("results")
    assert isinstance(results, list) and len(results) == len(batch)
    expected_ids = {item["caseId"] for item in batch}
    actual_ids = [item.get("caseId") for item in results]
    assert set(actual_ids) == expected_ids and len(actual_ids) == len(set(actual_ids))
    allowed = {
        "requestDecision": {"allow", "block", "review"},
        "toolDecision": {"allow", "block", "review", "none"},
        "route": {"primary", "restricted", "none"},
        "trajectory": {"normal", "watch", "intervene"},
    }
    for result in results:
        for key, choices in allowed.items():
            assert result.get(key) in choices, (index, result)
    return results

all_results: list[dict] = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(send_batch, i, batch) for i, batch in enumerate(batches)]
    for future in concurrent.futures.as_completed(futures):
        all_results.extend(future.result())
assert len(all_results) == 96
assert len({r["caseId"] for r in all_results}) == 96
print("Q4 PASS: all 96 cases returned once across four 24-case batches (max 2 concurrent)")
