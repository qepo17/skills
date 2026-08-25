# Report artifact (`report`)

Reports are generated deterministically from accepted artifacts, not composed by a model:

```bash
python3 <workflow_tools_path> render-report \
  --run-dir <run-dir> \
  --assignment <assignment-path> \
  --html <unique-absolute-html-path> \
  --output <output-artifact>
```

The generated artifact binds the assignment and records the HTML path, byte size, SHA-256, complete requirement IDs, high-impact topics, and blockers. Independently validate it with:

```bash
python3 <validator_path> report <output_artifact>
```
