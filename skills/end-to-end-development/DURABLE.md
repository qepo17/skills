# Durable LangGraph mode

Use for an existing run or explicitly selected durable orchestration. Ordinary work follows [DEVELOPMENT.md](DEVELOPMENT.md). Preserve active runs and their recorded policies; do not switch their work into the coordinator workflow.

LangGraph owns assignments, phases, workers, retries, state and completion. The coordinator discovers scope, prepares worktrees/bootstrap, presents decisions, inspects evidence and invokes supported commands. Never patch source or state, manually schedule workers, or call `workflow_tools.py run-batch` inside a managed run.

## Start or resume

Read [ORCHESTRATION.md](ORCHESTRATION.md) for runtime, bootstrap and command contracts and [ARTIFACTS.md](ARTIFACTS.md) for evidence. Load linked recovery schemas only for their matching condition. Workers read their assigned schema and blocker contract, not coordinator guides.

Resolve `SKILL_DIR` to this directory. Durable mode needs the installed `codebase-design` skill; if discovery cannot find it, set `E2E_CODEBASE_DESIGN_DIR` to its directory containing `SKILL.md` and `DEEPENING.md`.

```bash
ORCHESTRATOR="$SKILL_DIR/scripts/run-orchestrator"
```

For a new run:

1. Follow [DISCOVERY.md](DISCOVERY.md), preserving source wording, acceptance IDs and inherited answers. Resolve material choices before initialization; the planner owns detailed design.
2. Discover each remote/default branch or user-selected base. Fetch successfully before creating a new task branch. Create one clean dedicated worktree per repository, preferably with `wt switch --create <branch> --base <remote>/<base> --format json --no-cd`. Preserve supplied task branches/commits/edits; inspect divergence before isolation. Never copy `.env`, reset, discard or automatically rebase work.
3. Write the [bootstrap specification](ORCHESTRATION.md#bootstrap-specification), including intake, outside the empty run directory. Keep durable state under `${HOME}/.local/state/pi/end-to-end-development/<UTC-timestamp>-<slug>/`, never `/tmp`.
4. Initialize and execute:

   ```bash
   "$ORCHESTRATOR" init --spec "$BOOTSTRAP_SPEC" --run-dir "$RUN_DIR"
   "$ORCHESTRATOR" run "$RUN_DIR" --worker-runtime auto
   ```

For an existing run, inspect `status` and use `resume` from the command guide. Preserve its worktrees/baselines. For an unspecified “continue,” search the durable root for incomplete runs covering the current repository; resume only a unique match, otherwise list candidates. Recover intake and later clarification history before asking anything.

## Plan decision

Fast/standard bundles are policy-approved. A full-profile `awaiting-user` / `plan-review` interrupt requires a later explicit whole-bundle approval:

1. Read `plan_review.path` and verify its hash.
2. Present a concise [plan overview](PLAN-WRITING.md) with the bundle path/hash and each repository's tasks, packets, risks and validations. Never rewrite the pinned bundle for presentation.
3. Ask: **“Approve all plans in this exact review bundle, or send the changes you want.”** End the turn; do not invoke generic resume or start source work.
4. Apply the later exact wording through `approve` or `request-changes` in [ORCHESTRATION.md](ORCHESTRATION.md#plan-decisions). The engine rejects generic continuation and stale hashes.

Material implementation choices use the guarded `replan-decision` path and renewed approval within existing budgets. Contract/planning decision blockers have no general answer-to-resume transition; preserve the run and report that limitation.

## Policy and completion

`standard` is the automatic ordinary-work profile; `fast` is opt-in. Authorization, security, concurrency, migration/backfill, background processing, new storage, public-interface changes or high-cost mechanisms force `full`. Multiple repositories alone do not. The engine classifies and can escalate before implementation.

| Gate | Fast | Standard | Full |
| --- | --- | --- | --- |
| Shared contract | Embedded in plan | Multi-repository | Multi-repository |
| Design challenge | Risk-triggered escalation | Risk-only | Risk-only |
| Plan approval | Policy | Policy | Explicit user |
| Tasks per packet | ≤4 | ≤3 | ≤3 |
| Independent full review | One | One | One |
| Integration | No | Multi-repository | Multi-repository |
| HTML report | Requested | Requested | Requested |

Packets last at most 45 minutes. New runs allow one worker replacement per stage, artifact repair per action, contract revision, plan revision cycle, validation-fix cycle, review with one fix batch, and pipeline-fix cycle. No second review follows fixes. Legacy runs retain recorded limits. The [simplicity rubric](SIMPLICITY-CHALLENGE.md) applies when a challenge is required.

The graph enforces one writer per repository, isolated database-target evidence, exact approved scope, immutable artifacts, current checks, review/integration, verified delivery and worker cleanup. Bounded deviations must preserve requirements/contract, add no risk/mechanism, follow precedent and stay within the packet concern. All other changes block. Never change limits or policy versions on an active run.

Use orchestrator output in the final response: status, absolute run directory, latest PR URLs with actual draft/readiness state, warnings/exclusions, remaining action and optional report link. An older success must not hide a newer failure; warnings/exclusions are not “all tests passed.” For WSL HTML, provide the converted `file://wsl.localhost/Ubuntu-Shared...` link.
