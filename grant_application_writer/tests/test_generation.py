"""Run the complete writer pipeline with scripted Responses API results."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from grant_application_writer.application_writer import generate_application, section_evidence, validate_section
from grant_application_writer.evidence_builder import build_evidence
from grant_application_writer.main import load_application, main
from grant_application_writer.models import Claim, Section
from grant_application_writer.requirement_parser import parse_requirements
from grant_application_writer.review_exporter import export_review

ROOT = Path(__file__).resolve().parents[2]


def test_tp_g03_evaluation_retry_moves_unsupported_commitments_to_missing_information():
    folder = ROOT / "grant-03-school-workshops"
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    name = "Outcomes and Evaluation"
    spec = replace(spec, fields=tuple(field for field in spec.fields if field.name == name))
    item = pack.entries["TF-001"]
    claims = [{"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id}]
    commitment = "If awarded funds, Tidepath will prepare an evaluation protocol before collecting data."
    bad = section(name, f"{item.text} {commitment}", claims)
    corrected = section(name, item.text, claims)
    corrected["missing_information"] = ["Confirm the evaluation protocol and when it would be prepared."]
    finding = {"claim_id": "", "status": "insufficient_evidence", "quote": commitment,
               "detail": "No source supports this commitment."}
    client = client_with(bad, lambda context: reviewed(context, [finding]), corrected, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack)
    calls = client.responses.create.call_args_list
    assert "even conditionally if funded" in calls[0].kwargs["instructions"]
    assert json.loads(calls[2].kwargs["input"])["retry_issue_codes"] == ["insufficient_evidence"]
    candidate = result.application.sections[0]
    assert candidate.body == item.text
    assert candidate.missing_information == tuple(corrected["missing_information"])
    assert result.fields[0].semantic_checked and not result.fields[0].semantic


@pytest.mark.parametrize("unsupported", [False, True])
def test_tp_g02_equity_moves_review_request_and_keeps_fact_verification(unsupported):
    folder = ROOT / "grant-02-family-counseling"
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    name = "Equity and Access"
    spec = replace(spec, fields=tuple(field for field in spec.fields if field.name == name))
    evidence = pack.entries["TF-001"]
    assertion = "The project will offer weekend sessions."
    request = "To assess equity and access for this proposal, please confirm the service population."
    body = evidence.text + (" " + assertion if unsupported else "")
    output = section(name, body + "\n\n" + request, [
        {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id},
    ])
    output["required_information_gaps"] = ["service_population"]

    def verify(context):
        extra = ([{"claim_id": "", "status": "insufficient_evidence", "quote": assertion,
                   "detail": "No evidence for weekend sessions."}] if unsupported else [])
        result = reviewed(context, extra)
        result["coverage"] = [{"topic_id": "invented", "status": "missing", "quote": "", "detail": "Unexpected."}]
        return result

    client = client_with(*([output, verify] * (3 if unsupported else 1)))
    result = generate_application(client, "writer", "verifier", spec, pack)
    candidate = result.application.sections[0]
    review = result.fields[0]
    assert candidate.body == body
    assert candidate.recommendations_for_review == (request,)
    assert candidate.required_information_gaps == ("service_population",)
    assert review.semantic_checked and review.claim_assessments[0].status == "supported"
    assert review.coverage[0].origin == "unconfigured"
    assert [issue.code for issue in review.semantic] == (["insufficient_evidence"] if unsupported else [])
    assert 'Return exactly "coverage": []' in client.responses.create.call_args_list[1].kwargs["instructions"]


@pytest.mark.parametrize(("name", "failure"), [
    ("Program Summary", "claim_not_in_body"),
    ("Equity and Access", "funder_rule_in_body"),
])
def test_tp_g02_targeted_retry_keeps_claims_and_funder_rules_separate(name, failure):
    folder = ROOT / "grant-02-family-counseling"
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    spec = replace(spec, fields=tuple(field for field in spec.fields if field.name == name))
    item = pack.entries["TF-001"]
    claim = {"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id}
    body = ("Tidepath provides mentoring, family counseling, and workshops."
            if name == "Program Summary" else
            f"The proposed work must serve Miami-Dade County children and caregivers. {item.text}")
    corrected = section(name, item.text, [claim])
    if name == "Equity and Access":
        corrected["required_information_gaps"] = ["service_population"]
    client = client_with(section(name, body, [claim]), corrected, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack)
    calls = client.responses.create.call_args_list
    assert [call.kwargs["model"] for call in calls] == ["writer", "writer", "verifier"]
    assert failure in json.loads(calls[1].kwargs["input"])["retry_issue_codes"]
    assert result.fields[0].semantic_checked
    assert not any(issue.status == "fail" for issue in result.fields[0].deterministic)
    assert result.application.sections[0].claims[0].text in result.application.sections[0].body
    if name == "Equity and Access":
        assert result.application.sections[0].required_information_gaps == ("service_population",)
        assert "only as a requirement" in calls[0].kwargs["instructions"]
    else:
        assert "verbatim in both the body and claims.text" in calls[0].kwargs["instructions"]


@pytest.mark.parametrize(("folder_name", "field_name", "total"), [
    ("grant-01-youth-mentoring", "Financial Narrative", "$75,000.00"),
    ("grant-02-family-counseling", "Budget Narrative", "$90,000.00"),
    ("grant-03-school-workshops", "Use of Funds", "$65,000.00"),
])
def test_budget_narrative_scope_and_every_amount_are_enforced(folder_name, field_name, total):
    folder = ROOT / folder_name
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    scoped = section_evidence(spec.grant_id, field_name, pack)
    budget_items = [item for key, item in scoped.entries.items() if "-BUDGET-" in key]
    assert len(budget_items) == 7
    assert total in budget_items[0].text
    assert not any(key in section_evidence(spec.grant_id, spec.fields[0].name, pack).entries
                   for key in (item.evidence_id for item in budget_items))
    claims = tuple(Claim(item.text, item.kind, item.evidence_id) for item in budget_items)
    for omitted in claims:
        retained = tuple(claim for claim in claims if claim != omitted)
        draft = Section(field_name, " ".join(claim.text for claim in retained), retained)
        failures = [issue for issue in validate_section(draft, spec, scoped) if issue.status == "fail"]
        assert [issue.code for issue in failures] == ["missing_budget_amount"]
        assert omitted.evidence_id in failures[0].detail
    changed = replace(claims[1], text=claims[1].text.rsplit("$", 1)[0] + "$1.00.")
    wrong_claims = (claims[0], changed, *claims[2:])
    draft = Section(field_name, " ".join(claim.text for claim in wrong_claims), wrong_claims)
    assert "numeric_mismatch" in {issue.code for issue in validate_section(draft, spec, scoped)}

    body = " ".join(claim.text for claim in claims)
    if spec.grant_id == "TP-G02":
        assert claims[1].text == "Family services coordinator (part-time incl. benefits) — $30,000.00"
        body = f"{claims[0].text} Proposed allocations are: " + "; ".join(
            claim.text for claim in claims[1:]
        ) + "."
        legacy = replace(claims[1], text=(
            "The proposed allocation for Family services coordinator (part-time incl. benefits) is $30,000.00."
        ))
        bad_draft = Section(field_name, body, (claims[0], legacy, *claims[2:]))
        assert {issue.code for issue in validate_section(bad_draft, spec, scoped) if issue.status == "fail"} == {
            "claim_not_in_body", "uncited_numeric",
        }
    else:
        assert claims[1].text.startswith("The proposed allocation for ")
    if spec.grant_id == "TP-G03":
        wrong_span = replace(claims[1], text=claims[1].text.replace("The proposed allocation", "The allocation"))
        bad_draft = Section(field_name, body, (claims[0], wrong_span, *claims[2:]))
        assert {issue.code for issue in validate_section(bad_draft, spec, scoped) if issue.status == "fail"} == {
            "claim_not_in_body", "uncited_numeric",
        }
    output = section(field_name, body, [
        {"text": claim.text, "kind": claim.kind, "evidence_id": claim.evidence_id} for claim in claims
    ])
    client = client_with(output, reviewed)
    selected = replace(spec, fields=tuple(field for field in spec.fields if field.name == field_name))
    result = generate_application(client, "writer", "verifier", selected, pack)
    assert result.fields[0].semantic_checked
    assert not any(issue.status == "fail" for issue in result.fields[0].deterministic)
    context = json.loads(client.responses.create.call_args_list[0].kwargs["input"])
    assert context["required_budget_amount_evidence_ids"] == [claim.evidence_id for claim in claims]
    assert context["eligible_use"]


@pytest.mark.parametrize("wrong_amount", [False, True])
def test_tp_g02_recovers_corrupted_budget_claim_spans(wrong_amount):
    folder = ROOT / "grant-02-family-counseling"
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    field = next(field for field in spec.fields if field.name == "Budget Narrative")
    spec = replace(spec, fields=(field,))
    items = [item for key, item in pack.entries.items() if "-BUDGET-" in key]
    body = items[0].text + " Proposed allocations are: " + "; ".join(item.text for item in items[1:]) + "."
    if wrong_amount:
        body = body.replace("$30,000.00", "$30,001.00")
    output = section(field.name, body, [
        {"text": item.text if index == 0 else item.source.record + " " + "\0" * (410 if index == 1 else index),
         "kind": item.kind, "evidence_id": item.evidence_id}
        for index, item in enumerate(items)
    ])
    responses = [output] * 3 if wrong_amount else [output, reviewed]
    client = client_with(*responses)
    result = generate_application(client, "writer", "verifier", spec, pack)
    candidate = result.application.sections[0]
    assert candidate.body == body
    assert all(claim.text in body and "\0" not in claim.text for claim in candidate.claims)
    failures = {issue.code for issue in result.fields[0].deterministic if issue.status == "fail"}
    assert failures == ({"numeric_mismatch", "uncited_numeric"} if wrong_amount else set())
    assert result.fields[0].semantic_checked is not wrong_amount


@pytest.fixture
def fixture():
    folder = ROOT / "grant-01-youth-mentoring"
    spec = parse_requirements(folder)
    return replace(spec, fields=spec.fields[:2]), build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)


def section(name, body, claims=()):
    return {"section_name": name, "body": body, "claims": list(claims),
            "missing_information": [], "required_information_gaps": [], "generation_notes": [],
            "recommendations_for_review": []}


def budget_section(pack):
    entries = [item for key, item in pack.entries.items() if key.startswith(f"{pack.grant_id}-BUDGET-")]
    return section("Financial Narrative", " ".join(item.text for item in entries), [
        {"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id} for item in entries
    ])


def client_with(*results):
    client = Mock()
    scripted = iter(results)

    def respond(**kwargs):
        result = next(scripted)
        if callable(result):
            result = result(json.loads(kwargs["input"]))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            return SimpleNamespace(status="completed", output_text=json.dumps(result))
        return result

    client.responses.create.side_effect = respond
    return client


def reviewed(context, extra=()):
    return {
        "assessments": [
            {"claim_id": claim["claim_id"], "status": "supported", "quote": claim["text"], "detail": "Grounded."}
            for claim in context["claims"]
        ] + list(extra),
        "coverage": [
            {"topic_id": key, "status": "missing", "quote": "", "detail": "Provide the missing topic details."}
            for key in context["coverage_questions"]
        ],
    }


def test_field_retry_context_and_export(fixture, tmp_path):
    spec, pack = fixture
    first, second = (field.name for field in spec.fields)
    evidence = pack.entries["TP-G01-PLAN-REACH"]
    claim = {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    client = client_with(
        section(first, "word " * 76), section(first, evidence.text, [claim]), reviewed,
        section(second, "Program details are pending."), reviewed,
    )
    result = generate_application(client, "writer-model", "verifier-model", spec, pack)
    assert [field.attempts for field in result.fields] == [2, 1]
    assert all(field.semantic_checked for field in result.fields)
    assert "proposed_evidence" in {issue.code for issue in result.fields[0].deterministic}
    calls = [call.kwargs for call in client.responses.create.call_args_list]
    assert [call["model"] for call in calls] == [
        "writer-model", "writer-model", "verifier-model", "writer-model", "verifier-model",
    ]
    assert all(call["text"]["format"]["strict"] and not call["store"] for call in calls)
    first_context = json.loads(calls[0]["input"])
    ids = {item["evidence_id"] for item in first_context["evidence"]}
    assert [item["evidence_id"] for item in first_context["evidence"]] == [
        "TP-G01-PLAN-GOAL", "TP-G01-PLAN-REACH", "TP-G01-PLAN-PARTICIPANTS",
    ]
    assert "TP-G01-PLAN-REACH" in ids
    assert not ids.intersection({"TP-G01-ACTUAL-1", "TP-G01-BUDGET-TOTAL", "TP-G01-TARGET-1", "TF-005"})
    assert "word_limit" in json.loads(calls[1]["input"])["retry_issue_codes"]
    retry = json.loads(calls[1]["input"])
    assert retry["previous_body"] == "word " * 76
    assert retry["retry_failure_details"] == [
        {"check": "deterministic", "code": "word_limit", "detail": "76 words; limit is 75."},
    ]
    export_review(tmp_path, result, spec, pack)
    assert evidence.text in (tmp_path / "application_draft.md").read_text(encoding="utf-8")
    assert "proposed_evidence" in (tmp_path / "review_report.md").read_text(encoding="utf-8")
    assert load_application(tmp_path / "application_structured.json") == result.application


def test_semantic_finding_retries_only_current_field(fixture):
    spec, pack = fixture
    first, second = (field.name for field in spec.fields)
    text = "The project has already served families."
    finding = {"claim_id": "", "status": "contradicted", "quote": text, "detail": "No historical result is supplied."}
    client = client_with(
        section(first, text), lambda context: reviewed(context, [finding]),
        section(first, "Project details are pending."), reviewed,
        section(second, "Implementation details are pending."), reviewed,
    )
    result = generate_application(client, "writer", "verifier", spec, pack)
    assert [field.attempts for field in result.fields] == [2, 1]
    retry = json.loads(client.responses.create.call_args_list[2].kwargs["input"])
    assert retry["previous_body"] == text
    assert retry["retry_failure_details"] == [
        {"check": "semantic", "code": "contradicted", "detail": f"{text} | No historical result is supplied."},
    ]


def test_semantic_retry_preserves_grounded_non_numeric_claim(fixture):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[1:2])
    name = spec.fields[0].name
    evidence = pack.entries["TP-G01-PLAN-MENTORING"]
    claim = {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    unsupported = "The mentoring program already operates in every local school."
    finding = {"claim_id": "", "status": "insufficient_evidence", "quote": unsupported,
               "detail": "No school coverage evidence is supplied."}
    client = client_with(
        section(name, evidence.text + "\n\n" + unsupported, [claim]),
        lambda context: reviewed(context, [finding]),
        section(name, "Plans are under review."),
        section(name, evidence.text, [claim]),
        reviewed,
    )
    result = generate_application(client, "writer", "verifier", spec, pack, max_fields=1)
    assert result.fields[0].attempts == 3
    assert result.application.sections[0].body == evidence.text
    retry = json.loads(client.responses.create.call_args_list[3].kwargs["input"])
    assert retry["preserve_claims"] == [claim]
    assert retry["retry_issue_codes"] == ["retry_preserve_claim"]


def test_semantic_rejection_releases_previously_locked_claim(fixture):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[1:2])
    name = spec.fields[0].name
    evidence = pack.entries["TP-G01-PLAN-MENTORING"]
    claim = {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    unsupported = "Counseling and school workshops will be delivered as part of the mentoring project."
    first = section(name, f"{evidence.text} {unsupported}", [claim])
    first_finding = {"claim_id": "", "status": "insufficient_evidence", "quote": unsupported,
                     "detail": "The existing organizational services do not establish project delivery."}
    second = section(name, evidence.text, [claim])

    def dispute_locked(context):
        result = reviewed(context)
        result["assessments"][0].update(status="insufficient_evidence", detail="Recheck this claim.")
        return result

    reach = pack.entries["TP-G01-PLAN-REACH"]
    final = section(name, reach.text, [{"text": reach.text, "kind": reach.kind, "evidence_id": reach.evidence_id}])
    client = client_with(first, lambda context: reviewed(context, [first_finding]),
                         second, dispute_locked, final, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack)
    calls = client.responses.create.call_args_list
    assert json.loads(calls[2].kwargs["input"])["preserve_claims"] == [claim]
    assert json.loads(calls[4].kwargs["input"])["preserve_claims"] == []
    assert "Existing organizational services are background only" in calls[0].kwargs["instructions"]
    assert result.application.sections[0].body == reach.text
    assert not result.fields[0].semantic


def test_qualifications_keeps_sustainability_gap_out_of_body(fixture, tmp_path):
    _, pack = fixture
    full_spec = parse_requirements(ROOT / "grant-01-youth-mentoring")
    name = "Qualifications & Sustainability"
    spec = replace(full_spec, fields=tuple(field for field in full_spec.fields if field.name == name))
    entries = [pack.entries[key] for key in ("TF-001", "TF-002", "TF-003")]
    claims = [{"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id} for item in entries]
    body = " ".join(item.text for item in entries)
    inference = "These verified facts document direct-service programming and a small leadership and financial support structure."
    review_text = "The evidence does not document how the proposed work would be sustained after this grant."
    request = "The applicant should submit a concise sustainability plan."
    first = section(name, f"{body} {inference}", claims)
    second = section(name, f"{body} {review_text} {request}", claims)
    final = section(name, body, claims)
    final["missing_information"] = ["A documented post-grant sustainability plan."]
    final["recommendations_for_review"] = ["Confirm which funding or operating commitments exist."]
    finding = {"claim_id": "", "status": "insufficient_evidence", "quote": inference,
               "detail": "Service descriptions and staff roles do not establish delivery capacity."}
    client = client_with(first, lambda context: reviewed(context, [finding]), second, final, reviewed)

    result = generate_application(client, "writer", "verifier", spec, pack)
    review = result.fields[0]
    calls = client.responses.create.call_args_list
    assert [call.kwargs["model"] for call in calls] == ["writer", "verifier", "writer", "writer", "verifier"]
    assert "Do not infer management capacity" in calls[0].kwargs["instructions"]
    assert json.loads(calls[2].kwargs["input"])["retry_issue_codes"] == ["insufficient_evidence"]
    assert set(json.loads(calls[3].kwargs["input"])["retry_issue_codes"]) == {"body_review_metadata"}
    assert result.application.sections[0].body == body
    assert not review.deterministic and not review.semantic
    assert review.semantic_checked
    assert next(item for item in review.coverage if "continue" in item.question).status == "missing"
    export_review(tmp_path, result, spec, pack)
    draft = (tmp_path / "application_draft.md").read_text(encoding="utf-8")
    report = (tmp_path / "review_report.md").read_text(encoding="utf-8")
    for text in (review_text, request, inference, *final["missing_information"], *final["recommendations_for_review"]):
        assert text not in draft
    assert final["missing_information"][0] in report
    assert final["recommendations_for_review"][0] in report


def test_financial_summary_reaches_semantic_review_but_amounts_are_required(fixture):
    spec, pack = fixture
    full_spec = parse_requirements(ROOT / "grant-01-youth-mentoring")
    spec = replace(spec, fields=(full_spec.fields[-1],))
    complete = budget_section(pack)
    descriptions = [("mentor training", 2), ("direct youth activities", 3),
                    ("evaluation", 5), ("proportionate administration", 6)]
    complete["body"] += " These line items support " + ", ".join(text for text, _ in descriptions) + "."
    complete["claims"].extend(
        {"text": text, "kind": "proposed_project_plan", "evidence_id": f"TP-G01-BUDGET-CATEGORY-{number}"}
        for text, number in descriptions
    )
    amount = pack.entries["TP-G01-BUDGET-CATEGORY-2"].text
    missing_amount = {**complete, "body": complete["body"].replace(amount, ""),
                      "claims": [claim for claim in complete["claims"] if claim["text"] != amount]}
    client = client_with(missing_amount, complete, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack)
    review = result.fields[0]
    assert review.attempts == 2
    assert review.semantic_checked
    retry = json.loads(client.responses.create.call_args_list[1].kwargs["input"])
    assert retry["retry_issue_codes"] == ["missing_budget_amount"]
    assert len(retry["required_budget_amount_evidence_ids"]) == 7
    assert not any(issue.status == "fail" for issue in review.deterministic)
    assert sum(item.status == "supported" for item in review.claim_assessments) == 11


def test_max_fields_cli_marks_partial_and_exports_separate_files(monkeypatch, tmp_path, capsys):
    name = "Statement of Goals"
    client = client_with(section(name, "Caregiver participation needs confirmation."), reviewed)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: client)
    monkeypatch.setattr("sys.argv", [
        "main", "--generate", "--max-fields", "1", "--output-dir", str(tmp_path),
        "--writer-model", "mock-writer", "--verifier-model", "mock-verifier",
    ])
    assert main() == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "partial_test"
    assert summary["status"] == "review_required"
    assert client.responses.create.call_count == 2
    assert {path.name for path in tmp_path.iterdir()} == {
        "partial_test_draft.md", "partial_test_review.md", "partial_test_structured.json",
    }
    payload = json.loads((tmp_path / "partial_test_structured.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "partial_test"
    assert payload["requirements"] == []
    assert [item["section_name"] for item in payload["sections"]] == [name]
    assert "1 of 9" in (tmp_path / "partial_test_review.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["0", "-1"])
def test_max_fields_rejects_non_positive_values(monkeypatch, value):
    monkeypatch.setattr("sys.argv", ["main", "--generate", "--max-fields", value])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize("bad_case", ["new_id", "wrong_kind", "numeric_change", "uncited_numeric", "incomplete"])
def test_deterministic_failures_cannot_be_overridden(fixture, tmp_path, bad_case):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[:1])
    name = spec.fields[0].name
    evidence = pack.entries["TP-G01-PLAN-REACH"]
    body = evidence.text
    claim = {"text": body, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    if bad_case == "new_id":
        claim["evidence_id"] = "TP-G01-FAKE"
    elif bad_case == "wrong_kind":
        claim["kind"] = "verified_organizational_fact"
    elif bad_case == "numeric_change":
        body = body.replace("60", "61")
        claim["text"] = body
    elif bad_case == "uncited_numeric":
        body += " The budget is $900."
    response = section(name, body, [claim])
    if bad_case == "incomplete":
        response = SimpleNamespace(status="incomplete", output_text="")
    client = client_with(response, response, response)
    result = generate_application(client, "writer", "verifier", spec, pack)
    assert result.fields[0].attempts == 3
    assert not result.fields[0].semantic_checked
    assert any(issue.status == "fail" for issue in result.fields[0].deterministic)
    assert client.responses.create.call_count == 3
    export_review(tmp_path, result, spec, pack)
    assert "Section withheld" in (tmp_path / "application_draft.md").read_text(encoding="utf-8")


def test_semantic_api_failure_is_not_a_pass(fixture):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[:1])
    output = section(spec.fields[0].name, "Details are pending.")
    client = client_with(*([output, RuntimeError("Sensitive API details")] * 3))
    result = generate_application(client, "writer", "verifier", spec, pack)
    review = result.fields[0]
    assert review.attempts == 3
    assert not review.semantic_checked
    assert review.semantic[0].code == "semantic_api_error"
    assert "Sensitive" not in review.semantic[0].detail


def test_metadata_is_rejected_before_semantic_and_recommendations_stay_out_of_body(fixture, tmp_path):
    spec, pack = fixture
    name = spec.fields[0].name
    item = pack.entries["TP-G01-PLAN-GOAL"]
    claim = {"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id}
    invalid = section(name, f"{item.text} ({item.evidence_id}) Coverage question 1.", [claim])
    fixed = section(name, item.text, [claim])
    suggestion = "Confirm feasibility of bilingual outreach and weekend sessions."
    fixed["recommendations_for_review"] = [suggestion]
    client = client_with(invalid, fixed, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack, max_fields=1)
    calls = client.responses.create.call_args_list
    assert [call.kwargs["model"] for call in calls] == ["writer", "writer", "verifier"]
    retry = json.loads(calls[1].kwargs["input"])
    assert set(retry["retry_issue_codes"]) == {"body_review_metadata"}
    assert result.fields[0].claim_assessments[0].statement_type == "proposed_plan"
    export_review(tmp_path, result, spec, pack)
    assert suggestion in (tmp_path / "partial_test_review.md").read_text(encoding="utf-8")
    assert suggestion not in (tmp_path / "partial_test_draft.md").read_text(encoding="utf-8")


def test_tentative_unsupported_commitment_fails_but_non_factual_transition_does_not(fixture):
    spec, pack = fixture
    equity = next(field for field in parse_requirements(ROOT / "grant-01-youth-mentoring").fields
                  if field.name == "Advancing Equity")
    spec = replace(spec, fields=(equity,))
    unsupported = "We would tentatively offer childcare, bilingual outreach, and weekend sessions."
    transition = "With that in mind,"
    invalid = section(equity.name, f"{transition} {unsupported}")

    def assess(context):
        return reviewed(context, [
            {"claim_id": "", "status": "non_factual", "quote": transition, "detail": "A transition."},
            {"claim_id": "", "status": "insufficient_evidence", "quote": unsupported,
             "detail": "These project activities have no source."},
        ])

    result = generate_application(client_with(*([invalid, assess] * 3)), "writer", "verifier", spec, pack)
    review = result.fields[0]
    assert review.attempts == 3
    assert [issue.code for issue in review.semantic] == ["insufficient_evidence"]
    assert [item.statement_type for item in review.claim_assessments] == ["non_factual", "uncited_assertion"]


def test_word_limit_retry_cannot_replace_grounded_quantity(fixture):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[:1])
    name = spec.fields[0].name
    evidence = pack.entries["TP-G01-PLAN-REACH"]
    claim = {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    long_body = evidence.text + "\n\n" + "word " * 76
    client = client_with(
        section(name, long_body, [claim]),
        section(name, "Details are pending."),
        section(name, evidence.text, [claim]),
        reviewed,
    )
    result = generate_application(client, "writer", "verifier", spec, pack)
    assert result.fields[0].attempts == 3
    assert result.application.sections[0].body == evidence.text
    third_context = json.loads(client.responses.create.call_args_list[2].kwargs["input"])
    assert third_context["retry_issue_codes"] == ["retry_numeric_evidence"]
    assert third_context["preserve_numeric_evidence_ids"] == [evidence.evidence_id]


def test_realistic_tp_g01_mock_generation(fixture, tmp_path):
    _, pack = fixture
    spec = parse_requirements(ROOT / "grant-01-youth-mentoring")
    section_content = {
        "Statement of Goals": (["TP-G01-PLAN-GOAL", "TP-G01-PLAN-REACH"], "Confirm caregiver participation."),
        "Implementation": (["TF-001", "TP-G01-PLAN-MENTORING", "TP-G01-PLAN-PERIOD"],
                           "Confirm site readiness and the training sequence."),
        "Activities Measures": (["TP-G01-PLAN-MENTORING"], "Confirm activity logs and attendance measures."),
        "Outreach & Engagement": (["TP-G01-PLAN-REACH"], "Confirm referral routes and caregiver roles."),
        "Assessment": (["TP-G01-TARGET-3"], "Confirm the baseline instrument and timing."),
        "Outcomes Measures": (["TP-G01-TARGET-1", "TP-G01-TARGET-3"], "Confirm data sources for both measures."),
        "Qualifications & Sustainability": (["TF-001", "TF-002"], "Confirm staff credentials and a continuation plan."),
        "Advancing Equity": ([], "Confirm access barriers and mitigation strategies with families."),
        "Financial Narrative": ([key for key in pack.entries if key.startswith("TP-G01-BUDGET-")],
                                "Confirm the cost rationale for each allocation."),
    }

    def review_realistic(context):
        result = reviewed(context)
        if context["section_name"] == "Statement of Goals":
            result["coverage"][0].update(status="covered", quote=pack.entries["TP-G01-PLAN-GOAL"].text,
                                         detail="The intended change is stated.")
        if context["section_name"] == "Financial Narrative":
            result["coverage"][0].update(status="partial", quote=pack.entries["TP-G01-BUDGET-TOTAL"].text,
                                         detail="Explain the remaining budget allocations.")
        return result

    responses = []
    for field in spec.fields:
        ids, missing = section_content[field.name]
        entries = [pack.entries[key] for key in ids]
        claims = [{"text": entry.text, "kind": entry.kind, "evidence_id": entry.evidence_id} for entry in entries]
        body = "\n\n".join(entry.text for entry in entries)
        output = section(field.name, body or "Which participation barriers should the proposed project address?")
        output.update(claims=claims, missing_information=[missing], generation_notes=["Draft for review."])
        responses.extend([output, review_realistic])
    client = client_with(*responses)
    result = generate_application(client, "writer", "verifier", spec, pack)
    assert not result.requirements
    assert result.mode == "full_application"
    assert len(result.fields) == 9
    assert all(field.semantic_checked and field.attempts == 1 for field in result.fields)
    assert client.responses.create.call_count == 18
    assert [item.status for item in result.fields[0].coverage] == ["covered", "missing"]
    implementation = result.fields[1]
    assert len(implementation.claim_assessments) == 3
    assert all(item.status == "supported" for item in implementation.claim_assessments)
    assert "proposed_evidence" in {issue.code for issue in implementation.deterministic}
    assert pack.entries["TP-G01-PLAN-MENTORING"].approval_status == "proposed"
    for call in client.responses.create.call_args_list:
        context = json.loads(call.kwargs["input"])
        for item in context["evidence"]:
            entry = pack.entries[item["evidence_id"]]
            assert not entry.allowed_sections or context["section_name"] in entry.allowed_sections
            assert entry.approval_status in {"approved", "proposed"}
    export_review(tmp_path, result, spec, pack)
    assert load_application(tmp_path / "application_structured.json") == result.application
    report = (tmp_path / "review_report.md").read_text(encoding="utf-8")
    for heading in ("Deterministic validation", "Semantic fact verification", "Requirement coverage",
                    "Human review required"):
        assert f"### {heading}" in report
    assert "Explain the remaining budget allocations." in report
    draft = (tmp_path / "application_draft.md").read_text(encoding="utf-8")
    assert "$75,000.00" in draft
    assert pack.entries["TF-001"].text in draft


def test_synthesized_goals_cover_claims_and_separate_information_gaps(fixture, tmp_path):
    spec, pack = fixture
    name = spec.fields[0].name
    goal = "The proposed mentoring project would help children build social-emotional skills, strengthen their school connection, and improve their well-being"
    reach = "it aims to reach 60 children in Miami-Dade County"
    body = f"{goal}, and {reach}."
    output = section(name, body, [
        {"text": goal, "kind": "proposed_project_plan", "evidence_id": "TP-G01-PLAN-GOAL"},
        {"text": reach, "kind": "proposed_project_plan", "evidence_id": "TP-G01-PLAN-REACH"},
    ])
    output["required_information_gaps"] = ["service_population"]
    output["missing_information"] = ["Describe recruitment channels if confirmed."]
    client = client_with(output, reviewed)
    result = generate_application(client, "writer", "verifier", spec, pack, max_fields=1)
    review = result.fields[0]
    assert review.attempts == 1
    assert {item.status for item in review.claim_assessments} == {"supported"}
    assert {issue.code for issue in review.deterministic} == {"proposed_evidence", "unsupported_wording"}
    assert {item.origin for item in review.coverage} == {"inferred"}
    assert all(item.approval_status == "proposed" for item in
               (pack.entries["TP-G01-PLAN-GOAL"], pack.entries["TP-G01-PLAN-REACH"]))
    export_review(tmp_path, result, spec, pack)
    report = (tmp_path / "partial_test_review.md").read_text(encoding="utf-8")
    assert "Missing explicit funder requirement: Proposed work must serve Miami-Dade County children and caregivers." in report
    assert "Optional improvement: Describe recruitment channels if confirmed." in report
    assert "[inferred] missing:" in report
    assert body in (tmp_path / "partial_test_draft.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("status", ["insufficient_evidence", "review_required", "omitted"])
def test_declared_claim_must_receive_independent_assessment(fixture, status):
    spec, pack = fixture
    spec = replace(spec, fields=spec.fields[1:2])
    evidence = pack.entries["TF-001"]
    claim = {"text": evidence.text, "kind": evidence.kind, "evidence_id": evidence.evidence_id}
    output = section(spec.fields[0].name, evidence.text, [claim])

    def assess(context):
        response = reviewed(context)
        if status == "omitted":
            response["assessments"].clear()
        else:
            response["assessments"][0]["status"] = status
        return response

    client = client_with(*([output, assess] * 3))
    review = generate_application(client, "writer", "verifier", spec, pack).fields[0]
    if status == "omitted":
        assert not review.semantic_checked
        assert review.semantic[0].code == "semantic_invalid_response"
    else:
        assert review.claim_assessments[0].status == status
        assert review.semantic[0].status == ("fail" if status == "insufficient_evidence" else "review_required")
    assert pack.entries["TF-001"].approval_status == "approved"

