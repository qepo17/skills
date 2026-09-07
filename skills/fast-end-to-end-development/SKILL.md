---
name: fast-end-to-end-development
description: "Take an existing ticket, spec, or request through grounded implementation planning, coding, one independent review/revision, and verified PR delivery. Ask only essential evidence-unresolved questions, at most 10 per task. Use for ordinary single-repository changes without durable orchestration, high-risk approval, or multi-repository integration."
---

# Fast End-to-End Development

Use this skill for a small or medium change that should move from request to pull request in one bounded pass:

`ticket / spec / request → grounded implementation spec → implement + validate → review once → revise once → PR + required CI → [CI fix once] → [optional HTML explainer]`

Read [DISCOVERY.md](DISCOVERY.md) before intake/planning. Reuse existing tickets and specs; never require `idea-to-ticket` or a `to-tickets` stage. `plan.md` is the compact implementation spec, not an additional document.

The current agent owns the run. Keep the process fast by removing Herdr worker orchestration, multi-profile policy selection, mandatory plan-approval pauses, integration workers, and retry loops. Keep the safety that matters: preserve pre-existing work, inspect repository instructions, record evidence, use a fresh reviewer, cap remediation at one batch, and stop on material ambiguity or high-risk scope.

Resolve `SKILL_DIR` to this skill's directory. Set `RUN_DIR` to the run directory created below and pass absolute paths to the renderer.

## Agent runtime

Keep `gpt-6-astra` as the subagent model. Use `high` for independent review and any delegated planning/coding/fixes; use `medium` only for exceptional read-only artifact assistance. The active coordinator retains the user's runtime settings. Normally it owns planning, implementation, fixes, and all mechanical commands, delegating only the one fresh reviewer. Never start an agent just to run Git, wait for checks, write delivery prose, or render HTML.

For Codex pass `model_reasoning_effort="high"`; for Pi use `--model openai-codex/gpt-6-astra --thinking high` (substitute `medium` only for read-only assistance). Unsupported runtime configuration is an explicit environment blocker; do not silently substitute a model or reasoning level.

## Herdr pane lifecycle

When this workflow creates an agent pane through Herdr, record the returned `pane_id` separately from any `terminal_id`. As soon as that agent settles and its required result has been captured, close the workflow-created pane with `herdr pane close <pane_id>` and verify the command succeeds. Do this after planning, review, delivery, or any other delegated stage rather than leaving completed panes visible until the final handoff.

Before reporting completion, account for every Herdr pane created by this run and close any remaining settled pane. Never close the coordinator pane, a pre-existing user pane, or a pane that is still working, blocked, or needed to diagnose a timeout. If a completed pane cannot be closed, report pane cleanup as a blocker instead of making the user infer which pane is still active.

## Scope gate

Use the fast path for one repository and ordinary application changes. Before editing:

- Escalate to `end-to-end-development` for multiple repositories or changes involving authorization, security-sensitive code, database migrations or backfills, destructive data operations, concurrency/distributed behavior, background processing, new storage, public contracts, or another high-cost mechanism.
- Research before asking; adopt evidence-backed, reversible, in-scope recommendations without routine confirmation. Ask only unresolved material questions under the shared task-wide cap of 10 in [DISCOVERY.md](DISCOVERY.md), including inherited questions and follow-ups. Zero is valid. Do not pause merely for plan approval or guess to bypass a safety gate.
- Read repository-local instructions (`AGENTS.md`, `CONTRIBUTING.md`, `README`, package/build configuration, and relevant nested instructions) before planning.
- Verify Python 3.11+, Git, and authenticated forge access before implementation. GitHub delivery uses the bundled helper and `gh`; other forges use their established CLI with the same final-head evidence requirements.
- Never copy `.env` or database credentials into a worktree. Escalate migration-capable validation to the durable workflow and confirm an isolated local/test target before execution.

## Durable run record

Create a run directory outside the repository before changing code:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/codex/fast-end-to-end-development/<UTC-timestamp>-<request-slug>/
```

Keep concise evidence there; keep full command output in a `logs/` child directory. Write these files as stages complete:

| File | Required contents |
| --- | --- |
| `request.md` | User wording, resolved scope, ticket/spec reference and material snapshot, inherited decisions, and clarification ledger (limit, every question/resolution, count) |
| `plan.md` | Compact spec synthesis: problem/solution, relevant stories and acceptance IDs, implementation/testing decisions, non-goals, baseline evidence, vertical slices/dependencies, and checks |
| `implementation.md` | What changed, changed-file inventory, and pre-review checks |
| `review.md` | Exactly one independent review, findings, severity, and evidence |
| `revision.md` | Finding dispositions, any fixes, and post-revision checks |
| `delivery.md` | Final commit, branch, PR URL, checked head, required-check policy, and terminal check state |
| `delivery-input-N.json` / `delivery-output-N.json` | Immutable inputs and evidence for each scripted GitHub delivery attempt |
| `ci-revision.md` | When needed: the single CI-fix batch, failure classification, changed files, and revalidation |
| `pr-explainer.json` | When requested: sanitized structured input for the HTML renderer |
| `pr-explainer.html` | When requested: self-contained human-readable PR explainer |

Create `request.md` before asking any clarification; append questions before presenting them and resolutions afterward. Preserve source excerpts separately from interpretation. On continuation/escalation, hand off the existing question ledger and limit rather than starting a new interview. If a supplied spec is adequate, reference its captured version and add only the repository-grounded implementation delta in `plan.md`.

Do not put secrets, environment values, full diffs, or unbounded terminal transcripts in these artifacts. Record commands, exit codes, short conclusions, hashes, and paths instead.

## Invariants

- Capture `git status --short` and the baseline commit before editing. Preserve unrelated user changes; never use `reset --hard`, `clean`, broad checkout, or an overwrite to make the tree convenient.
- **Start from an up-to-date base.** Before creating a new task worktree or planning changes, identify the repository's remote and default branch; do not assume `origin/main`. Run `git fetch <remote>` and create the task branch from the latest remote default branch (or an explicitly user-selected base). If fetching or resolving the base fails, stop and report it rather than silently using a stale local base.
- Always use a clean dedicated task worktree and branch, preferring Worktrunk. For a new task branch, pass the fetched base explicitly: `wt switch --create <branch> --base <remote>/<default-branch> --format json --no-cd`. Preserve the original checkout and never bring credentials into the worktree.
- The fresh-base rule applies only to new task branches. For a supplied existing task branch or continued run, inspect status and divergence first and use that branch in an isolated worktree rather than recreating it from the default branch. Preserve existing commits, local changes, and recorded baselines; never automatically pull, reset, discard, or rebase existing work.
- Keep one project-file writer. Do not let a reviewer or delivery step edit source files.
- Close every workflow-created Herdr pane immediately after its agent settles and its result is captured; retain only working, blocked, or timed-out panes that still need attention.
- Treat the plan as the implementation contract. A simpler equivalent change or focused test is allowed; a new high-cost mechanism, public contract, migration, or unrelated refactor requires escalation.
- Perform at most one independent review and one review-revision batch. A no-op revision is valid when there are no `must-fix` findings. A separate CI-fix batch is allowed once; neither fix starts another full review.
- Create the PR only after review/revision and required local checks pass. Completion additionally requires the final-head CI gate. Pending checks are not success; a second change-related CI failure or incompatible correction blocks.
- For UI changes, inspect the running interface with browser tooling and record interaction/visual evidence. Tests or an implementer's claim alone do not satisfy this gate.
- Keep the HTML explainer derived from accepted artifacts, not from memory or raw transcripts.

## Workflow

### 1. Grounded implementation spec by the agent

Combine focused discovery and planning in one pass using [DISCOVERY.md](DISCOVERY.md). Inspect the source ticket/spec/request, current baseline, relevant code path and tests, and delivery configuration. Reuse captured evidence instead of rereading the whole repository in separate research/spec/ticket stages. Establish:

- the exact baseline commit and task branch;
- the user's problem/solution and meaningful user stories linked to original acceptance IDs, using the domain glossary and respecting applicable ADRs;
- current behavior with paths/symbols and relevant documentation evidence in a baseline-bound execution section, separate from durable spec prose;
- settled implementation decisions, the smallest suitable approach and rationale, meaningful edge/error cases, and independently verifiable vertical slices with genuine blocking dependencies;
- explicit testing decisions: externally observable behavior at the highest practical existing seam, modules exercised, similar tests as prior art, and focused/broad validation commands;
- evidence-backed recommendations, risks, non-goals, and any unresolved material decision.

Synthesize settled context into `plan.md` using the compact `to-spec`-inspired structure in [DISCOVERY.md](DISCOVERY.md); no separate spec, exhaustive story list, published tickets, routine test-seam confirmation, or breakdown-approval quiz is required. Put slice title/outcome, acceptance/verification, and `blocked by` in a small checklist and work the eligible frontier. Prefactor only when necessary and behavior-preserving. Wide refactors may need expand–contract; if the work exceeds fast scope/limits or requires unsafe intermediate steps, escalate rather than invent an integration branch or waive checks. Do not treat recommended product changes as user decisions. Stop on unresolved material ambiguity, even if the question budget is exhausted. If the tree is dirty, identify which changes predate the run and carry that inventory into `implementation.md` and `delivery.md`.

### 2. Implement

Implement the approved-by-the-agent plan in the task branch. Follow existing patterns, keep the diff narrow, and add or update focused tests with the behavior. Do not introduce an undeclared mechanism merely to avoid asking a question.

Run `git diff --check`, focused tests, and relevant broader checks in one validation pass. Record commands, exit codes, and browser evidence when applicable in `implementation.md`. After passing checks, record the content identity with `python3 "$SKILL_DIR/scripts/delivery_tools.py" fingerprint <worktree>`. Reuse evidence only while that identity is unchanged; rerun affected/broad checks after a fix and pin the new identity. Stop on an environment/dependency failure rather than presenting it as a code result.

### 3. Review once

Run one fresh, independent review against the baseline-to-current diff. Give the reviewer `request.md` (including original ticket/spec excerpts and decisions), `plan.md`, the acceptance criteria, repository instructions, changed-file inventory, and the diff; do not give it the implementer's conclusions. Review both standards and the original source plus implementation spec: following a plan that misinterprets the ticket is still a spec defect. The reviewer checks:

- original story/acceptance coverage, domain vocabulary, and applicable ADR consistency;
- correctness, edge cases, and error handling;
- security and data-safety implications appropriate to the scope;
- compatibility with repository conventions;
- tests of external behavior at the chosen seams, missing validation, and genuine slice dependencies;
- accidental scope expansion or undeclared mechanisms.

Do not fix files during review. Write `review.md` with a stable finding ID, severity (`must-fix` or `advisory`), evidence path/hunk, and disposition. A review with no findings must say so explicitly and record the reviewed baseline and head.

### 4. Revise once

Resolve all compatible `must-fix` findings in one bounded batch. Keep advisory findings visible without creating another worker or review cycle. If a finding requires changing the product decision, plan, public interface, migration strategy, or risk profile, stop and escalate instead of stretching the fast path.

Run the affected tests plus the relevant broad checks once after the batch. Write `revision.md` mapping every finding ID to `resolved`, `accepted-as-advisory`, or `blocked`, with changed files and command results. If no revision is needed, record a no-op revision and retain the passing checks.

### 5. Deliver and verify the PR

Audit the task-only diff for secrets and unexplained generated files. Confirm passing local checks, review dispositions, applicable browser verification, and the validated fingerprint before any push.

For GitHub, read [DELIVERY.md](DELIVERY.md), derive a concise commit/PR message from accepted artifacts, and invoke the bundled deterministic helper. It stages only the exact task inventory, reconciles existing commits/PRs, and binds required-check evidence to the local, pushed, and PR head. Do not delegate delivery to an agent.

Record the helper's output in `delivery.md`. A complete result requires positive discovery of the required-check policy and passing required checks on the final head. An empty rollup is not proof that no checks are required. An explicitly discovered absence is reported as `not-configured`, never as "CI passed". The helper polls for up to 30 minutes; a smaller timeout may be specified. Pending/timed-out, unknown-policy, authentication, permission, or infrastructure outcomes are not completion and do not spend the CI code-fix allowance. Preserve evidence and report the exact resume action.

For other forges, the coordinator uses the established CLI and records equivalent final-head and policy evidence. Unsupported policy discovery blocks; never silently fall back to an unverified PR. Do not amend or force-push unrelated history.

For a change-related required-check failure, allow **one separate compatible CI-fix batch** even if the review revision was already used. Inspect logs to distinguish existing/infrastructure failures from task defects; do not fix unrelated code. Record `ci-revision.md`, rerun affected and relevant broad checks (plus browser checks if affected), and update the validated fingerprint. Reconcile the same PR using a new immutable delivery input/output path. A second failure, unresolved must-fix, or change in product/risk scope blocks and recommends the durable workflow; never start another review or CI-fix batch.

### 6. Optionally render the PR explainer in HTML

Run this step only when the user requested an HTML report/explainer. After the PR exists, write a sanitized `pr-explainer.json` from the plan, implementation, review, revision, and delivery artifacts. Render a self-contained HTML file:

```bash
python3 "$SKILL_DIR/scripts/render_pr_explainer.py" \
  --input "$RUN_DIR/pr-explainer.json" \
  --output "$RUN_DIR/pr-explainer.html"
```

The explainer must include the request, outcome, plan, changed files, validation commands/results, the single review and finding dispositions, revision status, PR link, risks, and remaining notes. It must not embed secrets, raw logs, or a full diff. Link or mention the generated artifact in the final handoff; if the forge supports a comment or attachment workflow, add the artifact reference after rendering without modifying project files.

The renderer requires non-empty `title`, `summary`, `repository`, and `pr_url` fields. Also provide `branch`, `base`, `acceptance_criteria`, `plan`, `implementation`, `validation`, `review`, `revision`, `delivery`, `risks`, and `remaining_notes` so the explainer is useful rather than a placeholder.

## Completion handoff

Finish only when the PR exists, required local checks and applicable browser verification pass, must-fix findings are resolved, and required CI is verified on the final head (or positively identified as not configured). Any requested `pr-explainer.html` must be readable, and every settled Herdr pane created by the workflow must be closed. "PR created; CI pending" is progress, not completion. Report, briefly:

- status and PR URL;
- final commit and check state;
- run directory and HTML artifact path when requested;
- unresolved advisory findings or blockers, if any.

If any gate fails, do not claim completion. Leave the durable artifacts in place and state the exact resume action or escalation to the full `end-to-end-development` skill. Absence of an unrequested HTML explainer is not a failed gate.

## Bundled resource

[scripts/delivery_tools.py](scripts/delivery_tools.py) provides commit-independent fingerprints and deterministic GitHub delivery. Its standalone JSON/CLI contract is in [DELIVERY.md](DELIVERY.md); only Python's standard library, Git, and `gh` are required.

`[scripts/render_pr_explainer.py](scripts/render_pr_explainer.py)` renders the final explainer without third-party dependencies. It accepts JSON on disk or stdin and HTML-escapes all user/repository-controlled values.
