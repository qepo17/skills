---
name: end-to-end-development
description: Run deterministic, resumable end-to-end development across one or more repositories through a durable LangGraph control plane, risk-proportional approval and challenge gates, reusable validation evidence, single-pass review and remediation limits, isolated worktrees, auto-detected headless workers, and validated artifact handoffs.
disable-model-invocation: true
compatibility: Requires uv, Python 3.11+, Git worktrees, Pi or Codex, a repository forge CLI, and the installed codebase-design skill. Paseo, Herdr, and tmux are detected automatically when the coordinator runs inside them; otherwise workers run headlessly. LangGraph dependencies are installed from the locked skill project.
---

# End-to-End Development

Use the bundled **LangGraph workflow as the sole orchestration engine**. The current Pi/Codex agent performs request/repository discovery, dedicated-worktree creation, bootstrap-spec construction, presentation of a high-risk plan-review interrupt, read-only evidence inspection, translation of explicit user validation decisions or evidence-backed related-remediation decisions into the typed amendment command, and concise presentation of status. Do not manually choose phases, construct assignments, author source-work instructions, supervise workers, manage retries, mutate run state, or bypass graph routing.

Resolve `SKILL_DIR` to this directory. Before a new run or resume, read:

1. [ORCHESTRATION.md](ORCHESTRATION.md) completely;
2. [ARTIFACTS.md](ARTIFACTS.md) completely;
3. [SIMPLICITY-CHALLENGE.md](SIMPLICITY-CHALLENGE.md) only when explaining or diagnosing a challenged plan.

Workers read their assigned `schemas/<kind>.md` and its linked [blocker contract](schemas/blockers.md), never the coordinator documents.

## Non-negotiable invariants

1. **One executable state machine.** LangGraph owns phase selection, conditional routing, retries, interrupts, fan-out/fan-in, writer leases, and completion. Never reimplement those decisions in the coordinator conversation.
2. **Evidence is hash-pinned.** A result, validation, finding, blocker, approval, delivery, or next action is known only after it exists in validated durable state or an immutable artifact.
3. **Reconcile before action.** Every graph path starts by reconciling run artifacts with output files and external state. Resume from artifacts, never conversation memory.
4. **Follow the selected policy.** Ordinary single- and multi-repository work may use the standard no-pause path. High-risk discovery escalates to full before project-file work.
5. **One active project-file writer per repository.** The lease protects a role, not an agent identity. Work packets and fix batches preserve it.
6. **Workers do not mutate coordinator state.** They write only their exact output, allowed project files, and log directory. The graph updates run, agent, event, lease, and checkpoint state.
7. **Every loop is bounded.** New runs get one review, one review-fix batch, one validation-fix cycle, and one pipeline-fix cycle. Worker replacement and planning revision limits are also enforced by the graph. Never “continue until green.”
8. **Preserve evidence, not transcripts.** Full output stays in logs. Artifacts contain commands, hashes, exit codes, concise conclusions, and evidence paths.
9. **No silent degradation.** Missing, invalid, oversized, stale-tree, or contradictory evidence leaves the gate incomplete.
10. **Migration safety is mandatory.** The graph must have isolated local/test database-target evidence before migration-capable validation. Never use production, staging, shared, or ambiguous databases; never copy `.env` into a new worktree.
11. **No undeclared high-cost mechanism.** Stop rather than invent a trigger, database function/procedure, backfill, background/event flow, cache, seam/adapter, storage system, or comparable mechanism absent from the approved plan.
12. **Independent review remains mandatory.** Every profile gets at least one fresh baseline-to-worktree review before delivery.
13. **High-risk plan approval is a hard gate.** Full-profile implementation cannot begin until a later user message explicitly approves every plan in the exact current hash-pinned review bundle. Fast/standard policy records an automatic hash-pinned decision without pausing; discovery of a high-risk surface invalidates it and escalates before implementation.
14. **External side effects are idempotently reconciled.** LangGraph checkpointing does not make workers, commits, pushes, or PR creation exactly-once. Valid existing evidence is recovered instead of repeated.
15. **Completed worker handles are short-lived.** The supervisor records an opaque backend handle, cleans it as soon as its worker settles and its output is captured, and records the result. Crash recovery uses the pinned backend to apply the same cleanup even when the output artifact already exists. Never report completion while a settled workflow worker remains open.
16. **Policy versions are new-run only.** Initialization pins `validation_policy_version: 1` and `delivery_policy_version: 1`. Missing versions preserve legacy validation, recovery, and delivery behavior. Unknown versions fail; never infer, retrofit, migrate, or add an upgrade switch for an existing run.
17. **Completion and check disposition are distinct.** A worker reports `complete` after its assigned source work and factual check reporting finish even when a check fails. `blocked` means the assigned work could not finish. The engine alone evaluates blocking, advisory, and excluded checks; no decision manufactures a pass.

## Coordinator command interface

The orchestrator resolves the required `codebase-design` skill beside this skill and in common Pi/Codex global skill directories. If it is installed elsewhere, set `E2E_CODEBASE_DESIGN_DIR` to the directory containing its `SKILL.md` and `DEEPENING.md` files.

Always invoke the locked project through the wrapper, which keeps the generated virtual environment in the user cache rather than the installed skill directory:

```bash
ORCHESTRATOR="$SKILL_DIR/scripts/run-orchestrator"
```

Do not invoke `workflow_tools.py run-batch` directly during a graph-managed run. It is an internal graph primitive.

### New run

Treat skill arguments plus relevant user conversation as the complete request.

1. Discover every affected repository and every material risk before creating run state.
2. Ask the user only when repository identity or a material product choice cannot be established from the request and repository evidence. A later plan-review interrupt is mandatory only if policy selects full.
3. **Start from an up-to-date base.** Before creating a new task worktree or planning changes, identify each repository's remote and default branch; do not assume `origin/main`. Fetch the remote and create the task branch from the latest remote default branch (or an explicitly user-selected base). If fetching or resolving the base fails, stop and report it rather than silently using a stale local base. Create one dedicated worktree per repository, preferring Worktrunk and passing the base explicitly:

   ```bash
   git fetch <remote> && \
     wt switch --create <branch> --base <remote>/<default-branch> --format json --no-cd
   ```

   The dedicated worktree must be clean. Never copy `.env` or other database credentials into it. For a supplied existing task branch, inspect status and divergence first and use that branch in an isolated worktree rather than recreating it from the default branch. Preserve existing commits and local changes; never automatically pull, reset, discard, or rebase existing work.
4. Write a bootstrap specification using the exact shape in [ORCHESTRATION.md](ORCHESTRATION.md). Preserve material user wording in requirement source text and acceptance criteria.
5. Choose durable run state under:

   ```text
   ${HOME}/.local/state/pi/end-to-end-development/<UTC-timestamp>-<request-slug>/
   ```

   Never use `/tmp`.
6. Initialize, then execute:

   ```bash
   "$ORCHESTRATOR" init --spec "$BOOTSTRAP_SPEC" --run-dir "$RUN_DIR"
   "$ORCHESTRATOR" run "$RUN_DIR" --worker-runtime auto
   ```

The command runs until completion, a validated blocker, or a full-profile plan-review LangGraph interrupt.

### Resume

The fresh-base rule applies only to new task branches. Preserve the run's existing worktrees, commits, local changes, and recorded baselines; do not recreate branches or automatically pull, reset, discard, or rebase them to catch up with the remote.

For an explicit run directory:

```bash
"$ORCHESTRATOR" resume <absolute-run-directory> --worker-runtime auto
```

If the user says only “continue,” search the durable root for incomplete runs whose repository roots contain the current directory. Resume only when exactly one matches; otherwise list candidates. If that full-profile run is awaiting plan review, **do not call `resume`**: re-present the current bundle and request explicit whole-bundle approval or changes.

Inspect without advancing:

```bash
"$ORCHESTRATOR" status "$RUN_DIR"
```

Never edit `run.json`, `agents.json`, `events.jsonl`, assignments, or LangGraph SQLite state to repair a run. Diagnose the rejected evidence or use a supported CLI transition. For legacy runs, `resume` keeps its historical behavior and the recovery commands below remain legacy-only compatibility paths. For policy-version-1 runs, `resume` may additionally re-observe an identified same-content required-CI blocker through the existing read-only refresh path; it does not clear arbitrary code, dependency, or decision blockers, replay implementation, or spend a fix allowance. If an older engine created a validation assignment without the canonical plan IDs and then emitted the exact validation-coverage blocker, update the engine and use the narrowly guarded recovery command:

```bash
"$ORCHESTRATOR" retry-validation-evidence "$RUN_DIR" --worker-runtime auto
```

This command rejects every other blocker and reruns validation with a new plan-hash-bound assignment; it does not weaken ordinary code-blocker handling.

For an implementation result rejected only because `next_action` exceeds 300 characters, a later explicit user instruction may authorize shortening that field. Preserve the original rejected JSON first and change no other field. Recover through the guarded transition, not by editing run state:

```bash
"$ORCHESTRATOR" retry-corrected-handoff "$RUN_DIR" \
  --original-artifact /absolute/preserved-rejected-result.json \
  --worker-runtime auto
```

It verifies the exact rejection, complete schema, unchanged semantic evidence/current Git state, approved plan and closed handles. It hash-pins original/corrected evidence and accepts once without a worker replay, approval change or retry reset. Failed tests remain failed and ordinary graph routing owns the remaining work. Keep the original backup; do not use this for accepted artifacts or other blockers.

If a dependent fix was started concurrently with an upstream contract fix and stopped on the exact hash-pinned bundle-drift blocker, update the engine and use:

```bash
"$ORCHESTRATOR" retry-dependent-fixes "$RUN_DIR" --worker-runtime auto
```

The guarded transition rejects other dependency blockers, serializes remaining fixes in shared-contract dependency order, grants read-only access to upstream worktrees, and pins accepted upstream fix artifacts into each dependent assignment.

### Scoped validation and remediation decisions

For a policy-version-1 run, inspect `status.amendment_contexts[repo_id]` (the SHA-256 string directly) and `status.eligible_actions`. The coordinator may read the cited evidence and translate either (a) an explicit user instruction to exclude or restore eligible local checks, preserving the user's exact wording, or (b) an evidence-based determination that named local/CI failures are related to the approved change and may use the existing bounded fix path. The coordinator never chooses a graph phase, edits state, patches source, or authors the resulting assignment.

Write the exact request shape documented in [schemas/run-amendment.md](schemas/run-amendment.md), then submit it without a worker-runtime flag:

```bash
"$ORCHESTRATOR" amend "$RUN_DIR" --input /absolute/decision.json
```

`validation-exception` supports only `exclude` and `restore`, `target: local`, `authority: user`, and verbatim non-null `text`. Only supplemental, non-migration checks are eligible. Acceptance, repository-required, and migration-capable checks remain protected. `check-remediation` supports only `fix-related`, `target: local|ci`, `authority: coordinator`, `text: null`, and non-empty reviewed evidence. CI identities use `name@app_id`, or `name@*` when no app ID is pinned. Unknown or unrelated failures grant no source-write authority.

The supplied `expected_context` must exactly match current status. New decisions require an active new run with an approved bundle and settled actions/handles. Identical requests are idempotent even after application or run completion; stale or conflicting requests fail. An exclusion preserves historical failure evidence and omits only future execution of the scoped check. Source-only changes invalidate observations but not the exclusion; plan, contract, requirements, command/cwd, or review-bundle changes expire it. Restoration schedules validation-only refresh where needed. Other blockers and all retry budgets remain intact.

## Implementation decision replanning

A material decision discovered during approved implementation remains blocked until explicitly resolved by the user. With that authorization, use the guarded `replan-decision` transition documented in [ORCHESTRATION.md](ORCHESTRATION.md), pinning the current approved bundle and blocker ID. Preserve exact user wording separately from coordinator context. The transition preserves completed work and evidence, consumes existing revision allowances, invalidates approval, and replans all repositories (shared contract first). It cannot bypass review or authorize numerical proposals. Present the new full bundle and obtain renewed explicit approval before any product writer. Do not substitute `resume`, edit state, or recreate the task.

## Full-profile plan-review interrupt

Fast and standard runs still emit a complete hash-pinned review bundle, but policy accepts it atomically without a user pause. When a full-profile graph returns `status: awaiting-user` and `phase: plan-review`:

1. Read `plan_review.path` and verify the reported SHA-256 still matches.
2. Present the bundle path, hash, and concise per-repository task/packet/risk/validation summaries.
3. Ask exactly: **“Approve all plans in this exact review bundle, or send the changes you want.”**
4. End the turn. Do not create implementation work, edit project files, or invoke a generic resume.

On a later message, approval is valid only when the user's wording explicitly approves the whole current bundle. Preserve that wording exactly:

```bash
"$ORCHESTRATOR" approve "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_APPROVAL" \
  --worker-runtime auto
```

The CLI independently rejects generic continuation and a stale hash.

For requested changes:

```bash
"$ORCHESTRATOR" request-changes "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_FEEDBACK" \
  [--repository <repo-id>] \
  --worker-runtime auto
```

Omit `--repository` when feedback affects the whole bundle. The graph creates a hash-pinned revision basis, returns the affected plans through the bounded planning path, reruns required challenges, emits a new complete bundle, and interrupts again. Any canonical contract, plan, or challenge hash change invalidates prior approval.

## Database-target safety gate

If the graph blocks because a plan contains a migration-capable validation, independently confirm that the target is disposable and isolated. Never print or record the database URL or credentials. Then record only safe classification evidence:

```bash
"$ORCHESTRATOR" database-target "$RUN_DIR" \
  --repository <repo-id> \
  --classification isolated-test \
  --description "Ephemeral database dedicated to this worktree"
```

Allowed classifications are `isolated-local` and `isolated-test`. The command rejects production, staging, shared, and ambiguous targets. Resume through the graph afterward. This evidence does not authorize an unplanned destructive migration, reset, fresh migration, seed, or drop operation.

## Deterministic policy

The initializer applies:

```bash
python3 "$SKILL_DIR/scripts/workflow_tools.py" policy \
  --repository-count <N> \
  [--risk authorization] [--risk database-migration] \
  [--profile auto|fast|standard|full] [--report]
```

`fast` is opt-in. `standard` is the automatic ordinary-work default, including coordinated multi-repository changes. Authorization, security, concurrency, migration, backfill, background processing, new storage, public-interface changes, or another high-cost mechanism force `full`. Planning can escalate before implementation when it discovers risk. Repository count and the `cross-repository` flag alone do not force full.

| Gate | Fast | Standard | Full |
|---|---|---|---|
| Shared contract | embedded in plan | multi-repository only | multi-repository only |
| Design challenge | none unless discovery escalates | risk-only | risk-only |
| Complete-plan user approval | policy-accepted | policy-accepted | explicit user approval |
| Implementation packet | ≤4 tasks | ≤3 tasks | ≤3 tasks |
| Independent full review | one | one | one |
| Targeted second review | never | never | never |
| Cross-repository integration | no | multi-repository only | multi-repository only |
| Deterministic HTML report | requested only | requested only | requested only |

New runs use these hard stage limits:

```json
{
  "worker_replacements_per_stage": 1,
  "artifact_repairs_per_action": 1,
  "contract_revisions": 1,
  "plan_revision_cycles": 1,
  "validation_fix_cycles": 1,
  "review_rounds": 1,
  "pipeline_fix_cycles": 1
}
```

A review may produce one compatible `fix-1` batch, but that fix never starts another review. On validation-policy-version-1 runs, a blocking local or required-CI failure may produce one compatible fix batch only after the coordinator records evidence-backed `fix-related` scope; another failure blocks with preserved evidence. Advisory checks and pending CI never spend these allowances. Legacy runs retain their prior automatic routing. Never modify limits during an active run.

The graph checks `coordinator_attempt_budget` after each atomic batch. When reached, it checkpoints at `reconcile`; when `auto_resume` is true the CLI starts a fresh bounded graph invocation from that checkpoint, otherwise it returns `outcome: budget-checkpoint` for a supported later resume. Neither path can cross a pending plan-review interrupt.

## Executable phase behavior

The compiled graph contains these phase nodes, with `reconcile` between every transition:

1. `bootstrap`, auto-detecting and pinning the worker backend/runtime, then verifying Git worktrees, forge remotes, and forge CLI authentication
2. `contract` when policy requires it
3. `plan`, including conditional challenge and one bounded revision
4. `plan-review`, implemented with LangGraph `interrupt()` only for full; fast/standard records a policy decision and proceeds
5. `implement`, scheduling topologically eligible work packets
6. `validate`, with at most one validation-fix batch
7. `review-1`
8. `fix-1` when must-fix findings exist, with no follow-up review cycle
9. `integrate` when policy requires it
10. `deliver`, with at most one pipeline-fix batch for change-related failures
11. post-delivery content-evidence confirmation
12. `report` when required
13. `complete`, with final audit and deterministic metrics

The graph retains `review-2` and `fix-2` nodes only so older durable runs with a pinned two-round limit can resume safely. New runs never schedule them.

Repository IDs and stable IDs sort lexicographically. Independent repositories launch together through one supervisor batch. Contract dependency evidence is the only reason to serialize repositories.

### Worker routing

The graph constructs immutable assignments and invokes the supervisor internally. Users do not configure a terminal manager. Bootstrap selects the first positively detected active environment in this order: a reachable Paseo parent from `PASEO_AGENT_ID`, a compatible Herdr server from `HERDR_ENV`, the active tmux session from `TMUX`, then the always-available direct headless backend. `PASEO_HOST` alone never selects remote workers because remote paths may not match the coordinator's hash-pinned paths. The selected backend and evidence are pinned in `run.json` for recovery.

`--worker-runtime auto` inherits a Paseo parent's Pi/Codex provider when present, otherwise follows the coordinator: Codex when `CODEX_THREAD_ID` is present and Pi by default. `E2E_COORDINATOR_RUNTIME` remains an internal diagnostic override, not required user setup.

Workers keep `gpt-6-astra`. New runs pin `worker_reasoning_policy: stage-v1`: `xhigh` for full-profile contract/planning/challenge/review/integration; `high` for ordinary planning/review and all source-writing implementation/fixes; `medium` for artifact-only repair, validation-only work, and fallback delivery. Launchers honor the actual level across every backend. Legacy runs without a pinned stage policy retain xhigh, and surviving handles retain their recorded configuration. Unsupported configuration blocks; never silently substitute a model.

Workers never spawn nested agents. A Paseo coordinator creates Paseo subagents, Herdr creates non-focused workspaces, tmux creates detached windows, and direct mode runs non-interactively without a terminal manager. The supervisor archives or closes each settled handle immediately after capturing its artifact result, including rejected artifacts; working, blocked, and timed-out workers are retained for diagnosis.

### Artifact-only recovery

Workers should use the typed `artifact_guard.py block` command and [blocker schema](schemas/blockers.md). In new runs, a parseable blocked result missing only `blockers[*].kind` receives at most one five-minute, medium-reasoning artifact-only repair. It has a new immutable assignment/output, no project/Git/forge write permission, and pinned original semantics, logs, content, HEAD, branch, and index. It cannot manufacture a pass, rewrite evidence, or start another source writer. Ambiguous/invalid repair and stale evidence block with an actionable explanation. Missing files or process failures remain distinct from eligible schema repair. Resume never resets the allowance; legacy runs retain their existing policy.

### Work packets and bounded deviations

The plan defines the packet, not individual task, as the implementation unit. A worker may record a bounded deviation only when it preserves accepted requirements and contract, adds no risk or mechanism, follows repository precedent, remains within the packet concern, and records evidence. A new behavior, contract/interface change, migration, dependency edge, or high-cost mechanism is material and blocks rather than silently replans.

### Validation and review

For policy-version-1 plans, every validation declares `purpose: acceptance|repository-required|supplemental`, `gate: blocking|advisory`, and a concise `rationale`. Acceptance and repository-required checks must be blocking; migration-capable checks remain protected regardless of classification. Every task names at least one blocking acceptance validation. `scope` still describes breadth and is not waiver authority. Only supplemental non-migration checks can be explicitly excluded.

The graph computes a content fingerprint independent of commit identity. The final implementation/fix writer runs the complete effective suite, and the graph reuses evidence only when validation ID, exact command and cwd, current plan, content fingerprint, and acceptance-time log hash match. A delivery-only commit therefore causes no duplicate validation; a source change invalidates observations without invalidating a still-current exclusion. Predeclared advisory failures become warnings and never block, launch a fix, or spend the fix budget. Excluded checks are omitted from future commands and reported as `not-run`/excluded when there is no current observation; an older failure remains failed. A blocking failure is fixed only after evidence-backed `fix-related` authorization and within the existing one-cycle budget.

One fresh worker independently reviews the complete baseline-to-worktree state. Critical/high actionable findings always block; medium correctness/spec findings normally block; low findings remain advisory. Compatible must-fix findings are resolved in one repository batch, affected checks run once, and the workflow proceeds without a second review. An incompatible or still-failing correction blocks instead of opening another remediation loop.

### Delivery and completion

New GitHub.com runs pin a deterministic command executor using [scripts/delivery_tools.py](scripts/delivery_tools.py), not a delivery agent, and supply `pr_lifecycle: draft-until-verified` plus the run identity. After local, review, and integration gates are satisfied it audits the explicit task inventory, preserves unrelated work, commits/pushes without force, creates a run-owned draft, and checks CI against the local/pushed/PR head. Its latest PR URL and actual `pr_draft`/`pr_owned` state remain visible even when delivery is pending or blocked. Command intents are durable and recovered without worker handles; independent repositories can execute delivery concurrently. Other forges use fallback workers with the same draft/evidence obligations or report unsupported draft behavior. Legacy assignments and helper inputs without the policy retain their pinned worker/ready-PR behavior.

Version-2 delivery evidence requires positive required-check policy discovery, the final checked head, and every required identity passing. An empty rollup is not a waiver: verified absence is `not-configured`, never "CI passed." Pending/missing/timed-out, skipped/cancelled, changed-head/policy, or unknown-policy results cannot complete. `required-ci-failed` and `required-ci-pending` are factual latest outcomes, not automatic repair authority; only a coordinator `fix-related` decision may spend the existing pipeline-fix cycle. A green run-owned draft observed with `verify_only` returns `publication-required`; only a normal engine-authorized delivery action may publish it. `verify_only` never commits, pushes, creates, edits, or marks a PR ready. Existing user-owned drafts are preserved and may verify complete while still draft, with no misleading ready claim. Bootstrap can set a repository's `delivery_check_timeout_seconds` from 0 (observe once) to 1800 (default). This is a CI polling limit, not a whole-run deadline.

After delivery, the graph verifies that the committed content still matches passing evidence rather than invalidating it merely because `HEAD` changed. Completion then verifies the policy-selected plan decision, canonical hashes, current validation, required integration/report evidence, delivery artifacts, no unresolved must-fix finding, no unexplained writer lease, no open workflow worker handle, empty actions, and empty blockers. Metrics are generated deterministically, counting command attempts separately from agent launches. Do not infer elapsed-time improvements from mocked worker counts.

## Final response

Use the orchestrator JSON output. Keep the final response concise:

- status;
- absolute run directory;
- every known latest PR URL plus delivery readiness and actual draft state, including pending/blocked delivery;
- local-gate warnings/exclusions and supported next decision when present;
- report path/URL when present.

Never replace “completed with warnings/exclusions” with “all tests passed,” and never let an older successful delivery observation hide a newer failure.

For WSL local HTML, convert the absolute report path to a `file://wsl.localhost/Ubuntu-Shared...` URL on its own line.
