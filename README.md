# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Agent Skills for simple code and taking software changes from request to pull request:

| Skill | Use it for |
| --- | --- |
| `simple-code` | Minimal, readable code with YAGNI, readable one-liners, and WHY-only comments. |
| `idea-to-ticket` | Optional preparation for unticketed ideas: focused evidence, essential clarification, an outcome-oriented draft, and publication only when explicitly authorized. |
| `fast-end-to-end-development` | An existing ticket/spec/request through a compact grounded implementation spec, one review/revision, and verified single-repository PR delivery. |
| `end-to-end-development` | Durable single- or multi-repository orchestration with one review/remediation pass, automatic low-risk plan decisions, and explicit approval only for high-risk work. |

The repository follows the [Agent Skills specification](https://agentskills.io/specification) and uses the conventional `skills/<name>/SKILL.md` catalog layout supported by [`npx skills`](https://github.com/vercel-labs/skills).

## Two entry points, no mandatory interview

```text
Unticketed idea → idea-to-ticket → draft → explicitly authorized publication
Existing ticket / spec / request → grounded implementation spec
  → implement + validate → independent review → bounded fixes → PR + verified CI
```

The execution skills accept existing Jira/GitHub tickets directly; they do not recreate tickets, publish child issues, or require `idea-to-ticket`. They reuse source excerpts and code/doc evidence, then use the existing plan as the implementation contract. The fast skill keeps this in `plan.md`; the durable skill uses its canonical hash-pinned plan and internal work packets. Independent review checks the original source as well as the plan, so a mistaken interpretation cannot hide behind task completion.

Discovery is evidence-first: adopt justified, reversible, in-scope implementation recommendations without routine confirmation. Ask zero questions when clear, otherwise one at a time (up to three only when independent), and **at most 10 independently answerable clarification questions across the whole task**, including inherited discovery, follow-ups, escalation, and resume. Ten is a ceiling, not a quota; lower/no-interview preferences are honored. Unresolved material decisions remain blockers at the cap. High-risk plan approval, migration safety, and external-write authorization are never waived. See the bundled [discovery contract](skills/end-to-end-development/DISCOVERY.md).

### Prompt inspiration

The prompts adapt the actual `to-spec`, `to-tickets`, and `grill-with-docs` skills: synthesis rather than another interview; problem/solution and meaningful stories; implementation/testing decisions with high existing behavioral test seams; domain glossary/ADRs; and independently verifiable vertical slices with genuine blocking dependencies. Necessary prefactors and wide-refactor expand–contract sequences stay within existing safety gates. Long-lived ticket prose stays outcome-oriented while local execution evidence retains real baseline-bound paths and commands.

We deliberately do not import exhaustive story quotas, repeated seam/breakdown approval quizzes, automatic tracker publication/labels, or mandatory new tickets. See [source snapshots and adaptation rationale](docs/prompt-inspiration.md) and the self-contained [idea-to-ticket examples](skills/idea-to-ticket/EXAMPLES.md).

## Install with `npx skills`

Review skill instructions and scripts before installing them.

List the available skills:

```bash
npx skills add qepo17/skills --list
```

Install interactively:

```bash
npx skills add qepo17/skills
```

Install one skill globally for Pi:

```bash
npx skills add qepo17/skills \
  --global \
  --agent pi \
  --skill fast-end-to-end-development \
  --yes
```

Install all globally for Pi:

```bash
npx skills add qepo17/skills \
  --global \
  --agent pi \
  --skill '*' \
  --yes
```

For Codex, replace `--agent pi` with `--agent codex`. Omit `--global` to install into the current project. The CLI also accepts the SSH URL directly:

```bash
npx skills add git@github.com:qepo17/skills.git
```

Update installed global skills with:

```bash
npx skills update --global end-to-end-development fast-end-to-end-development idea-to-ticket simple-code
```

## Requirements

`simple-code` and `idea-to-ticket` have no executable runtime dependencies. `idea-to-ticket` can draft locally; duplicate checks and explicitly authorized publication require an available authenticated tracker tool.

### Fast workflow

- Git and the target repository's forge CLI, such as `gh`
- Python 3.11+ for the standalone delivery/fingerprint helper and optional explainer
- An agent runtime capable of running independent agent sessions

### Durable workflow

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Git worktrees (Worktrunk is preferred when available)
- Pi or Codex worker support
- The target repository's forge CLI
- The `codebase-design` skill

The durable workflow automatically uses Paseo when invoked by a Paseo parent agent, Herdr when invoked inside Herdr, or tmux when invoked inside tmux. Otherwise it runs workers directly in headless mode; users do not configure a terminal manager. The detected backend is pinned for resumability. New runs pin validation and delivery policy version 1: every task has blocking acceptance evidence, repository-required and migration-capable checks remain hard gates, and supplemental checks may be predeclared advisory or explicitly excluded through a scoped, immutable user decision. Check failure is reported separately from whether the assigned source/check-reporting work finished. Existing runs without these pins retain their legacy behavior and are never retrofitted or migrated.

New runs use `gpt-6-astra` with stage-specific reasoning: xhigh for full-profile planning/review/challenge/integration, high for ordinary planning/review and all source fixes, and medium for validation, artifact-only repair, and fallback delivery. GitHub.com delivery runs as deterministic commands rather than another agent. A narrow, bounded output-only repair handles missing blocker classifications without replaying implementation. Existing durable runs retain their pinned legacy policies.

Both skills require verified final-head required checks, not merely a PR URL. Pending CI is not completion. An explicit absence of configured required checks is reported as `not-configured`, not "CI passed"; unknown policy blocks. New durable GitHub runs create a run-owned draft after local/review/integration gates, keep its URL visible while required CI is pending or failed, and publish it only after a fresh green observation through an authorized normal delivery action. Read-only verification never commits, pushes, creates, edits, or publishes a PR. The fast skill retains its existing coordinator behavior; the shared delivery helper's draft lifecycle remains opt-in. See its [delivery contract](skills/fast-end-to-end-development/DELIVERY.md).

The durable workflow finds `codebase-design` beside the installed skill and in common Pi/Codex global skill directories. Set `E2E_CODEBASE_DESIGN_DIR` when it lives elsewhere. The workflow installs its locked Python dependencies into the user cache through its bundled wrapper; it does not place a virtual environment in the installed skill directory.

## Repository layout

```text
skills/
├── end-to-end-development/
│   ├── SKILL.md
│   ├── agents/
│   ├── schemas/
│   ├── scripts/
│   └── tests/
├── fast-end-to-end-development/
│   ├── SKILL.md
│   ├── agents/
│   └── scripts/
├── idea-to-ticket/
│   ├── SKILL.md
│   └── agents/
└── simple-code/
    ├── SKILL.md
    └── agents/
```

Each skill is self-contained so `npx skills` installs its supporting scripts, schemas, documentation, and metadata together with `SKILL.md`.

## Development

Run all repository checks:

```bash
./scripts/check.sh
```

The check validates the skill catalog, runs workflow/intake/repair/forge/reasoning tests, checks the identical standalone delivery and discovery resources, smoke-tests isolated fast-only and idea-to-ticket installations and the HTML renderer, and verifies discovery with the pinned `skills` CLI version. Intake tests cover zero/lower/capped questions, resolved inherited questions followed by no-more-interview, rejected unresolved or newly over-budget intake, bounded source snapshots, immutable handoffs, and unchanged stage counts; they do not claim to mechanically prove an agent's semantic question counting or live tracker behavior. Test Git operations target temporary local repositories; no real forge or database is modified.

See [CONTRIBUTING.md](CONTRIBUTING.md) before changing a skill.
