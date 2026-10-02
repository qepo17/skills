# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Agent Skills for taking a software request through implementation, verification, and requested delivery.

| Skill | Use it for |
| --- | --- |
| `simple-code` | Minimal, readable code. |
| `idea-to-ticket` | Optional research and a ticket draft for an unticketed idea; publish only when authorized. |
| `end-to-end-development` | Orchestrator-first development with bounded workers across one or more repositories and restart-safe GitHub delivery effects. |

## Development model

```text
Understand → coordinate implementation and iteration → verify → review → deliver as requested
```

The current agent owns understanding, decomposition, consequential decisions, coordination, integration, final acceptance, and authorized delivery. It defaults to bounded workers for substantive independently executable implementation, useful tests, research or inspection, and independent review. There is no workflow engine, prescribed phase graph, worker packet protocol, or automatic retry state machine.

- Reuse the request, repository evidence, and settled decisions. Ask only consequential unresolved questions.
- Let each worker own a coherent change with a compact assignment covering goal and acceptance, repository/worktree/baseline, exact scope and owner, constraints and dependencies, evidence and checks, and expected files or revisions, actual checks and unresolved issues. Inspect results before acceptance; workers report consequential choices, scope expansion, missing evidence or ownership conflicts and avoid recursive delegation unless explicitly authorized.
- Keep one concise optional task record with active worker targets, scopes, ownership, dependencies and pending results when useful. Reconcile existing workers before launching duplicates.
- Preserve existing changes and use an isolated worktree when needed.
- Keep one active source writer per repository across all worktrees, including the orchestrator. Settle and release ownership before integration or repair. Independent repositories and safe read-only investigations may progress concurrently; dependent changes proceed in dependency order.
- Use native runtime collaboration or launch facilities. Optional TypeSafe routing selects an approved model and effort for an already-bounded worker; TypeSafe and Herdr are not prerequisites for delegation. Execute directly for tiny reversible tasks, unavailable workers, or genuinely inseparable integration and decisions.
- Treat multi-repository delivery as independently observable effects rather than a fictional atomic transaction.
- Run meaningful acceptance and repository-required checks. Bind checks and independent review to stable exact content; content changes invalidate affected evidence.
- Use independent review for substantive changes and browser verification for UI changes. Report unavailable independent review honestly and preserve repository-required review gates.
- Finish the requested outcome: local work, an evidenced no-change result, or authorized publication. The skill name does not authorize publication.

## Durable external effects

GitHub publication uses the skill's standard-library `EffectGuard`. The guard exposes two operations:

```text
ensure(effect, approval?) → outcome
inspect(effect_id) → outcome
```

It stores external-effect intent and bounded observations in a task-local SQLite journal, coordinates branch ownership through a shared target registry, reconciles existing Git and GitHub state before retrying, and returns immutable completion receipts. It does not persist model reasoning or orchestrate development.

The first supported effect is a GitHub pull request with required-check observation. Additional effect kinds should be added only when their external postconditions can be observed reliably.

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
npx skills update --global end-to-end-development idea-to-ticket simple-code
```

## Requirements

Orchestrator-first development uses the repository's normal tools and available native runtime collaboration or worker launch facilities. When workers are unavailable, direct execution remains possible, with any independent review gap reported. Independent review requires an available independent reviewer when the change or repository requires it. Optional worker routing requires host-provided TypeSafe access and a launcher that supports approved model and effort selection; Herdr is one option. Neither TypeSafe nor Herdr is required for ordinary delegation or the development loop.

GitHub delivery requires Python 3.11+, Git, and authenticated `gh`. `EffectGuard` otherwise uses only the Python standard library.

## Development

```bash
./scripts/check.sh
```

Checks validate the catalog and supporting links, exercise `EffectGuard` and its GitHub adapter, verify fingerprinting does not mutate a repository, and test standalone skill discovery.
