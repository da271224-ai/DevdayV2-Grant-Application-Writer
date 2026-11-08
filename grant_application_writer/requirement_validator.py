"""Validate application structure and budget independently of facts."""

from decimal import Decimal

from .models import Application, Issue, RequirementSpec


def validate_requirements(application: Application, spec: RequirementSpec) -> list[Issue]:
    issues = []
    expected = [field.name for field in spec.fields]
    actual = [section.name for section in application.sections]
    limits = {field.name: field.maximum for field in spec.fields}

    def fail(code: str, location: str, detail: str) -> None:
        issues.append(Issue("fail", code, location, detail))

    if application.grant_id != spec.grant_id:
        fail("grant_id", "application", "Application grant ID differs from the requirements.")
    for name in expected:
        if name not in actual:
            fail("missing_field", name, "Required field is absent.")
    if actual != expected:
        fail("field_order", "application", "Field names and order must exactly match the requirements.")
    for section in application.sections:
        count = len(section.body.split())
        if count == 0:
            fail("empty_field", section.name, "Required body is empty.")
        if section.name not in limits:
            fail("unknown_field", section.name, "Field is absent from the requirements.")
        elif count > limits[section.name]:
            fail("word_limit", section.name, f"{count} words; limit is {limits[section.name]}.")

    budget = application.budget
    if budget.currency != spec.budget.currency:
        fail("budget_currency", "budget", "Budget currency differs from the award fixture.")
    if budget.categories != spec.budget.categories:
        fail("budget_categories", "budget", "Budget categories or amounts differ from the award fixture.")
    if budget.total != sum(budget.categories.values(), Decimal(0)) or budget.total != spec.budget.total:
        fail("budget_total", "budget", "Budget total must equal both the category sum and the award fixture total.")
    if spec.monthly_totals != spec.budget.categories:
        fail("monthly_budget", "budget", "Monthly plan category totals differ from the award fixture.")
    return issues
