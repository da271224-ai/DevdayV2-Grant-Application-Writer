"""Exercise offline validation against the original TP-G01 fixture."""

import json
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from grant_application_writer.evidence_builder import build_evidence
from grant_application_writer.fact_verifier import verify_facts
from grant_application_writer.main import main
from grant_application_writer.models import ApprovalStatus, Application, Claim, EvidenceKind, Section
from grant_application_writer.requirement_parser import parse_requirements
from grant_application_writer.requirement_validator import validate_requirements

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "grant-01-youth-mentoring"


class OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = parse_requirements(FOLDER)
        cls.pack = build_evidence(FOLDER, ROOT / "organization_fact_sheet.md", cls.spec)
        cls.draft = Application(
            cls.spec.grant_id,
            tuple(Section(field.name, "Draft text.") for field in cls.spec.fields),
            cls.spec.budget,
        )

    def with_goal(self, body, claims=()):
        goal = Section("Statement of Goals", body, claims)
        return replace(self.draft, sections=(goal, *self.draft.sections[1:]))

    def test_75_words_pass(self):
        self.assertEqual(validate_requirements(self.with_goal("word " * 75), self.spec), [])

    def test_single_paragraph_with_five_claims_has_no_uncovered_prose(self):
        ids = ["TF-001", "TF-002", "TP-G01-PLAN-GOAL", "TP-G01-PLAN-REACH", "TF-003"]
        evidence = [self.pack.entries[key] for key in ids]
        claims = tuple(Claim(item.text, item.kind, item.evidence_id) for item in evidence)
        body = " ".join(claim.text for claim in claims)
        draft = Application(self.spec.grant_id, (Section("Statement of Goals", body, claims),), self.spec.budget)
        issues = verify_facts(draft, self.pack)
        self.assertEqual([issue.code for issue in issues], ["proposed_evidence", "proposed_evidence"])
        unsupported = "All participants already have guaranteed placements."
        revised = replace(draft, sections=(replace(draft.sections[0], body=f"{body} {unsupported}"),))
        issues = verify_facts(revised, self.pack)
        self.assertEqual([issue.detail for issue in issues if issue.code == "unverified_prose"], [unsupported])

    def test_uncovered_qualifier_and_partial_numeric_token_are_not_cleared(self):
        evidence = self.pack.entries["TP-G01-PLAN-REACH"]
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        issues = verify_facts(self.with_goal(f"Officials deny this: {claim.text}", (claim,)), self.pack)
        self.assertIn("Officials deny this:", [issue.detail for issue in issues if issue.code == "unverified_prose"])
        text = "60"
        claim = Claim(text, evidence.kind, evidence.evidence_id)
        issues = verify_facts(self.with_goal("60.5 children", (claim,)), self.pack)
        self.assertIn("uncited_numeric", {issue.code for issue in issues})

    def test_internal_ids_and_numbered_list_are_not_factual_numbers(self):
        evidence = self.pack.entries["TF-001"]
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        body = (
            f"1) {claim.text} (TF-001, verified_organizational_fact)\n"
            "2) Coverage question 3: see TP-G01-TARGET-1.\n"
            "3) Missing information: confirm follow-up."
        )
        issues = verify_facts(self.with_goal(body, (claim,)), self.pack)
        self.assertIn("body_review_metadata", {issue.code for issue in issues})
        self.assertNotIn("uncited_numeric", {issue.code for issue in issues})

    def test_fact_numbers_next_to_formatting_are_still_checked(self):
        body = "1) Serve 61 children; 2) spend $8,000.50 by 2025-07-01; 3) reach 71%."
        issues = verify_facts(self.with_goal(body), self.pack)
        numeric = next(issue.detail for issue in issues if issue.code == "uncited_numeric")
        self.assertEqual(numeric, "Numeric content lacks a matching citation: 61, $8,000.50, 2025-07-01, 71%.")

    def test_numbered_claims_and_transitions_do_not_add_uncovered_prose(self):
        evidence = self.pack.entries["TP-G01-PLAN-REACH"]
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        body = f"1) Tentatively, {claim.text}"
        draft = Application(self.spec.grant_id, (Section("Statement of Goals", body, (claim,)),), self.spec.budget)
        self.assertEqual([issue.code for issue in verify_facts(draft, self.pack)], ["proposed_evidence"])

    def test_76_words_fail(self):
        self.assertEqual(
            [issue.code for issue in validate_requirements(self.with_goal("word " * 76), self.spec)],
            ["word_limit"],
        )

    def test_missing_required_field(self):
        draft = replace(self.draft, sections=self.draft.sections[1:])
        self.assertIn("missing_field", {issue.code for issue in validate_requirements(draft, self.spec)})

    def test_reordered_fields(self):
        draft = replace(self.draft, sections=self.draft.sections[::-1])
        self.assertEqual([issue.code for issue in validate_requirements(draft, self.spec)], ["field_order"])

    def test_wrong_budget_total(self):
        draft = replace(self.draft, budget=replace(self.draft.budget, total=Decimal("74000")))
        self.assertIn("budget_total", {issue.code for issue in validate_requirements(draft, self.spec)})

    def test_wrong_budget_category(self):
        budget = replace(self.draft.budget, categories={"Other": self.draft.budget.total})
        draft = replace(self.draft, budget=budget)
        self.assertEqual([issue.code for issue in validate_requirements(draft, self.spec)], ["budget_categories"])

    def test_projected_reach_as_history(self):
        text = "Tidepath served 60 Miami-Dade County children."
        claim = Claim(text, EvidenceKind.HISTORICAL_ACHIEVEMENT, "TP-G01-PLAN-REACH")
        self.assertIn("claim_kind", {issue.code for issue in verify_facts(self.with_goal(text, (claim,)), self.pack)})

    def test_missing_evidence_id(self):
        claim = Claim("Tidepath served children.", EvidenceKind.ORGANIZATIONAL_FACT, "TF-999")
        issues = verify_facts(self.with_goal(claim.text, (claim,)), self.pack)
        self.assertIn(("fail", "unknown_evidence"), {(issue.status, issue.code) for issue in issues})

    def test_synthetic_actual_is_blocked(self):
        evidence = self.pack.entries["TP-G01-ACTUAL-1"]
        claim = Claim(evidence.text, EvidenceKind.ORGANIZATIONAL_FACT, evidence.evidence_id)
        issues = verify_facts(self.with_goal(claim.text, (claim,)), self.pack)
        self.assertIn(("fail", "synthetic_actual"), {(issue.status, issue.code) for issue in issues})

    def test_exact_proposed_reach_requires_review_until_approved(self):
        evidence = self.pack.entries["TP-G01-PLAN-REACH"]
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        draft = Application(self.spec.grant_id, (Section("Statement of Goals", claim.text, (claim,)),), self.spec.budget)
        issues = verify_facts(draft, self.pack)
        self.assertIn(("review_required", "proposed_evidence"), {(issue.status, issue.code) for issue in issues})
        approved = replace(evidence, approval_status=ApprovalStatus.APPROVED)
        pack = replace(self.pack, entries={**self.pack.entries, approved.evidence_id: approved})
        self.assertEqual(verify_facts(draft, pack), [])

    def test_prohibited_status_blocks_otherwise_valid_fact(self):
        evidence = replace(self.pack.entries["TF-001"], approval_status=ApprovalStatus.PROHIBITED)
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        pack = replace(self.pack, entries={**self.pack.entries, evidence.evidence_id: evidence})
        issues = verify_facts(self.with_goal(claim.text, (claim,)), pack)
        self.assertIn(("fail", "prohibited_evidence"), {(issue.status, issue.code) for issue in issues})

    def test_unverified_status_blocks_automatic_clearance(self):
        evidence = replace(self.pack.entries["TF-001"], approval_status=ApprovalStatus.UNVERIFIED)
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        pack = replace(self.pack, entries={**self.pack.entries, evidence.evidence_id: evidence})
        issues = verify_facts(self.with_goal(claim.text, (claim,)), pack)
        self.assertIn(("review_required", "unverified_evidence"), {(issue.status, issue.code) for issue in issues})

    def test_numeric_mismatch(self):
        evidence = self.pack.entries["TP-G01-PLAN-REACH"]
        text = evidence.text.replace("60", "61")
        claim = Claim(text, evidence.kind, evidence.evidence_id)
        self.assertIn("numeric_mismatch", {issue.code for issue in verify_facts(self.with_goal(text, (claim,)), self.pack)})

    def test_partial_dates_and_changed_percent_still_fail(self):
        for key, name, text in (
            ("PLAN-PERIOD", "Implementation", "The project starts 2024-07-01."),
            ("TARGET-3", "Outcomes Measures", "The proposed improvement target is 71 percent."),
        ):
            with self.subTest(evidence=key):
                evidence = self.pack.entries[f"TP-G01-{key}"]
                claim = Claim(text, evidence.kind, evidence.evidence_id)
                draft = Application(self.spec.grant_id, (Section(name, text, (claim,)),), self.spec.budget)
                self.assertIn("numeric_mismatch", {issue.code for issue in verify_facts(draft, self.pack)})

    def test_amount_and_date_mismatches(self):
        for suffix, original, altered, name in (
            ("BUDGET-TOTAL", "75,000", "76,000", "Financial Narrative"),
            ("PLAN-PERIOD", "2024-07-01", "2024-07-02", "Implementation"),
        ):
            with self.subTest(suffix=suffix):
                evidence = self.pack.entries[f"TP-G01-{suffix}"]
                text = evidence.text.replace(original, altered)
                claim = Claim(text, evidence.kind, evidence.evidence_id)
                draft = Application(self.spec.grant_id, (Section(name, text, (claim,)),), self.spec.budget)
                self.assertIn("numeric_mismatch", {issue.code for issue in verify_facts(draft, self.pack)})

    def test_scope_mismatch(self):
        evidence = self.pack.entries["TP-G01-BUDGET-TOTAL"]
        claim = Claim(evidence.text, evidence.kind, evidence.evidence_id)
        issues = verify_facts(self.with_goal(claim.text, (claim,)), self.pack)
        self.assertIn(("fail", "evidence_scope"), {(issue.status, issue.code) for issue in issues})

    def test_unannotated_claim_requires_review(self):
        issues = verify_facts(self.with_goal("Our staff hold clinical certifications."), self.pack)
        self.assertIn(("review_required", "unverified_prose"), {(issue.status, issue.code) for issue in issues})

    def test_same_numbers_do_not_approve_historical_rewording(self):
        text = "Tidepath served 60 Miami-Dade County children."
        claim = Claim(text, EvidenceKind.PROJECT_PLAN, "TP-G01-PLAN-REACH")
        issues = verify_facts(self.with_goal(text, (claim,)), self.pack)
        self.assertIn(("review_required", "unsupported_wording"), {(issue.status, issue.code) for issue in issues})

    def test_date_fallback_and_source(self):
        self.assertEqual(self.spec.grant_start.isoformat(), "2024-07-01")
        self.assertTrue(self.spec.warnings)
        self.assertEqual(self.spec.monthly_totals, self.spec.budget.categories)

    def test_cli_reports_review_for_uncited_draft(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "draft.json"
            path.write_text(json.dumps(asdict(self.draft), default=str), encoding="utf-8")
            output = StringIO()
            with patch("sys.argv", ["main", "--application", str(path)]), redirect_stdout(output):
                self.assertEqual(main(), 2)
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "review_required")
            self.assertTrue(report["attachments_to_review"])

