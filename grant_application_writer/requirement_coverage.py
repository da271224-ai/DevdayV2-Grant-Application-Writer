"""Review inferred topics and identify source-backed field requirements."""

from dataclasses import dataclass

from .fact_verifier import normalize
from .models import RequirementSpec, Section
from .responses_client import STRING, StructuredResponseError, array_schema, object_schema


TP_G01_QUESTIONS = {
    "Statement of Goals": ("What change is the project intended to achieve?",
                           "Which Miami-Dade children and caregivers will it serve?"),
    "Implementation": ("What mentoring activities are proposed and in what sequence?",
                       "How will mentors be screened, trained, and supported?"),
    "Activities Measures": ("Which activities or participation outputs will be tracked?",
                            "How will those activities be recorded?"),
    "Outreach & Engagement": ("How will children and caregivers learn about and enter the program?",
                             "How will caregivers participate and barriers be addressed?"),
    "Assessment": ("How and when will outcomes be measured?",
                   "How will the team use the results?"),
    "Outcomes Measures": ("Which participant outcomes and targets will be assessed?",
                          "What measure or data source will be used for each?"),
    "Qualifications & Sustainability": ("What verified qualifications support delivery?",
                                        "How could the work continue after the grant?"),
    "Advancing Equity": ("Which access barriers does the design address?",
                        "What concrete steps will reduce those barriers?"),
    "Financial Narrative": ("What is the total request and how are funds allocated?",
                            "How do the proposed costs support eligible activities and respect restrictions?"),
}

COVERAGE_SCHEMA = array_schema(object_schema(
    topic_id=STRING,
    status={**STRING, "enum": ["covered", "partial", "missing", "review_required"]},
    quote=STRING,
    detail=STRING,
))


@dataclass(frozen=True)
class CoverageAssessment:
    question: str
    status: str
    quote: str
    detail: str
    origin: str = "inferred"


def explicit_requirements(spec: RequirementSpec, name: str) -> dict[str, str]:
    if (spec.grant_id, name) not in {
        ("TP-G01", "Statement of Goals"), ("TP-G02", "Equity and Access"),
    }:
        return {}
    requirement = "Proposed work must serve Miami-Dade County children and caregivers."
    for line in spec.source_text.splitlines():
        if line.startswith("- Applicant: ") and line.endswith(requirement):
            return {"service_population": requirement}
    return {}


def field_questions(spec: RequirementSpec, name: str) -> dict[str, str]:
    questions = TP_G01_QUESTIONS.get(name, ()) if spec.grant_id == "TP-G01" else ()
    return {str(index): question for index, question in enumerate(questions, 1)}


def assess_coverage(section: Section, questions: dict[str, str], rows: list[dict]) -> tuple[CoverageAssessment, ...]:
    by_id = {row["topic_id"]: row for row in rows}
    if by_id.keys() != questions.keys() or len(by_id) != len(rows):
        raise StructuredResponseError("Coverage did not assess every topic exactly once.")
    if not questions:
        return (CoverageAssessment(section.name, "review_required", "", "No reviewed coverage rubric is configured.",
                                   "unconfigured"),)
    result = []
    for topic_id, question in questions.items():
        row = by_id[topic_id]
        quote = normalize(row["quote"])
        if (quote and quote not in normalize(section.body)) or (
            row["status"] in {"covered", "partial"} and not quote
        ):
            raise StructuredResponseError("Coverage assessment did not quote the draft.")
        if row["status"] != "covered" and not row["detail"].strip():
            raise StructuredResponseError("Coverage assessment did not explain the gap.")
        result.append(CoverageAssessment(question, row["status"], quote, row["detail"]))
    return tuple(result)

