# Immutable worker assignment (`assignment`)

Assignments are coordinator-owned. Required common fields are schema/artifact/run/action identity, timestamp, stage, attempt, optional profile, repository scope, baseline/pre-existing status, access permissions, hash-pinned inputs, requirement IDs, instructions, validation commands, output kind/path, log directory, stage-specific `artifact_schema_path`, and validator path. Repository-scoped read-only assignments also pin `input_tree_fingerprint`; acceptance fails if their content changes. In every new run, assignments carry `validation_policy_version: 1` and `delivery_policy_version: 1`; a project-file writer also has a `plan_review` hashed-file reference identical to the approved bundle in `run.json`, and that same Markdown file appears in `input_artifacts`. Missing policy versions mean legacy behavior; workers never add or infer them.

Profiled stage fields:

- contract: optional `contract_revision`, distinct from a worker replacement attempt;
- plan: optional `plan_revision`, `contract_required`, and `design_challenge_policy`; a non-challenge revision also carries `revision_basis` with `kind` and a hash-pinned `artifact`;
- implementation: one `packet_id`, one to three sorted `task_ids` (up to four for fast), and validation IDs paired with its commands; the repository's final packet receives the complete planned suite;
- validation: every exact sorted effective validation ID from the canonical plan, paired with the assigned commands;
- review fixes: all compatible sorted `finding_ids` for that repository/round plus every effective validation ID/command;
- validation fixes: `failed_validation_ids` identify the approved repair targets while `validation_ids`/commands contain the full effective suite;
- legacy round-two review: the sorted finding IDs it verifies; new runs do not schedule this stage.

Thinking classification:

- `xhigh`: full-profile contract, plan, design challenge, review, and integration;
- `high`: ordinary planning/review and every source-writing implementation/fix;
- `medium`: artifact-only repair, validation-only work, and fallback delivery.

New assignments pin `reasoning_policy: stage-v1`; the runtime honors the classification with `gpt-6-astra`. Legacy assignments/runs use `legacy-xhigh` when no newer policy was pinned. Existing handles are recovered with their recorded runtime configuration. Deterministic delivery/report work does not launch an agent.

`execution_mode: artifact-repair` retains the original result stage and scope but has no project/Git/forge write access, a five-minute timeout, and medium reasoning. Its `repair_of` binds the original assignment, rejected output, referenced evidence, and repository states. Initialize from the original payload and follow the [blocker contract](blockers.md); this is not another implementation attempt.

`execution_mode: packet-verification` is a new read-only action after an explicitly authorized external source repair. It retains the original implementation packet/tasks/checks, pins `external_repair` recovery evidence and current canonical inputs, and grants no project/Git/forge writes in any repository. Verify existing packet completion, unchanged approved scope/contract, and the authorized source transition independently; run the assigned checks freshly in their canonical cwd. External passing logs and cached evidence cannot substitute. Use the new result's `packet_verification` fields described in [result.md](result.md). A material change must block for normal replanning and renewed approval. This one-shot action never upgrades run policy versions or resets source/review/fix allowances.

With validation-policy version 1, build IDs and commands together from sorted effective check objects. A scoped excluded check is absent from future executable lists, while its authorizing amendment is hash-pinned in `input_artifacts`. A remediation assignment carries `remediation`; a restoration assignment carries `validation_refresh`. The validator binds each reference to this run/repository, decision kind, stage, pinned inputs, and exact repair-target list. These decisions do not change retry limits. Execute each check from its canonical plan cwd. Fresh logs must stay under this assignment's `log_dir`; reused passing logs remain in the repository's run log directory. Never overwrite earlier action logs.

New GitHub delivery uses `execution_mode: command`, `delivery_evidence_version: 2`, and a pinned `check_timeout_seconds` (0–1800). Delivery-policy version 1 supplies `pr_lifecycle: draft-until-verified` and `run_id` to the helper. The graph executes it directly, with durable intent/reconciliation and no worker handle. Version-1 delivery assignments also pin `pr_ownership`: repository identity, branch, base branch, and stable `intent_path`. Fallback workers must prove ownership using the same nonce-bound intent and captured observation contract as the command helper; unsupported proof is a blocker, never adoption permission.

A `verify_only: true` command assignment (or version-1 fallback worker assignment) refreshes accepted delivery after interruption with `git_access: none` and `forge_access: none`; it cannot commit, push, create/edit a PR, or change readiness. Other forges retain worker delivery with the same draft/final-head obligations and must report unsupported behavior.

Only project-file stages receive one repository write scope. Only delivery receives Git/forge write access. Workers never mutate run/agent/event/checkpoint state. The LangGraph control plane constructs assignments; workers must not infer or schedule a subsequent phase. The batch supervisor must reject a project-file writer unless the complete current plan set has an approved policy/user decision and the assignment pins that exact review-bundle path/hash. Validate before launch:

```bash
python3 <validator_path> assignment <assignment-path>
```
