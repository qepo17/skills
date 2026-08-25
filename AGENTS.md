# Repository Instructions

This repository distributes Agent Skills through `npx skills`.

- Distributable skills live at `skills/<name>/SKILL.md`.
- Preserve Agent Skills frontmatter constraints and keep `name` equal to the parent directory.
- Keep every skill self-contained; relative references must resolve within its skill directory.
- Do not add a root `SKILL.md`, because it would shadow catalog skills during default `npx skills` discovery.
- Do not commit `.venv`, `__pycache__`, `.pytest_cache`, generated reports, logs, secrets, or run artifacts.
- Use locked dependencies for executable skill resources.
- Run `./scripts/check.sh` before committing.
