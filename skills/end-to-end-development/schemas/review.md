# Review artifact (`review`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Round one uses `mode: full` and reviews the entire baseline-to-worktree state. New runs stop after that review and at most one fix batch. A resumed legacy run may schedule round two with `mode: verification` and exactly the assigned `verified_finding_ids`; it verifies the fix batch and affected hunks rather than repeating the whole review.

Each finding contains stable ID, category (`standards` or `spec`), severity, actionable flag, `disposition` (`must-fix` or `advisory`), optional requirement ID, path/line, summary, and concrete evidence.

- Critical and high actionable findings are always `must-fix`.
- Medium correctness/spec findings normally block; low findings normally remain advisory and are grouped into the report.
- Do not repeat style findings enforced by passing tooling.
- Check contract/plan conformance and complexity drift.
- Reviewers never edit project files.

Validate before returning:

```bash
python3 <validator_path> review <output_artifact>
```
