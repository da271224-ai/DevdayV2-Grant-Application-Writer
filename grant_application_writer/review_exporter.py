"""Export generation results for human review."""

import json
import re
from dataclasses import asdict
from pathlib import Path

from .application_writer import QUALIFICATIONS_FIELD, QUALIFICATIONS_REVIEW_TEXT, GenerationResult
from .fact_verifier import BODY_METADATA, normalize
from .models import EvidencePack, RequirementSpec
from .requirement_coverage import explicit_requirements


REVIEW_REQUEST = re.compile(
    r"\b(?:please (?:provide|confirm|clarify|describe|submit)|"
    r"the applicant (?:should|needs to) (?:provide|submit|confirm|clarify)|"
    r"(?:measures and )?data sources should be defined|keep proposed steps tentative)\b",
    re.I,
)
EXPORT_NOTICE = "**Synthetic data. Human review required. Not submission-ready.**"


def export_findings(section):
    body = normalize(section.body)
    patterns = [BODY_METADATA, REVIEW_REQUEST]
    if section.name == QUALIFICATIONS_FIELD:
        patterns.append(QUALIFICATIONS_REVIEW_TEXT)
    return tuple(dict.fromkeys(match.group() for pattern in patterns for match in pattern.finditer(body)))


def review_status(result: GenerationResult, spec: RequirementSpec) -> str:
    issues = list(result.requirements)
    for field in result.fields:
        issues.extend(field.deterministic + field.semantic)
    if any(issue.status == "fail" for issue in issues):
        return "fail"
    if (issues or spec.attachments or any(export_findings(section) for section in result.application.sections)
            or any(item.status != "covered" for field in result.fields for item in field.coverage)
            or any(section.required_information_gaps for section in result.application.sections)):
        return "review_required"
    return "pass"


def export_review(output_dir: Path, result: GenerationResult, spec: RequirementSpec,
                  pack: EvidencePack, *, exclusive: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    draft = [f"# {spec.funder} | {spec.grant_id}", "", EXPORT_NOTICE]
    report = ["# Application review", "", EXPORT_NOTICE, "", "## Package warnings and attachment checks"]
    status_summary = review_status(result, spec)
    report[2:2] = [f"- Overall status: {status_summary}", ""]
    partial = result.mode == "partial_test"
    if partial:
        label = (
            f"**partial_test — {len(result.fields)} of {len(spec.fields)} fields attempted. "
            "For integration testing only.**"
        )
        draft[:3] = [f"# Partial test draft | {spec.grant_id}", "", label, "", EXPORT_NOTICE]
        report[:2] = ["# Partial test review", "", label, ""]
    report.extend(f"- {warning}" for warning in spec.warnings)
    report.extend(f"- Confirm attachment: {attachment}" for attachment in spec.attachments)
    report.extend(f"- {issue.status} / {issue.code}: {issue.detail}" for issue in result.requirements)

    section_records = []
    limits = {field.name: field.maximum for field in spec.fields}
    for section, review in zip(result.application.sections, result.fields, strict=True):
        issues = review.deterministic + review.semantic
        blocked = any(issue.status == "fail" for issue in issues)
        export_flags = export_findings(section)
        gaps = [item for item in review.coverage if item.status != "covered"]
        needs_review = bool(issues or gaps or section.required_information_gaps or export_flags)
        status = "fail" if blocked else ("review_required" if needs_review else "pass")
        body = "[Section withheld. See the review report.]" if blocked or export_flags else section.body
        draft.extend(("", f"## {section.name}", "", body))
        report.extend(("", f"## {section.name}", "",
                       f"- Status: {status}",
                       f"- Words: {len(section.body.split())} / {limits.get(section.name, 'unknown limit')}",
                       f"- Generation attempts: {review.attempts}",
                       "", "### Deterministic validation"))
        report.extend(f"- {issue.status} / {issue.code}: {issue.detail}" for issue in review.deterministic)
        if not review.deterministic:
            report.append("- No deterministic issues.")
        report.extend(("", "### Semantic fact verification",
                       f"- Completed: {review.semantic_checked}"))
        if review.semantic_reused:
            report.append("- Reused matching historical verification. No new semantic check ran.")
        report.extend(f"- {issue.status} / {issue.code}: {issue.detail}" for issue in review.semantic)
        report.extend(f"- Claim {item.claim_id or '(uncited)'} — {item.status}: {item.quote} | {item.detail}"
                      for item in review.claim_assessments)
        report.extend(("", "### Requirement coverage"))
        if not review.coverage:
            report.append("- Coverage was not assessed.")
        for item in review.coverage:
            report.append(f"- [{item.origin}] {item.status}: {item.question} {item.detail}")
            if item.quote:
                report.append(f"  - Draft excerpt: {item.quote}")
        report.extend(("", "### Human review required"))
        if export_flags:
            report.append("- Content incomplete. The draft withholds this field; the original body, claims, "
                          "and review remain in the structured JSON.")
            report.extend(f"- Review embedded text: {flag}" for flag in export_flags)
        if blocked:
            report.append("- Resolve blocking issues before including this field.")
        report.extend(f"- Review {issue.code}: {issue.detail}" for issue in issues
                      if issue.status == "review_required")
        report.extend(f"- Review coverage gap [{item.origin}]: {item.question}" for item in gaps)
        if not needs_review:
            report.append("- No field-specific items flagged. Package attachments still require confirmation.")
        requirements = explicit_requirements(spec, section.name)
        report.extend(f"- Missing explicit funder requirement: {requirements.get(key, key)}"
                      for key in section.required_information_gaps)
        report.extend(f"- Optional improvement: {item}" for item in section.missing_information)
        report.extend(f"- Recommendation for review: {item}" for item in section.recommendations_for_review)
        report.extend(f"- Generation note: {item}" for item in section.generation_notes)
        if review.api_diagnostics:
            report.extend(("", "### API diagnostics", *(f"- {item}" for item in review.api_diagnostics)))
        for evidence_id in dict.fromkeys(claim.evidence_id for claim in section.claims):
            evidence = pack.entries.get(evidence_id)
            if evidence is not None:
                report.append(f"- {evidence_id} ({evidence.approval_status.value}): "
                              f"{evidence.source.path}, {evidence.source.record}")
        record = asdict(section)
        record["section_name"] = section.name
        record["explicit_requirements"] = requirements
        record["review"] = asdict(review)
        record["status"] = status
        if export_flags:
            record["content_status"] = "content_incomplete"
            record["export_findings"] = export_flags
        section_records.append(record)

    payload = {
        "mode": result.mode,
        "status": status_summary,
        "grant_id": spec.grant_id, "budget": asdict(result.application.budget),
        "sections": section_records, "requirements": [asdict(issue) for issue in result.requirements],
        "warnings": spec.warnings, "attachments_to_review": spec.attachments,
    }
    draft_name, report_name, structured_name = (
        ("partial_test_draft.md", "partial_test_review.md", "partial_test_structured.json") if partial
        else ("application_draft.md", "review_report.md", "application_structured.json")
    )
    documents = {
        draft_name: "\n".join(draft),
        report_name: "\n".join(report),
        structured_name: json.dumps(payload, indent=2, default=str, ensure_ascii=False),
    }
    for name, content in documents.items():
        with (output_dir / name).open("x" if exclusive else "w", encoding="utf-8") as handle:
            handle.write(content + "\n")
