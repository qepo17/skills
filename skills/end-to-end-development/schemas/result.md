# Worker result artifact (`result`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Used by implementation, validation, batched fixes, and pipeline fixes. For a stage that cannot finish, follow the [blocker contract](blockers.md) and prefer the typed `block` command.

For `execution_mode: artifact-repair`, initialization copies the original result. Repair only missing existing blocker classifications from the pinned evidence. Keep all other semantic fields unchanged, including status, outcomes, validations, blocker text, and IDs. Do not run tests or write project/Git/forge state. The graph pins the original assignment/output, evidence files, content, HEAD, branch, and index; any mutation or failed repair blocks rather than starting another source writer.

For `execution_mode: packet-verification`, do not edit or replay source work. Independently inspect existing packet completion and compatibility with approved requirements/contract, including the pinned external repair/rebase. Add:

```json
"packet_verification": {
  "outcome": "compatible",
  "summary": "Concise factual packet/scope inspection conclusion.",
  "evidence_path": "/absolute/assigned/log_dir/scope.md",
  "evidence_sha256": null
}
```

The coordinator fills `evidence_sha256`. Outcomes are `compatible`, `material-change`, or `incomplete`. Only compatible fully present work can report complete; material/unfinished work must be blocked. Material change needs a decision blocker for normal replanning and renewed whole-bundle approval. Inventory exactly the recovery record's `changed_files` (preserved packet work plus authorized repairs), not invented verifier edits. Report every assigned check freshly in its canonical cwd with a new assignment-local log, null `source_artifact` and `cache_status: fresh`. No external or cached evidence is admissible. Complete factual reporting can include failed checks even on legacy runs, but **does not pass the recovery gate** or grant an automatic fix/retry. All historical evidence remains untouched.

Required rules:

- For an assignment with `validation_policy_version: 1`, return `status: complete` when the assigned source work and factual check reporting are finished, even when one or more checks failed. Return `blocked` only when the assigned work/reporting could not finish. Never omit a failed record, invent a passing result, or use a blocker solely because a command exited nonzero.
- Implementation copies the assignment's `packet_id` and exact sorted `task_ids` (one to three for standard/full; up to four for fast).
- A review-fix batch resolves every assigned `finding_id` in `resolutions`; one worker may resolve multiple compatible findings.
- `changed_files` is the complete sorted repository-relative inventory.
- The worker may leave assignment hash, `tree_fingerprint`, `git`, validation command hashes/fingerprints, and fresh-cache metadata at their skeleton values. The coordinator computes these mechanical fields at acceptance time.
- Every validation records ID, exact command/cwd, exit code, result, summary, and action-specific log path. Implementation, review-fix, validation-fix, pipeline-fix, and `validate` results cover every exact ID/command pair in a policy-version-1 assignment. A failed record has a nonzero exit code; `not-run` has a null exit code. The coordinator adds `log_sha256` at acceptance. Fresh logs must resolve beneath the assigned `log_dir`, not arbitrary files or symlinks outside it; paths are checked before hashing. Never overwrite an older action's log.
- `cache_status: reused` requires a hash-pinned `source_artifact`; use it only when command hash, canonical cwd, tree fingerprint, passing outcome, and original log path/hash match. The earlier log must remain within this repository's run log directory.
- Decisions have an ID, `kind`, summary, and evidence. Use `bounded-plan-deviation` only for a change that preserves requirements/contract, adds no mechanism, follows repository precedent, and stays within the packet concern.
- Full output stays in log files. The coordinator adds an authoritative acceptance-time Git snapshot and runs final schema validation after the worker settles.

The assignment already omits currently excluded checks, so do not execute them speculatively. Predeclared advisory checks that are assigned are still attempted and reported. Their failures remain `result: fail`; the engine turns them into warnings without a blocker or fix-budget charge. An exception is never a pass. If future current-tree evidence has no record because the command was excluded, the engine—not the worker—reports `not-run`/excluded and retains any historical failed artifact separately.

Return after the semantic payload and logs are complete; do not spend a separate worker pass repairing coordinator-owned mechanical fields.
