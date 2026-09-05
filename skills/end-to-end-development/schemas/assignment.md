# Immutable worker assignment (`assignment`)

Assignments are coordinator-owned. Required common fields are schema/artifact/run/action identity, timestamp, stage, attempt, optional profile, repository scope, baseline/pre-existing status, access permissions, hash-pinned inputs, requirement IDs, instructions, validation commands, output kind/path, log directory, stage-specific `artifact_schema_path`, and validator path. Repository-scoped read-only assignments also pin `input_tree_fingerprint`; acceptance fails if their content changes. In every new run, a project-file writer also has a `plan_review` hashed-file reference identical to the approved bundle in `run.json`; that same Markdown file appears in `input_artifacts`.

Profiled stage fields:

- contract: optional `contract_revision`, distinct from a worker replacement attempt;
- plan: optional `plan_revision`, `contract_required`, and `design_challenge_policy`; a non-challenge revision also carries `revision_basis` with `kind` and a hash-pinned `artifact`;
- implementation: one `packet_id`, one to three sorted `task_ids` (up to four for fast), and validation IDs paired with its commands; the repository's final packet receives the complete planned suite;
- validation: every exact sorted validation ID from the canonical plan, paired with the assigned commands;
- review fixes: all compatible sorted `finding_ids` for that repository/round plus every planned validation ID/command;
- validation fixes: compatible sorted `validation_ids`;
- legacy round-two review: the sorted finding IDs it verifies; new runs do not schedule this stage.

Thinking classification:

- `xhigh`: full-profile plan, design challenge, review, and integration;
- `high`: standard planning/review, implementation, and complex fixes;
- `medium`: validation, mechanical fixes, delivery, and report tooling.

The supervisor launches every classification with runtime `xhigh`; the assignment value remains policy metadata.

Only project-file stages receive one repository write scope. Only delivery receives Git/forge write access. Workers never mutate run/agent/event/checkpoint state. The LangGraph control plane constructs assignments; workers must not infer or schedule a subsequent phase. The batch supervisor must reject a project-file writer unless the complete current plan set has an approved policy/user decision and the assignment pins that exact review-bundle path/hash. Validate before launch:

```bash
python3 <validator_path> assignment <assignment-path>
```
