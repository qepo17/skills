# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Agent Skills for taking a software request through implementation, verification, and requested delivery.

| Skill | Use it for |
| --- | --- |
| `simple-code` | Minimal, readable code. |
| `idea-to-ticket` | Optional research and a ticket draft for an unticketed idea; publish only when authorized. |
| `end-to-end-development` | Agent-led development across one or more repositories, with restart-safe GitHub delivery effects. |

## Development model

```text
Understand → implement and iterate → verify → review → deliver as requested
```

The current agent owns the loop. There is no workflow engine, prescribed phase graph, worker packet protocol, or automatic retry state machine.

- Reuse the request, repository evidence, and settled decisions. Ask only consequential unresolved questions.
- Keep one concise task record when a persistent handoff is useful; tiny work needs no dossier.
- Preserve existing changes and use an isolated worktree when needed.
- Keep one source writer per repository. Independent repositories may progress concurrently, while dependent changes proceed in dependency order.
- Treat multi-repository delivery as independently observable effects rather than a fictional atomic transaction.
- Run meaningful acceptance and repository-required checks. Content changes invalidate affected evidence.
- Use independent review for substantive changes and browser verification for UI changes.
- Finish the requested outcome: local work, an evidenced no-change result, or authorized publication.

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

Agent-led development uses the repository's normal tools and the current agent runtime. Independent review requires an available independent agent when the change or repository requires it.

GitHub delivery requires Python 3.11+, Git, and authenticated `gh`. `EffectGuard` otherwise uses only the Python standard library.

## Development

```bash
./scripts/check.sh
```

Checks validate the catalog and supporting links, exercise `EffectGuard` and its GitHub adapter, verify fingerprinting does not mutate a repository, and test standalone skill discovery.
