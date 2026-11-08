# Narration script

**OpenAI DevDay Hackathon — Challenge 6**

English narration. Recorded generation snapshots and an offline validation replay. Synthetic data.

## 01 · Grant Application Writer

Nonprofits must tailor the same project to different funders, often with limited staff time.

Grant Application Writer turns funder rules and sourced evidence into drafts that a human can review.

## 02 · Turn funder rules into checks

The project loads ten synthetic grant packages. For this demo, we use TP G zero one, a youth mentoring proposal.

The parser reads field limits and budget files: nine application fields and a proposed budget of seventy-five thousand dollars.

## 03 · Every claim has a source

The writer uses field-specific evidence and returns the application text separately from claim references and reviewer notes.

Here, sixty Miami-Dade County children is proposed reach. The evidence ID preserves that distinction from a reported outcome.

## 04 · Two independent checks

The fact verifier checks citations, evidence scope and numbers. A separate semantic review asks whether the source supports the claim.

The requirement validator checks field order, word limits and budget consistency. Semantic review cannot override a deterministic failure.

## 05 · Failures are visible

In the initial recorded generation, eight fields failed validation and one required review.

Some drafts included internal review text or evidence identifiers. The financial narrative was empty after a recorded API error.

## 06 · Fix the field that failed

After targeted retries, qualifications and sustainability was the only remaining failed field. It inferred capacity that the evidence did not establish.

The final retry retained documented services and roles. The other eight field bodies were unchanged, and the sustainability plan still needed review.

## 07 · No hard failures. Review remains.

The offline replay revalidates the saved draft without calling the API. The current result is review required, with an empty failed-fields list.

All nine fields have saved text. The export guard withholds three from the Markdown draft because they still contain review text.

## 08 · Keep the audit trail

Reviewers can inspect the original body, claims and findings in the structured export. Missing plans, commitments and attachments remain visible.

This is synthetic data and an application draft. It requires human review before any submission.

## 09 · Replay the demo on GitHub

The public repository includes the code, tests, and three recorded snapshots. The offline demo runs without an API key.

