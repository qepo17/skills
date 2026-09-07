# Review artifact (`review`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a review that cannot finish, follow the [blocker contract](blockers.md). Must-fix findings from a finished review are not stage blockers.

Round one uses `mode: full` and reviews the entire baseline-to-worktree state. New runs stop after that review and at most one fix batch. A resumed legacy run may schedule round two with `mode: verification` and exactly the assigned `verified_finding_ids`; it verifies the fix batch and affected hunks rather than repeating the whole review.

Version-1 delivery validates the review's canonical requirements/contract/plan provenance. The existing bounded fix policy does not create another independent round: later accepted fixes must hash-pin the review and unchanged approved meaning; validation/pipeline remediation also needs its authorized amendment. Report this as **historical review with accepted bounded revisions**, never as an independent review of the final tree. A scoped exclusion/restoration after review is likewise reported as **historical review with authorized policy amendments**, not review of the amended policy. The explicit authority may change only eligible supplemental obligations under the identical canonical requirements/contract/plan/approval basis. Changed canonical meaning or missing provenance blocks delivery and completion without resetting budgets.

Each finding contains stable ID, category (`standards` or `spec`), severity, actionable flag, `disposition` (`must-fix` or `advisory`), optional requirement ID, path/line, summary, and concrete evidence.

- Critical and high actionable findings are always `must-fix`.
- Medium correctness/spec findings normally block; low findings normally remain advisory and are grouped into the report.
- Do not repeat style findings enforced by passing tooling.
- Check repository standards and the original request/ticket/spec (including pinned `requirements.json.intake` source excerpts when present), not only contract/plan conformance and complexity drift. A plan that misinterprets the ticket is a spec defect even if every task was implemented. Trace original acceptance IDs through requirements, task validations, and observed code behavior; distinguish source facts/user decisions from agent recommendations.
- Reuse pinned source evidence rather than restart discovery or interview the user. Report unresolved material choices through decision blockers; workers cannot allocate another question budget or edit the source tracker.
- For validation-policy version 1, inspect every plan validation's semantic `purpose`, `gate`, and `rationale`; reject mandatory acceptance/repository/migration work presented as advisory or supplemental. Confirm every task retains blocking acceptance evidence.
- Review the effective policy and pinned exclusions supplied by the assignment. Preserve historical failures as failures and disclose advisory/excluded warnings, but do not recreate a must-fix finding solely because an eligible supplemental command is advisory or explicitly excluded. Exceptions never satisfy genuine acceptance, security, contract, or integration obligations.
- Reviewers never edit project files.
- A review that finished examining the assigned tree uses `status: complete`, including when it reports `must-fix` findings. Use `status: blocked` and `blockers` only when the review itself could not finish.
- `reviewed_status_path` contains only the exact final `git status --short` output for the assigned worktree; keep commentary and conclusions in the review artifact or separate logs.

Validate before returning:

```bash
python3 <validator_path> review <output_artifact>
```
