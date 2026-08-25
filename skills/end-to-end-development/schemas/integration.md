# Integration artifact (`integration`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

Integration is used only when the selected workflow requires it. Record:

- one requirement-matrix row per requirement with repositories and existing validation evidence;
- contracted interface results and evidence;
- one mechanism-conformance entry per repository;
- the final changed-file inventory, rollout order, risks, and blockers.

`design_challenge_path` is null only when that repository's canonical plan explicitly waived the critic. A complete artifact has only passing entries and covers every repository in the requirement matrix.

Validate before returning:

```bash
python3 <validator_path> integration <output_artifact>
```
