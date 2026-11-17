from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Avoid a global fallback masking failures in shared multi-user mode.
os.environ.pop("STUDENT_EMAIL", None)

from fastapi.testclient import TestClient
from main import app
from rag_engine import generate_knowledge_base

client = TestClient(app)


def test_student_link_generator_page():
    response = client.get("/student-link")
    assert response.status_code == 200
    assert "Generate my URLs" in response.text
    assert "encodeURIComponent(email)" in response.text


def test_student_url_path_selects_personalized_kb():
    email = "student-a@ds.study.iitm.ac.in"
    response = client.post(
        "/u/student-a%40ds.study.iitm.ac.in/query",
        json={"question": "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [0]


def test_student_route_alias():
    response = client.post(
        "/student/student-b%40ds.study.iitm.ac.in/query",
        json={"question": "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [0]


def test_header_identity_supported_on_root_query():
    response = client.post(
        "/query",
        headers={"X-Student-Email": "student-c@ds.study.iitm.ac.in"},
        json={"question": "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sources"] == [0]


def test_different_students_get_different_personalized_passages():
    kb_a = generate_knowledge_base("student-a@ds.study.iitm.ac.in")
    kb_b = generate_knowledge_base("student-b@ds.study.iitm.ac.in")
    assert len(kb_a) == len(kb_b) == 50
    assert kb_a != kb_b


def test_missing_identity_does_not_silently_use_wrong_student():
    response = client.post(
        "/query",
        json={"question": "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?", "top_k": 3},
    )
    assert response.status_code == 400
    assert "student's course email" in response.json()["detail"]


def test_path_identity_overrides_conflicting_header():
    response = client.post(
        "/u/path-student%40ds.study.iitm.ac.in/query",
        headers={"X-Student-Email": "header-student@ds.study.iitm.ac.in"},
        json={"question": "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?", "top_k": 3},
    )
    from rag_engine import answer_question
    expected = answer_question(
        "What is the duration in milliseconds between periodic keepalive signals transmitted by the cluster coordinator to prevent election triggers among subordinate replicas?",
        "path-student@ds.study.iitm.ac.in",
        3,
    )
    assert response.status_code == 200, response.text
    assert response.json() == expected


def test_classify_json_batch_contract():
    cases = [{"caseId": f"test-{i}", "messages": [], "proposedTool": None} for i in range(24)]
    response = client.post(
        "/classify",
        json={"profile": "agent-harness-2026-09", "batchId": "batch-test", "cases": cases},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["batchId"] == "batch-test"
    assert [x["caseId"] for x in payload["results"]] == [x["caseId"] for x in cases]


def test_classify_rejects_non_json_media_type():
    response = client.post("/classify", content="{}", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415


def test_classify_rejects_oversized_batches_and_duplicate_ids():
    too_many = [{"caseId": f"case-{i}"} for i in range(25)]
    response = client.post("/classify", json={"cases": too_many})
    assert response.status_code == 413
    duplicate = [{"caseId": "duplicate"}, {"caseId": "duplicate"}]
    response = client.post("/classify", json={"cases": duplicate})
    assert response.status_code == 400


def test_classify_rejects_request_over_2_mib():
    body = b'{"cases":[]}' + (b" " * (2 * 1024 * 1024))
    response = client.post(
        "/classify",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


if __name__ == "__main__":
    for test in (
        test_student_link_generator_page,
        test_student_url_path_selects_personalized_kb,
        test_student_route_alias,
        test_header_identity_supported_on_root_query,
        test_different_students_get_different_personalized_passages,
        test_missing_identity_does_not_silently_use_wrong_student,
        test_path_identity_overrides_conflicting_header,
        test_classify_json_batch_contract,
        test_classify_rejects_non_json_media_type,
        test_classify_rejects_oversized_batches_and_duplicate_ids,
        test_classify_rejects_request_over_2_mib,
    ):
        test()
    print("HTTP identity tests PASS: path/header routing and missing-identity failure")
