# Explicit external-repair recovery (coordinator only)

`recover-external-repair` is an opt-in compatibility transition for a **rejected, blocked implementation result** whose only schema defect is an overlong `next_action`, with genuine code/check failures, followed by a separately authorized external test-fixture repair and optional forward base update. It is not artifact correction, validation exclusion, source-remediation permission, plan approval, or acceptance of external passing logs. LangGraph remains the sole workflow engine. Never mutate the rejected JSON, run/agent/event projections, assignments, accepted artifacts, or SQLite cursor manually.

## Authority and reviewed request

First inspect the original rejection, failed checks, preservation evidence, external source authorization, and current canonical approval **read-only**. Preserve the exact external authorization wording in `external_authorization.text`, with non-secret hashed evidence for that authorization. Coordinator interpretation belongs only in `--context`. A later user must explicitly authorize recovery of the exact reviewed request; pass their affirmative wording via `--text`. Generic continuation, negation, or qualified approval is refused. Do not substitute the earlier permission to repair source for permission to advance the workflow.

Prepare this exact request shape outside the live run's mutable workflow files:

```json
{
  "run_id": "the-existing-run-id",
  "repo_id": "core",
  "blocker_id": "the-exact-rejection-blocker-id",
  "expected_run_sha256": "SHA256 of the reviewed run.json bytes",
  "result": {"path": "/absolute/rejected-result.json", "sha256": "reviewed SHA256"},
  "assignment": {"path": "/absolute/original-assignment.json", "sha256": "reviewed SHA256"},
  "rejection": {"path": "/absolute/supervisor/manifest.json", "sha256": "reviewed SHA256"},
  "transition": {
    "before_head": "original baseline commit object ID",
    "before_tree": "Git tree object ID proving the rejected content fingerprint",
    "after_head": "reviewed current commit object ID",
    "after_tree": "reviewed current content tree object ID",
    "target_ref": "refs/remotes/origin/main",
    "repair_paths": ["internal/api/server/example_test.go"]
  },
  "external_authorization": {
    "text": "Verbatim user authorization of the external rebase and test-only repair.",
    "evidence": [{"path": "/absolute/preserved-source-authorization.md", "sha256": "reviewed SHA256"}]
  },
  "reviewed_evidence": [
    {"path": "/absolute/preserved-evidence-file", "sha256": "reviewed SHA256"}
  ],
  "database_target": {"path": "/absolute/run/repos/core/database-target.json", "sha256": "reviewed SHA256"}
}
```

`reviewed_evidence` must include the original result, assignment, rejection manifest, approved review bundle, every historical accepted artifact and assignment in every repository and globally, and every file referenced by their `evidence_path`, `log_path`, `status_short_path`, and reused `source_artifact` fields, including the rejected result's evidence and existing run-local absolute files cited by `decisions[*].evidence`. Also include reviewed external preservation/scope reports, source manifests/patches, and relevant logs. Existing unpinned logs are **review-time preservation evidence**, never retroactive accepted-time proof. The command refuses missing or changed hashes; it does not silently collect replacements. Mutable `run.json`, `agents.json`, `events.jsonl`, and SQLite files cannot be referenced as immutable files. `expected_run_sha256` instead binds the decision-time projection, including exact approval text, requirements/contract/plan/challenge hashes, accepted references, blockers, budgets, and pending work. The immutable recovery record separately preserves the entire old approval and blocker.

`database_target` is null only when the canonical plan has no migration-capable checks. Otherwise it must equal the run's current hash-pinned `isolated-test` or `isolated-local` evidence. Reconfirm its applicability on the repaired tree before reviewing the request; record safe classification evidence, never URLs or credentials. The fresh worker must independently check the target before running migration-capable commands. No recovery command accesses a database, authorizes a destructive command, or copies `.env`.

Capture the request digest **when reviewing**, using SHA-256 of Python `json.dumps(request, sort_keys=True, separators=(",", ":")).encode()` (canonical JSON, not formatted file bytes). Keep this digest separate from later coordinator interpretation. Never recompute a digest, tree, or approval merely to make stale authorization pass. Submit only after the later explicit recovery authorization:

```bash
"$ORCHESTRATOR" recover-external-repair "$RUN_DIR" \
  --input "$REVIEWED_RECOVERY_REQUEST" \
  --request-sha256 "$REVIEWED_REQUEST_SHA256" \
  --text "$EXACT_USER_RECOVERY_AUTHORIZATION" \
  --context "$COORDINATOR_INTERPRETATION" \
  --worker-runtime auto
```

## Source proof and deliberately unsupported transitions

The before tree must be an existing Git tree object whose v3 fingerprint is exactly `SHA256(b"end-to-end-development-content-v3\0" + tree_oid.encode())`, matching the **unchanged rejected result**. Its HEAD must equal both the rejected HEAD and the original recorded baseline. Normal content fingerprinting writes tree objects to the Git object store; preserve these historical objects and source backups. A missing/pruned before tree is an evidence blocker, not permission to manufacture a replacement baseline.

The after tree must match the current content fingerprint, HEAD, unchanged branch and unstaged index. The explicit remote-tracking target must still equal the reviewed after HEAD. The before HEAD must be its ancestor. The command never fetches, rebases, commits, checks out, stages, or updates refs. It compares Git entries across before/after content and before/after HEAD:

- untouched upstream paths retain the exact pre-repair task content and modes;
- paths without local changes receive exactly the new upstream entries;
- overlapping regular non-executable text paths must reproduce a clean three-way merge of old task content, old base, and new base, byte-for-byte;
- only the exact sorted `repair_paths` may differ beyond that merge. Each must be an actually changed regular test file (`*_test.go`, `test_*.py`, or `*.test/spec.[cm]?[jt]sx?`). Test naming is not semantic proof: the fresh worker also audits fixture-only scope and unchanged production/contract behavior.

Rewritten task commits, branch drift, staged changes, active Git operations/locks, submodules, conflicting/nontrivial merge resolutions, repairs overlapping a three-way merge, and non-test repairs are unsupported. Stop for explicit normal planning/review rather than widening this transition. Other repositories must retain their recorded source bindings, with no hidden unresolved latest source result.

## Graph action, gates and crash behavior

Admission requires one exact decision rejection, a settled LangGraph cursor, no pending actions/decisions/writer leases, and closed/cleaned agent and supervisor handles. All canonical plans and the current user approval must match. The original result must report all exact assigned `(id, command, cwd)` checks and have code blockers with genuine failed validation. Probing the schema with a short in-memory hint does not edit or accept the old result.

The engine writes immutable `external-repair-<action-hash>.json` (at most 128 KiB) and atomically appends its reference to `run.external_repair_recoveries`. It clears only the identified rejection by refusing any unrelated unresolved outcome. It accepts no source work at admission. The record pins the request digest, exact recovery authorization, separately labelled coordinator context, prior approval/blocker, all repository states, and the preserved packet/repair file inventory.

Before any ordinary packet scheduling, the implement node creates one new `execution_mode: packet-verification` assignment. It retains the original packet/tasks/check IDs/commands, pins the recovery record and canonical inputs, gives all repositories read-only scope, denies project/Git/forge writes, and uses medium reasoning under an already pinned stage-v1 policy. It freshly checks the current packet and source-transition scope, runs the original assigned checks in their canonical cwd, and writes a new result and action-specific logs. No external or reused log is accepted. All subsequent newly created action/replacement logs are also isolated for recovered legacy runs; existing assignments and policies are unchanged.

Only a new compatible, complete verification result **with every assigned check passing** admits the affected packet as completed. Real failures are accepted as factual new evidence and remain blocked: this one-shot recovery does not automatically repair, waive, or retry them, including on legacy runs. Dependent/remaining approved packets resume normally; final full-plan validation still runs or requires current full-suite evidence. Independent baseline-to-current review, required integration, delivery/CI, and completion audits remain mandatory. Source drift after admission or verification acceptance is refused; later source changes must be attributable to accepted ordinary workflow writers. Original failures, rejected status, assignments, approval history, baselines, and every retry allowance remain unchanged.

A material scope/contract discovery is a new accepted **blocked decision result**, not a compatible verification. Resolve it through normal `replan-decision` if its existing revision allowances permit, then obtain renewed whole-bundle approval before any source writer. Exhausted planning budgets remain exhausted; recovery never grants an extra revision.

`run.external_repair_attempts` pins the new assignment before launch. A crash before the projection write may reuse only identical immutable recovery intent. Repeating an applied request is a read-only `already-applied` response, including after a later blocker or completion; conflicting authorization fails. Use ordinary `run`/`resume` to continue a committed transition. Reconcile adopts an already launched worker and accepts valid captured output once; it never replays the rejected source writer. A claimed verification with missing/invalid evidence is conservatively blocked without relaunch or replacement. Unclaimed pre-existing output cannot substitute for a fresh worker. Acceptance-to-projection crashes reuse accepted verification. Historical and fresh scope/check hashes remain checked on subsequent run loads.

Do not install an updated skill or apply this transition to a live run without separate authorization. Synthetic tests use only disposable Git repositories and injected worker responses; never use a live run as a mutable fixture or access real databases.
