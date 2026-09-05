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

The canonical standalone delivery helper is `skills/end-to-end-development/scripts/delivery_tools.py`. After changing it, copy it verbatim to `skills/fast-end-to-end-development/scripts/delivery_tools.py`; `scripts/check.sh` rejects drift and exercises the fast-only installation. Never import a sibling skill at runtime. The helper uses only Python's standard library, Git, and the existing forge CLI.

Keep regression coverage at the existing engine/artifact/supervisor interfaces and the helper's Git/forge command seam. Use temporary Git repositories and fake forge responses for automated tests; real GitHub smoke tests are opt-in against an authorized disposable repository. Preserve legacy run/assignment policies in compatibility tests. Distinguish measured agent-launch counts from actual elapsed-time results.

## Pull requests

Keep each pull request focused. Describe the workflow behavior changed, list validation commands, and call out new runtime dependencies or compatibility requirements.
