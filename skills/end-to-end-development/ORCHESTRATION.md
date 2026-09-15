# LangGraph orchestration

LangGraph alone advances durable runs. The coordinator discovers scope, prepares bootstrap, presents decisions, inspects evidence and submits supported commands; it never authors assignments, patches source, manages retries or edits state.

## Authority model

`langgraph.sqlite` stores the cursor/interrupt; `run.json.phase` is the canonical routing projection. Git, forge state, assignments, accepted artifacts and agent records supply evidence. Every invocation begins with reconciliation. New runs pin validation/delivery policy version 1; missing fields retain legacy behavior and unknown versions fail. Never retrofit active runs.

A run lock serializes advancing invocations; a short-held lock protects projections. Side effects follow durable intent → writer lease → execution → artifact validation → settled-worker cleanup → acceptance/release → checkpoint. The coordinator computes mechanical hashes/Git metadata; workers report semantics and actual check outcomes.

On replay, reconcile outstanding intent before scheduling: pending may already be launched, and partial later-packet writes can stale predecessor evidence. Reuse accepted output unchanged. Accept unaccepted output only after its original worker settles and cleans. Adopt its recorded backend handle; never overwrite it or replace a timed-out writer with unknown cleanup. Retain its action/lease/one-shot claim. A matching late exit status or live Herdr `done` observation can permit cleanup, then ordinary bounded replacement if output is invalid. New actions use separate output/log paths.

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

### Source intake and question history

For new skill-driven runs, add `intake` to the bootstrap specification. It is optional at the engine interface for compatibility; absent intake does not add a migration, phase, approval, or retry policy. Follow [DISCOVERY.md](DISCOVERY.md). The request stays verbatim; intake separates source snapshots from interpretation:

```json
{
  "intake": {
    "sources": [{
      "reference": "Jira APP-123, supplied snapshot, updated 2026-09-07",
      "text": "AC-1: Archived rates must not appear in the selector."
    }],
    "codebase_evidence": ["api at baseline <sha>: src/rates.py:list_rates currently includes archived rows; tests/test_rates.py covers active rows."],
    "recommendations": ["Agent recommendation: extend the existing selector filter and focused tests rather than add a new service; follows src/rates.py precedent."],
    "question_limit": 10,
    "questions": []
  }
}
```

All five fields are required when intake is present. `sources` must be non-empty, with non-empty `reference` (at most 2,000 characters) and `text` (at most 12,000). `codebase_evidence` and `recommendations` are unique string arrays and may be empty. The enclosing requirements artifact retains its 64 KiB limit. Capture only relevant excerpts without secrets; cite source/revision and preserve original acceptance IDs. For a direct request, use a descriptive conversation reference. For a reused spec, capture the applicable version and implementation delta rather than duplicate the entire document.

`question_limit` is an integer 0–10 honoring lower user limits. Each ordered cumulative `questions` entry has `question` (≤2,000 characters) and non-empty `resolution` (≤4,000), preserving user wording or labelling evidence-based resolution. Resolve material choices before initialization; keep unresolved drafts outside the empty run directory.

Optional `prior_question_count` defaults to 0 and identifies the already-asked prefix, bounded by ledger length. Record provenance and lower-limit preferences in `sources`; never relabel new questions as inherited. Total entries must not exceed `max(question_limit, prior_question_count)`; remaining permission is `max(0, question_limit - len(questions))`. Two prior answers followed by “no more interview” therefore use limit 0, prior count 2 and both entries. Preserve/disclose historical overruns without blocking otherwise-ready work or granting more questions.

Initialization validates intake before creating state and pins it in `requirements.json`. Workers use that canonical input; planning follows [schemas/plan.md](schemas/plan.md), review follows [schemas/review.md](schemas/review.md). No extra research/spec/ticket stage is created.

After initialization, append questions before presentation and answers afterward to `logs/clarifications.md`, including later lower-limit preferences. Count intake plus later questions under the lowest applicable cap; recover missing history before asking. This interaction log cannot alter requirements, approval or gates. Apply answers only through supported transitions. Contract/planning decision blockers lack a general recovery path; preserve them and report the limitation. Any explicitly authorized replacement run must retain work and source/decision/question history. The engine checks intake bounds; the coordinator enforces semantic counting and later limits.

An optional repository `delivery_check_timeout_seconds` is an integer from 0 (one observation) to 1800 (default); it bounds CI polling only. Initialization pins GitHub.com delivery to the command executor, other forges to workers, new delivery evidence to version 2, and delivery-policy version 1 to the `draft-until-verified` lifecycle with its run identity. Fallback workers receive the same lifecycle/evidence obligations and must report unsupported draft creation or draft-only CI rather than silently creating a ready PR or polling forever.

The coordinator must discover all affected repositories before initialization and create one clean dedicated worktree per repository. The initializer verifies the `.git` worktree file, actual branch, baseline, and empty initial status, writes requirements and run state, applies the deterministic profile classifier, and validates the result. The graph's bootstrap node then detects and pins the active worker environment, verifies its positive probe, and checks forge remotes and provider CLI authentication before scheduling a worker. Initialization never copies `.env` files or creates database targets.

Worker detection requires a positive active-context probe, in order: Paseo parent (`PASEO_AGENT_ID`), Herdr (`HERDR_ENV=1`), tmux (`TMUX`), then direct. Stale markers fall through. `PASEO_HOST` alone cannot select a remote filesystem for local pinned paths.

### Worker permission boundary

New direct/tmux/Herdr Codex workers use `workspace-write`, extra writable roots restricted to the run directory, normal temporary allowances, disabled shell network and `never` approval. Denied operations fail; this is not unrestricted execution. Pi retains host controls. Access does not authorize every writable file, and the sandbox does not cover every model tool/read; keep secrets out and retrieved inputs untrusted.

**New Paseo Codex launches are blocked**, including preflight, previews and actual launches. [Provider configuration overrides mode presets](https://github.com/getpaseo/paseo/blob/main/packages/server/src/server/agent/providers/codex-app-server-agent.ts), [run](https://github.com/getpaseo/paseo/blob/main/packages/cli/src/commands/agent/run.ts) submits the prompt during creation, and [inspect](https://github.com/getpaseo/paseo/blob/main/packages/cli/src/commands/agent/inspect.ts) shows mode rather than effective permissions. No parent probe, label or operator assertion proves child permissions before execution; send no exploratory prompt.

Paseo Pi remains supported. A separately authorized new Codex run may use another supported active backend; never silently switch an existing run's pinned backend/runtime. Existing Paseo Codex handles can be adopted/waited/archived, but not replaced. Restoring launches requires backend-enforced permissions or prompt-free creation with effective-policy verification.

Report denied Git/dependency/network/check operations for scoped operator action, without disabling protections or switching runtime to evade controls. Adopting a live worker preserves its permissions and lifecycle evidence; settle it before protected replacement.

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

Read [schemas/run-amendment.md](schemas/run-amendment.md) for the exact request, authority, context and evidence contract, then invoke:

```bash
"$ORCHESTRATOR" amend "$RUN_DIR" --input /absolute/decision.json
```

Only version-1 active runs accept new amendments. User-authorized exclusions/restorations target supplemental non-migration local checks; coordinator `fix-related` decisions require reviewed evidence of current task-related local/CI failure within approved scope and budget. Use the exact current status context; never refresh stale decisions automatically. Atomic amendments preserve failed observations, untargeted blockers and limits. Identical requests return `already-applied` even after completion.

## Recovery commands

Use only the matching documented condition. Preserve reviewed hashes, original evidence, approval and budgets; never edit state or generalize a recovery to other blockers.

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

### Incident recovery index

Read the linked full contract before preparing or submitting its request; each requires explicit scoped authorization.

| Condition | Command and contract |
| --- | --- |
| Code-blocked implementation rejected only for overlong `next_action`, then authorized test-fixture repair/forward base update | [`recover-external-repair`](schemas/external-repair-recovery.md): fresh read-only packet verification |
| Lost later-packet intent after proven local reboot, initializer output and stale predecessor checks | [`recover-interrupted-packet`](schemas/interrupted-packet-recovery.md): one remaining budgeted replacement; separate host-origin confirmation |
| Protected process metadata prevents interrupted-packet admission | [One-time privileged inspection](schemas/privileged-process-inspection.md): separately authorized read-only helper, never elevated orchestration |
| Exact overlapping Herdr writer incident with overwritten accepted blocked output | [`recover-writer-incident`](schemas/writer-incident-recovery.md): quarantine unavailable reference and freshly verify combined source |

These transitions neither accept historical failures as passes nor replay source blindly. Preserve original source/artifacts, require fresh checks, and continue remaining validation/review/integration/delivery through LangGraph. `--no-drive`, where supported, permits inspection before graph execution. Do not apply live recovery or install engine changes without authorization.

## Plan decisions

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

Delivery requires current content/HEAD, canonical meaning, amendments and review provenance. Later bounded fixes/policy amendments retain a historical review; never claim independent review of the final revision. Required integration refreshes against current writers/meaning/amendments; reports refresh without overwriting historical evidence.

GitHub uses command assignments and durable input/output/log evidence, with no agent handles; other forges retain workers. Independent deliveries may run concurrently. Follow [schemas/delivery.md](schemas/delivery.md) for exact ownership, draft, CI and output contracts. Version 1 uses a nonce-bound run-owned draft after local/review/integration gates; human edits and user-owned readiness are preserved.

Cold recovery schedules read-only `verify_only` refresh. A verified owned draft yields `publication-required`; only a normal delivery action can publish it, then re-observe required policy/checks. Pending CI spends no fix allowance; failed CI needs a scoped `fix-related` amendment. Version-2 results require matching local/pushed/checked heads and positively discovered policy. Unknown, skipped/cancelled, changed-head/policy, unsupported draft-only CI or publication failure blocks.

`pending_delivery_refresh` survives active peer actions and drains afterward. Before acceptance, recovery preserves action snapshots; after acceptance, use a new assignment/output. A ready PR remains ready during read-only refresh even if checks regress. Completion audits canonical approval, current checks/integration/report/delivery, unchanged validated content, resolved must-fix findings, empty actions/blockers/leases and cleaned workers. Metrics distinguish command attempts from worker launches; counts do not measure elapsed speedup.

## Testing seams

`WorkflowEngine` is the graph module interface. `WorkerSupervisor` is the execution module interface shared by direct, Paseo, Herdr, and tmux adapters. Production uses auto-detection; tests inject an in-process batch adapter or fake external CLI at the supervisor seam. Tests assert observable run, handle, and artifact outcomes rather than adapter internals.
