"""Build an auditable evidence catalog from the challenge files."""

import re
from pathlib import Path

from .models import ApprovalStatus, Evidence, EvidenceKind, EvidencePack, RequirementSpec, Source
from .requirement_parser import read_csv


def build_evidence(folder: Path, fact_sheet: Path, spec: RequirementSpec) -> EvidencePack:
    entries = {}
    for line in fact_sheet.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("| TF-"):
            continue
        evidence_id, statement, status, _ = (part.strip() for part in line.strip("|").split("|"))
        kind = (
            EvidenceKind.ORGANIZATIONAL_FACT if status == "Synthetic scenario fact"
            else EvidenceKind.UNVERIFIED
        )
        approval = (
            ApprovalStatus.APPROVED if kind == EvidenceKind.ORGANIZATIONAL_FACT
            else ApprovalStatus.UNVERIFIED
        )
        entries[evidence_id] = Evidence(
            evidence_id, kind, statement, Source(str(fact_sheet), evidence_id), approval_status=approval,
        )
    if not entries:
        raise ValueError("No organizational evidence found")

    def add(suffix: str, kind: EvidenceKind, statement: str, filename: str, record: str,
            sections: tuple[str, ...] = ()) -> None:
        evidence_id = f"{spec.grant_id}-{suffix}"
        entries[evidence_id] = Evidence(
            evidence_id, kind, statement, Source(str(folder / filename), record), spec.grant_id, sections,
            ApprovalStatus.PROHIBITED if kind == EvidenceKind.SYNTHETIC_ACTUAL else ApprovalStatus.PROPOSED,
        )

    filename = "proposal_reference.md"
    reference = (folder / filename).read_text(encoding="utf-8-sig")
    population = re.search(r"^\*\*Primary population:\*\* (\d+) Miami-Dade County children\b", reference, re.M)
    if spec.grant_id == "TP-G01":
        if not population:
            raise ValueError("TP-G01 proposed reach is missing")
        add("PLAN-REACH", EvidenceKind.PROJECT_PLAN,
            f"The proposed project aims to serve {population[1]} Miami-Dade County children.",
            filename, "Primary population", ("Statement of Goals", "Implementation", "Outreach & Engagement"))
        if "children in elementary and middle school, with caregiver engagement" in reference:
            add("PLAN-PARTICIPANTS", EvidenceKind.PROJECT_PLAN,
                "The proposed project would serve children in elementary and middle school and engage their caregivers.",
                filename, "Primary population", ("Statement of Goals", "Outreach & Engagement"))
        goal = "strengthen the well-being, school connection, and social-emotional skills"
        if goal not in reference:
            raise ValueError("TP-G01 proposed mentoring goal is missing")
        add("PLAN-GOAL", EvidenceKind.PROJECT_PLAN,
            f"The proposed mentoring project aims to {goal} of participating children.",
            filename, "Statement of Goals, opening paragraph", ("Statement of Goals",))
        activity = "The program will pair each child with a screened, trained adult mentor or stable small-group mentor team."
        if activity not in reference:
            raise ValueError("TP-G01 proposed mentoring activity is missing")
        add("PLAN-MENTORING", EvidenceKind.PROJECT_PLAN,
            "The proposed program would pair each child with a screened, trained adult mentor or stable small-group mentor team.",
            filename, "Implementation, opening paragraph", ("Implementation", "Activities Measures"))

    filename = "outcomes_data.csv"
    for index, row in enumerate(read_csv(folder / filename), start=1):
        if row["grant_id"] != spec.grant_id:
            raise ValueError("Outcome belongs to a different grant")
        measure = row["measure"]
        add(f"TARGET-{index}", EvidenceKind.PROJECTED_OUTCOME,
            f"Proposed target ({measure}): {row['target']} {row['unit']}.",
            filename, f"data row {index}, target", ("Assessment", "Outcomes Measures"))
        add(f"ACTUAL-{index}", EvidenceKind.SYNTHETIC_ACTUAL,
            f"Reported result ({measure}): {row['synthetic_actual']} {row['unit']} on {row['measurement_date']}.",
            filename, f"data row {index}, synthetic_actual")

    add("BUDGET-TOTAL", EvidenceKind.PROJECT_PLAN,
        "The proposed budget totals ${:,.2f}.".format(spec.budget.total),
        "award_budget.csv", "TOTAL / approved_amount_usd", ("Financial Narrative",))
    for index, (category, amount) in enumerate(spec.budget.categories.items(), start=1):
        add(f"BUDGET-CATEGORY-{index}", EvidenceKind.PROJECT_PLAN,
            "The proposed allocation for {} is ${:,.2f}.".format(category, amount),
            "award_budget.csv", category, ("Financial Narrative",))
    add("PLAN-PERIOD", EvidenceKind.PROJECT_PLAN,
        f"The proposed grant period is {spec.grant_start} through {spec.grant_end}.",
        "award_budget.csv", "grant_start / grant_end",
        tuple(field.name for field in spec.fields if re.search(r"implementation|timeline", field.name, re.I))
        or (spec.fields[0].name,))
    return EvidencePack(spec.grant_id, entries)
