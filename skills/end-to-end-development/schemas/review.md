# Review artifact (`review`)

Before any work, read [SKILL.md — Validation rules](../SKILL.md#validation-rules). It contains the shared limits, required fields, evidence rules, and role boundaries; this file is a stage-specific reminder.

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a review that cannot finish, follow the [blocker contract](blockers.md). Must-fix findings from a finished review are not stage blockers.

Round one uses `mode: full` and reviews the entire baseline-to-worktree state. New runs stop after that review and at most one fix batch. A resumed legacy run may schedule round two with `mode: verification` and exactly the assigned `verified_finding_ids`; it verifies the fix batch and affected hunks rather than repeating the whole review.

Each finding contains stable ID, category (`standards` or `spec`), severity, actionable flag, `disposition` (`must-fix` or `advisory`), optional requirement ID, path/line, summary, and concrete evidence.

- Critical and high actionable findings are always `must-fix`.
- Medium correctness/spec findings normally block; low findings normally remain advisory and are grouped into the report.
- Do not repeat style findings enforced by passing tooling.
- Check contract/plan conformance and complexity drift.
- Reviewers never edit project files.
- A review that finished examining the assigned tree uses `status: complete`, including when it reports `must-fix` findings. Use `status: blocked` and `blockers` only when the review itself could not finish.
- `reviewed_status_path` contains only the exact final `git status --short` output for the assigned worktree; keep commentary and conclusions in the review artifact or separate logs.

Follow the shared semantic preflight before returning. When mechanical metadata is ready, validate; otherwise report normalization pending and leave mandatory normalization/final validation to the graph:

```bash
python3 <validator_path> review <output_artifact>
```
