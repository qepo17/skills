# Worker result artifact (`result`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Used by implementation, validation, batched fixes, and pipeline fixes. For a stage that cannot finish, follow the [blocker contract](blockers.md) and prefer the typed `block` command.

For `execution_mode: artifact-repair`, initialization copies the original result. Repair only missing existing blocker classifications from the pinned evidence. Keep all other semantic fields unchanged, including status, outcomes, validations, blocker text, and IDs. Do not run tests or write project/Git/forge state. The graph pins the original assignment/output, evidence files, content, HEAD, branch, and index; any mutation or failed repair blocks rather than starting another source writer.

Required rules:

- Implementation copies the assignment's `packet_id` and exact sorted `task_ids` (one to three for standard/full; up to four for fast).
- A review-fix batch resolves every assigned `finding_id` in `resolutions`; one worker may resolve multiple compatible findings.
- `changed_files` is the complete sorted repository-relative inventory.
- The worker may leave assignment hash, `tree_fingerprint`, `git`, validation command hashes/fingerprints, and fresh-cache metadata at their skeleton values. The coordinator computes these mechanical fields at acceptance time.
- Every validation records ID, exact command/cwd, exit code, result, summary, and log path. Implementation, review-fix, pipeline-fix, and `validate` results cover every exact ID/command pair in their assignment. The final repository writer receives the complete planned suite, allowing the graph to skip a duplicate validation worker.
- `cache_status: reused` requires a hash-pinned `source_artifact`; use it only when command hash and tree fingerprint match passing evidence.
- Decisions have an ID, `kind`, summary, and evidence. Use `bounded-plan-deviation` only for a change that preserves requirements/contract, adds no mechanism, follows repository precedent, and stays within the packet concern.
- Full output stays in log files. The coordinator adds an authoritative acceptance-time Git snapshot and runs final schema validation after the worker settles.

Return after the semantic payload and logs are complete; do not spend a separate worker pass repairing coordinator-owned mechanical fields.
