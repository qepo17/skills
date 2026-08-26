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
5. Close the settled worker by its Herdr `pane_id` (never its `terminal_id`) and record the close result.
6. Record the accepted hash reference and release the lease.
7. Checkpoint the graph superstep.

On replay, existing valid output is accepted rather than repeated. Crash recovery still waits for and closes a surviving worker pane when the artifact was written before the coordinator stopped. Invalid or absent output follows the recorded replacement limit.

## Executable graph

```text
START
  -> reconcile
  -> bootstrap
  -> contract?
  -> plan <-> design challenge / bounded revision
  -> plan_review (dynamic interrupt)
  -> implement (packet scheduler)
  -> validate <-> validation-fix
  -> review_1 -> fix_1?
  -> review_2? -> fix_2?
  -> integrate?
  -> deliver <-> pipeline-fix
  -> report?
  -> complete
  -> END
```

Every phase node returns to `reconcile`. Conditional policy is read from the validated `workflow_policy`; disabled phases are not executed. Repository batches are built lexicographically and handed to the existing concurrent `run-batch` supervisor in one call. `reconcile` also enforces `coordinator_attempt_budget` after an atomic batch and ends the current graph invocation with `budget-checkpoint`; the CLI starts a new bounded invocation automatically when policy enables `auto_resume`, without crossing a human interrupt.

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

The coordinator must discover all affected repositories before initialization and create one clean dedicated worktree per repository. The initializer verifies the `.git` worktree file, actual branch, baseline, and empty initial status, writes requirements and run state, applies the deterministic profile classifier, and validates the result. The graph's bootstrap node then verifies `HERDR_ENV`, Herdr server health, forge remotes, and provider CLI authentication before scheduling a worker. Initialization never copies `.env` files or creates database targets.

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

A pending plan review is a dynamic LangGraph interrupt. Approval must include the exact current hash and the user's exact explicit wording:

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

`scripts/run-orchestrator` invokes `uv run --project`, uses `uv.lock`, and sets `UV_PROJECT_ENVIRONMENT` to `${XDG_CACHE_HOME:-$HOME/.cache}/pi/end-to-end-development/venv` unless already configured. Workers remain Herdr-managed Pi/Codex sessions launched by `workflow_tools.py run-batch`; LangGraph does not replace Herdr or the worker artifact protocol.

## Testing seams

`WorkflowEngine` is the module interface. Production injects the real Herdr batch runner; tests inject an in-process batch adapter. Both exercise the same assignment, validation, transition, retry, and approval implementation. Tests should assert observable run/artifact outcomes through this interface rather than reaching into graph internals.
