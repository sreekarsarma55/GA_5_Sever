from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag_engine import answer_question, generate_knowledge_base

EMAIL = os.getenv("STUDENT_EMAIL") or os.getenv("GA5_TEST_EMAIL") or "student@example.invalid"
probes = json.loads((Path(__file__).parent / "q1_probes.json").read_text())
expected = {
    0: [0, 1, 3], 1: [10, 11, 19], 2: [20, 21, 25], 3: [40, 41, 37],
    4: None, 5: None, 6: None, 7: None,
    8: [0, 1, 3], 9: [10, 11, 19], 10: [20, 21, 25], 11: [40, 41, 37],
    12: [0, 1, 3], 13: [0, 1, 3], 14: [12, 10, 19], 15: None,
    16: [4, 5, 2], 17: [48, 40, 49], 18: [16, 17, 18], 19: [21, 20, 25],
}

kb = generate_knowledge_base(EMAIL)
assert len(kb) == 50
reference_email = os.getenv("GA5_REFERENCE_EMAIL", "").strip().lower()
if reference_email and EMAIL == reference_email:
    golden = json.loads((Path(__file__).parent / "legacy_passages_reference.json").read_text())
    assert list(kb) == golden, "seedrandom port did not reproduce the provided 50 passages"

for i, question in enumerate(probes):
    result = answer_question(question, EMAIL, 3)
    target = expected[i]
    if target is None:
        assert result["answer"] is None and result["sources"] == [], (i, result)
    else:
        assert result["sources"] == target, (i, target, result["sources"])
        assert all(isinstance(v, int) and 0 <= v < 50 for v in result["sources"])
        assert len(result["scores"]) == len(result["sources"])
        assert result["scores"] == sorted(result["scores"], reverse=True)
        assert 0.6 < result["confidence"] <= 1.0
        assert result["answer"] and all(kb[idx] in result["answer"] for idx in target[:3])

print(f"Q1 PASS: generated 50 personalized passages and verified all {len(probes)} probes")
