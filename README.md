# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Agent Skills for taking a software request through implementation, verification, and an open task PR watched until green and mergeable by default with `end-to-end-development`.

| Skill | Use it for |
| --- | --- |
| `idea-to-ticket` | Optional research and a ticket draft for an unticketed idea; publish only when authorized. |
| `end-to-end-development` | Orchestrator-first development with bounded workers across repositories, through verified changes and open task PRs watched until mergeable by default. |

## Development model

```text
Understand → coordinate implementation and iteration → locally verify → review → commit → push → create or update task PR → watch until mergeable
```

The current agent owns understanding, decomposition, consequential decisions, coordination, integration, final acceptance, and authorized delivery. It defaults to bounded workers for substantive independently executable implementation, useful tests, research or inspection, independent review, and PR watching. There is no workflow engine, prescribed phase graph, worker packet protocol, or automatic retry state machine.

- Reuse the request, repository evidence, and settled decisions. Ask only consequential unresolved questions.
- Let each worker own a coherent change with a compact assignment covering goal and acceptance, repository/worktree/baseline, exact scope and owner, constraints and dependencies, evidence and checks, and expected files or revisions, actual checks and unresolved issues. Inspect results before acceptance; workers report consequential choices, scope expansion, missing evidence or ownership conflicts and avoid recursive delegation unless explicitly authorized.
- Keep one concise optional task record with active worker targets, scopes, ownership, dependencies and pending results when useful. Reconcile existing workers before launching duplicates.
- Preserve existing changes and use an isolated worktree when needed.
- Keep one active source writer per repository across all worktrees, including the orchestrator. Settle and release ownership before integration or repair. Independent repositories and safe read-only investigations may progress concurrently; dependent changes proceed in dependency order.
- Use native runtime collaboration or launch facilities with the runtime's configured workers and honor explicit model requirements. Execute directly for tiny reversible tasks, unavailable workers, or genuinely inseparable integration and decisions.
- Treat multi-repository delivery as independently observable effects rather than a fictional atomic transaction.
- Run meaningful acceptance and repository-required checks. Bind checks and independent review to stable exact content; content changes invalidate affected evidence.
- Use independent review for substantive changes and browser verification for UI changes. Report unavailable independent review honestly and preserve repository-required review gates.
- The orchestrator owns default completion: locally verify, independently review as required, commit task-scoped changes, push to the established appropriate task branch/remote, create or update an open task PR, have it watched until mergeable, and return its URL with its actual merge state. Reuse an existing open task PR. Worker completion, local edits, a commit, a pushed branch, or a created PR alone is not normal completion.
- Once the PR exists, a fresh bounded PR watcher takes writer ownership of the task branch. It waits for every check; fixes red checks, conflicts and an out-of-date base within task scope by publishing verified revisions; and stops only when the PR is mergeable or genuinely blocked. The orchestrator confirms the PR's actual state before finishing.

Using `end-to-end-development` for a repository change requests the full PR workflow without a separate reminder or invitation. Read its [delivery guidance](skills/end-to-end-development/DELIVERY.md) for normal GitHub PR completion. Honor explicit local-only/no-push/no-PR instructions, repository policy, exact-approval requirements, and tool/sandbox permissions; publication must be task-scoped with an unambiguous destination. This does not authorize merge, auto-merge, deployment, migrations, permissions changes, tracker writes, creating remote repositories, or destructive work.

No-change requests end with evidence and no empty PR; explicit opt-outs end with the actual local result. Missing authentication or remote, ambiguous destinations, denied permissions, or failed required verification/review yield explicit blocked or partial results with the next needed action. Continue useful local development when remote access is missing, without silently downgrading delivery or claiming completion. A PR with pending or failing checks, conflicts, or another unmet merge requirement is not complete even if it exists; gates only a human can satisfy, such as a required approval, are reported as the remaining blockers.

## Durable external effects

GitHub publication uses the skill's standard-library `EffectGuard`. The guard exposes two operations:

```text
ensure(effect, approval?) → outcome
inspect(effect_id) → outcome
```

It stores external-effect intent and bounded observations in a task-local SQLite journal, coordinates branch ownership through a shared target registry, reconciles existing Git and GitHub state before retrying, and returns immutable completion receipts. It does not persist model reasoning or orchestrate development.

The first supported effect is a GitHub pull request with required-check observation. The PR watcher observes the remaining merge requirements with `gh` and publishes each fix as a revised effect. Additional effect kinds should be added only when their external postconditions can be observed reliably.

## Install with `npx skills`

The catalog follows the [Agent Skills specification](https://agentskills.io/specification) and `skills/<name>/SKILL.md` layout. Review skills and executable resources before installing.

List available skills:

```bash
npx skills add qepo17/skills --list
```

Install the development skill globally for Codex:

```bash
npx skills add qepo17/skills --global --agent codex --skill end-to-end-development --yes
```

Update installed skills:

```bash
npx skills update --global end-to-end-development idea-to-ticket
```

## Requirements

Orchestrator-first development uses the repository's normal tools and available native runtime collaboration or worker launch facilities. When workers are unavailable, direct execution remains possible, with any independent review gap reported. Independent review requires an available independent reviewer when the change or repository requires it.

GitHub delivery requires Python 3.11+, Git, and authenticated `gh`. `EffectGuard` otherwise uses only the Python standard library.

## Development

```bash
./scripts/check.sh
```

Checks validate the catalog and supporting links, exercise `EffectGuard` and its GitHub adapter, verify fingerprinting does not mutate a repository, and test standalone skill discovery.
