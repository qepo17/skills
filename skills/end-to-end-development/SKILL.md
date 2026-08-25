---
name: end-to-end-development
description: Run deterministic, resumable end-to-end development across one or more repositories through a durable LangGraph control plane, risk-proportional gates, explicit approval of the complete plan bundle, bounded work packets and remediation, isolated worktrees, short-lived Herdr workers, and validated artifact handoffs.
disable-model-invocation: true
compatibility: Requires uv, Python 3.11+, Git worktrees, Herdr, Pi or Codex inside Herdr, a repository forge CLI, and the installed codebase-design skill. LangGraph dependencies are installed from the locked skill project.
---

# End-to-End Development

Use the bundled **LangGraph workflow as the sole orchestration engine**. The current Pi/Codex agent performs only request/repository discovery, dedicated-worktree creation, bootstrap-spec construction, presentation of the plan-review interrupt, and concise presentation of terminal status. Do not manually choose phases, construct assignments, supervise workers, manage retries, mutate `run.json`, or bypass graph routing.

Resolve `SKILL_DIR` to this directory. Before a new run or resume, read:

1. [ORCHESTRATION.md](ORCHESTRATION.md) completely;
2. [ARTIFACTS.md](ARTIFACTS.md) completely;
3. [SIMPLICITY-CHALLENGE.md](SIMPLICITY-CHALLENGE.md) only when explaining or diagnosing a challenged plan.

Workers read only their assigned `schemas/<kind>.md`, never the coordinator documents.

## Non-negotiable invariants

1. **One executable state machine.** LangGraph owns phase selection, conditional routing, retries, interrupts, fan-out/fan-in, writer leases, and completion. Never reimplement those decisions in the coordinator conversation.
2. **Evidence is hash-pinned.** A result, validation, finding, blocker, approval, delivery, or next action is known only after it exists in validated durable state or an immutable artifact.
3. **Reconcile before action.** Every graph path starts by reconciling run artifacts with output files and external state. Resume from artifacts, never conversation memory.
4. **Follow the selected policy.** Conditional gates may be skipped only because the validated `workflow_policy` permits it. Profiles can escalate and never silently de-escalate.
5. **One active project-file writer per repository.** The lease protects a role, not an agent identity. Work packets and fix batches preserve it.
6. **Workers do not mutate coordinator state.** They write only their exact output, allowed project files, and log directory. The graph updates run, agent, event, lease, and checkpoint state.
7. **Every loop is bounded.** Worker replacement, planning revision, validation fix, review, and pipeline fix limits are enforced by the graph. Never “continue until green.”
8. **Preserve evidence, not transcripts.** Full output stays in logs. Artifacts contain commands, hashes, exit codes, concise conclusions, and evidence paths.
9. **No silent degradation.** Missing, invalid, oversized, stale-tree, or contradictory evidence leaves the gate incomplete.
10. **Migration safety is mandatory.** The graph must have isolated local/test database-target evidence before migration-capable validation. Never use production, staging, shared, or ambiguous databases; never copy `.env` into a new worktree.
11. **No undeclared high-cost mechanism.** Stop rather than invent a trigger, database function/procedure, backfill, background/event flow, cache, seam/adapter, storage system, or comparable mechanism absent from the approved plan.
12. **Independent review remains mandatory.** Every profile gets at least one fresh baseline-to-worktree review before delivery.
13. **Complete-plan approval is an unconditional hard gate.** Implementation cannot begin until a later user message explicitly approves every plan in the exact current hash-pinned review bundle. Pre-approval, silence, generic continuation, partial approval, and stale-bundle approval do not count.
14. **External side effects are idempotently reconciled.** LangGraph checkpointing does not make workers, commits, pushes, or PR creation exactly-once. Valid existing evidence is recovered instead of repeated.

## Coordinator command interface

Always invoke the locked project through the wrapper, which keeps the generated virtual environment in the user cache rather than the installed skill directory:

```bash
ORCHESTRATOR="$SKILL_DIR/scripts/run-orchestrator"
```

Do not invoke `workflow_tools.py run-batch` directly during a graph-managed run. It is an internal graph primitive.

### New run

Treat skill arguments plus relevant user conversation as the complete request.

1. Discover every affected repository and every material risk before creating run state.
2. Ask the user only when repository identity or a material product choice cannot be established from the request and repository evidence. The later plan-review interrupt is always mandatory.
3. Create one dedicated worktree per repository, preferring Worktrunk:

   ```bash
   wt switch --create <branch> --format json --no-cd
   ```

   The dedicated worktree must be clean. Never copy `.env` or other database credentials into it.
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

The command runs until completion, a validated blocker, or the plan-review LangGraph interrupt.

### Resume

For an explicit run directory:

```bash
"$ORCHESTRATOR" resume <absolute-run-directory> --worker-runtime auto
```

If the user says only “continue,” search the durable root for incomplete runs whose repository roots contain the current directory. Resume only when exactly one matches; otherwise list candidates. If that run is awaiting plan review, **do not call `resume`**: re-present the current bundle and request explicit whole-bundle approval or changes.

Inspect without advancing:

```bash
"$ORCHESTRATOR" status "$RUN_DIR"
```

Never edit `run.json`, `agents.json`, `events.jsonl`, assignments, or LangGraph SQLite state to repair a run. Diagnose the rejected evidence or use a supported CLI transition. `resume` retries blockers classified as environment, authentication, permission, or infrastructure after the external condition is fixed; it never clears code, dependency, or decision blockers.

## Mandatory plan-review interrupt

When the graph returns `status: awaiting-user` and `phase: plan-review`:

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

`fast` is opt-in. `standard` is the automatic low-risk single-repository default. Multiple repositories or authorization, security, concurrency, migration, backfill, background processing, new storage, or another high-cost mechanism force `full`. Planning can escalate the profile when it discovers risk.

| Gate | Fast | Standard | Full |
|---|---|---|---|
| Shared contract | embedded in plan | embedded in plan | worker required |
| Design challenge | none unless discovery escalates | risk-only | every plan |
| Complete-plan user approval | required | required | required |
| Implementation packet | ≤4 tasks | ≤3 tasks | ≤3 tasks |
| Independent full review | one | one | one |
| Targeted second review | never | high-risk fixes | high-risk fixes |
| Cross-repository integration | no | no | required |
| Deterministic HTML report | requested only | requested only | required |

Default retry limits remain:

```json
{
  "worker_replacements_per_stage": 1,
  "contract_revisions": 1,
  "plan_revision_cycles": 1,
  "validation_fix_cycles": 2,
  "review_rounds": 2,
  "pipeline_fix_cycles": 2
}
```

Never modify limits during an active run. The graph checks `coordinator_attempt_budget` after each atomic batch. When reached, it checkpoints at `reconcile`; when `auto_resume` is true the CLI starts a fresh bounded graph invocation from that checkpoint, otherwise it returns `outcome: budget-checkpoint` for a supported later resume. Neither path can cross a pending plan-review interrupt.

## Executable phase behavior

The compiled graph contains these phase nodes, with `reconcile` between every transition:

1. `bootstrap`, verifying `HERDR_ENV`, Herdr server health, Git worktrees, forge remotes, and forge CLI authentication
2. `contract` when policy requires it
3. `plan`, including conditional challenge and one bounded revision
4. `plan-review`, implemented with LangGraph `interrupt()`
5. `implement`, scheduling topologically eligible work packets
6. `validate`, with tree-keyed evidence and bounded validation-fix batches
7. `review-1`
8. `fix-1` when must-fix findings exist
9. `review-2` only when policy and high-risk fixes require targeted verification
10. `fix-2` for one verification-regression batch; never round three
11. `integrate` when policy requires it
12. `deliver`, with bounded pipeline-fix cycles for change-related failures
13. post-delivery current-tree validation
14. `report` when required
15. `complete`, with final audit and deterministic metrics

Repository IDs and stable IDs sort lexicographically. Independent repositories launch together through one supervisor batch. Contract dependency evidence is the only reason to serialize repositories.

### Worker routing

The graph constructs immutable assignments and invokes the supervisor internally. `--worker-runtime auto` follows the coordinator: Codex when `CODEX_THREAD_ID` is present, otherwise Pi, unless `E2E_COORDINATOR_RUNTIME` explicitly overrides it.

Every worker uses `gpt-5.6-luna` with maximum runtime reasoning. Assignment `thinking` remains the policy classification:

- `xhigh`: full contract, planning, design challenge, review, integration;
- `high`: standard planning/review, implementation, complex fixes;
- `medium`: validation, mechanical fixes, delivery, report tooling.

Workers never spawn nested agents.

### Work packets and bounded deviations

The plan defines the packet, not individual task, as the implementation unit. A worker may record a bounded deviation only when it preserves accepted requirements and contract, adds no risk or mechanism, follows repository precedent, remains within the packet concern, and records evidence. A new behavior, contract/interface change, migration, dependency edge, or high-cost mechanism is material and blocks rather than silently replans.

### Validation and review

The graph computes the exact Git worktree fingerprint and reuses passing validation only when validation ID, exact command hash, and tree fingerprint match accepted evidence. Compatible failures are fixed in one batch and checked once afterward.

Round one independently reviews the complete baseline-to-worktree state. Critical/high actionable findings always block; medium correctness/spec findings normally block; low findings remain advisory. Compatible must-fix findings are resolved in one repository batch. Round two is targeted verification only and cannot become another unrestricted review.

### Delivery and completion

Delivery workers may write Git and forge state but not project files. They preserve pre-existing changes, commit only task changes, push, create/update PRs, and monitor required checks. Authentication, permission, and infrastructure failures block rather than churn. Change-related failures use the bounded pipeline-fix path.

Because delivery changes `HEAD`, the graph re-keys validation to the committed tree before completion. Completion then verifies exact plan approval, canonical hashes, current validation, required integration/report evidence, delivery artifacts, no unresolved must-fix finding, no unexplained writer lease, empty actions, and empty blockers. Metrics are generated deterministically.

## Final response

Use the orchestrator JSON output. Keep the final response concise:

- status;
- absolute run directory;
- PR URLs;
- report path/URL when present.

For WSL local HTML, convert the absolute report path to a `file://wsl.localhost/Ubuntu-Shared...` URL on its own line.
