# Development Workflow Skills

[![skills.sh](https://skills.sh/b/qepo17/skills)](https://skills.sh/qepo17/skills)
[![CI](https://github.com/qepo17/skills/actions/workflows/ci.yml/badge.svg)](https://github.com/qepo17/skills/actions/workflows/ci.yml)

Two Agent Skills for taking software changes from request to pull request:

| Skill | Use it for |
| --- | --- |
| `fast-end-to-end-development` | A small or medium, low-risk change in one repository with one plan, review, and revision pass. |
| `end-to-end-development` | Higher-risk or multi-repository work that needs durable orchestration, explicit plan approval, bounded retries, and resumability. |

The repository follows the [Agent Skills specification](https://agentskills.io/specification) and uses the conventional `skills/<name>/SKILL.md` catalog layout supported by [`npx skills`](https://github.com/vercel-labs/skills).

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

Install both globally for Pi:

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
npx skills update --global end-to-end-development fast-end-to-end-development
```

## Requirements

### Fast workflow

- Git and the target repository's forge CLI, such as `gh`
- Python 3 for the bundled HTML explainer renderer
- An agent runtime capable of running independent agent sessions

### Full workflow

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Git worktrees (Worktrunk is preferred when available)
- Herdr with Pi or Codex worker support
- The target repository's forge CLI
- The `codebase-design` skill

The full workflow finds `codebase-design` beside the installed skill and in common Pi/Codex global skill directories. Set `E2E_CODEBASE_DESIGN_DIR` when it lives elsewhere. The workflow installs its locked Python dependencies into the user cache through its bundled wrapper; it does not place a virtual environment in the installed skill directory.

## Repository layout

```text
skills/
├── end-to-end-development/
│   ├── SKILL.md
│   ├── agents/
│   ├── schemas/
│   ├── scripts/
│   └── tests/
└── fast-end-to-end-development/
    ├── SKILL.md
    ├── agents/
    └── scripts/
```

Each skill is self-contained so `npx skills` installs its supporting scripts, schemas, documentation, and metadata together with `SKILL.md`.

## Development

Run all repository checks:

```bash
./scripts/check.sh
```

The check validates the skill catalog, runs the full workflow's unit suite, smoke-tests the fast workflow's HTML renderer, and verifies local discovery with the pinned `skills` CLI version.

See [CONTRIBUTING.md](CONTRIBUTING.md) before changing a skill.
