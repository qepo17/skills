# Worker result artifact (`result`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Used by implementation, validation, batched fixes, and pipeline fixes.

Required rules:

- Implementation copies the assignment's `packet_id` and exact sorted `task_ids` (one to three for standard/full; up to four for fast).
- A review-fix batch resolves every assigned `finding_id` in `resolutions`; one worker may resolve multiple compatible findings.
- `changed_files` is the complete sorted repository-relative inventory.
- Compute `tree_fingerprint` with `workflow_tools.py fingerprint <worktree>` after changes and checks.
- Every validation records ID, exact command/cwd, exit code, result, summary, log path, SHA-256 of the exact command, the result tree fingerprint, and `cache_status`. A `validate` result uses every exact ID from the assignment's `validation_ids`; it must not invent generic replacement IDs.
- `cache_status: reused` requires a hash-pinned `source_artifact`; use it only when command hash and tree fingerprint match passing evidence.
- Decisions have an ID, `kind`, summary, and evidence. Use `bounded-plan-deviation` only for a change that preserves requirements/contract, adds no mechanism, follows repository precedent, and stays within the packet concern.
- Full output stays in log files. `git.head` and `git.status_short_path` reflect the final worktree.

Validate before returning:

```bash
python3 <validator_path> result <output_artifact>
```
