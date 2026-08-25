# Contributing

## Skill structure

- Put distributable skills under `skills/<skill-name>/`.
- Keep the directory name and the `name` in `SKILL.md` identical.
- Include a specific `description` that says what the skill does and when it should be used.
- Keep supporting files inside the skill directory and reference them with relative links.
- Add product-specific metadata under `agents/`; keep portable instructions in `SKILL.md`.
- Do not commit virtual environments, caches, logs, credentials, or generated run state.

## Validation

Before opening a pull request, run:

```bash
./scripts/check.sh
```

For a quick installability check:

```bash
npx skills add . --list
```

Changes to the full orchestrator should include focused unit tests under `skills/end-to-end-development/tests/`. Changes to the fast renderer should include or extend its smoke coverage in `scripts/check.sh`.

## Pull requests

Keep each pull request focused. Describe the workflow behavior changed, list validation commands, and call out new runtime dependencies or compatibility requirements.
