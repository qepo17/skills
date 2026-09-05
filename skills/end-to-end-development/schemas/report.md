# Report artifact (`report`)

Before any work, read [SKILL.md — Validation rules](../SKILL.md#validation-rules). It contains the shared limits, required fields, evidence rules, and role boundaries; this file is a stage-specific reminder.

Reports are generated deterministically from accepted artifacts, not composed by a model:

```bash
python3 <workflow_tools_path> render-report \
  --run-dir <run-dir> \
  --assignment <assignment-path> \
  --html <unique-absolute-html-path> \
  --output <output-artifact>
```

Blockers use the [common blocker shape](blockers.md); do not rewrite an accepted report to repair it.

The generated artifact binds the assignment and records the HTML path, byte size, SHA-256, complete requirement IDs, high-impact topics, and blockers. Independently validate it with:

```bash
python3 <validator_path> report <output_artifact>
```
