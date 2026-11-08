# Challenge 6 | Evidence-grounded Grant Application Writer

Nonprofits have to answer different funders' questions using the same limited staff time. Each application needs the right field order, word limits, budget details, and defensible claims. Reworking a single failed answer should not require regenerating or reviewing the whole application.

**Synthetic data. Human review required. Not submission-ready.** Tidepath Family Alliance and the supplied opportunities, budgets, outcomes, and organizational facts are fictional challenge fixtures. No real nonprofit or applicant data is required.

## Demo video

[Download the English demo video (MP4, 2:32, 1080p)](https://raw.githubusercontent.com/da271224-ai/DevdayV2-Grant-Application-Writer/main/demo_video/demo.mp4). The video uses recorded TP-G01 results and an offline replay, with English narration and captions.

[Narration script](demo_video/narration_script.md) · [Storyboard](demo_video/storyboard.md)

## Workflow

1. **Load the grant.** Python reads the funder rules, narrative limits, and budget files into a `RequirementSpec`.
2. **Select evidence.** The `EvidencePack` links each claim source to an evidence ID, grant scope, and approval status. Organizational facts, proposed plans and targets, unverified material, and prohibited synthetic actuals are kept separate.
3. **Generate each field.** The Writer sends only relevant evidence and field constraints to the OpenAI Responses API. Structured Outputs separate applicant-facing prose, exact claim spans and evidence IDs, missing information, and reviewer notes.
4. **Validate independently.** `FactVerifier` checks evidence IDs, scope, claim type, and numeric consistency. `RequirementValidator` checks required fields, order, word limits, and budget consistency. A separate semantic review checks claim support, and coverage review identifies missing topics. Semantic results cannot override deterministic failures.
5. **Export for human review.** Markdown is an inspection draft. Fields containing recognized internal commentary, requests for missing information, or evidence metadata are marked `content_incomplete` and withheld from the Markdown draft. The structured JSON preserves the original body, claims, evidence mapping, and review. Reviewers confirm qualifications, plans, attachments, and inferred coverage before any use.
6. **Regenerate targeted fields.** A reviewer can retry one or more named fields against saved JSON. The other fields' content is retained and the merged application is reviewed again. Offline revalidation only reuses historical semantic results when the verifier version and input fingerprint match.

## Run from the project root

Use PowerShell with Python 3.10 or later. The demo, package inspection, offline revalidation, and tests need no API key. Install the development dependencies once to run the full suite, including tests that mock the OpenAI SDK.

```powershell
python -m pip install -r .\grant_application_writer\requirements-dev.txt
python -m pytest -q
python -m grant_application_writer.main
```

Read the [recorded TP-G01 demo](demo/tp-g01/README.md) or revalidate its final snapshot in a fresh output directory.

```powershell
$source = '.\demo\tp-g01\03-final\application_structured.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
python -m grant_application_writer.main --revalidate $source `
  --grant-dir .\grant-01-youth-mentoring --fact-sheet .\organization_fact_sheet.md `
  --output-dir ".\grant_application_writer\outputs\demo-replay-$stamp"
```

The replay writes a fresh review draft, report, and structured JSON. Exit code `0` means validation passed, `1` means a hard failure, and `2` means human review is required. The saved demo is expected to require human review.

### Optional live commands

These commands call the OpenAI API. They are not part of the offline demo. Set `OPENAI_API_KEY` in your local environment using your own credential. Keep credentials out of files, command examples, and Git. The example model names are configurable.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
python -m grant_application_writer.main --generate --max-fields 1 `
  --output-dir ".\grant_application_writer\outputs\tp-g01-single-field-$stamp" `
  --writer-model gpt-5-mini --verifier-model gpt-5-mini

$source = '.\demo\tp-g01\02-targeted-retry\application_structured.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
python -m grant_application_writer.main --application $source `
  --retry-fields "Qualifications & Sustainability" `
  --output-dir ".\grant_application_writer\outputs\tp-g01-retry-$stamp" `
  --writer-model gpt-5-mini --verifier-model gpt-5-mini
```

Omit `--max-fields` to generate every field. A single-field test uses separate `partial_test` output names. Use a fresh directory for each run. The CLI help is available via `python -m grant_application_writer.main --help`.

## Scope and limitations

- TP-G01 is the end-to-end demo. All ten mock grant packages can be loaded. Detailed field coverage rubrics are configured for TP-G01 and are inferred when full question wording is absent.
- Proposed evidence remains proposed. Missing facts, unconfirmed partnerships, and sustainability plans require applicant input. Candidate Plan Approval is outside this submission.
- Semantic review can disagree across runs. The final export guard detects known review-text patterns and does not establish that unflagged text is ready to submit.
- The project exports review artifacts. It does not submit applications to funders, verify real-world facts or attachments, or automate grant accounting and post-award reporting.
- The archived [original data bundle documentation](docs/DATA_BUNDLE.original.md) explains the fixture files. The [submission checklist](docs/SUBMISSION_CHECKLIST.md) covers the final handoff.

