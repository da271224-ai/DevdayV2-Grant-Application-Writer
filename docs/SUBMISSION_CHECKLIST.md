# Challenge 6 | Submission checklist

## Completed

- English project README with workflow, offline replay, and scoped live commands.
- Three recorded TP-G01 snapshots in [demo/tp-g01](../demo/tp-g01/README.md), from initial failures to the final `review_required` result.
- Final export protection with original bodies, claims, and review records preserved.
- Offline and Mock API tests, and an offline replay of the final demo.
- Credential-pattern scan and ignore rules for local keys, environment files, caches, and working outputs.

## Human checks before submission

- Run the README offline replay and confirm the draft and report are marked synthetic, human review required, and not submission-ready.
- Verify the demo links and include the three curated JSON snapshots. Keep local runs and personal data out of the handoff.
- In the actual submission repository, inspect staged filenames and diffs for credentials and unintended files. Scan Git history for secrets if history will be included. This workspace has no Git metadata to audit.
- Confirm that the hackathon submission presents the tool and recorded demo. The sample application remains a review draft.

## Known limitations

- TP-G01 is the demonstrated end-to-end workflow. Full coverage rubrics and end-to-end runs for the other nine grants remain outside this demo.
- Real qualifications, post-grant funding, partner commitments, and attachments require human verification. Automated coverage and export checks can miss cases.
- No portal submission, live applicant data, candidate plan approval, or post-award reporting is needed for this demo.

