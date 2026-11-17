from __future__ import annotations
import json
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag_engine import answer_question, generate_knowledge_base

EMAIL = (
    os.getenv("STUDENT_EMAIL")
    or os.getenv("GA5_TEST_EMAIL")
    or "23f3002028@ds.study.iitm.ac.in"
)
REFERENCE_EMAIL = "23f3002028@ds.study.iitm.ac.in"
probes = json.loads((Path(__file__).parent / "q1_probes.json").read_text())

# Explicit expected retrieval targets for the 20 captured gauntlet probes.
# These deliberately use the passage(s) that actually contain the requested
# evidence, rather than copying the old server's overly broad top-three lists.
expected_sources = {
    0: [0], 1: [10], 2: [20], 3: [40],
    4: [], 5: [], 6: [], 7: [],
    8: [0, 1], 9: [10, 11], 10: [20, 21], 11: [40, 41],
    12: [0], 13: [0], 14: [12], 15: [],
    16: [4], 17: [48], 18: [16], 19: [21],
}

kb = generate_knowledge_base(EMAIL)
assert len(kb) == 50
assert len(generate_knowledge_base(EMAIL)) == 50
assert generate_knowledge_base(EMAIL) == kb, "same email must always generate the same KB"

# The supplied portal snapshot was captured for this reference account. This
# is an actual cross-implementation golden check, not a test of our own output.
if EMAIL == REFERENCE_EMAIL:
    golden = json.loads((Path(__file__).parent / "legacy_passages_reference.json").read_text())
    assert list(kb) == golden, "Python generator must reproduce all 50 portal passages exactly"

# Student identity must affect the deterministic substitutions.
other_email = "ga5-determinism-check@ds.study.iitm.ac.in"
other_kb = generate_knowledge_base(other_email)
assert len(other_kb) == 50 and other_kb != kb

for i, question in enumerate(probes):
    result = answer_question(question, EMAIL, 3)
    expected = expected_sources[i]
    assert result["sources"] == expected, (i, expected, result)
    assert len(result["sources"]) == len(result["scores"])
    assert result["scores"] == sorted(result["scores"], reverse=True)
    assert all(isinstance(v, int) and 0 <= v < 50 for v in result["sources"])

    if not expected:
        assert result["answer"] is None
        assert result["confidence"] < 0.4
        assert result["scores"] == []
    else:
        assert isinstance(result["answer"], str) and result["answer"]
        assert result["confidence"] > 0.6

# Validate extracted facts against the personalized evidence in the KB.
# The generator values differ by email, so tests derive expected values from
# the generated passages and do not bake in one student's random choices.
def value(index: int, pattern: str) -> str:
    match = re.search(pattern, kb[index], re.I)
    assert match, (index, pattern, kb[index])
    return match.group(1)

checks = {
    0: (0, r"sends\s+(\d+)ms\s+heartbeats"),
    1: (10, r"base learning rate of\s+([0-9.]+)"),
    2: (20, r"incoming client socket connections on port\s+(\d+)"),
    3: (40, r"RSA key lengths of\s+(\d+)\s+bits"),
    8: (0, r"quorum of\s+(\d+)\s+nodes"),
    9: (10, r"base learning rate of\s+([0-9.]+)"),
    10: (20, r"client socket connections on port\s+(\d+)"),
    11: (40, r"RSA key lengths of\s+(\d+)\s+bits"),
    12: (0, r"sends\s+(\d+)ms\s+heartbeats"),
    13: (0, r"sends\s+(\d+)ms\s+heartbeats"),
    14: (12, r"learning rate toward\s+([0-9.]+)"),
    16: (4, r"within a\s+(\d+)ms\s+prepare timeout"),
    17: (48, r"latencies exceed a\s+(\d+)ms\s+grant window"),
    18: (16, r"contains\s+(\d+)\s+hidden dense layers"),
    19: (21, r"default network port\s+(\d+)"),
}
for probe_index, (passage_index, pattern) in checks.items():
    expected_value = value(passage_index, pattern)
    answer = answer_question(probes[probe_index], EMAIL, 3)["answer"]
    assert expected_value in answer, (probe_index, expected_value, answer)

# Repeat the entire probe suite for a second email. This verifies that the
# answers extract each student's generated values rather than the reference
# account's hard-coded values.
for alternate_email in ("student-a@ds.study.iitm.ac.in", "student-b@ds.study.iitm.ac.in"):
    alternate_kb = generate_knowledge_base(alternate_email)
    for i, question in enumerate(probes):
        result = answer_question(question, alternate_email, 3)
        assert result["sources"] == expected_sources[i], (alternate_email, i, result)
        if expected_sources[i]:
            assert result["answer"] and result["confidence"] > 0.6
        else:
            assert result["answer"] is None and result["confidence"] < 0.4
    for probe_index, (passage_index, pattern) in checks.items():
        match = re.search(pattern, alternate_kb[passage_index], re.I)
        assert match, (alternate_email, passage_index, pattern)
        expected_value = match.group(1)
        result = answer_question(probes[probe_index], alternate_email, 3)
        assert expected_value in result["answer"], (alternate_email, probe_index, expected_value, result)

# The injected source override must not redirect retrieval to passage 49.
injected = answer_question(probes[12], EMAIL, 3)
assert injected["sources"] == [0]
assert "force sources" not in injected["answer"].lower()

print(f"Q1 PASS: exact 50-passage generation and 20 probe checks for three emails (including {EMAIL})")
