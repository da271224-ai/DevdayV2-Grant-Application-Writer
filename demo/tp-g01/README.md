# TP-G01 Youth Mentoring | Recorded offline demo

**Synthetic data. Human review required. Not submission-ready.**

These are byte-for-byte copies of saved structured results from real API runs on fictional grant data. The walkthrough uses the archived results and does not rerun the API. Each JSON retains original candidate bodies, claims, notes, and review results, including failed content. Use the replay to see the current export protection.

| Stage | Recorded run | What to show |
| --- | --- | --- |
| [01 Initial generation](01-initial/application_structured.json) | `tp-g01-full-live` | Eight fields failed and one required review. Implementation and other fields included evidence IDs or review text in the draft. Financial Narrative was empty and recorded an API failure. The original JSON predates the top-level status field. |
| [02 Targeted retries](02-targeted-retry/application_structured.json) | `tp-g01-retry-remaining-20261108-124026` | Eight fields were `review_required`. Qualifications & Sustainability was the only failed field. Its review identified an unsupported capacity inference and a reviewer comment inside the body. |
| [03 Final targeted retry](03-final/application_structured.json) | `tp-g01-qualifications-retry-20261108-125539` | All nine fields had text and were `review_required`. The qualifications body retained sourced services and roles. The missing post-grant plan remained a human review item. |

## Walkthrough

1. In stage 01, open the `review` blocks for Implementation and Financial Narrative to show failures separate from the candidate text.
2. Compare the qualifications section in stages 02 and 03. The last retry targeted that field. The other eight field bodies were retained.
3. Run the offline replay below to produce a current guarded draft and review report. The saved stage 03 JSON remains intact. For any field flagged `content_incomplete`, the Markdown draft uses a placeholder and the structured JSON retains the original text, claims, and review. Highlight the remaining coverage and attachment checks.

```powershell
$source = '.\demo\tp-g01\03-final\application_structured.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
python -m grant_application_writer.main --revalidate $source `
  --grant-dir .\grant-01-youth-mentoring --fact-sheet .\organization_fact_sheet.md `
  --output-dir ".\grant_application_writer\outputs\demo-replay-$stamp"
```

Run from the project root. Exit code `2` means human review is required. The snapshots are intended for demonstration and review, never for submission to a funder.

The freeze replay returned `review_required` with no hard-failed fields. Export protection withheld Outreach & Engagement, Outcomes Measures, and Advancing Equity because their archived bodies still contain review text. This is a current export finding, not a change to the recorded stage 03 result.

