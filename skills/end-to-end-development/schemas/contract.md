# Contract artifact (`contract`)

Before any work, read [SKILL.md — Validation rules](../SKILL.md#validation-rules). It contains the shared limits, required fields, evidence rules, and role boundaries; this file is a stage-specific reminder.

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a stage that cannot finish, follow the [blocker contract](blockers.md) and use the typed `block` command.

Fill the generated skeleton. Keep text concise and put verbose evidence in logs.

Required semantic rules:

- `requirement_map` covers every assigned requirement and uses sorted repository IDs.
- `domain_terms` and `behavior_rules` describe observable behavior.
- `interfaces` describe only necessary interoperability; each has `id`, producer, non-empty consumers, `kind`, description, and existing `evidence_paths`.
- `dependencies` use `from_repo_id`, `to_repo_id`, `reason`, and concrete `evidence`; the graph must be acyclic.
- `compatibility`, `rollout`, and `cross_repository_validation` are explicit arrays.
- A complete contract has no `open_questions` or blockers.
- Never prescribe a speculative implementation mechanism merely to complete the contract.

Validate before returning:

```bash
python3 <validator_path> contract <output_artifact>
```
