# LangGraph orchestration

LangGraph is the only executable control-flow engine for this skill. The Pi/Codex coordinator performs repository discovery and translates that evidence into a bootstrap specification; it does not choose phases, construct worker assignments, launch batches, manage retries, or mutate run state after initialization.

## Authority model

There is one state machine and two durable fact classes:

1. `${RUN_DIR}/langgraph.sqlite` stores LangGraph's execution cursor and interrupt state.
2. `run.json`, `agents.json`, immutable assignments, accepted worker artifacts, Git, and forge state store workflow facts and evidence.

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

An optional repository `delivery_check_timeout_seconds` is an integer from 0 (one observation) to 1800 (default); it bounds CI polling only. Initialization pins GitHub.com delivery to the command executor, other forges to workers, and new delivery evidence to version 2.

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

Resume ordinary recoverable execution:

```bash
"$ORCHESTRATOR" resume "$RUN_DIR" --worker-runtime auto
```

After updating an engine that emitted the exact validation-coverage blocker from an ID-less validation assignment, use the guarded recovery transition:

```bash
"$ORCHESTRATOR" retry-validation-evidence "$RUN_DIR" --worker-runtime auto
```

It accepts only that exact validate-phase blocker and creates a new assignment bound to the canonical plan hash and validation IDs. It does not clear other code, dependency, or decision blockers.

For the exact result rejection `$.next_action: must be at most 300 characters` emitted before oversized-handoff repair was supported:

```bash
"$ORCHESTRATOR" retry-artifact-repair "$RUN_DIR" --worker-runtime auto
```

This requires a pinned unused repair allowance, no active actions/writers or unsettled worker cleanup, the original rejection manifest/assignment, and still-current content/HEAD/branch/status evidence. It pins the original artifact and evidence into a read-only repair before clearing the blocker. It never normalizes stale validation evidence onto a changed tree, resets attempts, clears unrelated blockers, or bypasses review/delivery. A crash before launch reuses the saved repair; a claimed attempt is never relaunched.

For a saved exhausted validation gate whose sole pending check is the coordinator-owned whitespace check:

```bash
"$ORCHESTRATOR" retry-coordinator-validation "$RUN_DIR" --worker-runtime auto
```

The transition requires approved plans, the exact exhaustion blocker and accepted source evidence, unchanged content/HEAD/branch/status, settled workers, and a consumed no-change permission-blocked fix containing only pending `git diff --check` evidence. It records a hash-pinned command assignment in `coordinator_validation_recoveries` before advancing. It neither resets the code-fix limit nor reopens approval, and it rejects genuinely failed checks and unrelated blockers. Plain logs cannot establish acceptance; the graph captures its own bounded read-only execution. UI handoff rejection uses the separate `retry-artifact-repair` transition.

After updating an engine that ran a dependent fix concurrently with an upstream contract fix and emitted the exact hash-pinned bundle-drift blocker, use:

```bash
"$ORCHESTRATOR" retry-dependent-fixes "$RUN_DIR" --worker-runtime auto
```

This guarded transition accepts only that fix-phase blocker. Remaining fixes follow the shared contract's dependency order, receive accepted upstream fix artifacts as hash-pinned inputs, and get read-only access to upstream worktrees.

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

Worker schemas link a concise blocker contract and typed construction command. Rejections carry an error code and field path through both acceptance seams. Runs with a pinned repair allowance permit one artifact-only correction of a parseable result with only missing blocker kinds and/or `next_action` text longer than 300 characters. The advisory text may be shortened to at most 300 characters or set to null; valid existing text and every semantic result field remain unchanged. The graph persists a derived read-only assignment/output and binds the original payload, referenced evidence, content, HEAD, branch, and index. A persisted launch claim prevents a failed/missing repair output from starting another attempt after a crash. Repair never changes outcomes, reruns validation, resets retries, or falls back to another source writer. Unsupported/ambiguous repairs and stale evidence remain blocked. Explicit external-condition resume after a valid blocked repair is distinct from crash recovery.

GitHub delivery assignments use `execution_mode: command` with normal durable `next_actions`; they never create agent records or backend handles. The graph executes the standard-library helper, records immutable input/output evidence, and reconciles Git/forge state after interruption. Independent command deliveries and remaining forge workers can run concurrently. The graph's cold-entry `recover` node refreshes completed delivery through read-only commands; ordinary phase reconciliation does not repeat those queries endlessly. Hash-pinned refresh obligations survive active peer actions and drain after the existing batch settles, so a pending fix in one repository cannot hide stale delivery in another. Recovery before acceptance re-observes the forge without commit/push/PR writes, retaining earlier snapshots; recovery after acceptance uses a new assignment/output. Recovered CI failures retain the same bounded fix route. Version-2 results require matching local/pushed/checked heads and positive required-check policy evidence. A changing policy/head invalidates the observation. Pending CI is not completion and never spends the code-fix allowance. Other forges retain an explicit worker path with equivalent evidence requirements; unknown policy blocks rather than silently downgrading.

Delivery and worker policies are version-pinned at initialization. Existing runs without those extension fields keep their historical delivery/retry policies. The narrowly allowlisted coordinator validation executor is pinned in each new immutable command assignment, including explicit recovery of a legacy exhausted gate; it does not retrofit limits or worker policy. Do not retrofit active runs by editing state.

### Coordinator-owned validation

A `not-run` record never justifies a source fix. When a complete current result covers every planned ID/command and all non-whitespace checks pass, the graph can fill a pending exact `git diff --check` through [scripts/coordinator_validation.py](scripts/coordinator_validation.py). This command assignment runs without an agent, Git/forge write access, shell interpretation, or migration execution. It captures exit status, a hashed log, and content/HEAD/branch/index state; a new deterministic result reuses the prior passing records unchanged except for their reuse provenance. A durable assignment digest is verified before execution/reconciliation, and the assignment must pin every source evidence file; neither the assignment nor unrelated semantic result fields may be rewritten during recovery. Actual failures retain the ordinary bounded code-fix gate, including exhaustion. Other pending checks block without consuming that allowance.

Command evidence surviving a crash is reused before reconstructing the output; a valid output is reconciled without re-execution or delivery-specific forge refresh. A crash before command capture can repeat only this read-only check. Invalid, changed, or missing evidence never becomes a pass or a replacement source writer.

## Testing seams

`WorkflowEngine` is the graph module interface. `WorkerSupervisor` is the execution module interface shared by direct, Paseo, Herdr, and tmux adapters. Production uses auto-detection; tests inject an in-process batch adapter or fake external CLI at the supervisor seam. Tests assert observable run, handle, and artifact outcomes rather than adapter internals.
