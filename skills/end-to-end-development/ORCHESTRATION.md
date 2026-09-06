# LangGraph orchestration

LangGraph is the only executable control-flow engine for this skill. The Pi/Codex coordinator performs repository discovery and translates that evidence into a bootstrap specification. For new policy-version-1 runs it may also inspect hash-pinned evidence read-only and translate explicit user validation exceptions or evidence-based related remediation into the typed amendment request. It does not choose phases, construct or author worker assignments, launch batches, manage retries, patch source, or mutate run state directly.

## Authority model

There is one state machine and two durable fact classes:

1. `${RUN_DIR}/langgraph.sqlite` stores LangGraph's execution cursor and interrupt state.
2. `run.json`, `agents.json`, immutable assignments, accepted worker artifacts, Git, and forge state store workflow facts and evidence.

New initialization pins `validation_policy_version: 1` and `delivery_policy_version: 1`. Their absence means the entire historical path remains legacy: no retrofit, migration, amendment support, or draft-lifecycle inference. Unknown values are rejected. Existing recovery commands retain their legacy semantics and do not upgrade a run.

`run.json.phase` is the canonical phase projection used for routing. The graph checkpoint never overrules it. Every graph execution starts at `reconcile`, validates the projection and accepted artifacts, recovers valid outputs left by a crash, clears stale writer leases, and routes to the projected phase. This prevents LangGraph checkpoint state and `run.json` from becoming competing state machines.

A run-scoped execution lock permits only one advancing graph invocation at a time; projection writes use a separate short-held lock. External side effects are not assumed to be exactly-once. A worker, commit, push, or PR may finish immediately before a process crash. Nodes therefore use this sequence:

1. Persist immutable assignment intent and `next_actions`.
2. Acquire the repository writer lease when applicable.
3. Execute the side effect.
4. Validate the output at the artifact seam.
5. Clean the settled worker through its pinned backend handle and record the result.
6. Record the accepted hash reference and release the lease.
7. Checkpoint the graph superstep.

At the artifact seam, the coordinator—not the worker—records assignment hashes, Git HEAD/status, content fingerprints, and command hashes. This keeps semantic worker conclusions independent from mechanical metadata and avoids replacing correct work for a stale copied status file.

On replay, existing valid output is accepted rather than repeated. Crash recovery reads the durable supervisor record, adopts the surviving Paseo agent, Herdr workspace, tmux window, or direct process, and cleans it when settled—even when the artifact was written before the coordinator stopped. A worker retained at the timeout boundary is reclassified as settled and cleaned when its durable exit-status file appears later. Invalid or absent output follows the recorded replacement limit.

## Executable graph

```text
START
  -> reconcile
  -> bootstrap
  -> contract?
  -> plan <-> design challenge / bounded revision
  -> plan_review? (dynamic interrupt for full; policy decision otherwise)
  -> implement (packet scheduler)
  -> validate -> validation-fix? -> validate
  -> review_1 -> fix_1?
  -> integrate?
  -> deliver -> pipeline-fix? -> deliver
  -> report?
  -> complete
  -> END
```

Every phase node returns to `reconcile`. Conditional policy is read from the validated `workflow_policy`; disabled phases are not executed. New runs allow one review, one review-fix batch, one validation-fix batch, and one pipeline-fix batch. A failed check after its fix blocks instead of starting another cycle. The retained `review_2` and `fix_2` nodes exist only to resume older runs whose durable state already permits two rounds. Fast/standard planning writes and policy-accepts the hash-pinned bundle in one transition, while full pauses at the dynamic interrupt. Repository batches are built lexicographically and handed to the concurrent supervisor in one call. `reconcile` also enforces `coordinator_attempt_budget` after an atomic batch and ends the current graph invocation with `budget-checkpoint`; the CLI starts a new bounded invocation automatically when policy enables `auto_resume`, without crossing a human interrupt.

On validation-policy version 1, implementation completion and gate readiness are separate. A worker completes when assigned source work and factual check reporting finish, even if a command failed; blocked means the work/reporting did not finish. The graph evaluates the current exact-command/cwd/tree/plan evidence plus active amendments. Acceptance and repository-required checks are always blocking, every task has a blocking acceptance check, and migration-capable checks remain protected. Advisory supplemental failures warn without blocking or consuming a fix allowance. Excluded supplemental non-migration checks are omitted from future execution while their historical failures remain failed. Remediation and restoration enter the existing `validation-fix`, `pipeline-fix`, or validation-only paths through `pending_check_remediations` and `pending_validation_refresh`; they do not add graph phases or reset budgets.

The graph state is deliberately small:

```python
class WorkflowState(TypedDict, total=False):
    run_dir: str
    last_transition: str
    outcome: str
```

Plans, diffs, logs, findings, and terminal output never enter graph state.

## Bootstrap specification

The coordinator writes a temporary JSON file outside the repository and passes it to `orchestrator.py init`:

```json
{
  "run_id": "20260822T100000Z-request-slug",
  "request": "The user's request verbatim.",
  "profile": "auto",
  "report_requested": false,
  "risk_flags": [],
  "requirements": [
    {
      "id": "REQ-001",
      "source_text": "Material source wording.",
      "acceptance_criteria": ["Observable acceptance criterion."],
      "repository_ids": ["api"]
    }
  ],
  "constraints": ["Preserve repository conventions."],
  "repositories": [
    {
      "repo_id": "api",
      "root": "/absolute/source/repository",
      "worktree": "/absolute/dedicated/worktree",
      "base_branch": "main",
      "branch": "feat/request-slug"
    }
  ]
}
```

An optional repository `delivery_check_timeout_seconds` is an integer from 0 (one observation) to 1800 (default); it bounds CI polling only. Initialization pins GitHub.com delivery to the command executor, other forges to workers, new delivery evidence to version 2, and delivery-policy version 1 to the `draft-until-verified` lifecycle with its run identity. Fallback workers receive the same lifecycle/evidence obligations and must report unsupported draft creation or draft-only CI rather than silently creating a ready PR or polling forever.

The coordinator must discover all affected repositories before initialization and create one clean dedicated worktree per repository. The initializer verifies the `.git` worktree file, actual branch, baseline, and empty initial status, writes requirements and run state, applies the deterministic profile classifier, and validates the result. The graph's bootstrap node then detects and pins the active worker environment, verifies its positive probe, and checks forge remotes and provider CLI authentication before scheduling a worker. Initialization never copies `.env` files or creates database targets.

Worker detection requires active-context evidence rather than installed binaries: `PASEO_AGENT_ID` plus a successful parent inspection, `HERDR_ENV=1` plus a compatible server, or `TMUX` plus a successful session probe. Precedence is Paseo, Herdr, tmux, then direct headless execution. A stale marker falls through to the next candidate. `PASEO_HOST` without a parent agent is ignored so a local coordinator never sends hash-pinned absolute paths to an unrelated remote filesystem.

## CLI interface

Run from any directory after resolving `SKILL_DIR`. The wrapper uses the locked project and places its generated virtual environment under the user cache, not inside the installed skill:

```bash
ORCHESTRATOR="$SKILL_DIR/scripts/run-orchestrator"
```

Initialize and execute:

```bash
"$ORCHESTRATOR" init --spec /absolute/bootstrap.json --run-dir "$RUN_DIR"
"$ORCHESTRATOR" run "$RUN_DIR" --worker-runtime auto
```

Inspect without advancing:

```bash
"$ORCHESTRATOR" status "$RUN_DIR"
"$ORCHESTRATOR" diagram "$RUN_DIR"
```

For validation-policy version 1, `status` also exposes `amendment_contexts` keyed by repository (each value is the SHA-256 string to use directly as `expected_context`), effective local-gate results with exclusions/warnings, and typed `eligible_actions` for current local/CI candidates. It reports the latest delivery observation and URL even when pending or blocked, including actual draft/ownership state and a typed reason. Treat candidates as bounded options, not permission to infer a user exception or a task-related failure.

Resume ordinary recoverable execution:

```bash
"$ORCHESTRATOR" resume "$RUN_DIR" --worker-runtime auto
```

Legacy `resume` behavior is unchanged. On a new run it may re-observe an identified same-content required-CI blocker through the existing read-only refresh path, including one whose factual result kind is `code`. It never clears arbitrary code/decision/dependency blockers, changes source, spends a fix allowance, or weakens required-head/policy checks.

### Typed run amendments

Read [schemas/run-amendment.md](schemas/run-amendment.md) before submitting a decision. The request JSON must contain exactly these fields:

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
  "expected_context": "64-character-status-context-sha256",
  "evidence": []
}
```

Submit it through the sole supported transition:

```bash
"$ORCHESTRATOR" amend "$RUN_DIR" --input /absolute/decision.json
```

Supported combinations are exact:

- `kind: validation-exception`, `decision: exclude|restore`, `target: local`, `authority: user`, and non-null verbatim `text`. Only named supplemental, non-migration validations are eligible.
- `kind: check-remediation`, `decision: fix-related`, `target: local|ci`, `authority: coordinator`, `text: null`, and non-empty hash-pinned `evidence`. The rationale/evidence must establish task relatedness and approved-scope compatibility. Required-CI IDs are `name@app_id`, or `name@*` when the policy has no app ID.

`check_ids` are sorted, unique, and non-empty; every evidence item is `{path, sha256}` and must be captured inside the run without secrets. The coordinator may translate exact user wording or its own read-only, evidence-based relatedness assessment, but may not invent authority, waive CI, treat unchanged files as proof of a pre-existing failure, or automatically authorize an unknown/unrelated fix.

The command rejects legacy/unknown-policy runs without creating run, event, assignment, checkpoint, or recovery state. For supported runs, an identical request is recognized read-only as `already-applied`, even after completion or later restoration. A new request requires an active run, approved current bundle, settled graph cursor/actions, no writer lease, and cleaned handles. Its `expected_context` binds the current requirements/contract/plan/review hashes, active amendments, repository content/HEAD/branch/index, selected source or delivery observation, and blockers. Stale input is rejected, not refreshed automatically.

Application writes one immutable `run-amendment-vN.json`, appends its hash reference to `run.run_amendments`, and lets the graph recompute the earliest affected gate. It never rewrites plans/results/logs, creates a fake pass, promotes unfinished work, clears untargeted blockers, changes approval, or resets a budget. Source-only changes invalidate observations but not an otherwise current exclusion; requirements, contract, plan/review, command/cwd, or explicit restoration expire it. Restoration requests fresh validation-only evidence when needed. An action-specific log directory and acceptance-time `log_sha256` preserve old observations; later actions never overwrite old logs. Log paths are confined before reading. Reviewed decision evidence is rechecked from one byte read under the transaction, and the 64 KiB amendment limit is enforced before snapshots or intent are persisted.

After updating an engine that emitted the exact validation-coverage blocker from an ID-less validation assignment, use the guarded recovery transition:

```bash
"$ORCHESTRATOR" retry-validation-evidence "$RUN_DIR" --worker-runtime auto
```

It accepts only that exact validate-phase blocker and creates a new assignment bound to the canonical plan hash and validation IDs. It does not clear other code, dependency, or decision blockers.

After updating an engine that ran a dependent fix concurrently with an upstream contract fix and emitted the exact hash-pinned bundle-drift blocker, use:

```bash
"$ORCHESTRATOR" retry-dependent-fixes "$RUN_DIR" --worker-runtime auto
```

This guarded transition accepts only that fix-phase blocker. Remaining fixes follow the shared contract's dependency order, receive accepted upstream fix artifacts as hash-pinned inputs, and get read-only access to upstream worktrees.

For the exact implementation-result rejection `$.next_action: must be at most 300 characters`, an explicitly user-authorized correction can be recovered without replaying the source writer. Preserve the rejected JSON before changing only `next_action`, then use:

```bash
"$ORCHESTRATOR" retry-corrected-handoff "$RUN_DIR" \
  --original-artifact /absolute/preserved-rejected-result.json \
  --worker-runtime auto
```

This opt-in transition accepts only an otherwise valid, complete implementation result whose only changed field is a 1–300-character `next_action`. It requires the exact rejection manifest, closed worker handles, unchanged current source/HEAD/branch/index-status evidence, matching assignment and current approved plan. It hash-pins both results and referenced evidence, atomically accepts the result once, and returns control to the graph. Failed validations remain failed. It does not reset retry limits, change approval, rewrite assignments or repair other blockers. Preserve the original file afterward; later reconciliation verifies its hash. Ordinary `resume` remains unchanged. Do not edit already accepted artifacts or coordinator state.

### Rejected blocked packet after authorized external repair

`recover-external-repair` is a separate explicit compatibility transition; it never changes the semantics of `resume`, `retry-corrected-handoff`, decision replanning, or any packet compiler-dependency continuation. Read [schemas/external-repair-recovery.md](schemas/external-repair-recovery.md) for the exact reviewed request, source proof, authorization, and crash contract.

```bash
"$ORCHESTRATOR" recover-external-repair "$RUN_DIR" \
  --input "$REVIEWED_RECOVERY_REQUEST" \
  --request-sha256 "$REVIEWED_REQUEST_SHA256" \
  --text "$EXACT_USER_RECOVERY_AUTHORIZATION" \
  --context "$COORDINATOR_INTERPRETATION" \
  --worker-runtime auto
```

Admission requires the exact rejected code-blocked implementation with real failed checks and only the overlong hint schema error, current user-approved canonical plans, a settled graph cursor and cleaned handles, no active/pending actions or leases, and isolated database-target evidence where required. It pins exact external authorization separately from later explicit recovery authorization and coordinator interpretation. Reviewed hashes cannot be refreshed. A forward baseline update is proved from historical/current Git content trees, unchanged task content or deterministic clean merges, and an explicit test-file-only repair allowlist. Peer source changes, unrelated outcomes, rewritten commits and nontrivial resolutions are refused.

The immutable recovery record is a scheduling obligation, **not accepted implementation or validation evidence**. Before ordinary packet scheduling, the existing implement node issues one new `packet-verification` worker with no source/Git/forge write permission. It independently inspects preserved packet completion and scope and runs the original assigned checks freshly. Only compatible, passing new evidence completes that packet. Factual new failures stay blocked without source replay or automatic fixes. Remaining packets, mandatory full-plan validation, fresh independent review, required integration and final delivery gates remain unchanged. Material changes use normal bounded replanning and renewed full-bundle approval; exhausted limits remain exhausted.

Identical applied requests return `already-applied` without advancing, even after another blocker or completion. An identical pre-projection intent can be reused. A durable launch claim prevents duplicate verification; crash reconciliation may adopt a surviving worker and accept its output but never relaunch a claimed attempt without accepted evidence. Subsequent run loads validate original and fresh evidence hashes. Ordinary `run`/`resume` continues a committed transition; neither resets its allowance. Do not execute live recovery or install over an existing skill without separate authorization.

A pending full-profile plan review is a dynamic LangGraph interrupt. Approval must include the exact current hash and the user's exact explicit wording. Fast/standard bundles are already `approved` with `approval_source: workflow-policy` evidence and never use this command:

```bash
"$ORCHESTRATOR" approve "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_APPROVAL"
```

Generic continuation words are rejected. Requested changes return selected repositories to planning and create a hash-pinned revision basis:

```bash
"$ORCHESTRATOR" request-changes "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_FEEDBACK" \
  --repository api
```

Omit `--repository` to revise every repository plan.

After explicit user authorization of a material product/contract choice discovered during implementation, use the separate guarded transition (not `resume` or `request-changes`):

```bash
"$ORCHESTRATOR" replan-decision "$RUN_DIR" \
  --review-sha256 "$APPROVED_BUNDLE_SHA256" \
  --blocker-id "$CURRENT_DECISION_BLOCKER_ID" \
  --blocker-evidence-sha256 "$REVIEWED_BLOCKER_EVIDENCE_SHA256" \
  --text "$EXACT_USER_FEEDBACK" \
  --context "$COORDINATOR_EXPLANATION_OF_THE_CHOICE" \
  --worker-runtime auto
```

Read the blocker evidence and capture its SHA-256 when reviewing the decision; do not recompute it merely to make a stale decision pass. The supplied hash must still match at transition time. This pins the reviewed evidence, not a claim of retroactive accepted-time log verification. Existing unpinned auxiliary logs are preservation snapshots only and cannot validate a revised plan.

It accepts only a settled, blocked full-profile implementation run with one decision matching an accepted blocked result bound to the current user-approved bundle. Closed/cleaned handles, no actions/leases, unchanged worktree/HEAD/branch/status and unstaged index, and remaining contract/plan revision budgets are mandatory. It does not recover schema rejections or arbitrary blockers. `--text` preserves exact user wording; optional `--context` is separately labelled interpretation, never approval.

The transition hash-pins immutable `decision-replan-vN.json` feedback containing the old approval, blocker, repository states, and existing artifact/assignment/evidence references. It atomically invalidates approval and returns every repository to planning, first revising the shared contract when required. Existing worktrees, baselines, source work, accepted artifacts, worker history, and retry limits are preserved. Revised plans describe remaining deltas; revised implementation actions have new plan-version scopes, so old packets cannot satisfy new plans or be overwritten. Validation must bind the new plan. Independent review remains mandatory. The graph stops for approval of the new whole bundle before any writer. Numerical proposals in new plans are not pre-approved by the original choice.

Accepted replanning contract/plan/challenge outputs are reused without relaunching their workers after an acceptance-to-projection crash. Latest repository outcomes are selected from recorded worker order, not second-resolution timestamps or packet names.

A crash after the projection write resumes through ordinary `run`/`resume`; repeating `replan-decision` cannot spend another revision or revive the old approval. A pre-projection crash may reuse only identical immutable feedback intent. A pending SQLite cursor is refused rather than redirected manually. Never edit coordinator state or accepted evidence to force eligibility.

## Database-target gate

The graph refuses to schedule any migration-capable validation until non-secret evidence identifies an isolated local/test database. Record only a classification and description—never a URL, credential, or secret:

```bash
"$ORCHESTRATOR" database-target "$RUN_DIR" \
  --repository api \
  --classification isolated-test \
  --description "Ephemeral database created solely for this worktree"
```

Production, staging, shared, and ambiguous targets are rejected by the CLI. This gate does not authorize destructive commands; worker assignments still forbid unplanned destructive migration or seeding operations.

## Dependency and runtime policy

The skill uses the locked project in this directory:

- `langgraph==1.2.11`
- `langgraph-checkpoint-sqlite==3.1.1`

`scripts/run-orchestrator` invokes `uv run --project`, uses `uv.lock`, and sets `UV_PROJECT_ENVIRONMENT` to `${XDG_CACHE_HOME:-$HOME/.cache}/pi/end-to-end-development/venv` unless already configured. `workflow_tools.py run-batch` delegates lifecycle to the auto-detected worker supervisor while LangGraph retains the immutable assignment and artifact protocol. Workers use `gpt-6-astra`. New runs pin `stage-v1` reasoning: full-profile contract/plan/challenge/review/integration use xhigh, ordinary planning/review and all source writers use high, and artifact-only repair/validation/fallback delivery use medium. No delivery/report agent is needed for deterministic commands. Legacy runs without the new reasoning-policy field retain xhigh; pinned assignments and live handles are not rewritten.

## Output repair and command delivery

Worker schemas link a concise blocker contract and typed construction command. Rejections carry an error code and field path through both acceptance seams. New runs permit one artifact-only correction of a parseable blocked result missing only blocker kinds. The graph persists a derived read-only assignment/output and binds the original payload, referenced evidence, content, HEAD, branch, and index. A persisted launch claim prevents a failed/missing repair output from starting another attempt after a crash. Repair never changes outcomes, reruns validation, resets retries, or falls back to another source writer. Unsupported/ambiguous repairs and stale evidence remain blocked. Explicit external-condition resume after a valid blocked repair is distinct from crash recovery.

New delivery requires canonical review provenance: either the reviewed source or the historical review plus its accepted, hash-linked bounded revisions. A revision is not falsely described as another independent review of the final tree. Required integration must pin current writers, semantic inputs, and amendments; the existing read-only integration phase refreshes stale evidence before delivery without changing review/fix budgets. Delivery must match current content/HEAD and repository policy amendments, including a normal summary publication for owned PRs. Late amendments return to this gate even when another blocker still pauses execution. Context-scoped reports refresh stale summaries without overwriting historical reports.

GitHub delivery assignments use `execution_mode: command` with normal durable `next_actions`; they never create agent records or backend handles. Delivery-policy version 1 supplies `pr_lifecycle: draft-until-verified` and `run_id`. Once local/review/integration gates are satisfied, the helper commits and pushes through the audited path, creates a run-owned draft, and records actual `pr_draft`, `pr_owned`, URL, and typed `reason_code`. The URL remains visible if CI blocks. A stable `pr_intent_path` binds local creation intent and a random nonce to the PR marker; a public marker alone never proves ownership. Managed-content hashes prevent overwriting human edits, including inside the marked section. Recorded body/readiness conflicts can be re-observed read-only after external resolution; other decision blockers stay blocked. A matching user-owned draft is preserved and may verify complete while still draft; neither its body nor readiness is changed, and output must not claim it is ready.

The graph executes the standard-library helper, records immutable input/output evidence, and reconciles Git/forge state after interruption. Independent command deliveries and remaining forge workers can run concurrently. The graph's cold-entry `recover` node refreshes delivery through `verify_only`, which never commits, pushes, creates, edits, or publishes a PR. Green required CI on a run-owned draft produces `publication-required`; the engine then authorizes an ordinary delivery action, which alone may mark it ready. Required CI is re-observed after publication. `required-ci-pending` waits/re-observes without budget use; `required-ci-failed` remains a factual blocker until a `fix-related` decision authorizes the one existing pipeline-fix cycle. Unknown or unrelated red CI does not authorize source work.

Hash-pinned refresh obligations survive active peer actions and drain after the existing batch settles, so a pending fix in one repository cannot hide stale delivery in another. Recovery before acceptance retains earlier action-specific snapshots; recovery after acceptance uses a new assignment/output. Version-1 fallback workers can also execute a `verify_only` refresh with no Git/forge write access. Version-2 results require matching local/pushed/checked heads and positive required-check policy evidence. A changing policy/head invalidates the observation. Unknown policy, skipped/cancelled required CI, draft-only CI, unsupported draft operations, and publication failures block explicitly rather than silently downgrading. A ready PR remains ready during later read-only refresh even if CI regresses; delivery readiness, not an invented state rollback, is authoritative.

All new behavior is version-pinned at initialization. Existing runs without extension fields keep their historical execution/retry paths. Do not retrofit active runs by editing state.

## Testing seams

`WorkflowEngine` is the graph module interface. `WorkerSupervisor` is the execution module interface shared by direct, Paseo, Herdr, and tmux adapters. Production uses auto-detection; tests inject an in-process batch adapter or fake external CLI at the supervisor seam. Tests assert observable run, handle, and artifact outcomes rather than adapter internals.
