# Run amendment artifact (`run-amendment`)

Run amendments are coordinator-only, immutable policy/remediation decisions for runs pinned to `validation_policy_version: 1`. Workers never create them. Submit the request through:

```bash
"$ORCHESTRATOR" amend "$RUN_DIR" --input /absolute/decision.json
```

Runs without the version pin remain legacy and reject `amend` without creating or changing run, agent, event, assignment, checkpoint, or recovery state. There is no migration, retrofit, or upgrade command.

## Exact request

The input object must contain exactly these fields:

```json
{
  "kind": "validation-exception",
  "decision": "exclude",
  "repo_id": "api",
  "target": "local",
  "check_ids": ["API-VAL-004"],
  "authority": "user",
  "text": "Exclude API-VAL-004 from this run.",
  "rationale": "The user explicitly accepted the scoped supplemental risk.",
  "expected_context": "64-character-sha256-from-current-status",
  "evidence": []
}
```

Common rules:

- `repo_id` names one repository in the run. `check_ids` is a non-empty, sorted, unique list.
- `expected_context` is the exact repository context hash returned by current `status`; never invent or refresh it merely to accept a stale decision.
- Every `evidence` item is an existing hash-pinned `{ "path": "/absolute/path", "sha256": "..." }` reference. Decision evidence must be captured inside the run and contain no secrets.
- `rationale` records the scoped reason. It is not a check result or user authentication.

Supported combinations are deliberately narrow:

| `kind` | `decision` | `target` | `authority` | `text` | Additional rule |
| --- | --- | --- | --- | --- | --- |
| `validation-exception` | `exclude` | `local` | `user` | Exact non-null user wording | Every ID is supplemental and non-migration. |
| `validation-exception` | `restore` | `local` | `user` | Exact non-null user wording | Every ID has an active exclusion. |
| `check-remediation` | `fix-related` | `local` or `ci` | `coordinator` | `null` | Non-empty reviewed evidence and rationale establish task relatedness, approved scope, current failure, and remaining budget. |
| `validation-retry` | `retry-interrupted` | `local` | `user` | Exact non-null authorization wording | One validation-only retry per repository/run; additional interruption attestation below. |

Acceptance, repository-required, and migration-capable checks are protected regardless of user wording. A validation exception never targets CI. CI check identities are `name@app_id`, or `name@*` when the required policy has no app ID. Unknown or unrelated red local/CI checks do not authorize source work. Unchanged files or a worker assertion alone do not prove a failure was pre-existing.

## Interrupted validation-only retry

This is not an exception or another source fix. It handles a **complete, accepted `validation-fix`** result after the existing source-fix allowance is exhausted, whose current local gate in `implement` or `validate` is blocked by exactly one required command interrupted by an enclosing harness timeout. Unfinished/unaccepted workers use their existing settlement paths instead.

Use the common fields above with `kind: validation-retry`, `decision: retry-interrupted`, `target: local`, `authority: user`, verbatim authorization in `text`, and exactly one additional field:

```json
"interruption": {
  "kind": "enclosing-harness-timeout",
  "harness_exit_code": 124,
  "child_exit_code": null
}
```

The coordinator must read and explicitly attest the distinction between a harness timeout and a child assertion/exit. **Exit 124 alone is not proof**; the schema checks this reviewed attestation, not arbitrary log prose. `evidence` must include the current accepted source artifact and every selected interrupted log with their acceptance-time hashes, plus any separate harness transcript needed to substantiate the rationale. Do not invent an unknown child outcome when a child exit was observed. All selected records must currently be failed/non-excluded with recorded harness outcome 124 and belong to the matching typed local gate. Protected checks may be retried but never waived.

Apply without launching, inspect, then resume through the graph:

```bash
"$ORCHESTRATOR" amend "$RUN_DIR" --input /absolute/retry.json --no-drive
"$ORCHESTRATOR" status "$RUN_DIR"
"$ORCHESTRATOR" resume "$RUN_DIR"
```

`--no-drive` is also available for other amendments. It records the guarded decision only; it does not advance the checkpoint or construct/launch worker assignments. Repeating the same request is idempotent, not another retry.

A retry enters `pending_validation_refresh`. The graph creates a separate `validate` assignment with no project/Git/forge writes and claims it durably in `validation_retry_attempts` before launch. No source-fix budget is spent or reset. The claim cannot be replenished by another request, source change, rejection, timeout, or crash. Reconciliation may accept the original settled/cleaned verifier; an unaccepted claimed verifier cannot be replaced or relaunched automatically.

Selected commands must execute freshly once each with new logs, adequate **individual** tool timeouts, approved guarded launchers, and confirmed private disposable storage. Never put a long suite batch under one short enclosing timeout. Other passing observations may be reused only from the pinned current source artifact with matching ID/exact command/cwd/tree/log hashes. The new artifact still covers all effective checks; broader passing commands cannot substitute for a targeted check. Source/HEAD/branch/index must remain identical through acceptance. Original source assignment and validation-log hashes are rechecked on every subsequent run validation, not just at authorization. An accepted unfinished verifier retains its pending refresh obligation so ordinary environment resume cannot create another validation attempt. Fresh failures remain blocking, old failures/logs stay immutable, and implementation/review/integration/delivery still require their usual evidence.

## Immutable artifact

After validating the request and current context, the engine creates `run-amendment-vN.json` with this shape:

```json
{
  "schema_version": 1,
  "artifact_kind": "run-amendment",
  "run_id": "20260817T083000Z-rate-management",
  "created_at": "2026-08-17T10:00:00Z",
  "kind": "validation-exception",
  "decision": "exclude",
  "repo_id": "api",
  "target": "local",
  "check_ids": ["API-VAL-004"],
  "authority": "user",
  "text": "Exclude API-VAL-004 from this run.",
  "rationale": "The user explicitly accepted the scoped supplemental risk.",
  "request": {
    "kind": "validation-exception",
    "decision": "exclude",
    "repo_id": "api",
    "target": "local",
    "check_ids": ["API-VAL-004"],
    "authority": "user",
    "text": "Exclude API-VAL-004 from this run.",
    "rationale": "The user explicitly accepted the scoped supplemental risk.",
    "expected_context": "64-character-sha256-from-current-status",
    "evidence": []
  },
  "request_sha256": "sha256-of-canonical-original-request",
  "basis": {
    "requirements_sha256": "64-character-sha256",
    "contract_sha256": null,
    "plan_sha256": "64-character-sha256",
    "review_sha256": "64-character-sha256"
  },
  "review": {"path": "/absolute/run/plan-review-v1.md", "sha256": "64-character-sha256"},
  "repository_state": {
    "fingerprint": "64-character-sha256",
    "head": "40-or-64-character-git-object-id",
    "branch": "feat/task",
    "index_sha256": "64-character-sha256"
  },
  "source_artifact": {"path": "/absolute/run/repos/api/implementation-api-packet-001-1.json", "sha256": "64-character-sha256"},
  "delivery_artifact": null,
  "evidence": [
    {"path": "/absolute/run/amendment-evidence/request-sha/log-sha.log", "sha256": "64-character-sha256"}
  ]
}
```

The flattened decision fields must exactly match the original request. `request_sha256` hashes that full original request, including `expected_context` and original evidence references. The artifact stores immutable snapshots of selected request evidence plus relevant validation or CI logs; these are decision-time evidence, not retroactive acceptance-time proof. `review`, `source_artifact`, and `delivery_artifact` are nullable hashed references as applicable. `basis` and `repository_state` bind the approved meaning and selected worktree evidence. The maximum size is 64 KiB, enforced before any snapshot or intent is persisted. Under the transaction, every selected evidence file is read once and matched against its reviewed/acceptance-time hash; those exact bytes become the snapshot.

The engine appends `{path, sha256}` to `run.json.run_amendments`. A `fix-related` decision is also placed in `pending_check_remediations`; a restoration that needs new evidence or an interrupted-validation retry is placed in `pending_validation_refresh`. The graph consumes those references through its existing bounded validation/pipeline paths. The coordinator does not author the resulting assignment or choose its phase.

## Preconditions, effects, and lifetime

A new decision requires an active versioned run, approved current plan bundle, settled graph cursor, no pending actions or writer leases, cleaned worker handles, unchanged repository content/HEAD/branch/index, and current accepted source/delivery evidence when required. It cannot complete unfinished worker work. The entire target set is accepted or rejected atomically; a valid decision may be recorded while another blocker remains, but never clears or edits that blocker.

An exclusion changes only future policy disposition/execution for the named checks. Historical observations and logs remain immutable: a failed check stays `fail`. When a later tree has no observation because the excluded command was omitted, status reports `not-run`/excluded with the amendment reference. Required checks continue to execute. Predeclared advisory warnings need no amendment, never block, and never spend a fix allowance.

An exclusion survives source-only changes within the same approved context even though those changes invalidate check observations. It expires when the requirements, contract, plan/review bundle, check command/cwd, or explicit restoration changes its meaning. Restoration creates fresh validation-only work if needed; it does not replay implementation or reset a budget. A `fix-related` decision uses the existing single validation-fix or pipeline-fix allowance and no more.

The same canonical request is idempotent and returns `already-applied`, including after projection, completion, restoration, or a post-application crash; it never reactivates old intent. A matching pre-projection orphan file may be reused, but a conflicting orphan or stale context is rejected without overwrite. New decisions are rejected after run completion.

An amendment never creates a check pass, erases a failed observation, overwrites an action log, weakens required-head/check-policy safeguards, waives CI, changes plan approval, replans work, resets retries, or grants the coordinator permission to edit source.
