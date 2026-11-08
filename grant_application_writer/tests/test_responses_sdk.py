"""Check SDK serialization and parsing using an in-process HTTP transport."""

import json
from dataclasses import replace
from pathlib import Path

import httpx2
import pytest
from openai import OpenAI

from grant_application_writer.application_writer import generate_application
from grant_application_writer.evidence_builder import build_evidence
from grant_application_writer.requirement_parser import parse_requirements
from grant_application_writer.responses_client import classify_api_error

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("status", "api_code", "category"), [
    (429, None, "rate_limit"), (429, "insufficient_quota", "quota"),
    (408, None, "timeout"), (401, None, "authentication"), (502, None, "server_error"),
])
def test_api_diagnostics_redact_raw_error(status, api_code, category):
    error = RuntimeError("Sensitive request details")
    error.status_code = status
    error.code = api_code
    error.request_id = "req_safe123"
    result = classify_api_error(error)
    assert result.code == category
    assert str(result) == f"API request failed. (HTTP {status}, request_id=req_safe123)"


@pytest.mark.parametrize("mode", ["success", "refusal", "incomplete", "http_error"])
def test_sdk_responses_transport(mode):
    folder = ROOT / "grant-01-youth-mentoring"
    spec = parse_requirements(folder)
    spec = replace(spec, fields=spec.fields[:1])
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    calls = []

    def send(request):
        assert request.url.host == "mock.invalid"
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["store"] is False
        format_spec = payload["text"]["format"]
        assert format_spec["type"] == "json_schema"
        assert format_spec["strict"] is True
        schema = format_spec["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        context = json.loads(payload["input"])
        if mode == "http_error":
            return httpx2.Response(503, headers={"x-request-id": "req_fixture503"},
                                   json={"error": {"message": "Private fixture error"}})

        if format_spec["name"] == "grant_section":
            result = {
                "section_name": context["section_name"],
                "body": "The intended change needs confirmation.",
                "claims": [], "missing_information": ["Confirm the intended change."], "generation_notes": [],
                "required_information_gaps": [],
                "recommendations_for_review": [],
            }
        else:
            assert format_spec["name"] == "semantic_findings"
            result = {"assessments": [], "coverage": [
                {"topic_id": key, "status": "missing", "quote": "", "detail": "Confirm with the applicant."}
                for key in context["coverage_questions"]
            ]}
        content = {"type": "output_text", "text": json.dumps(result), "annotations": []}
        if mode == "refusal":
            content = {"type": "refusal", "refusal": "Private fixture refusal"}
        return httpx2.Response(200, json={
            "id": "resp_fixture", "object": "response", "created_at": 0,
            "status": "incomplete" if mode == "incomplete" else "completed",
            "output": [{"type": "message", "id": "msg_fixture", "role": "assistant",
                        "status": "completed", "content": [content]}],
        })

    with OpenAI(api_key="fixture-only", base_url="https://mock.invalid/v1",
                max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(send))) as client:
        result = generate_application(client, "mock-writer", "mock-reviewer", spec, pack)
    review = result.fields[0]
    if mode == "success":
        assert len(calls) == 2
        assert review.semantic_checked
        assert all(item.status == "missing" for item in review.coverage)
        assert not any(issue.status == "fail" for issue in review.deterministic + review.semantic)
    else:
        code = "server_error" if mode == "http_error" else mode
        assert len(calls) == 3
        assert not review.semantic_checked
        assert review.deterministic[0].code == f"generation_{code}"
        assert "Private fixture" not in review.deterministic[0].detail
        if mode == "http_error":
            assert "HTTP 503" in review.api_diagnostics[0]
            assert "request_id=req_fixture503" in review.api_diagnostics[0]
        assert not result.application.sections[0].body

