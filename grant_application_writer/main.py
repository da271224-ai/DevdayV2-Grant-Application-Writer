"""Inspect the fixture or validate a local application JSON file."""

import argparse
import json
import os
from contextlib import closing
from dataclasses import asdict
from decimal import InvalidOperation
from pathlib import Path

from .evidence_builder import build_evidence
from .fact_verifier import verify_facts
from .models import Application, Budget, Claim, EvidenceKind, Section
from .requirement_parser import money, parse_requirements
from .requirement_validator import validate_requirements


def load_application(path: Path) -> Application:
    return parse_application(read_payload(path))


def read_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=str)


def parse_application(payload: dict) -> Application:
    budget = payload["budget"]
    sections = tuple(
        Section(
            section["name"], section["body"],
            tuple(Claim(claim["text"], EvidenceKind(claim["kind"]), claim["evidence_id"])
                  for claim in section.get("claims", ())),
            tuple(section.get("missing_information", ())),
            tuple(section.get("generation_notes", ())),
            tuple(section.get("required_information_gaps", ())),
            tuple(section.get("recommendations_for_review", ())),
        )
        for section in payload["sections"]
    )
    return Application(
        payload["grant_id"], sections,
        Budget({name: money(value) for name, value in budget["categories"].items()},
               money(budget["total"]), budget["currency"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    parser.add_argument("--grant-dir", type=Path, default=root / "grant-01-youth-mentoring")
    parser.add_argument("--fact-sheet", type=Path, default=root / "organization_fact_sheet.md")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--application", type=Path, help="Validate an application JSON file.")
    mode.add_argument("--generate", action="store_true", help="Generate a draft using the OpenAI API.")
    mode.add_argument("--revalidate", type=Path, help="Revalidate a saved draft offline and export a new review.")
    parser.add_argument("--retry-fields", nargs="+", metavar="FIELD",
                        help="Regenerate only these exact field names in the --application input.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-fields", type=int, help="Generate at most this many fields for a partial test.")
    parser.add_argument("--writer-model", default=os.getenv("OPENAI_WRITER_MODEL"))
    parser.add_argument("--verifier-model", default=os.getenv("OPENAI_VERIFIER_MODEL"))
    args = parser.parse_args()
    if args.max_fields is not None and (not args.generate or args.max_fields < 1):
        parser.error("--max-fields requires --generate and a positive integer.")
    if args.retry_fields and not args.application:
        parser.error("--retry-fields requires --application.")
    try:
        spec = parse_requirements(args.grant_dir)
        pack = build_evidence(args.grant_dir, args.fact_sheet, spec)
        if args.generate or args.revalidate or args.retry_fields:
            from .application_revalidation import regenerate_fields, retry_field_specs, revalidate_application
            from .application_writer import generate_application
            from .review_exporter import export_review, review_status

            if not args.output_dir:
                parser.error("An output directory is required.")
            source = args.revalidate or args.application
            if source:
                if args.output_dir.resolve() == source.resolve().parent or (
                    args.output_dir.exists() and any(args.output_dir.iterdir())
                ):
                    parser.error("Use a new or empty output directory separate from the saved application.")
                payload = read_payload(source)
                generated = revalidate_application(parse_application(payload), payload, spec, pack)
            if not args.revalidate:
                if args.retry_fields:
                    retry_field_specs(generated, spec, args.retry_fields)
                if not all((args.writer_model, args.verifier_model, os.getenv("OPENAI_API_KEY"))):
                    parser.error("Generation requires both model names and OPENAI_API_KEY.")
                try:
                    from openai import OpenAI
                except ImportError:
                    parser.error("Install grant_application_writer/requirements.txt to generate a draft.")
                with closing(OpenAI(max_retries=0, timeout=60.0)) as client:
                    if args.retry_fields:
                        generated = regenerate_fields(
                            client, args.writer_model, args.verifier_model, generated, spec, pack, args.retry_fields,
                        )
                    else:
                        generated = generate_application(
                            client, args.writer_model, args.verifier_model, spec, pack, max_fields=args.max_fields,
                        )
            export_review(args.output_dir, generated, spec, pack, exclusive=bool(source))
            status = review_status(generated, spec)
            result = {
                "status": status, "mode": generated.mode, "output_dir": str(args.output_dir),
                "failed_fields": [field.section_name for field in generated.fields
                                  if any(issue.status == "fail" for issue in field.deterministic + field.semantic)],
            }
            exit_code = {"pass": 0, "fail": 1, "review_required": 2}[status]
        elif args.application is None:
            result = {"requirements": asdict(spec), "evidence": asdict(pack)}
            exit_code = 0
        else:
            application = load_application(args.application)
            issues = validate_requirements(application, spec) + verify_facts(application, pack)
            status = "fail" if any(issue.status == "fail" for issue in issues) else (
                "review_required" if issues else "pass"
            )
            result = {"status": status, "issues": [asdict(issue) for issue in issues],
                      "warnings": spec.warnings, "attachments_to_review": spec.attachments}
            exit_code = {"pass": 0, "fail": 1, "review_required": 2}[status]
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, InvalidOperation) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
