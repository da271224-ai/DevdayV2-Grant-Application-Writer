"""Parse the shared virtual grant package format."""

import csv
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Budget, FieldSpec, RequirementSpec


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def money(value: str) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValueError(f"Invalid budget amount: {value}")
    return amount


def parse_requirements(folder: Path) -> RequirementSpec:
    source = (folder / "funder_requirements.md").read_text(encoding="utf-8-sig")
    limits = read_csv(folder / "narrative_limits.csv")
    award = read_csv(folder / "award_budget.csv")
    grant_id = limits[0]["grant_id"]
    funder = limits[0]["mock_funder"]

    if f"**Grant ID:** {grant_id}" not in {line.strip() for line in source.splitlines()}:
        raise ValueError("Markdown grant ID differs from the CSV")
    if source.splitlines()[0] != f"# Mock Funder Requirements — {funder}":
        raise ValueError("Markdown funder differs from the CSV")
    for row in limits + award:
        if (row["grant_id"], row["mock_funder"]) != (grant_id, funder):
            raise ValueError("Mixed grant or funder in package")

    fields = tuple(FieldSpec(row["field_name"], int(row["maximum"])) for row in limits)
    markdown_fields = tuple(
        FieldSpec(name.strip(), int(limit))
        for name, limit in re.findall(r"^\|([^|\n]+)\|\s*(\d+)\s*\|", source, re.M)
    )
    if fields != markdown_fields or len({field.name for field in fields}) != len(fields):
        raise ValueError("Narrative field definitions disagree or contain duplicates")
    if any(row["unit"] != "words" for row in limits) or "whitespace-delimited" not in source:
        raise ValueError("Unsupported counting rule")
    if any(field.maximum < 1 for field in fields):
        raise ValueError("Word limits must be positive")

    amounts = {}
    metadata = ("currency", "grant_start", "grant_end", "funder_fiscal_year", "report_due")
    for row in award:
        if any(row[key] != award[0][key] for key in metadata):
            raise ValueError("Inconsistent award metadata")
        category = row["funder_budget_category"]
        if category in amounts:
            raise ValueError(f"Duplicate budget category: {category}")
        amounts[category] = money(row["approved_amount_usd"])
    total = amounts.pop("TOTAL")
    mock_award = re.search(r"^- Mock award: \$([\d,.]+) USD\s*$", source, re.M)
    if not mock_award or money(mock_award[1].replace(",", "")) != total:
        raise ValueError("Markdown award amount differs from the CSV")
    if total != sum(amounts.values(), Decimal(0)):
        raise ValueError("Award categories do not add up to the award total")
    currency, start, end, fiscal_year, due = (award[0][key] for key in metadata)
    if currency != "USD" or not date.fromisoformat(start) <= date.fromisoformat(end) <= date.fromisoformat(due):
        raise ValueError("Unsupported currency or invalid grant dates")

    monthly_totals: dict[str, Decimal] = {}
    for row in read_csv(folder / "monthly_budget_plan_and_actual_tracker.csv"):
        category = row["Budget category"]
        monthly_totals[category] = monthly_totals.get(category, Decimal(0)) + money(row["Planned budget (USD)"])

    warnings = []
    period = re.search(r"^- Mock project period: (.+)$", source, re.M)
    if period and period[1].strip() == "{start.isoformat()} through {grant_end.isoformat()}":
        warnings.append("Project dates are placeholders in funder_requirements.md; using award_budget.csv.")
    elif not period or period[1].strip() != f"{start} through {end}":
        raise ValueError("Project period conflicts with award_budget.csv")

    attachment_section = source.split("## Required attachments (mock)", 1)[1].split("\n## ", 1)[0]
    attachments = tuple(line[2:] for line in attachment_section.splitlines() if line.startswith("- "))
    return RequirementSpec(
        grant_id, funder, fields, Budget(amounts, total, currency), monthly_totals,
        date.fromisoformat(start), date.fromisoformat(end), fiscal_year, date.fromisoformat(due),
        attachments, source, tuple(warnings),
    )
