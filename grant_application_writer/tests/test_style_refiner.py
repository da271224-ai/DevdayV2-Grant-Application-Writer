"""Test conservative A/B acceptance with isolated model responses."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from grant_application_writer.application_writer import FieldReview, evidence_context, section_evidence
from grant_application_writer.evidence_builder import build_evidence
from grant_application_writer.models import Claim, Issue, Section
from grant_application_writer.requirement_coverage import CoverageAssessment, field_questions
from grant_application_writer.requirement_parser import parse_requirements
from grant_application_writer.semantic_fact_verifier import SEMANTIC_VERSION, semantic_fingerprint
from grant_application_writer.style_refiner import issue_changes, main, refine_field

from test_generation import budget_section, client_with, reviewed

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sources():
    folder = ROOT / "grant-01-youth-mentoring"
    spec = parse_requirements(folder)
    return spec, build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)


def from_evidence(pack, evidence_id, name):
    item = pack.entries[evidence_id]
    return Section(name, item.text, (Claim(item.text, item.kind, item.evidence_id),))


def edit(body, claims, cleanup=()):
    return {"edit_status": "edited", "body": body, "claims": list(claims), "rules": ["7"],
            "style_improvements": ["Varied sentence structure."], "content_cleanup": list(cleanup)}


def record(claim, text=None):
    return {"text": claim.text if text is None else text, "kind": claim.kind, "evidence_id": claim.evidence_id}


def preservation(context):
    return {
        "a_claims": [{"claim_id": key, "status": "preserved", "detail": "Equivalent."}
                     for key in context["a_claims"]],
        "substantive_changes": [], "cleanup_findings": [], "verdict": "equivalent",
    }


def run_field(sources, original, candidate, comparison=preservation, review=reviewed):
    spec, pack = sources
    field = next(field for field in spec.fields if field.name == original.name)
    coverage = tuple(CoverageAssessment(question, "missing", "", "Fixture gap.")
                     for question in field_questions(spec, original.name).values())
    baseline = FieldReview(original.name, 1, (), (), True, coverage=coverage)
    client = client_with(candidate, review, comparison)
    result = refine_field(client, "editor", "verifier", original, baseline, field, spec, pack)
    return result, client


@pytest.mark.parametrize("case", ["total_missing", "category_missing", "amounts_swapped"])
def test_financial_amounts_are_locked(sources, case):
    _, pack = sources
    source = budget_section(pack)
    original = Section(source["section_name"], source["body"], tuple(Claim(**item) for item in source["claims"]))
    claims = [record(claim) for claim in original.claims]
    if case == "amounts_swapped":
        first, second = claims[1]["text"], claims[2]["text"]
        claims[1]["text"] = first.replace("$28,000.00", "$12,000.00")
        claims[2]["text"] = second.replace("$12,000.00", "$28,000.00")
    else:
        claims.pop(0 if case == "total_missing" else 1)
    (candidate, _, review, _, _, recommendation), _ = run_field(
        sources, original, edit(" ".join(claim["text"] for claim in claims), claims),
    )
    assert recommendation == "reject_b"
    codes = {issue.code for issue in review.deterministic}
    assert "style_numeric_change" in codes
    assert ("numeric_mismatch" if case == "amounts_swapped" else "missing_budget_amount") in codes


@pytest.mark.parametrize(("evidence_id", "name", "altered"), [
    ("TP-G01-TARGET-3", "Outcomes Measures", "The proposed target is 70 percent of all participants improving."),
    ("TP-G01-PLAN-REACH", "Statement of Goals", "The project has committed to serving 60 Miami-Dade County children."),
])
def test_equal_numbers_do_not_clear_denominator_or_commitment_changes(sources, evidence_id, name, altered):
    _, pack = sources
    original = from_evidence(pack, evidence_id, name)

    def changed(context):
        result = preservation(context)
        result["a_claims"][0].update(status="changed", detail="Scope or commitment changed.")
        result.update(verdict="changed", substantive_changes=["Changed scope or commitment."])
        return result

    (_, _, review, _, comparison, recommendation), _ = run_field(
        sources, original, edit(altered, [record(original.claims[0], altered)]), changed,
    )
    assert recommendation == "reject_b"
    assert comparison["verdict"] == "changed"
    assert "style_meaning_change" in {issue.code for issue in review.deterministic}
    assert "style_numeric_change" not in {issue.code for issue in review.deterministic}


def test_missing_review_request_must_be_migrated_verbatim(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Outreach & Engagement")
    request = "To help reviewers, please provide the outreach and enrollment steps."
    original = replace(original, body=f"{original.body} {request}",
                       missing_information=("Confirm partner roles.",))
    bare = edit(original.claims[0].text, [record(original.claims[0])])
    (_, _, review, _, _, recommendation), _ = run_field(sources, original, bare)
    assert recommendation == "reject_b"
    assert "cleanup_not_migrated" in {issue.code for issue in review.deterministic}
    bare["content_cleanup"] = [{"original_text": request, "destination": "missing_information"}]
    (candidate, _, _, _, _, recommendation), _ = run_field(sources, original, bare)
    assert recommendation == "eligible_for_blind_review"
    assert candidate.missing_information == ("Confirm partner roles.", request)
    assert request not in candidate.body


def test_natural_rewrite_updates_claim_span_and_uses_fresh_verifier(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    body = "The project proposes serving 60 children in Miami-Dade County."
    (candidate, _, review, _, _, recommendation), client = run_field(
        sources, original, edit(body, [record(original.claims[0], body)]),
    )
    assert recommendation == "eligible_for_blind_review"
    assert candidate.claims[0].text == body
    assert review.semantic_checked and not review.semantic_reused
    assert [call.kwargs["model"] for call in client.responses.create.call_args_list] == [
        "editor", "verifier", "verifier",
    ]
    assert [call.kwargs["text"]["format"]["name"] for call in client.responses.create.call_args_list] == [
        "grant_style_edit", "semantic_findings", "style_claim_preservation",
    ]


def test_over_limit_is_rejected_even_if_semantic_reviews_approve(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    body = original.body + " " + "word " * 76
    (_, _, review, _, _, recommendation), _ = run_field(
        sources, original, edit(body, [record(original.claims[0])]),
    )
    assert recommendation == "reject_b"
    assert "word_limit" in {issue.code for issue in review.deterministic}


@pytest.mark.parametrize("reject", [False, True])
def test_cli_freezes_source_and_writes_blind_reports(sources, monkeypatch, tmp_path, reject):
    spec, pack = sources
    sections = [{"name": field.name, "body": "Details require confirmation.", "claims": []}
                for field in spec.fields]
    financial = budget_section(pack)
    sections[-1].update(body=financial["body"], claims=financial["claims"])
    first = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    sections[0].update(body=first.body, claims=[record(first.claims[0])])
    payload = {"mode": "full_application", "grant_id": spec.grant_id, "sections": sections,
               "budget": {"categories": spec.budget.categories, "total": spec.budget.total, "currency": "USD"}}
    source = tmp_path / "input.json"
    raw = json.dumps(payload, default=str).encode()
    source.write_bytes(raw)
    claim_text = "The project proposes serving 60 children in Miami-Dade County."
    body = claim_text + (" word" * 76 if reject else "")
    client = client_with(edit(body, [record(first.claims[0], claim_text)]), reviewed, reviewed, preservation)
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: client)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    output = tmp_path / "experiment"
    monkeypatch.setattr("sys.argv", ["style_refiner", "--application", str(source), "--output-dir", str(output),
                                    "--fields", first.name, "--writer-model", "editor", "--verifier-model", "verifier"])
    assert main() == int(reject)
    assert source.read_bytes() == (output / "version_a/application_structured.json").read_bytes() == raw
    assert client.responses.create.call_count == 4
    report = json.loads((output / "ab_comparison.json").read_text(encoding="utf-8"))
    assert len(report["fields"]) == 9
    row = report["fields"][0]
    assert row["b_body"] == body
    assert row["adoption_recommendation"] == ("reject_b" if reject else "eligible_for_blind_review")
    if reject:
        assert all(value is None for value in row["blind_ratings"].values())
        assert "Section withheld" in (output / "version_b/application_draft.md").read_text(encoding="utf-8")
    else:
        assert all(value["preference"] is None for value in row["blind_ratings"].values())
        assert "### X" in (output / "blind_reviewer_1.md").read_text(encoding="utf-8")
    assert all(item["adoption_recommendation"] == "not_selected" for item in report["fields"][1:])
    assert (output / "version_b/application_structured.json").exists()
    with pytest.raises(SystemExit):
        main()
    assert client.responses.create.call_count == 4


def test_editor_can_keep_a_unchanged_without_new_reviews(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    response = edit(original.body, [record(original.claims[0])])
    response.update(rules=[], style_improvements=[])
    (candidate, _, _, _, _, recommendation), client = run_field(sources, original, response)
    assert candidate == original
    assert recommendation == "no_change"
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize("verified", [True, False])
def test_no_change_preserves_baseline_failure_and_discards_invented_cleanup(sources, verified):
    spec, pack = sources
    field = spec.fields[0]
    original = from_evidence(pack, "TP-G01-PLAN-REACH", field.name)
    original = replace(original, missing_information=("Confirm partner roles.",))
    failure = Issue("fail", "insufficient_evidence", field.name, "Original claim. | Source gap.")
    fingerprint = semantic_fingerprint(
        original, evidence_context(section_evidence(spec.grant_id, field.name, pack)),
        field_questions(spec, field.name),
    )
    baseline = FieldReview(field.name, 1, (), (failure,), True,
                           semantic_version=SEMANTIC_VERSION if verified else None,
                           semantic_fingerprint=fingerprint)
    response = edit(original.body, [record(original.claims[0])], [
        {"original_text": original.missing_information[0], "destination": "recommendations_for_review"},
    ])
    client = client_with(response)
    candidate, a, b, changes, _, recommendation = refine_field(
        client, "editor", "verifier", original, baseline, field, spec, pack,
    )
    assert candidate == original
    assert recommendation == "no_change"
    assert a == b and failure in b.semantic
    assert b.semantic_checked == verified
    assert ("verification_pending" in {issue.code for issue in b.semantic}) == (not verified)
    assert changes == {"edit_status": "no_change", "rules": [], "style_improvements": [], "content_cleanup": []}
    assert len(issue_changes(a, b)["persistent_issue"]) == 1
    assert not issue_changes(a, b)["introduced_issue"]
    assert client.responses.create.call_count == 1


def test_review_issue_attribution_matches_claim_not_only_error_code():
    name = "Financial Narrative"
    persistent_a = Issue("fail", "insufficient_evidence", name, "Original statement. | First explanation.")
    persistent_b = replace(persistent_a, detail="Original statement. | Updated explanation.")
    resolved = replace(persistent_a, detail="Removed unsupported statement. | Source gap.")
    introduced = replace(persistent_a, detail="New unsupported statement. | Source gap.")
    a = FieldReview(name, 1, (), (persistent_a, resolved), True)
    b = FieldReview(name, 1, (), (persistent_b, introduced), True)
    changes = issue_changes(a, b)
    assert len(changes["persistent_issue"]) == 1
    assert changes["persistent_issue"][0]["a"]["detail"] == persistent_a.detail
    assert changes["resolved_issue"][0]["detail"] == resolved.detail
    assert changes["introduced_issue"][0]["detail"] == introduced.detail


def test_changed_body_cannot_claim_existing_metadata_as_cleanup(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    original = replace(original, generation_notes=("Confirm local outreach.",))
    body = "The project proposes serving 60 children in Miami-Dade County."
    response = edit(body, [record(original.claims[0], body)], [
        {"original_text": original.generation_notes[0], "destination": "missing_information"},
    ])
    (candidate, _, b, changes, _, recommendation), _ = run_field(sources, original, response)
    assert recommendation == "reject_b"
    assert changes["content_cleanup"] == []
    assert candidate.generation_notes == original.generation_notes
    assert not candidate.missing_information
    assert "invalid_cleanup" in {issue.code for issue in b.deterministic}


def test_new_unsupported_claim_is_attributed_to_b_and_rejected(sources):
    _, pack = sources
    original = from_evidence(pack, "TP-G01-PLAN-REACH", "Statement of Goals")
    added = "The project will offer weekend sessions."
    response = edit(f"{original.body} {added}", [record(original.claims[0])])

    def unsupported(context):
        return reviewed(context, [{"claim_id": "", "status": "insufficient_evidence", "quote": added,
                                   "detail": "No source establishes a weekend schedule."}])

    (_, a, b, _, _, recommendation), _ = run_field(sources, original, response, review=unsupported)
    assert recommendation == "reject_b"
    introduced = issue_changes(a, b)["introduced_issue"]
    assert any(item["code"] == "insufficient_evidence" and added in item["detail"] for item in introduced)

