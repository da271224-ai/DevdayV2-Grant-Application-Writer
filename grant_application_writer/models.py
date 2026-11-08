"""Data contracts shared by the offline pipeline."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class EvidenceKind(str, Enum):
    ORGANIZATIONAL_FACT = "verified_organizational_fact"
    PROJECT_PLAN = "proposed_project_plan"
    PROJECTED_OUTCOME = "projected_outcome"
    HISTORICAL_ACHIEVEMENT = "historical_achievement"
    SYNTHETIC_ACTUAL = "synthetic_post_award_actual"
    UNVERIFIED = "missing_or_unverified"


class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    PROPOSED = "proposed"
    UNVERIFIED = "unverified"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class Source:
    path: str
    record: str


@dataclass(frozen=True)
class FieldSpec:
    name: str
    maximum: int


@dataclass(frozen=True)
class Budget:
    categories: dict[str, Decimal]
    total: Decimal
    currency: str = "USD"


@dataclass(frozen=True)
class RequirementSpec:
    grant_id: str
    funder: str
    fields: tuple[FieldSpec, ...]
    budget: Budget
    monthly_totals: dict[str, Decimal]
    grant_start: date
    grant_end: date
    fiscal_year: str
    report_due: date
    attachments: tuple[str, ...]
    source_text: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    text: str
    source: Source
    grant_id: str | None = None
    allowed_sections: tuple[str, ...] = ()
    approval_status: ApprovalStatus = ApprovalStatus.UNVERIFIED


@dataclass(frozen=True)
class EvidencePack:
    grant_id: str
    entries: dict[str, Evidence]


@dataclass(frozen=True)
class Claim:
    text: str
    kind: EvidenceKind
    evidence_id: str


@dataclass(frozen=True)
class Section:
    name: str
    body: str
    claims: tuple[Claim, ...] = ()
    missing_information: tuple[str, ...] = ()
    generation_notes: tuple[str, ...] = ()
    required_information_gaps: tuple[str, ...] = ()
    recommendations_for_review: tuple[str, ...] = ()


@dataclass(frozen=True)
class Application:
    grant_id: str
    sections: tuple[Section, ...]
    budget: Budget


@dataclass(frozen=True)
class Issue:
    status: str
    code: str
    location: str
    detail: str
