# Contract artifact (`contract`)

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
- `dependencies` use `from_repo_id` (the dependent consumer), `to_repo_id` (its prerequisite producer), `reason`, and concrete `evidence`; the graph must be acyclic. For API-first implementation, Core → API and UI → Core mean Core waits for API and UI waits for Core. Do not encode producer-to-consumer arrows. Never rewrite an accepted contract to repair an older direction mismatch; use only its explicitly authorized guarded recovery.
- `compatibility`, `rollout`, and `cross_repository_validation` are explicit arrays.
- A complete contract has no `open_questions` or blockers.
- Never prescribe a speculative implementation mechanism merely to complete the contract.

Validate before returning:

```bash
python3 <validator_path> contract <output_artifact>
```
