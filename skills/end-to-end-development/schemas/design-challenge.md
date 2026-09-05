# Design challenge artifact (`design-challenge`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a stage that cannot finish, follow the [blocker contract](blockers.md) and use the typed `block` command.

Apply the pinned simplicity and codebase-design guidance. The artifact must:

- hash-bind the exact plan;
- use `mode: full` for a candidate or `verification` for a revised plan;
- assess every declared mechanism exactly once with retain, replace, or remove;
- inspect tasks for undeclared high-cost mechanisms;
- record concise evidence-backed findings sorted by severity, target, and ID;
- return exactly one verdict: `accept`, `revise-plan`, `revise-contract`, or `blocked`.

An accepting challenge has no actionable finding. A replace/remove assessment needs a linked actionable finding. Do not write a replacement plan or project files.

Validate before returning:

```bash
python3 <validator_path> design-challenge <output_artifact>
```
