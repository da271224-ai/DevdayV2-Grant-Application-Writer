"""Exercise offline revalidation and selective regeneration from exported drafts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from grant_application_writer.application_revalidation import revalidate_application
from grant_application_writer.application_writer import FieldReview, GenerationResult, generate_application
from grant_application_writer.evidence_builder import build_evidence
from grant_application_writer.main import main, parse_application
from grant_application_writer.models import Application, Claim, Issue, Section
from grant_application_writer.requirement_parser import parse_requirements
from grant_application_writer.review_exporter import export_review, review_status

from test_generation import budget_section, client_with, reviewed, section

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def saved(tmp_path):
    folder = ROOT / "grant-01-youth-mentoring"
    spec = parse_requirements(folder)
    pack = build_evidence(folder, ROOT / "organization_fact_sheet.md", spec)
    responses = []
    for field in spec.fields:
        if field.name in {"Implementation", "Financial Narrative"}:
            invalid = section(field.name, "Coverage question 1: missing details.")
            responses.extend([invalid] * 3)
        else:
            responses.extend([section(field.name, "Project details remain to be confirmed."), reviewed])
    result = generate_application(client_with(*responses), "writer", "verifier", spec, pack)
    source_dir = tmp_path / "original"
    export_review(source_dir, result, spec, pack)
    return spec, pack, source_dir / "application_structured.json"


@pytest.mark.parametrize("change", ["none", "body", "version", "evidence", "claim"])
def test_offline_semantic_reuse_requires_matching_inputs(saved, change):
    spec, pack, source = saved
    payload = json.loads(source.read_text(encoding="utf-8"))
    record = payload["sections"][0]
    if change == "body":
        record["body"] += " An extra sentence."
    elif change == "version":
        del record["review"]["semantic_version"]
    elif change == "evidence":
        key = "TP-G01-PLAN-GOAL"
        pack = replace(pack, entries={**pack.entries, key: replace(pack.entries[key], text="A changed source.")})
    elif change == "claim":
        item = pack.entries["TP-G01-PLAN-GOAL"]
        record["claims"] = [{"text": item.text, "kind": item.kind, "evidence_id": item.evidence_id}]
    result = revalidate_application(parse_application(payload), payload, spec, pack)
    review = result.fields[0]
    assert review.semantic_reused == (change == "none")
    assert review.semantic_checked == (change == "none")
    if change != "none":
        assert [issue.code for issue in review.semantic] == ["semantic_not_revalidated"]
    if change == "claim":
        assert "claim_not_in_body" in {issue.code for issue in review.deterministic}


def test_revalidate_cli_never_creates_api_client_and_preserves_source(saved, tmp_path, monkeypatch, capsys):
    _, _, source = saved
    original = source.read_bytes()
    output = tmp_path / "revalidated"

    def unexpected_client(**kwargs):
        pytest.fail("Revalidation must not create an OpenAI client")

    monkeypatch.setattr("openai.OpenAI", unexpected_client)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["main", "--revalidate", str(source), "--output-dir", str(output)])
    assert main() == 1
    assert source.read_bytes() == original
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed_fields"] == ["Implementation", "Financial Narrative"]
    report = (output / "review_report.md").read_text(encoding="utf-8")
    assert "Reused matching historical verification" in report
    assert "semantic_not_revalidated" in report


def test_retry_cli_calls_only_requested_fields_and_updates_status(saved, tmp_path, monkeypatch, capsys):
    _, pack, source = saved
    original = source.read_bytes()
    output = tmp_path / "retried"
    fields = ["Financial Narrative", "Implementation"]
    client = client_with(
        section("Implementation", "The activity sequence needs confirmation."), reviewed,
        budget_section(pack), reviewed,
    )
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: client)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    monkeypatch.setattr("sys.argv", [
        "main", "--application", str(source), "--retry-fields", *fields, "--output-dir", str(output),
        "--writer-model", "writer", "--verifier-model", "verifier",
    ])
    assert main() == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "review_required"
    assert summary["failed_fields"] == []
    contexts = [json.loads(call.kwargs["input"]) for call in client.responses.create.call_args_list]
    assert [item["section_name"] for item in contexts] == [
        "Implementation", "Implementation", "Financial Narrative", "Financial Narrative",
    ]
    assert source.read_bytes() == original
    updated = json.loads((output / "application_structured.json").read_text(encoding="utf-8"))
    assert updated["status"] == "review_required"
    original_app, updated_app = parse_application(json.loads(original)), parse_application(updated)
    assert [item.name for item in original_app.sections] == [item.name for item in updated_app.sections]
    assert [item for item in original_app.sections if item.name not in fields] == [
        item for item in updated_app.sections if item.name not in fields
    ]


def test_revalidate_cannot_write_to_source_directory(saved, monkeypatch):
    _, _, source = saved
    original = source.read_bytes()
    monkeypatch.setattr("sys.argv", ["main", "--revalidate", str(source), "--output-dir", str(source.parent)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert source.read_bytes() == original


@pytest.mark.parametrize("embedded", [
    "To help reviewers, please provide the enrollment plan.",
    "Measures and data sources should be defined during planning.",
    "Coverage question 1: see TF-001 (verified_organizational_fact).",
])
def test_export_withholds_internal_text_and_preserves_original_review(saved, tmp_path, embedded):
    spec, pack, _ = saved
    spec = replace(spec, attachments=())
    evidence = pack.entries["TF-001"]
    claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
    name = "Outreach & Engagement"
    section = Section(name, f"{claim.text} {embedded}", (claim,), missing_information=("Confirm outreach.",))
    prior = Issue("review_required", "fixture_review", name, "Keep this review record.")
    field = FieldReview(name, 1, (), (prior,), True)
    result = GenerationResult(Application(spec.grant_id, (section,), spec.budget), (field,), ())
    output = tmp_path / "export-guard"
    export_review(output, result, spec, pack)
    draft = (output / "application_draft.md").read_text(encoding="utf-8")
    assert "Not submission-ready." in draft and "Section withheld" in draft
    assert embedded not in draft
    report = (output / "review_report.md").read_text(encoding="utf-8")
    assert "Content incomplete" in report and prior.detail in report
    payload = json.loads((output / "application_structured.json").read_text(encoding="utf-8"))
    assert payload["status"] == review_status(result, spec) == "review_required"
    assert review_status(replace(result, fields=(replace(field, semantic=()),)), spec) == "review_required"
    assert payload["sections"][0]["content_status"] == "content_incomplete"
    assert payload["sections"][0]["review"]["semantic"][0]["detail"] == prior.detail
    assert parse_application(payload).sections == (section,)

