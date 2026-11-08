"""Verify source-bound claims without a model."""

import re

from .models import ApprovalStatus, Application, EvidenceKind, EvidencePack, Issue

NUMBER = re.compile(r"(?<!\w)(?:USD\s+|\$\s*)?[-+]?(?:\d{4}-\d{2}-\d{2}|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?)", re.I)
CONNECTORS = re.compile(
    r"(?:[\W_]|\b(?:and|or|but|also|however|in addition|together|tentatively|first|next|finally|"
    r"in sum|overall|in short|for example|moreover|at the same time|with that in mind)\b)*", re.I,
)
BODY_METADATA = re.compile(
    r"\b(?:TF-\d+|TP-G\d+(?:-[A-Z0-9]+)+)\b"
    r"|\b(?:" + "|".join(re.escape(kind.value) for kind in EvidenceKind) + r")\b"
    r"|\bcoverage (?:question|topic)(?:\s+\d+)?\b"
    r"|\b(?:evidence IDs?|claim types?|missing information|generation notes?|review comments?|"
    r"recommendations for review)\s*:"
    r"|\b(?:the evidence|the materials|the submission|the proposal text) "
    r"(?:does not specify|do not specify|does not provide|do not provide|does not describe)\b",
    re.I,
)
LIST_MARKER = re.compile(r"(?:^[ \t]*(?:[-*][ \t]+)?|(?<=[:;])[ \t]+)(\d{1,2}[.)])(?=[ \t]+\S)", re.M)
MASK = "\0"


def normalize(text: str) -> str:
    return " ".join(text.split())


def mask_formatting(text: str) -> str:
    """Mask only identified metadata and list prefixes, preserving normalized offsets."""
    text = LIST_MARKER.sub(lambda match: match[0][:match.start(1) - match.start()] + MASK * len(match[1]), text)
    return normalize(BODY_METADATA.sub(lambda match: "".join(
        char if char.isspace() else MASK for char in match[0]
    ), text))


def verify_facts(application: Application, pack: EvidencePack) -> list[Issue]:
    if application.grant_id != pack.grant_id:
        return [Issue("fail", "evidence_grant", application.grant_id, "Evidence pack belongs to another grant.")]

    issues = []
    for section in application.sections:
        body = normalize(section.body)
        factual_body = mask_formatting(section.body)
        for match in BODY_METADATA.finditer(body):
            issues.append(Issue("fail", "body_review_metadata", section.name,
                                f"Move internal review text out of the application body: {match[0]}"))
        spans = []
        for claim in section.claims:
            evidence = pack.entries.get(claim.evidence_id)
            statement = normalize(claim.text)
            numbers = NUMBER.findall(mask_formatting(claim.text))
            matches = list(re.finditer(r"(?<!\w)" + re.escape(statement) + r"(?!\w)", body)) if statement else []
            status = "fail"

            if evidence is None:
                code = "unknown_evidence"
            elif evidence.grant_id not in (None, application.grant_id):
                code = "evidence_grant"
            elif evidence.kind == EvidenceKind.SYNTHETIC_ACTUAL:
                code = "synthetic_actual"
            elif evidence.approval_status == ApprovalStatus.PROHIBITED:
                code = "prohibited_evidence"
            elif evidence.allowed_sections and section.name not in evidence.allowed_sections:
                code = "evidence_scope"
            elif claim.kind != evidence.kind:
                code = "claim_kind"
            elif not matches:
                code = "claim_not_in_body"
            elif evidence.kind == EvidenceKind.UNVERIFIED or evidence.approval_status == ApprovalStatus.UNVERIFIED:
                code, status = "unverified_evidence", "review_required"
            elif numbers and numbers != NUMBER.findall(mask_formatting(evidence.text)):
                code = "numeric_mismatch"
            else:
                # Each citation accounts for one occurrence. A repeated
                # assertion elsewhere in the body needs its own citation.
                for match in matches:
                    if match.span() not in spans:
                        spans.append(match.span())
                        break
                if evidence.approval_status == ApprovalStatus.PROPOSED:
                    issues.append(Issue("review_required", "proposed_evidence", section.name,
                                        f"{claim.evidence_id}: {claim.text}"))
                if statement != normalize(evidence.text):
                    code, status = "unsupported_wording", "review_required"
                else:
                    continue
            issues.append(Issue(status, code, section.name, f"{claim.evidence_id}: {claim.text}"))

        # Check the text outside valid claim spans without treating a whole
        # paragraph as one assertion or silently discarding qualifiers.
        cursor = 0
        for start, end in [*sorted(spans), (len(body), len(body))]:
            gap = factual_body[cursor:start].replace(MASK, " ").strip()
            if not CONNECTORS.fullmatch(gap):
                issues.append(Issue("review_required", "unverified_prose", section.name, gap))
            cursor = max(cursor, end)
        uncited_numbers = [
            match.group() for match in NUMBER.finditer(factual_body)
            if not any(start <= match.start() and match.end() <= end for start, end in spans)
        ]
        if uncited_numbers:
            issues.append(Issue("fail", "uncited_numeric", section.name,
                                f"Numeric content lacks a matching citation: {', '.join(uncited_numbers)}."))
    return issues
