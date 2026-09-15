# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Agent Skills for taking a software request through implementation and verification with a proportional workflow.

| Skill | Use it for |
| --- | --- |
| `simple-code` | Minimal, readable code. |
| `idea-to-ticket` | Optional research and a ticket draft for an unticketed idea; publish only when authorized. |
| `fast-end-to-end-development` | Everyday development in the current agent, with a short plan and productive edit/test iteration. |
| `end-to-end-development` | The same coordinator-led development, plus an explicit durable LangGraph option and existing-run recovery. |

## Default development workflow

```text
Understand → implement and iterate → verify → review → deliver as requested
```

Both development entrypoints use the same self-contained [development guide](skills/end-to-end-development/DEVELOPMENT.md):

- Reuse the request, relevant repository evidence and prior decisions. Ask only consequential unresolved questions.
- Keep one task record when a persistent handoff is useful. Small fixes need no stage dossier.
- Use the current suitable checkout; isolate work when necessary to protect existing changes or concurrent work.
- Refine plans and fix related failures as development progresses. Revisit affected work and real dependencies, not every repository.
- Treat task counts and estimates as guidance. Stop repeated unsuccessful attempts when no new evidence or approach supports another retry, and honor the user's effort limits.
- Run meaningful acceptance and repository-required checks. Additional advisory checks may warn without stopping work; failed required checks remain failures.
- Use independent review for substantive changes and browser verification for UI changes.
- Complete the requested outcome: local code, an evidenced no-change result, or a PR with verified required CI. Missing forge access delays publication while useful local work continues.

APIs, authorization code, background jobs and multiple repositories do not automatically trigger a different process. Assess the actual behavior, compatibility, data and permission consequences. Honor existing authorization and prepare a concrete operation before asking for additional permission.

GitHub delivery uses the bundled [standard-library helper](skills/end-to-end-development/DELIVERY.md) with a selected remote, explicit task inventory, verified content fingerprint, operation-specific timeouts and final-head checks. A ready PR can trigger CI; readiness alone does not mean checks passed. Draft-until-verified publication is an optional lifecycle for repositories that run the necessary checks on drafts.

## Durable mode and compatibility

Use [DURABLE.md](skills/end-to-end-development/DURABLE.md) when explicitly selecting LangGraph orchestration or resuming an existing run. It retains persistent worker supervision, immutable assignments, hash-pinned plans, existing profile/approval/fix limits, and guarded recovery. Those contracts apply inside the durable engine; they are not prerequisites for the default workflow.

Existing runs retain their recorded policies. Do not migrate, reset budgets, mutate accepted artifacts, or bypass an active engine by moving its task into the coordinator workflow. The specialized recovery and artifact guides remain bundled for those runs and are loaded only in durable mode.

The durable engine still enforces its stricter planning-decision, packet, advisory-coverage and cleanup rules. This release changes the ordinary development path rather than retroactively changing those run semantics. Its historical delivery inputs retain `origin` and 30-second Git-write defaults; new coordinator delivery inputs select the remote and timeout explicitly.

## Install with `npx skills`

The catalog follows the [Agent Skills specification](https://agentskills.io/specification) and `skills/<name>/SKILL.md` layout. Review skills and executable resources before installing.

List available skills:

```bash
npx skills add qepo17/skills --list
```

Install interactively:

```bash
npx skills add qepo17/skills
```

Install the everyday workflow globally for Pi:

```bash
npx skills add qepo17/skills --global --agent pi --skill fast-end-to-end-development --yes
```

For Codex, replace `--agent pi` with `--agent codex`. Omit `--global` for a project installation. Install all with `--skill '*'`.

Update installed skills:

```bash
npx skills update --global end-to-end-development fast-end-to-end-development idea-to-ticket simple-code
```

## Requirements

Coordinator-led development uses the repository's normal tools and the current agent runtime. No LangGraph, external design skill, or fixed subagent model is required. Independent review requires an available independent agent when the change or repository requires it.

Scripted GitHub delivery requires Python 3.11+, Git and authenticated `gh`. An optional fast-workflow HTML explainer uses Python's standard library.

Durable mode additionally requires Python 3.11+, `uv`, Git worktrees, Pi/Codex worker support, a forge CLI and the installed `codebase-design` skill. Its locked dependencies, backend detection and permission contracts are documented in [DURABLE.md](skills/end-to-end-development/DURABLE.md) and [ORCHESTRATION.md](skills/end-to-end-development/ORCHESTRATION.md).

## Development

```bash
./scripts/check.sh
```

Checks validate the catalog and supporting links, verify shared resources and standalone installations, run engine/helper regression tests, smoke-test the optional renderer, and verify discovery with a pinned `skills` CLI. Tests use temporary local repositories and fake forge/worker responses.

See [CONTRIBUTING.md](CONTRIBUTING.md). The [prompt-inspiration notes](docs/prompt-inspiration.md) describe the earlier durable planning guidance; they are not additional runtime dependencies.
