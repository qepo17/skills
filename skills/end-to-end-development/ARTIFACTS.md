# End-to-End Development Coordinator Artifact Contract

This file is normative for the LangGraph control plane. The graph is the only executable state machine and the only writer of coordinator state after initialization. Workers read the stage-specific file under [`schemas/`](schemas/) and its linked [blocker contract](schemas/blockers.md), initialized from their immutable assignment with:

```bash
python3 "$SKILL_DIR/scripts/artifact_guard.py" init <assignment-path>
```

Validate every artifact before acceptance:

```bash
python3 "$SKILL_DIR/scripts/artifact_guard.py" <kind> <artifact-path>
```

## General rules

- JSON is UTF-8, two-space indented, newline-terminated, and uses `schema_version: 1`.
- Every JSON artifact has `artifact_kind` and `run_id`.
- Worker artifacts bind `assignment_path` and its actual `assignment_sha256`.
- Timestamps are UTC RFC 3339 (`2026-08-17T08:30:00Z`).
- Repository IDs match `^[a-z0-9][a-z0-9-]*$`; requirement IDs look like `REQ-001`.
- Paths to repositories, worktrees, artifacts, and logs are absolute. Changed source paths are repository-relative and contain no `..`.
- Unordered arrays are sorted by stable ID/path. Accepted artifacts are immutable; a retry writes a new file.
- Only `run.json`, `agents.json`, `langgraph.sqlite`, and active `supervisor/worker-*.json` lifecycle records are mutable. JSON projections use a sibling temporary file and atomic rename. `events.jsonl` and supervisor batch logs are append-only. Worker records become settled evidence after cleanup. The SQLite checkpoint stores the execution cursor; `run.json.phase` remains the canonical phase projection used by reconciliation and routing.
- JSON contains concise facts, commands, exit codes, hashes, and evidence paths—not secrets, environment values, full diffs, source files, or command output.
- A complete artifact has no blockers. A blocked artifact has at least one blocker. For policy-version-1 result/review artifacts, `complete` means the assigned work and factual reporting finished; it does not assert that every observed check passed or every finding is advisory.
- Older schema-v1 runs without profile fields remain valid and behave as legacy `full` runs when resumed.
- New fast/standard runs set `workflow_policy.user_plan_approval_required: false`; full sets it to `true`. Every run still records an approved hash-pinned bundle before project-file work. On resume, omission of this key in an older profiled run is treated as approval-required for backward safety.
- New runs pin `validation_policy_version: 1`, `delivery_policy_version: 1`, `worker_reasoning_policy: stage-v1`, `retry_limits.artifact_repairs_per_action: 1`, and repository `delivery_executor` (`github-command` or `worker`), `delivery_repository`, `delivery_evidence_version: 2`, and `delivery_check_timeout_seconds` (0–1800). Missing policy versions preserve the entire legacy validation/recovery/delivery path. Unknown versions fail. Never infer, retrofit, migrate, or mutate a policy on an existing run.
- Accepted output is never re-normalized or relaunched. A retained/unsettled handle prevents replacement, even if an output file exists; recover the original backend identity rather than overwriting its lifecycle record. The only unavailable-reference quarantine is the explicitly authorized [writer-incident transition](schemas/writer-incident-recovery.md), which preserves the original reference and never converts overwritten bytes to accepted evidence.
- Before first acceptance, the coordinator normalizes mechanical evidence (`assignment_sha256`, Git HEAD/status, content fingerprint, command hashes, and policy-version-1 validation `log_sha256`). Workers remain responsible for semantic conclusions, command execution results, findings, and blockers. Every action has its own log directory; a later action never overwrites an older log.

## Directory layout

```text
<run-dir>/
├── request.md
├── requirements.json                   # includes optional immutable source intake/question history
├── logs/clarifications.md               # optional append-only coordinator interaction ledger; not gate evidence
├── run.json
├── agents.json
├── events.jsonl
├── langgraph.sqlite                     # durable graph cursor and interrupts
├── .orchestrator.lock                   # cross-process projection lock
├── .orchestrator-execution.lock         # one graph invocation per run
├── metrics.json                         # generated at completion
├── assignments/<action-id>.json
├── plan-review-vN.md                    # complete hash-pinned plan-decision bundle
├── plan-feedback-vN.json                # exact user-requested revision basis
├── decision-replan-vN.json              # preserved implementation decision/approval/work evidence
├── external-repair-<action-hash>.json    # explicit rejected-packet source transition; not a pass
├── logs/incidents/writer-recovery-*/*   # immutable incident quarantine, history and live cleanup proof
├── run-amendment-vN.json                # scoped validation/remediation decision
├── amendment-evidence/<request-sha>/*   # immutable decision-time log snapshots
├── profile-escalation-*.json            # deterministic escalation evidence
├── contract-vN*.json                    # coordinated multi-repository runs only
├── integration-*.json                   # when policy requires it
├── report-*.json                        # when policy requires it
├── supervisor/manifest-*.json           # graph-consumed batch manifests
├── supervisor/worker-*.json             # durable backend handles for recovery
├── supervisor/batch-*.jsonl             # append-only batch outcomes
├── supervisor/status/*.json             # direct/tmux process exit status
├── supervisor/logs/*                     # bounded worker stdout/stderr evidence
└── repos/<repo-id>/
    ├── initial-status.txt
    ├── database-target.json             # migration-capable checks only; no secrets
    ├── plan-vN*.json
    ├── design-challenge-vN.json         # only when plan requires it
    ├── implementation-<packet-id>-N.json
    ├── validation-N.json
    ├── validation-fix-batch-N.json
    ├── review-1.json
    ├── fix-1-batch-N.json
    ├── review-2.json                    # legacy two-round runs only
    ├── fix-2-batch-N.json               # legacy two-round runs only
    ├── delivery-N.json
    └── logs/
```

Omit conditional files; never create empty placeholders.

## Common blocker

```json
{
  "id": "BLOCK-001",
  "kind": "decision|environment|authentication|permission|infrastructure|dependency|code",
  "summary": "What prevents the gate from passing.",
  "evidence_path": "/absolute/existing/evidence.log",
  "required_action": "Exact user, external, or subsequent-stage action."
}
```

## `run.json` (`run`)

The LangGraph control plane is the sole writer after initialization. New runs record an explicit profile and executable policy:

```json
{
  "schema_version": 1,
  "artifact_kind": "run",
  "run_id": "20260817T083000Z-rate-management",
  "created_at": "2026-08-17T08:30:00Z",
  "updated_at": "2026-08-17T08:31:00Z",
  "status": "working",
  "phase": "plan",
  "validation_policy_version": 1,
  "delivery_policy_version": 1,
  "profile": "standard",
  "profile_reasons": ["single-repository change with no declared high-risk surface"],
  "risk_flags": [],
  "workflow_policy": {
    "contract_required": false,
    "design_challenge": "risk-only",
    "integration_required": false,
    "report_required": false,
    "max_tasks_per_packet": 3,
    "max_packet_minutes": 45,
    "second_review": "never",
    "blocking_severities": ["critical", "high", "medium"],
    "coordinator_attempt_budget": 30,
    "auto_resume": true,
    "user_plan_approval_required": false
  },
  "worker_execution": {
    "schema_version": 1,
    "backend": "direct",
    "runtime": "pi",
    "detected_from": "fallback",
    "evidence": {}
  },
  "request_path": "/absolute/run/request.md",
  "request_sha256": "64-character-sha256",
  "requirements_path": "/absolute/run/requirements.json",
  "requirements_sha256": "64-character-sha256",
  "contract_path": null,
  "contract_sha256": null,
  "plan_review": null,
  "run_amendments": [],
  "pending_check_remediations": {},
  "pending_validation_refresh": {},
  "retry_limits": {
    "worker_replacements_per_stage": 1,
    "artifact_repairs_per_action": 1,
    "contract_revisions": 1,
    "plan_revision_cycles": 1,
    "validation_fix_cycles": 1,
    "review_rounds": 1,
    "pipeline_fix_cycles": 1
  },
  "repositories": {
    "api": {
      "root": "/absolute/source/api",
      "worktree": "/absolute/worktree/api-task",
      "artifact_dir": "/absolute/run/repos/api",
      "base_branch": "main",
      "branch": "feat/task",
      "baseline": "40-or-64-character-git-object-id",
      "initial_status_path": "/absolute/run/repos/api/initial-status.txt",
      "stage": "plan",
      "status": "pending",
      "active_writer": null,
      "plan_path": null,
      "plan_sha256": null,
      "design_challenge_required": false,
      "design_challenge_path": null,
      "design_challenge_sha256": null,
      "accepted_artifacts": {}
    }
  },
  "accepted_artifacts": {},
  "next_actions": [],
  "blockers": []
}
```

Profiles are `fast`, `standard`, and `full`. Generate policy with `workflow_tools.py policy`; do not hand-weaken it. Ordinary multi-repository work uses standard with shared-contract and integration workers. Authorization, security, concurrency, migration, backfill, background-processing, storage, public-interface changes, or comparable high-cost risk force `full`; repository count and `cross-repository` alone do not.

Run phases are `bootstrap`, `contract`, `plan`, `plan-review`, `implement`, `validate`, `review-1`, `fix-1`, `review-2`, `fix-2`, `integrate`, `deliver`, `report`, `complete`, but conditional phases may be skipped according to `workflow_policy`. New runs schedule only `review-1` and at most one `fix-1` batch; `review-2` and `fix-2` remain valid solely for resuming older two-round runs. Every run creates a plan-decision bundle; only full enters `plan-review`. Repository stage uses the same values. Run status additionally permits `awaiting-user`, exclusively for a pending full review.

A repository always needs a canonical accepted plan after planning. It needs a canonical accepting challenge only when that plan says `design_challenge_required: true`. `accepted_artifacts` at run level stores global contract/integration/report artifacts; repository artifacts remain repository-scoped.

For new runs, `plan_review` is null before planning completes. Full creates a pending review and interrupts; fast/standard creates the same bundle already approved by workflow policy. The full pending shape is:

```json
{
  "status": "pending",
  "requested_at": "2026-08-17T09:00:00Z",
  "review_path": "/absolute/run/plan-review-v1.md",
  "review_sha256": "64-character-sha256",
  "contract_sha256": null,
  "plans": {
    "api": {
      "plan_path": "/absolute/run/repos/api/plan-v1.json",
      "plan_sha256": "64-character-sha256",
      "design_challenge_path": null,
      "design_challenge_sha256": null
    }
  },
  "approved_at": null,
  "approval_text": null,
  "approval_source": null
}
```

The review bundle must visibly contain every recorded repository, canonical path, and hash. While a full review is pending, the run is `phase: plan-review`, `status: awaiting-user`, with no blockers, next actions, or active writer. Explicit whole-bundle approval records the user's exact text, `approval_source: user`, and atomically advances to `implement`. Fast/standard instead records `status: approved`, equal request/decision timestamps, `approval_source: workflow-policy`, and `approval_text: "Automatically accepted by the selected low-risk workflow policy."` in the same planning transition. Any canonical contract/plan/challenge hash change makes either decision stale. “Continue,” pre-authorization, and partial approval never satisfy a pending full gate.

A next action contains unique ascending `order`, unique `action_id`, phase, nullable repository ID, attempt, sorted input paths, output path, and status (`pending`, `working`, or `blocked`). It records its immutable `assignment_path`. There are no next actions while plan review is pending.

The graph may add these coordinator fields when applicable:

- `worker_execution`: the automatically detected and pinned backend/runtime plus non-secret probe evidence;
- `plan_feedback`: path/hash plus sorted affected repository IDs;
- `decision_replans`: ordered hashed `decision-replan-vN.json` references. Each immutable plan-feedback artifact preserves exact user `text`, separate coordinator `context`, `previous_plan_review`, the resolved `blocker`, the caller's `blocker_evidence_sha256` captured when reviewing that decision, `repository_states`, and nested hashed `evidence` references. Auxiliary logs are transition-time preservation snapshots, not retroactive accepted-time proof. All references are verified on subsequent run validation. Old approval is evidence only, never current authorization;
- `pending_contract_revision`: the next bounded contract `revision` and hashed decision `feedback`, valid only in the contract phase and removed atomically on contract acceptance (including crash recovery);
- `profile_escalation`: path/hash of deterministic classifier evidence;
- `pending_plan_revisions`: per-repository predecessor plan plus the hash-pinned feedback/escalation/contract basis used after canonical pointers must be cleared;
- `corrected_handoff_recoveries`: one record per explicitly recovered implementation action, containing hashed `original`, `corrected`, `assignment`, `rejection`, and `evidence` references plus the recovery-time `repository_state`. Every reference is checked on subsequent run validation. This is not a retry-budget reset or permission to rewrite accepted artifacts;
- `external_repair_recoveries`: hashed [external-repair records](schemas/external-repair-recovery.md), preserving rejected evidence/source and authorizations; schedules fresh verification, never accepts the old result;
- `interrupted_packet_recoveries`: hashed [interrupted-packet records](schemas/interrupted-packet-recovery.md), keyed by original action, preserving initializer/history, host proof and replacement. Optional [privileged inspection](schemas/privileged-process-inspection.md) pins consumed authorization and fresh original-UID evidence;
- `writer_incident_recoveries` and `writer_incident_attempts`: hashed [incident records](schemas/writer-incident-recovery.md) and one-shot verification assignments; quarantined references and incident outputs stay unaccepted;
- `external_repair_attempts`: one hashed `packet-verification` assignment per new verification action, saved before launch. This is a one-shot launch claim, not a retry-budget reset. Accepted fresh results and their scope/check logs are revalidated on subsequent run loads. No missing/invalid claimed result can cause another worker launch;
- `run_amendments`: ordered hashed references to immutable [`run-amendment`](schemas/run-amendment.md) artifacts. This field is valid only with `validation_policy_version: 1`; repeated request hashes are invalid;
- `pending_check_remediations`: at most one hashed `fix-related` amendment per repository, consumed by the existing `validation-fix` or `pipeline-fix` route;
- `pending_validation_refresh`: at most one hashed restoration amendment per repository, consumed by validation-only work. Neither pending map adds a graph phase or resets a retry budget;
- repository `database_target_evidence`: path/hash of a non-secret `isolated-local` or `isolated-test` classification.

Validators ignore unknown schema-v1 extension fields for compatibility, but the graph treats these references as immutable inputs. They never contain credentials, database URLs, or full user/session transcripts.

For validation-policy version 1, read-only status derives one local-gate summary per repository from the canonical validations, current accepted observations, and active amendments. Each check row keeps its factual `result` (`pass`, `fail`, or `not-run`) separate from `disposition` (`required`, `advisory`, or `excluded`) and includes purpose/gate, exact command/cwd, summary, log, and exception reference where applicable. The result's `amendment_contexts` map provides each repository's current context SHA-256 string, directly usable as `expected_context`; `eligible_actions` contains typed candidate requests. The context binds requirements/contract/plan/review, active amendments, repository content/HEAD/branch/index, selected source/delivery artifacts, and blockers. Partial current packets retain their actual observations rather than being mislabeled historical; future unobserved checks remain `not-run`. `fix-related` candidates contain only actual failed identities within remaining allowances. `review_provenance` distinguishes reviewed source from historical review with accepted bounded revisions or subsequently authorized policy amendments. Candidates describe what the engine could validate; they are not authority to infer a user exception or related remediation. The latest accepted delivery observation per repository supplies the visible PR URL and readiness even when pending/blocked; an older success never hides a newer failure.

The local gate is satisfied only when every effective blocking check has current passing evidence and no effective check is missing. A failing advisory check is a warning and does not spend a fix cycle. An excluded check is covered by its amendment rather than execution; it is never counted as a pass. Missing/protected/contradictory evidence remains incomplete.

## `requirements.json` (`requirements`)

```json
{
  "schema_version": 1,
  "artifact_kind": "requirements",
  "run_id": "20260817T083000Z-rate-management",
  "created_at": "2026-08-17T08:30:00Z",
  "requirements": [
    {
      "id": "REQ-001",
      "source_text": "Create rate management.",
      "acceptance_criteria": ["An authorized user can create and archive rates."],
      "repository_ids": ["api"]
    }
  ],
  "constraints": ["Preserve existing authorization conventions."]
}
```

Every requirement has non-empty source text, acceptance criteria, and repository IDs. Preserve the user's material wording and original ticket acceptance IDs in the criteria.

New skill-driven runs include `intake`; its exact source/evidence/question shape and limits are in [ORCHESTRATION.md](ORCHESTRATION.md#source-intake-and-question-history). It is copied verbatim into this hash-pinned artifact within the 64 KiB limit; missing intake remains compatible. Later interactions belong in append-only `logs/clarifications.md`, never immutable requirements. That ledger preserves the shared cap and cannot authorize work or unlock a gate.

## `agents.json` (`agents`)

Records every session, including failed/replacement workers:

```json
{
  "schema_version": 1,
  "artifact_kind": "agents",
  "run_id": "20260817T083000Z-rate-management",
  "updated_at": "2026-08-17T08:40:00Z",
  "agents": [
    {
      "name": "e2e-api-implement-ab12cd34-a1",
      "stage": "implement",
      "repo_id": "api",
      "attempt": 1,
      "backend": "tmux",
      "handle_id": "@12",
      "status": "closed",
      "cleanup_status": "complete",
      "cleanup_error": null,
      "started_at": "2026-08-17T08:35:00Z",
      "ended_at": "2026-08-17T08:40:00Z",
      "output_artifact": "/absolute/run/repos/api/implementation-api-packet-001-1.json"
    }
  ]
}
```

Statuses are `starting`, `working`, `blocked`, `idle`, `failed`, and `closed`. `backend` is `direct`, `paseo`, `herdr`, `tmux`, or a test/legacy adapter name. `handle_id` is opaque to the graph. Cleanup status is `pending`, `retained`, `complete`, or `failed`; completion requires every settled worker to be `complete`. Older schema-v1 Herdr records with `pane_id` and optional `pane_closed` remain valid on resume.

New worker names match `^[a-z][a-z0-9_-]{0,31}$` for Herdr compatibility. They use an `e2e-` prefix, a sanitized/truncated repository-stage label, and a hash of the full run ID, action ID, and attempt. Truncation preserves the identity hash; the readable attempt is omitted only if it cannot fit. Resume preserves recorded launch-time names (or the legacy name for pre-supervisor Herdr runs) rather than renaming existing workers. Run IDs and immutable assignments are unchanged.

## Immutable assignment (`assignment`)

Read [schemas/assignment.md](schemas/assignment.md) for fields, stage scopes and policy variants. LangGraph generates assignments; do not hand-author them. Inputs are unique, path-sorted hashed references. Source writers pin the exact approved bundle and receive one repository write scope; only delivery writes Git/forge. Read-only repository assignments pin the creation-time content fingerprint; global assignments use null repository/baseline/status/fingerprint.

Validation IDs/commands come from sorted effective checks, omitting excluded checks while pinning their amendments. Remediation targets are separate from the full effective rerun suite. Each action owns its logs.

The supervisor records actual model/reasoning/backend and opaque handle for recovery. After artifact capture it archives/closes/reaps settled handles even for rejected output. Unknown or failed cleanup retains the action/lease/claim and blocks acceptance/replacement; reconciliation adopts the original handle before accepting output.

### Artifact-only assignments

An `execution_mode: artifact-repair` assignment keeps the original result stage, IDs, commands, and canonical inputs but grants no project/Git/forge write access. It has a new action/output path, medium reasoning, and a 300-second timeout. `repair_of` contains hashed `assignment`, `artifact`, and `evidence` references plus `repository_states` keyed by repository ID (`fingerprint`, `head`, `branch`, `index_sha256`). The index hash represents staged entries, not volatile stat-cache bytes.

`run.json.artifact_repairs` maps the original action ID to a hashed repair assignment and its `resume_generation`, persisted before launch. Its `launch_started_at` claim is saved before entering the supervisor: after a crash, adopt/wait for surviving work and accept a valid output, but never relaunch a claimed repair with missing/invalid output. An indeterminate launch blocks conservatively. `external_resume_generation` advances only on supported explicit external-condition resume; crash recovery never replenishes the one-repair allowance. Accepted repairs remain immutable. Only previously missing blocker kinds and coordinator-owned metadata can differ from the original payload. Genuine blocked outcomes remain blocked; arbitrary field edits, changed input/evidence/Git state, or invalid/ambiguous classification do not become replacement source work.

### Packet verification

Read [schemas/result.md](schemas/result.md) for `packet-verification`. It preserves original packet/task/check IDs, pins exactly one recovery record (`external_repair` or `writer_incident`), current approval and source state, and uses read-only scope with fresh output/logs. Inventory preserved work, not claimed verifier edits. Compatible inspected work and fresh passing checks are required; material/incomplete/failed work remains blocked. Recovery grants no replay, policy upgrade or extra fix allowance.

### Command delivery evidence

Read [schemas/delivery.md](schemas/delivery.md) for version-2 head/policy evidence and version-1 ownership/draft semantics. Command assignments persist normal intents and unique command snapshots without agent records; manifests have a separate `commands` array. Recovered observations use fresh read-only forge queries. Accepted output is immutable; cold recovery creates a new `verify_only` assignment.

`pending_delivery_refresh` pins prior observations, survives peer actions and clears only after acceptance of its bound refresh. Completion refuses outstanding refresh; saved graph nodes cannot execute superseded/blocked intent. Fallback workers have the same policy obligations. Unsupported behavior blocks.

## Worker artifact schemas

Workers use only the schema matching `output_kind`:

| Kind | Schema | Key v2 behavior |
|---|---|---|
| `contract` | [`schemas/contract.md`](schemas/contract.md) | Coordinated cross-repository behavior only |
| `plan` | [`schemas/plan.md`](schemas/plan.md) | Risk flags, bounded work packets, and versioned validation purpose/gates |
| `design-challenge` | [`schemas/design-challenge.md`](schemas/design-challenge.md) | Risk-bearing plans only |
| `result` | [`schemas/result.md`](schemas/result.md) | Finished-work status separated from tree-keyed check outcomes |
| `review` | [`schemas/review.md`](schemas/review.md) | Must-fix/advisory disposition; legacy targeted round two remains resumable |
| `integration` | [`schemas/integration.md`](schemas/integration.md) | Conditional, challenge may be explicitly waived |
| `delivery` | [`schemas/delivery.md`](schemas/delivery.md) | Git/forge evidence, actual draft ownership/state, and typed readiness |
| `report` | [`schemas/report.md`](schemas/report.md) | Deterministically generated |

Important compact shapes follow for graph scheduling and worker handoff.

### Plan work packet

```json
{
  "id": "API-PACKET-001",
  "summary": "Implement and test the local rate-management behavior.",
  "task_ids": ["API-TASK-001", "API-TASK-002"],
  "depends_on": [],
  "estimated_minutes": 35
}
```

Every task belongs to exactly one packet; a packet follows its profile's three-or-four-task limit and lasts at most 45 minutes. Cross-packet task dependencies must appear as packet dependencies.

### Validation evidence and reuse

```json
{
  "id": "API-VAL-001",
  "command": "python -m unittest",
  "command_sha256": "sha256-of-exact-command",
  "cwd": "/absolute/worktree",
  "tree_fingerprint": "worktree-fingerprint",
  "cache_status": "fresh",
  "source_artifact": null,
  "exit_code": 0,
  "result": "pass",
  "summary": "Focused tests passed.",
  "log_path": "/absolute/run/repos/api/logs/implement-api-packet-001/test.log",
  "log_sha256": "64-character-sha256"
}
```

`reused` evidence hash-pins the earlier result artifact. Reuse only when command hash, cwd, content fingerprint, and current canonical plan match; after decision replanning, the result assignment must pin that plan. For policy-version-1 evidence the coordinator checks fresh paths beneath the assignment log directory before reading and computes `log_sha256` at acceptance. Cached passing logs remain beneath the repository's run log directory and retain their original path/hash. Action-specific logs and hashes are immutable: reruns create new logs rather than changing old observations. The final implementation/fix writer is assigned every effective validation so its evidence can satisfy the gate directly. A failed observation remains `fail`; an exception changes only its policy disposition. If an excluded command has no current-tree observation, the evaluated row says `not-run`/excluded and cites the amendment. The fingerprint excludes parent `HEAD`, so an identical delivery commit reuses evidence; source content, mode, symlink, deletion, untracked content, or submodule-state changes invalidate observations but not a still-current scoped exclusion. Compute it with:

```bash
python3 "$SKILL_DIR/scripts/workflow_tools.py" fingerprint <worktree>
```

### Review finding

```json
{
  "id": "API-R1-001",
  "category": "spec",
  "severity": "high",
  "actionable": true,
  "disposition": "must-fix",
  "requirement_id": "REQ-001",
  "path": "src/rates.py",
  "line": 42,
  "summary": "Archived rates remain selectable.",
  "evidence": "The selection query does not filter archived state."
}
```

Critical/high actionable findings always block. Medium correctness findings normally block. Low findings are normally advisory and do not independently trigger a worker/revalidation cycle.

## `run-amendment-vN.json` (`run-amendment`)

See [schemas/run-amendment.md](schemas/run-amendment.md) for the exact request, authority, snapshots, lifetime and idempotency contract. The engine alone creates the artifact and pins it in `run.json.run_amendments`.

Delivery reuse requires current content/HEAD, canonical meaning and amendments. Owned PRs need a normal delivery publishing the current policy summary; read-only observation cannot substitute. Late amendments return to delivery without clearing unrelated blockers.

Reports are immutable evidence snapshots labelled with capture time, not live lifecycle state. Regenerate stale reports; `report_paths` lists current and `historical_report_paths` older outputs. Versioned direct `render-report` calls require coordinator `--evaluated-status`; the renderer does not evaluate gates. Show exclusions and current/historical failures truthfully.

## `events.jsonl`

One compact transition per line. Allowed names are `run-created`, `agent-started`, `agent-closed`, `artifact-accepted`, `artifact-rejected`, `phase-changed`, `writer-acquired`, `writer-released`, `plan-review-requested`, `plan-approved`, `plan-changes-requested`, `run-amended`, `blocked`, `resumed`, and `completed`; deterministic delivery also emits `command-started`.

`artifact-rejected` records `error_code` and `error_path` when available. Metrics count `command_attempts` separately from `worker_attempts`.

```json
{"at":"2026-08-17T09:00:00Z","run_id":"20260817T083000Z-rate-management","event":"plan-review-requested","phase":"plan-review","artifact":"/absolute/run/plan-review-v1.md","next_action":null}
```

Events describe transitions; they never duplicate artifact narratives.

## Size limits

| Kind | Maximum |
|---|---:|
| `run` | 160 KiB |
| `requirements` | 64 KiB |
| `agents` | 128 KiB |
| `assignment` | 32 KiB |
| `contract` | 96 KiB |
| `plan` | 64 KiB |
| `design-challenge` | 64 KiB |
| `result` | 64 KiB |
| `review` | 64 KiB |
| `integration` | 96 KiB |
| `delivery` | 64 KiB |
| `report` | 32 KiB |
| `run-amendment` | 64 KiB |
| coordinator `external-repair-recovery` | 128 KiB |
| coordinator `writer-incident-recovery` | 128 KiB |

Move verbose evidence into logs rather than growing an artifact.
