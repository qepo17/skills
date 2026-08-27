# Immutable worker assignment (`assignment`)

Assignments are coordinator-owned. Required common fields are schema/artifact/run/action identity, timestamp, stage, attempt, optional profile, repository scope, baseline/pre-existing status, access permissions, hash-pinned inputs, requirement IDs, instructions, validation commands, output kind/path, log directory, stage-specific `artifact_schema_path`, and validator path. In every new run, a project-file writer also has a `plan_review` hashed-file reference identical to the approved bundle in `run.json`; that same Markdown file appears in `input_artifacts`.

Profiled stage fields:

- contract: optional `contract_revision`, distinct from a worker replacement attempt;
- plan: optional `plan_revision`; a non-challenge revision also carries `revision_basis` with `kind` and a hash-pinned `artifact`;
- implementation: one `packet_id` and one to three sorted `task_ids` (up to four for fast);
- validation: every exact sorted validation ID from the canonical plan, paired with the assigned commands;
- review fixes: all compatible sorted `finding_ids` for that repository/round;
- validation fixes: compatible sorted `validation_ids`;
- round-two review: the sorted finding IDs it verifies.

Thinking routing:

- `xhigh`: full-profile contract, plan, design challenge, review, and integration;
- `high`: standard planning/review, implementation, and complex fixes;
- `medium`: validation, mechanical fixes, delivery, and report tooling.

Only project-file stages receive one repository write scope. Only delivery receives Git/forge write access. Workers never mutate run/agent/event/checkpoint state. The LangGraph control plane constructs assignments; workers must not infer or schedule a subsequent phase. The batch supervisor must reject a project-file writer unless the complete current plan set has explicit user approval and the assignment pins that exact review-bundle path/hash. Validate before launch:

```bash
python3 <validator_path> assignment <assignment-path>
```
