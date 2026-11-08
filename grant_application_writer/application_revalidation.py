"""Revalidate saved drafts and merge replacements without regenerating other fields."""

from dataclasses import replace

from .application_writer import (
    FieldReview, GenerationResult, evidence_context, generate_application, section_evidence, validate_section,
)
from .models import Application, EvidencePack, Issue, RequirementSpec
from .requirement_coverage import CoverageAssessment, field_questions
from .requirement_validator import validate_requirements
from .semantic_fact_verifier import SEMANTIC_VERSION, ClaimAssessment, semantic_fingerprint


def revalidate_application(application: Application, payload: dict, spec: RequirementSpec,
                           pack: EvidencePack) -> GenerationResult:
    if application.grant_id != spec.grant_id or pack.grant_id != spec.grant_id:
        raise ValueError("Saved application, requirements, and evidence must belong to the same grant.")
    mode = payload.get("mode", "full_application")
    if mode not in {"full_application", "partial_test"}:
        raise ValueError(f"Unsupported application mode: {mode}")
    fields = spec.fields
    if mode == "partial_test":
        count = len(application.sections)
        if not 0 < count < len(fields):
            raise ValueError("Invalid field count for a partial test.")
        fields = fields[:count]

    reviews = []
    requirements = validate_requirements(application, replace(spec, fields=fields))
    for section, record in zip(application.sections, payload["sections"], strict=True):
        previous = record.get("review") or {}
        scoped_pack = section_evidence(spec.grant_id, section.name, pack)
        deterministic = tuple(validate_section(section, spec, scoped_pack)) + tuple(
            issue for issue in requirements if issue.location == section.name
        )
        fingerprint = semantic_fingerprint(
            section, evidence_context(scoped_pack), field_questions(spec, section.name),
        )
        attempts = previous.get("attempts", 0)
        diagnostics = tuple(previous.get("api_diagnostics", ()))
        if (
            previous.get("semantic_checked") is True
            and previous.get("semantic_version") == SEMANTIC_VERSION
            and previous.get("semantic_fingerprint") == fingerprint
        ):
            try:
                reviews.append(FieldReview(
                    section.name, attempts, deterministic,
                    tuple(Issue(**item) for item in previous["semantic"]), True,
                    tuple(ClaimAssessment(**item) for item in previous["claim_assessments"]),
                    tuple(CoverageAssessment(**item) for item in previous["coverage"]),
                    diagnostics, SEMANTIC_VERSION, fingerprint, True,
                ))
                continue
            except (KeyError, TypeError):
                pass
        unavailable = Issue(
            "review_required", "semantic_not_revalidated", section.name,
            "No reusable semantic result matches this field and the current verifier inputs.",
        )
        reviews.append(FieldReview(section.name, attempts, deterministic, (unavailable,), False,
                                   api_diagnostics=diagnostics))

    return GenerationResult(application, tuple(reviews), tuple(requirements), mode)


def retry_field_specs(original: GenerationResult, spec: RequirementSpec, names: list[str]):
    requested = set(names)
    if not requested or len(requested) != len(names):
        raise ValueError("Provide unique field names to retry.")
    present = [section.name for section in original.application.sections]
    expected = [field.name for field in spec.fields]
    if original.mode == "partial_test":
        expected = expected[:len(present)]
    if present != expected:
        raise ValueError("Saved fields must match the funder field order before a targeted retry.")
    if requested - set(present):
        raise ValueError(f"Unknown or absent retry fields: {', '.join(sorted(requested - set(present)))}")
    return tuple(field for field in spec.fields if field.name in requested)


def regenerate_fields(client, writer_model: str, verifier_model: str, original: GenerationResult,
                      spec: RequirementSpec, pack: EvidencePack, names: list[str]) -> GenerationResult:
    selected = retry_field_specs(original, spec, names)
    replacement = generate_application(client, writer_model, verifier_model, replace(spec, fields=selected), pack)
    new_sections = {section.name: section for section in replacement.application.sections}
    new_reviews = {review.section_name: review for review in replacement.fields}
    application = replace(
        original.application,
        sections=tuple(new_sections.get(section.name, section) for section in original.application.sections),
    )
    reviews = tuple(new_reviews.get(review.section_name, review) for review in original.fields)
    fields = spec.fields[:len(application.sections)] if original.mode == "partial_test" else spec.fields
    requirements = validate_requirements(application, replace(spec, fields=fields))
    return GenerationResult(application, reviews, tuple(requirements), original.mode)

