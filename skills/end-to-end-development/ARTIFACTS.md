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
- A complete artifact has no blockers. A blocked artifact has at least one blocker.
- Older schema-v1 runs without profile fields remain valid and behave as legacy `full` runs when resumed.
- New fast/standard runs set `workflow_policy.user_plan_approval_required: false`; full sets it to `true`. Every run still records an approved hash-pinned bundle before project-file work. On resume, omission of this key in an older profiled run is treated as approval-required for backward safety.
- New runs pin `worker_reasoning_policy: stage-v1`, `retry_limits.artifact_repairs_per_action: 1`, and repository `delivery_executor` (`github-command` or `worker`), `delivery_repository`, `delivery_evidence_version: 2`, and `delivery_check_timeout_seconds` (0–1800). Missing fields retain legacy xhigh/no-repair/worker/version-1 behavior; never mutate pinned policies in an active run.
- Before validation, the coordinator normalizes mechanical evidence (`assignment_sha256`, Git HEAD/status, content fingerprint, and command hashes). Workers remain responsible for semantic conclusions, command execution results, findings, and blockers.

## Directory layout

```text
<run-dir>/
├── request.md
├── requirements.json
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
- `profile_escalation`: path/hash of deterministic classifier evidence;
- `pending_plan_revisions`: per-repository predecessor plan plus the hash-pinned feedback/escalation/contract basis used after canonical pointers must be cleared;
- repository `database_target_evidence`: path/hash of a non-secret `isolated-local` or `isolated-test` classification.

Validators ignore unknown schema-v1 extension fields for compatibility, but the graph treats these references as immutable inputs. They never contain credentials, database URLs, or full user/session transcripts.

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

Every requirement has non-empty source text, acceptance criteria, and repository IDs. Preserve the user's material wording.

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

Read [`schemas/assignment.md`](schemas/assignment.md). New profiled assignments add `profile`, stage-specific packet/finding/validation IDs, and point `artifact_schema_path` to exactly one schema file rather than this contract.

```json
{
  "schema_version": 1,
  "artifact_kind": "assignment",
  "run_id": "20260817T083000Z-rate-management",
  "action_id": "implement:api:api-packet-001:1",
  "created_at": "2026-08-17T09:10:00Z",
  "stage": "implement",
  "attempt": 1,
  "profile": "standard",
  "repo_id": "api",
  "cwd": "/absolute/worktree/api-task",
  "thinking": "high",
  "timeout_seconds": 3600,
  "project_file_access": "write",
  "git_access": "none",
  "forge_access": "none",
  "repositories": [{
    "repo_id": "api",
    "root": "/absolute/source/api",
    "worktree": "/absolute/worktree/api-task",
    "access": "write"
  }],
  "baseline": "40-character-git-object-id",
  "preexisting_status_path": "/absolute/run/repos/api/initial-status.txt",
  "input_tree_fingerprint": null,
  "input_artifacts": [
    {"path": "/absolute/run/plan-review-v1.md", "sha256": "64-character-sha256"},
    {"path": "/absolute/run/repos/api/plan-v1.json", "sha256": "64-character-sha256"},
    {"path": "/absolute/run/request.md", "sha256": "64-character-sha256"},
    {"path": "/absolute/run/requirements.json", "sha256": "64-character-sha256"}
  ],
  "requirement_ids": ["REQ-001"],
  "task_ids": ["API-TASK-001", "API-TASK-002"],
  "finding_ids": [],
  "validation_ids": ["API-VAL-001"],
  "packet_id": "API-PACKET-001",
  "plan_review": {
    "path": "/absolute/run/plan-review-v1.md",
    "sha256": "64-character-sha256"
  },
  "instructions": ["Execute the assigned work packet and its bounded deviation policy."],
  "validation_commands": ["repository-specific focused command"],
  "output_kind": "result",
  "output_artifact": "/absolute/run/repos/api/implementation-api-packet-001-1.json",
  "log_dir": "/absolute/run/repos/api/logs",
  "artifact_schema_path": "/absolute/skill/schemas/result.md",
  "validator_path": "/absolute/skill/scripts/artifact_guard.py"
}
```

Input references are unique and path-sorted. Every project-file writer in a new run includes the exact approved review bundle—user-approved or policy-approved—in `input_artifacts` and repeats that hashed reference as `plan_review`; the batch supervisor compares it to current run state. A plan revision pins the superseded plan plus exactly one accepted design challenge or coordinator revision basis. Only implementation/fix stages write project files, exactly one repository at a time. Repository-scoped read-only assignments pin the content fingerprint present at assignment creation; the coordinator rejects any acceptance-time change. Only delivery writes Git/forge. Global assignments use null repository, baseline, pre-existing status, and input fingerprint.

New assignments pin `reasoning_policy: stage-v1`: use `medium` for artifact-only repair, validation-only work, and fallback delivery; `high` for ordinary planning/review and every source writer; `xhigh` for full-profile contract/planning/challenge/review/integration. Legacy policy remains `legacy-xhigh` when not explicitly versioned.

The supervisor's worker runtime is selected per batch: `--worker-runtime auto` follows the coordinator's Codex/Pi runtime (or `E2E_COORDINATOR_RUNTIME` when explicitly set). Workers keep `gpt-6-astra`, honoring the stage level. The actual configuration is recorded in the manifest and handle record for recovery. Deterministic commands do not create agent records.

Each supervisor worker entry records `backend`, opaque `handle_id`, `cleanup_status`, and optional `cleanup_error`. Backend details remain in the durable supervisor record rather than leaking into graph routing. After a worker settles, its Paseo agent is archived, Herdr workspace is closed, tmux window is closed (or recognized as already gone), or direct process is reaped after artifact capture whether the artifact is accepted or rejected. A timeout or non-settled worker is retained for diagnosis. Crash reconciliation reads the same record and performs the same cleanup, including when the worker wrote its artifact before the coordinator stopped.

### Artifact-only assignments

An `execution_mode: artifact-repair` assignment keeps the original result stage, IDs, commands, and canonical inputs but grants no project/Git/forge write access. It has a new action/output path, medium reasoning, and a 300-second timeout. `repair_of` contains hashed `assignment`, `artifact`, and `evidence` references plus `repository_states` keyed by repository ID (`fingerprint`, `head`, `branch`, `index_sha256`). The index hash represents staged entries, not volatile stat-cache bytes.

`run.json.artifact_repairs` maps the original action ID to a hashed repair assignment and its `resume_generation`, persisted before launch. Its `launch_started_at` claim is saved before entering the supervisor: after a crash, adopt/wait for surviving work and accept a valid output, but never relaunch a claimed repair with missing/invalid output. An indeterminate launch blocks conservatively. `external_resume_generation` advances only on supported explicit external-condition resume; crash recovery never replenishes the one-repair allowance. Accepted repairs remain immutable. Only previously missing blocker kinds and coordinator-owned metadata can differ from the original payload. Genuine blocked outcomes remain blocked; arbitrary field edits, changed input/evidence/Git state, or invalid/ambiguous classification do not become replacement source work.

### Command delivery evidence

New GitHub delivery uses `execution_mode: command` and `delivery_evidence_version: 2`. The graph persists ordinary action intent, a portable input JSON, command logs/results, and a delivery artifact; it does not construct an agent handle. Active output projections may be completed during recovery, preserving prior snapshots and unique command result files; accepted artifacts remain immutable. Recovered complete outputs require fresh read-only forge queries, and cold recovery after acceptance schedules a new `verify_only: true` command assignment with no Git/forge write access. `pending_delivery_refresh` hash-pins accepted observations that need refresh after cold recovery. It survives other repositories' active actions and is cleared only when a new command artifact bound to the old observation is accepted; completion rejects an outstanding refresh. Blocked recovered CI failures retain the ordinary bounded fix route. A saved graph node cannot execute after recovery blocks or supersedes its intent. Command manifests have a separate `commands` array. Other forges retain worker execution.

Version-2 delivery adds `head_sha`, `pushed_head_sha`, `checked_head_sha`, and `check_policy` (`status`, `required_checks` with name/app identity, hashed `evidence`). Complete results require all heads to equal the final commit/current worktree and every required identity to be present and passing. Explicit absence is `not-configured`; empty current checks, permission failures, and unknown policy are not absence. Scripted artifacts also bind `command_evidence` and record `delivery_outcome` (`complete`, `pending`, or `blocked`). A pending outcome maps to an infrastructure blocker, not a code-fix attempt. Evidence follows [schemas/delivery.md](schemas/delivery.md).

## Worker artifact schemas

Workers use only the schema matching `output_kind`:

| Kind | Schema | Key v2 behavior |
|---|---|---|
| `contract` | [`schemas/contract.md`](schemas/contract.md) | Coordinated cross-repository behavior only |
| `plan` | [`schemas/plan.md`](schemas/plan.md) | Risk flags and bounded work packets |
| `design-challenge` | [`schemas/design-challenge.md`](schemas/design-challenge.md) | Risk-bearing plans only |
| `result` | [`schemas/result.md`](schemas/result.md) | Multi-task packets, fix batches, tree-keyed validation |
| `review` | [`schemas/review.md`](schemas/review.md) | Must-fix/advisory disposition; legacy targeted round two remains resumable |
| `integration` | [`schemas/integration.md`](schemas/integration.md) | Conditional, challenge may be explicitly waived |
| `delivery` | [`schemas/delivery.md`](schemas/delivery.md) | Git/forge evidence |
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
  "log_path": "/absolute/run/repos/api/logs/test.log"
}
```

`reused` evidence hash-pins the earlier result artifact. Reuse only when command hash and content fingerprint match. The final implementation/fix writer is assigned every planned validation so its passing evidence can satisfy the gate directly. The fingerprint excludes parent `HEAD`, so an identical delivery commit reuses evidence; file content, mode, symlink, deletion, untracked content, or submodule-state changes invalidate it. Compute it with:

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

## `events.jsonl`

One compact transition per line. Allowed names are `run-created`, `agent-started`, `agent-closed`, `artifact-accepted`, `artifact-rejected`, `phase-changed`, `writer-acquired`, `writer-released`, `plan-review-requested`, `plan-approved`, `plan-changes-requested`, `blocked`, `resumed`, and `completed`; deterministic delivery also emits `command-started`.

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

Move verbose evidence into logs rather than growing an artifact.
