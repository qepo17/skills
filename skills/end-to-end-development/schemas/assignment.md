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

- `xhigh`: full-profile contract, plan, design challenge, review, and integration;
- `high`: ordinary planning/review and every source-writing implementation/fix;
- `medium`: artifact-only repair, validation-only work, and fallback delivery.

New assignments pin `reasoning_policy: stage-v1`; the runtime honors the classification with `gpt-6-astra`. Legacy assignments/runs use `legacy-xhigh` when no newer policy was pinned. Existing handles are recovered with their recorded runtime configuration. Deterministic delivery/report work does not launch an agent.

`execution_mode: artifact-repair` retains the original result stage and scope but has no project/Git/forge write access, a five-minute timeout, and medium reasoning. Its `repair_of` binds the original assignment, rejected output, referenced evidence, and repository states. Initialize from the original payload and follow the [blocker contract](blockers.md); this is not another implementation attempt.

New GitHub delivery uses `execution_mode: command`, `delivery_evidence_version: 2`, and a pinned `check_timeout_seconds` (0–1800). The graph executes it directly, with durable intent/reconciliation and no worker handle. A `verify_only: true` command assignment refreshes accepted delivery after interruption with `git_access: none` and `forge_access: none`; it cannot commit, push, or create a PR. Other forges retain worker delivery with version-2 final-head evidence.

Only project-file stages receive one repository write scope. Only delivery receives Git/forge write access. Workers never mutate run/agent/event/checkpoint state. The LangGraph control plane constructs assignments; workers must not infer or schedule a subsequent phase. The batch supervisor must reject a project-file writer unless the complete current plan set has an approved policy/user decision and the assignment pins that exact review-bundle path/hash. Validate before launch:

```bash
python3 <validator_path> assignment <assignment-path>
```
