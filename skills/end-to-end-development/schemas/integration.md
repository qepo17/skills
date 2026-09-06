# Integration artifact (`integration`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a stage that cannot finish, follow the [blocker contract](blockers.md) and use the typed `block` command.

Integration is used only when the selected workflow requires it. Record:

- one requirement-matrix row per requirement with repositories and existing validation evidence;
- contracted interface results and evidence;
- one mechanism-conformance entry per repository;
- the final changed-file inventory, rollout order, risks, and blockers.

`design_challenge_path` is null only when that repository's canonical plan explicitly waived the critic. A complete artifact has only passing entries and covers every repository in the requirement matrix.

For validation-policy version 1, use the effective policy and exclusion references supplied by the assignment. Advisory/excluded supplemental checks may be disclosed as warnings and must not become blockers merely because their historical observation is red. Requirement-matrix and contracted-interface rows still require actual current passing evidence; an exception cannot substitute for acceptance, security, repository-required, migration, or interface proof.

For new runs, reuse requires the latest accepted integration to pin every current source writer, canonical meaning, and amendment. A later source fix or policy amendment invalidates that integration snapshot; the graph reruns the existing read-only integration stage with a new context-scoped output before delivery. Historical integration artifacts remain immutable.

Validate before returning:

```bash
python3 <validator_path> integration <output_artifact>
```
