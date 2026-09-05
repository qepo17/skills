---
name: end-to-end-development
description: Run deterministic, resumable end-to-end development across one or more repositories through a durable LangGraph control plane, risk-proportional approval and challenge gates, reusable validation evidence, single-pass review and remediation limits, isolated worktrees, auto-detected headless workers, and validated artifact handoffs.
disable-model-invocation: true
compatibility: Requires uv, Python 3.11+, Git worktrees, Pi or Codex, a repository forge CLI, and the installed codebase-design skill. Paseo, Herdr, and tmux are detected automatically when the coordinator runs inside them; otherwise workers run headlessly. LangGraph dependencies are installed from the locked skill project.
---

# End-to-End Development

**Every coordinator and worker reads [Validation rules](#validation-rules) before planning, project edits, validation commands, or artifact construction.** This is the shared human-readable validation contract; stage schemas are field-shape reminders, not a separate source of rules. [scripts/artifact_guard.py](scripts/artifact_guard.py) enforces the contract at every handoff.

**Coordinator role:** use the bundled **LangGraph workflow as the sole orchestration engine**. Perform only request/repository discovery, dedicated-worktree creation, bootstrap-spec construction, presentation of a high-risk plan-review interrupt when requested by policy, and concise presentation of terminal status. Do not manually choose phases, construct assignments, supervise workers, manage retries, mutate `run.json`, or bypass graph routing.

**Worker role:** execute only your immutable assignment. Read this validation contract and the assigned schema before work; coordinator-only commands later in this file are not permission to initialize/resume a run, approve plans, schedule work, or change limits. Never spawn nested agents or mutate coordinator state.

Resolve `SKILL_DIR` to this directory. Coordinators additionally read before a new run or resume:

1. [ORCHESTRATION.md](ORCHESTRATION.md) completely;
2. [ARTIFACTS.md](ARTIFACTS.md) completely;
3. [SIMPLICITY-CHALLENGE.md](SIMPLICITY-CHALLENGE.md) only when explaining or diagnosing a challenged plan.

Workers do not need the separate coordinator projection/CLI documents; their complete upfront validation contract follows.

## Validation rules

### Before work and before handoff

1. Read this entire section and the immutable assignment. Check `stage`, `output_kind`, IDs, repository/command ownership, pinned inputs, output/log paths, and access grants **before** executing anything. Missing/unreadable rules or stale inputs are a blocker, not permission to improvise.
2. Initialize only a missing, exact assigned output: `python3 <validator_path> init <assignment_path>`. It supplies the correct required fields and null/array shapes. Never overwrite an existing/accepted artifact or invent another output/assignment path.
3. Keep every required field, even when its permitted value is `null` or `[]`. Fill semantic fields and real command outcomes; leave verbose evidence in logs. Check the text/byte limits below while drafting, not after implementation.
4. Run only authorized planned checks with their exact IDs, commands, and cwd. A passed shell command or a coordinator log alone is not accepted workflow evidence. Never represent a skipped, unavailable, coordinator-owned, or not-yet-run check as passed or as a code failure.
5. Before returning, check **all semantic fields** against the common and stage rules here, including required keys, enums, text/byte limits, IDs, outcomes, and evidence paths. Fix mistakes in the unaccepted output without replaying source work or passing tests. A validator stops at its first error, so one diagnostic never establishes that the remaining fields are valid.
6. Run `python3 <validator_path> <output_kind> <output_artifact>` when the artifact has valid mechanical metadata. For normalization-dependent result/review skeletons, leave coordinator-owned assignment hashes, content/command fingerprints, Git HEAD/status snapshots, and fresh-cache defaults alone: perform the semantic checklist and report **normalization pending**, rather than running raw validation against known placeholders or inventing their values. If validation was attempted, report its exact remaining diagnostic and never claim it passed. The graph must normalize and validate every artifact before acceptance; workers must not start a separate pass to compute mechanical fields. This exception does not waive any semantic rule.
7. An accepted artifact is immutable. Repairs, retries, and recovery are graph-owned, bounded, and use new assignments/outputs. A rejected handoff must not cause an agent to redo already-implemented source work, erase evidence, reset an allowance, or request another approval for an unchanged approved bundle.

### Common JSON, identity, and evidence rules

- Use a UTF-8 JSON object with `schema_version` equal to 1, exact `artifact_kind`, and the assignment's `run_id`; format with two-space indentation and a final newline. Integers are not booleans; booleans are JSON `true`/`false`; required strings must contain non-whitespace text unless explicitly nullable. Do not emit comments, markdown fences, transcripts, secrets, or environment values inside JSON.
- Every worker artifact includes `assignment_path` and `assignment_sha256`, and matches that assignment's run, output kind/path, repository, attempt, and result stage. Validate the assignment and its input hashes, not just the result in isolation.
- Repository IDs match `^[a-z0-9][a-z0-9-]*$`; requirement IDs match `^REQ-[0-9]{3,}$`. Preserve assigned stable IDs exactly. Git object IDs are 40 or 64 lowercase hex characters; SHA-256 values are 64 lowercase hex characters. UTC timestamps use `YYYY-MM-DDTHH:MM:SSZ`.
- Repository/worktree/cwd, artifact, assignment, and evidence paths are absolute. Required directories/files must already exist and have the expected type. Source inventories/finding paths are repository-relative, never absolute and never contain `..`.
- Hashed references are objects with `path` and `sha256` naming existing files with matching bytes. Paired nullable path/hash fields are both null or both valid. Do not edit pinned inputs or fix hash mismatches by rebinding old evidence to new content.
- String arrays have unique nonempty entries. Sort IDs, repository keys, references, inventories, and dependency lists lexicographically where specified; preserve execution order for steps and command/ID pairing. Findings use the severity order `critical`, `high`, `medium`, `low`, followed by their stage's tie-breakers.
- `complete` artifacts have no blockers; `blocked` artifacts have at least one. Contract, plan, design-challenge, review, and report statuses are `complete` or `blocked`; result, integration, and delivery additionally support `failed`. A finished review with findings is still complete, not blocked. A completed check-bearing stage still cannot satisfy a passing gate with failed/pending check evidence.

### Text limits

These are per-string character limits (not bytes); nested fields with the same name have the same listed cap. Nullable fields still require their key. Full explanations belong in existing log files.

| Fields | Maximum |
|---|---|
| `run_id` | 160 characters |
| `action_id` | 200 characters |
| `next_action` | 300 characters |
| `summary` | 1200 characters |
| `command`, `meaning`, `description`, `reason`, `evidence` | 2000 characters |
| `required_action`, `necessity`, `repository_evidence`, `necessity_assessment` | 2000 characters |
| `simpler_alternative`, `operational_risk`, `required_change`, `cleanup_error` | 2000 characters |
| `source_text`, `approval_text` | 4000 characters |

`next_action` is a required result key: use `null` or a nonempty string of at most 300 characters, e.g. `"Proceed to independent review."` It is advisory, never graph routing. Arrays such as `simpler_alternatives` are not interchangeable with the singular bounded field. Other strings remain subject to the total artifact cap; concise text is still required.

### Artifact byte limits

Check serialized UTF-8 size including whitespace and metadata. Reserve space for coordinator normalization; the cap is checked before and after normalization. `1 KiB = 1024 bytes`.

| Kind | Maximum |
|---|---|
| `run` | 160 KiB |
| `requirements` | 64 KiB |
| `agents` | 128 KiB |
| `assignment` | 32 KiB |
| `contract` | 96 KiB |
| `plan` | 64 KiB |
| `design-challenge` | 64 KiB |
| `result` | 64 KiB |
| `review` | 64 KiB |
| `integration` | 96 KiB |
| `delivery` | 64 KiB |
| `report` | 32 KiB |

### Assignment scope and numeric bounds

- Assignments are coordinator-owned. Only `implement`, `validation-fix`, `fix-1`, legacy `fix-2`, and `pipeline-fix` may grant project writes, to exactly one assigned repository. Other repositories remain `access: read`. Global assignments have null repository/baseline/pre-existing status/fingerprint; repository assignments pin their baseline and initial status. Repository-scoped read-only assignments pin the input content fingerprint.
- Access flags are **write grants**: `project_file_access: none` and `git_access: none` do not prohibit read-only inspection in an authorized repository. Only delivery may grant Git/forge writes; it may not edit project files. Explicit coordinator-only command ownership in the approved plan still applies. Workers never edit run/agent/event/checkpoint state.
- Profiled implementation has one `packet_id` and exact sorted `task_ids`: 1–3 for standard/full, 1–4 for fast. Other assignment stages have no task IDs/packet ID. `fix-1`/`fix-2` require finding IDs; only those stages and legacy `review-2` use them. Validation-fix assignments require validation IDs. Evidence stages pair every assigned command with its planned validation ID.
- Output mapping: `contract`→contract, `plan`→plan, `design-challenge`→design-challenge, `implement`/`validate`/all source fixes→result, `review-1`/`review-2`→review, `integrate`→integration, `deliver`→delivery, `report`→report. Inputs must include the canonical requirements/request, plan, required accepting challenge, and approved review bundle wherever required by the stage; no waived/stale challenge or superseded plan may substitute.
- Attempts/revisions/action order start at 1; review rounds are 1 or legacy 2; non-null finding line numbers and required-check app IDs start at 1. Assignment timeout is 60–7200 seconds; artifact repair is at most 300 seconds; CI polling is 0–1800 seconds. Profiled packet estimates are 5–45 minutes (legacy unprofiled: at most 60).
- Profile policy bounds: 1–4 tasks, 10–45 packet minutes, 12–60 coordinator attempts; standard/full select three tasks and fast four. Retry counts are nonnegative; `artifact_repairs_per_action` is at most one. New-run limits below are fixed, not agent-tunable; legacy pins remain unchanged.
- Reasoning is `medium`, `high`, or `xhigh`, according to the pinned stage policy below. Implementation cannot use medium except artifact repair; stage-v1 source fixes cannot use medium; full contract/plan/challenge/review/integration use xhigh. Worker names are generated, unique, at most 32 characters, matching `^[a-z][a-z0-9_-]{0,31}$`; never rename surviving handles.

### Blockers and validation records

- Every blocker has **five** required fields: unique `id`, `kind`, `summary`, existing-file `evidence_path`, and `required_action`. Kinds: `decision`, `environment`, `authentication`, `permission`, `infrastructure`, `dependency`, `code`. Choose from evidence; never omit `kind` or relabel a code/decision blocker as retryable.
- Prefer `python3 <validator_path> block <assignment_path> --kind <kind> --summary <concise-text> --evidence-path <existing-log> --required-action <specific-action>` after initialization; optional `--id` supplies the ID. It writes only a live unaccepted output and does not fill other fields, authorize migrations, or repair code. Artifact-repair assignments may not use it to append blockers.
- Each validation record contains `id`, exact `command`, absolute `cwd`, `command_sha256`, `tree_fingerprint`, `cache_status`, nullable `source_artifact`, `exit_code`, `result`, `summary`, and `log_path`. IDs are unique. Hashes must match the exact command and result tree. `pass` requires exit code 0; `fail` records the actual failed command outcome; `not-run` requires null exit code. Executed checks need an existing log; a not-run log may be null.
- `fresh` evidence has null `source_artifact`. `reused` evidence pins an existing result with the same tree and exactly one matching passing ID/command/hash/tree record; it cannot reference itself. Never rebind a stale pass to the present tree. A delivery-only commit may reuse checks only because the content fingerprint is unchanged, not because a commit is trusted.
- The final writer receives the planned suite. A complete profiled implement/validate/review-fix/pipeline-fix result covers every assigned ID/command pair; complete validate results have nonempty evidence. The workflow gate needs every planned check passing on the current tree, bound to the latest writer. Additional unrun/failed records do not silently disappear.
- `not-run` is pending, not a code defect. A coordinator-reserved command stays pending even when someone has an unbound passing log. Only the graph may complete a pending exact `git diff --check` through its allowlisted command executor when all other planned checks pass on current evidence. No shell-expanded variant, arbitrary command, migration, source edit, or suite rerun is authorized; other pending checks block without spending a source-fix allowance.
- Before **any migration-capable command**, confirm disposable isolated-local/test target evidence; never print/copy credentials or run destructive migration/seed/reset operations on production, staging, shared, or ambiguous databases. Missing isolation evidence blocks. Record `migration_capable` honestly, including framework tests that auto-run migrations.

### Artifact field inventories

All kinds inherit the common identity fields above; worker kinds also inherit assignment binding. The initialized skeleton is the exact shape. Keep required nullable/empty fields. Conditional profiled/versioned fields follow the semicolon; legacy artifacts retain their recorded schema/policy rather than acquiring new claims.

| Kind | Fields beyond common identity |
|---|---|
| `run` | Required: `created_at`, `updated_at`, `status`, `phase`, `request_path`, `request_sha256`, `requirements_path`, `requirements_sha256`, nullable paired `contract_path`/`contract_sha256`, `retry_limits`, `repositories`, `accepted_artifacts`, `next_actions`, `blockers`; profiled/versioned `profile`, `profile_reasons`, `risk_flags`, `workflow_policy`, `plan_review`, `worker_execution`, `worker_reasoning_policy`, `pending_delivery_refresh` |
| `requirements` | Required: `created_at`, `requirements`, `constraints` |
| `agents` | Required: `updated_at`, `agents` |
| `assignment` | Required: `action_id`, `created_at`, `stage`, `attempt`, `repo_id`, `cwd`, `thinking`, `timeout_seconds`, `project_file_access`, `git_access`, `forge_access`, `repositories`, `baseline`, `preexisting_status_path`, `input_artifacts`, `requirement_ids`, `instructions`, `validation_commands`, `output_kind`, `output_artifact`, `log_dir`, `validator_path`, `artifact_schema_path` (legacy `artifact_contract_path`); profiled/versioned/stage controls `profile`, `reasoning_policy`, `input_tree_fingerprint`, `task_ids`, `packet_id`, `finding_ids`, `validation_ids`, `plan_review`, `execution_mode`, `repair_of`, `coordinator_validation`, `delivery_evidence_version`, `contract_revision`, `plan_revision`, `contract_required`, `design_challenge_policy`, `revision_basis`, `verify_only`, `check_timeout_seconds` |
| `contract` | Required: `revision`, `created_at`, `status`, `requirement_map`, `domain_terms`, `behavior_rules`, `interfaces`, `dependencies`, `compatibility`, `rollout`, `cross_repository_validation`, `risks`, `open_questions`, `blockers` |
| `plan` | Required: `repo_id`, `revision`, `supersedes_plan`, `design_challenge`, `created_at`, `status`, `baseline`, `contract_sha256`, `validations`, `tasks`, `complexity_mechanisms`, `finding_resolutions`, `non_goals`, `risks`, `blockers`; profiled `requirements_sha256`, `risk_flags`, `design_challenge_required`, `work_packets`, nullable `revision_basis` |
| `design-challenge` | Required: `repo_id`, `attempt`, `created_at`, `status`, `baseline`, `contract_sha256`, `plan`, `mode`, `verdict`, `summary`, `mechanism_assessments`, `findings`, `blockers` |
| `result` | Required: `repo_id`, `stage`, `attempt`, `created_at`, `status`, `summary`, `requirement_ids`, `task_ids`, `changed_files`, `validations`, `decisions`, `resolutions`, `git`, `blockers`, `next_action`; profiled `tree_fingerprint`, implementation `packet_id`, coordinator command `command_evidence` |
| `review` | Required: `repo_id`, `round`, `created_at`, `status`, `baseline`, `reviewed_status_path`, `findings`, `blockers`; profiled `mode`, `verified_finding_ids` |
| `integration` | Required: `created_at`, `status`, `requirement_matrix`, `interfaces`, `mechanism_conformance`, `changed_files_by_repo`, `rollout`, `risks`, `blockers` |
| `delivery` | Required: `repo_id`, `attempt`, `created_at`, `status`, `branch`, `base_branch`, `commits`, `pr_url`, `checks`, `blockers`; version 2 `head_sha`, `pushed_head_sha`, `checked_head_sha`, `check_policy`; scripted `command_evidence`, `delivery_outcome` |
| `report` | Required: `created_at`, `status`, `html_path`, `html_size_bytes`, `html_sha256`, `requirement_ids`, `high_impact_topics`, `blockers` |

### Contract and plan rules

- Contracts: a nonempty `requirement_map` covers assigned requirements with nonempty sorted repository lists. Domain terms have `term`/`meaning`; behavior rules have `id`, nonempty sorted `requirement_ids`, `description`. Interfaces have unique `id`, `producer_repo_id`, nonempty sorted `consumer_repo_ids`, `kind`, `description`, and sorted existing `evidence_paths`.
- Contract dependencies have `from_repo_id`, `to_repo_id`, `reason`, and `evidence`; reject duplicate edges, self-dependencies, and cycles. Keep compatibility, rollout, cross-repository validation, risks, and open questions as unique string arrays. Complete contracts have no open questions or blockers. Do not add speculative mechanisms.
- Plans: a complete plan has nonempty tasks/validations and, when profiled, bounded work packets. Bind the assigned repository/baseline, actual requirements hash, and the policy-selected contract hash (null only when no shared contract is required). Validation IDs are unique/sorted; commands are unique; each validation has `id`, `command`, existing absolute `cwd`, `scope` (`focused`, `broad`, `integration`), and boolean `migration_capable`.
- Tasks have unique sorted `id`, nonempty sorted `requirement_ids`, sorted `depends_on`, `summary`, nonempty `steps`, sorted relative `expected_files`, nonempty sorted known `validation_ids`, and sorted known `mechanism_ids`. Dependencies use known tasks, no self-links or cycles.
- Packets have unique sorted `id`, `summary`, nonempty sorted known `task_ids`, sorted known `depends_on`, and bounded `estimated_minutes`. Every task has exactly one owner packet. Cross-packet task dependencies must appear as packet dependencies; packet graphs also reject self-links/cycles. Do not disguise an oversized packet with tiny nominal tasks.
- Risk vocabulary: `authorization`, `background-processing`, `concurrency`, `cross-repository`, `data-backfill`, `database-migration`, `high-cost-mechanism`, `new-storage`, `public-interface`, `security`. All except structural cross-repository scope are high risk. Migration-capable validation requires `database-migration`. High-risk flags or any complexity mechanism require a challenge; assignment `all` policy also requires it. Low-risk fast plans cannot invent a critic gate.
- Mechanism types: `database-trigger`, `database-function`, `stored-procedure`, `data-backfill`, `background-job`, `event-driven-flow`, `cache`, `new-seam-or-adapter`, `new-storage-system`, `other`. Prefer an empty ledger. Each mechanism has unique sorted `id`, `type`, nonempty known requirement/task/validation IDs, `summary`, `necessity`, `repository_evidence`, nonempty `simpler_alternatives`, and nonempty `operational_considerations`. Task links are reciprocal; linked task requirements cover mechanism requirements.
- Revision 1 has null predecessor/challenge/basis and no finding resolutions. Revision N is exactly predecessor revision +1, on the same repository/baseline, with hashed `supersedes_plan` and **one** basis: the preceding revision-verdict challenge, or an object with `kind` and hashed `artifact`, where kind is `user-feedback`, `profile-escalation`, or `contract-revision`. Pin both predecessor and basis in the assignment.
- A challenge-based plan revision resolves exactly the actionable challenge finding IDs when complete (only a subset when blocked), using `finding_id`, `outcome` (`resolved`, `inapplicable`), `summary`, `evidence`, unique/sorted by finding ID. The challenge must bind the predecessor hash. `revise-plan` preserves its contract hash; `revise-contract` requires a changed contract hash. Other revision bases have no challenge finding resolutions. A canonical plan is never, by itself, approval to implement.

### Design challenge and review rules

- Challenge assignments inspect exactly the assigned repository and pin the exact plan, same repository/baseline/contract, `SIMPLICITY-CHALLENGE.md`, and installed codebase-design `SKILL.md`/`DEEPENING.md` guidance. Use `mode: full` for an initial candidate and `verification` only for a revised plan. Verdicts are `accept`, `revise-plan`, `revise-contract`, or `blocked`.
- Mechanism assessments have `mechanism_id`, `decision` (`retain`, `replace`, `remove`), `necessity_assessment`, `repository_evidence`, `simpler_alternative`, and `operational_risk`. IDs are unique/sorted, exactly covering plan mechanisms for complete challenges (a known subset for blocked challenges). Replace/remove needs a linked actionable finding; also inspect for undeclared mechanisms.
- Challenge findings have unique `id`, `target` (`plan`, `contract`), `category` (`necessity`, `scope`, `seam`, `database`, `migration`, `operability`, `testability`), `severity`/boolean `actionable`, nonempty known `requirement_ids`, known `task_ids` (nonempty for plan findings), nullable known `mechanism_id`, `summary`, `evidence`, `simpler_alternative`, and `required_change`. Sort by severity, target, ID.
- Accepting challenges have no actionable finding; `revise-plan` needs an actionable plan finding and no actionable contract finding; `revise-contract` needs an actionable contract finding. Blocked status and blocked verdict must agree. Challengers do not write replacement plans or project files.
- Independent review round 1 uses `mode: full`, empty `verified_finding_ids`, and examines the complete baseline-to-worktree change. Legacy round 2 uses `verification` and exactly the nonempty assigned finding IDs. New runs never schedule it. Reviewers have read-only repository access. Check contract/plan conformance and complexity drift against the accepted inputs, not just syntax or passing tests.
- Review findings have unique `id`, category (`standards`, `spec`), `severity`/boolean `actionable`, `disposition` (`must-fix`, `advisory`), required nullable `requirement_id`, relative `path`, nullable positive `line`, `summary`, and `evidence`. Sort by severity, path, line (null sorts as 0), ID. Non-actionable findings are advisory; actionable critical/high/medium findings must be must-fix. Low findings are normally advisory. Do not duplicate findings enforced by passing tooling.
- A review that finished is `complete` even with must-fix findings. Use blocked only when review itself cannot finish. `reviewed_status_path` holds only exact final `git status --short` output, without commentary; the graph adds its authoritative snapshot. Findings remain a delivery gate, not another plan-approval request.

### Implementation, fixes, integration, delivery, and report rules

- Results match the assigned stage/attempt/packet/tasks and may claim only assigned requirement IDs. `changed_files` is the complete sorted relative inventory. `git` contains `head` and existing `status_short_path`; the acceptance seam verifies/normalizes these along with current content and validation command hashes.
- Decisions have `id`, `kind` (`implementation`, `bounded-plan-deviation`, `validation`, `finding-resolution`, `pipeline`), `summary`, and `evidence`. A bounded deviation preserves accepted requirements/contract, adds no risk/mechanism, follows repository precedent, and stays within the packet concern. Material behavior/interface/migration/dependency changes block instead.
- Result resolutions have unique `finding_id`, `outcome` (`fixed`, `inapplicable`), `summary`, and existing `evidence_path`; complete review-fix batches resolve exactly the assigned finding IDs. Do not confuse result resolution `fixed` with plan resolution `resolved`.
- Integration requires a nonempty requirement matrix with unique sorted `requirement_id`, nonempty sorted `repository_ids` and existing-file `validation_evidence`, plus contracted interfaces (`interface_id`, `status`, nonempty existing sorted `evidence_paths`). Entry states are `pass`, `fail`, or `blocked`.
- Integration mechanism-conformance entries cover exactly the matrix repositories, sorted/unique by `repo_id`, and contain `plan_path`, `design_challenge_path`, `status`, and existing sorted nonempty file `evidence_paths`. The challenge is null exactly when the plan waived it; otherwise it must accept that exact plan hash/repository. `changed_files_by_repo` has sorted repository keys and sorted relative inventories. Complete integration has only passing entries.
- Delivery records actual branch/base, unique Git commit IDs, nullable HTTP(S) PR URL, and checks with `name`, HTTP(S) `url`, boolean `required`, `state` (`passed`, `failed`, `cancelled`, `skipped`, `pending`), and existing-file `evidence_path`. Before committing, audit the baseline diff and untracked files, preserve pre-existing changes, and commit only task files. Complete delivery requires commits, a PR URL, no blockers, and every required check passed; never force-push.
- Version-2 delivery binds local/pushed/checked heads to the last delivered commit and actual worktree HEAD/base. `check_policy` has `status` (`required`, `not-configured`, `unknown`), `required_checks` (`name`, nullable positive `app_id`), and hashed evidence. Complete delivery needs nonempty policy evidence, no unknown policy, and exactly the required/nonempty versus not-configured/empty policy distinction. Every required name/app identity must match passing required checks.
- Empty rollups are not absence evidence; positive absence is `not-configured`, never “CI passed.” Pending/missing/timed-out/skipped/cancelled checks, changed heads/policy, and unknown policy cannot complete. Pending/infrastructure/authentication/permission failures do not consume source-fix cycles; compatible real code failures retain the bounded pipeline-fix gate. Scripted delivery also binds `command_evidence` and `delivery_outcome`; verify-only commands have no Git/forge writes.
- Reports are graph-generated, not model-written. Record exact HTML path/byte size/hash, sorted requirement IDs, unique high-impact topics, and blockers. Complete reports need nonempty requirement coverage and an existing nonempty HTML file whose bytes/hash match, with `<html` or `<!doctype html` in its first 1024 characters. Never rewrite an accepted report.

### Repair, coordinator-command, and projection validation

- Artifact repair is only for otherwise-intact results with missing blocker kinds and/or an originally oversized `next_action`. It retains original stage/IDs/commands/inputs, a distinct bounded action/output, medium reasoning, at most 300 seconds, no project/Git/forge writes, and `repair_of` with pinned original `assignment`/`artifact`/`evidence` plus `repository_states` (each has SHA-256 `fingerprint`/`index_sha256`, Git `head`, and `branch`). No recursive repair, new blocker, test rerun, changed outcome/text/check/evidence, or manufactured pass. Only missing kinds, oversized advisory text (shortened or null), and coordinator-owned metadata may differ. Ambiguous classification stays unresolved in logs and blocks.
- Coordinator validation is a graph-only `validate` command assignment whose `coordinator_validation` has `executor` equal to `git-diff-check-v1`, exact hashed `source`/`evidence` inventory, and pinned `repository_state`, protected by an immutable assignment digest. It accepts only complete same-run/repository/tree records covering every planned pair, with all other checks passing and only pending exact `git diff --check`. The command capture binds `assignment`, `repository_state`, fixed `argv`, nonnegative `exit_code`, UTC `completed_at`, and hashed `log`. The entire new result is deterministic; reused records preserve original facts, only the check gets its captured outcome, and only the Git snapshot is normalization-owned. Workers never author these artifacts or trust unbound logs.
- Coordinator projections are not worker outputs. `requirements` has nonempty unique sorted `id` entries with `source_text`, nonempty `acceptance_criteria`/`repository_ids`, and unique `constraints`. `run` binds request/requirements/contract hashes, nonempty sorted repositories, canonical accepted plans/challenges, policy, phase/status, actions, and blockers. Repository `root`/`worktree`/`artifact_dir` directories and `initial_status_path` files must exist; scope entries have `access` equal to `read` or `write`. Run repository records also bind `branch`, `base_branch`, `baseline`, `stage`, `status`, nullable `active_writer`, paired `plan_path`/`plan_sha256` and `design_challenge_path`/`design_challenge_sha256`. Canonical plans/challenges must occur in repository `accepted_artifacts`; a required contract must exist after contract, a canonical plan after planning, and a required accepting challenge before advancing beyond planning. Challenges require a plan and bind its exact repository/plan/contract hashes; recorded `design_challenge_required` matches the plan.
- Run phases are bootstrap, contract, plan, plan-review, implement, validate, review-1, fix-1, legacy review-2/fix-2, integrate, deliver, report, complete. Run states are working, awaiting-user, blocked, failed, complete; repository states are pending, working, blocked, failed, complete. `next_actions` have unique ascending positive `order`, unique `action_id`, valid `repo_id`, sorted existing `input_artifacts`, `output_artifact` paths, positive `attempt`, and pending/working/blocked `status`.
- Profiled runs require nonempty unique `profile_reasons` and sorted `risk_flags`; fast allows one repository and no run risks. Multiple repositories require both shared contract and integration. `workflow_policy` contains boolean `contract_required`, `integration_required`, `report_required`, `auto_resume`, and `user_plan_approval_required` (legacy omission means true), enum `design_challenge` (`none`, `risk-only`, `all`), numeric `max_tasks_per_packet`, `max_packet_minutes`, `coordinator_attempt_budget`, `second_review` (`never`, legacy `high-risk-fixes`), and sorted nonempty `blocking_severities` containing critical/high/medium (optionally low). Full requires explicit approval and risk-only or legacy all challenges; standard requires risk-only; fast requires no shared contract/integration/challenge/second review. Other bounds and new-run selections are below.
- `plan_review` has `status`, `requested_at`, `review_path`/`review_sha256`, canonical `contract_sha256`, sorted `plans` covering every repository exactly once with canonical plan/challenge path/hash pairs, required nullable `approved_at`/`approval_text`, and `approval_source`. It is null before required plan review. Approval bundles are versioned `plan-review-vN.md`, hash-pinned, and name every repository/canonical path/hash. Pending approval has no approval evidence; approved timestamps cannot precede the request and the decision source is user or workflow-policy. Awaiting-user requires all repositories parked at plan-review with no actions/blockers/writers; approved bundles advance atomically. Any canonical hash change invalidates approval; unchanged valid approval is preserved through recovery.
- Agents have unique `name`, `stage`/`repo_id`/`attempt`, `backend`/`handle_id` (legacy `pane_id`), `started_at`/nullable `ended_at` timestamps, `output_artifact`, `status` (starting, working, blocked, idle, failed, closed), and `cleanup_status` (pending, retained, complete, failed). Failed/closed agents require an end time; settled handles must be cleaned before completion. Worker execution pins contain `backend` (direct/herdr/paseo/tmux), `runtime` (pi/codex), `detected_from`, an `evidence` object, and `schema_version` equal to 1; never substitute an unsupported configuration.
- `pending_delivery_refresh` names only known repositories and pins one of that repository's accepted delivery observations; it must be empty before completion. Completion requires phase/status complete, empty actions/blockers/refresh obligations, valid approved canonical inputs, passing current validation, required accepted integration/report/delivery evidence, no unresolved must-fix finding, no unexplained writer lease, and no open settled worker. Restore evidence through supported transitions only, not manual state edits. The bounds, role permissions, and decision/retry gates elsewhere in this file apply throughout.

## Non-negotiable invariants

1. **One executable state machine.** LangGraph owns phase selection, conditional routing, retries, interrupts, fan-out/fan-in, writer leases, and completion. Never reimplement those decisions in the coordinator conversation.
2. **Evidence is hash-pinned.** A result, validation, finding, blocker, approval, delivery, or next action is known only after it exists in validated durable state or an immutable artifact.
3. **Reconcile before action.** Every graph path starts by reconciling run artifacts with output files and external state. Resume from artifacts, never conversation memory.
4. **Follow the selected policy.** Ordinary single- and multi-repository work may use the standard no-pause path. High-risk discovery escalates to full before project-file work.
5. **One active project-file writer per repository.** The lease protects a role, not an agent identity. Work packets and fix batches preserve it.
6. **Workers do not mutate coordinator state.** They write only their exact output, allowed project files, and log directory. The graph updates run, agent, event, lease, and checkpoint state.
7. **Every loop is bounded.** New runs get one review, one review-fix batch, one validation-fix cycle, and one pipeline-fix cycle. Worker replacement and planning revision limits are also enforced by the graph. Never “continue until green.”
8. **Preserve evidence, not transcripts.** Full output stays in logs. Artifacts contain commands, hashes, exit codes, concise conclusions, and evidence paths.
9. **No silent degradation.** Missing, invalid, oversized, stale-tree, or contradictory evidence leaves the gate incomplete.
10. **Migration safety is mandatory.** The graph must have isolated local/test database-target evidence before migration-capable validation. Never use production, staging, shared, or ambiguous databases; never copy `.env` into a new worktree.
11. **No undeclared high-cost mechanism.** Stop rather than invent a trigger, database function/procedure, backfill, background/event flow, cache, seam/adapter, storage system, or comparable mechanism absent from the approved plan.
12. **Independent review remains mandatory.** Every profile gets at least one fresh baseline-to-worktree review before delivery.
13. **High-risk plan approval is a hard gate.** Full-profile implementation cannot begin until a later user message explicitly approves every plan in the exact current hash-pinned review bundle. Fast/standard policy records an automatic hash-pinned decision without pausing; discovery of a high-risk surface invalidates it and escalates before implementation.
14. **External side effects are idempotently reconciled.** LangGraph checkpointing does not make workers, commits, pushes, or PR creation exactly-once. Valid existing evidence is recovered instead of repeated.
15. **Completed worker handles are short-lived.** The supervisor records an opaque backend handle, cleans it as soon as its worker settles and its output is captured, and records the result. Crash recovery uses the pinned backend to apply the same cleanup even when the output artifact already exists. Never report completion while a settled workflow worker remains open.

## Coordinator command interface

The orchestrator resolves the required `codebase-design` skill beside this skill and in common Pi/Codex global skill directories. If it is installed elsewhere, set `E2E_CODEBASE_DESIGN_DIR` to the directory containing its `SKILL.md` and `DEEPENING.md` files.

Always invoke the locked project through the wrapper, which keeps the generated virtual environment in the user cache rather than the installed skill directory:

```bash
ORCHESTRATOR="$SKILL_DIR/scripts/run-orchestrator"
```

Do not invoke `workflow_tools.py run-batch` directly during a graph-managed run. It is an internal graph primitive.

### New run

Treat skill arguments plus relevant user conversation as the complete request.

1. Discover every affected repository and every material risk before creating run state.
2. Ask the user only when repository identity or a material product choice cannot be established from the request and repository evidence. A later plan-review interrupt is mandatory only if policy selects full.
3. Create one dedicated worktree per repository, preferring Worktrunk:

   ```bash
   wt switch --create <branch> --format json --no-cd
   ```

   The dedicated worktree must be clean. Never copy `.env` or other database credentials into it.
4. Write a bootstrap specification using the exact shape in [ORCHESTRATION.md](ORCHESTRATION.md). Preserve material user wording in requirement source text and acceptance criteria.
5. Choose durable run state under:

   ```text
   ${HOME}/.local/state/pi/end-to-end-development/<UTC-timestamp>-<request-slug>/
   ```

   Never use `/tmp`.
6. Initialize, then execute:

   ```bash
   "$ORCHESTRATOR" init --spec "$BOOTSTRAP_SPEC" --run-dir "$RUN_DIR"
   "$ORCHESTRATOR" run "$RUN_DIR" --worker-runtime auto
   ```

The command runs until completion, a validated blocker, or a full-profile plan-review LangGraph interrupt.

### Resume

For an explicit run directory:

```bash
"$ORCHESTRATOR" resume <absolute-run-directory> --worker-runtime auto
```

If the user says only “continue,” search the durable root for incomplete runs whose repository roots contain the current directory. Resume only when exactly one matches; otherwise list candidates. If that full-profile run is awaiting plan review, **do not call `resume`**: re-present the current bundle and request explicit whole-bundle approval or changes.

Inspect without advancing:

```bash
"$ORCHESTRATOR" status "$RUN_DIR"
```

Never edit `run.json`, `agents.json`, `events.jsonl`, assignments, or LangGraph SQLite state to repair a run. Diagnose the rejected evidence or use a supported CLI transition. `resume` retries blockers classified as environment, authentication, permission, or infrastructure after the external condition is fixed; it never clears code, dependency, or decision blockers. If an older engine created a validation assignment without the canonical plan IDs and then emitted the exact validation-coverage blocker, update the engine and use the narrowly guarded recovery command:

```bash
"$ORCHESTRATOR" retry-validation-evidence "$RUN_DIR" --worker-runtime auto
```

This command rejects every other blocker and reruns validation with a new plan-hash-bound assignment; it does not weaken ordinary code-blocker handling.

If an older engine rejected a result solely because `next_action` exceeded 300 characters, update the engine and use:

```bash
"$ORCHESTRATOR" retry-artifact-repair "$RUN_DIR" --worker-runtime auto
```

This guarded transition requires the exact handoff-metadata rejection, intact current evidence, settled workers, and an unused pinned repair allowance. It creates a read-only artifact repair, not another implementation or validation attempt. It does not clear unrelated blockers, replenish attempts, or skip independent review and delivery gates. Do not edit the rejected artifact or coordinator state by hand.

If an older run exhausted validation fixes solely because a permission-blocked `git diff --check` was recorded as `not-run`, update the engine and use:

```bash
"$ORCHESTRATOR" retry-coordinator-validation "$RUN_DIR" --worker-runtime auto
```

This requires the exact exhausted gate, unchanged current evidence, a no-change permission-blocked fix, and an already-approved plan bundle. The graph executes only the allowlisted whitespace check and records a new hash-bound result, reusing the other passing checks. A loose coordinator log is not accepted as proof; the safe command is observed again under durable assignment intent. Limits and approval are never reset. Real check failures, stale evidence, and unrelated blockers are refused. For an accompanying oversized UI handoff, use `retry-artifact-repair` on that run separately; neither recovery requests another plan approval or bypasses independent review/PR checks.

If a dependent fix was started concurrently with an upstream contract fix and stopped on the exact hash-pinned bundle-drift blocker, update the engine and use:

```bash
"$ORCHESTRATOR" retry-dependent-fixes "$RUN_DIR" --worker-runtime auto
```

The guarded transition rejects other dependency blockers, serializes remaining fixes in shared-contract dependency order, grants read-only access to upstream worktrees, and pins accepted upstream fix artifacts into each dependent assignment.

## Full-profile plan-review interrupt

Fast and standard runs still emit a complete hash-pinned review bundle, but policy accepts it atomically without a user pause. When a full-profile graph returns `status: awaiting-user` and `phase: plan-review`:

1. Read `plan_review.path` and verify the reported SHA-256 still matches.
2. Present the bundle path, hash, and concise per-repository task/packet/risk/validation summaries.
3. Ask exactly: **“Approve all plans in this exact review bundle, or send the changes you want.”**
4. End the turn. Do not create implementation work, edit project files, or invoke a generic resume.

On a later message, approval is valid only when the user's wording explicitly approves the whole current bundle. Preserve that wording exactly:

```bash
"$ORCHESTRATOR" approve "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_APPROVAL" \
  --worker-runtime auto
```

The CLI independently rejects generic continuation and a stale hash.

For requested changes:

```bash
"$ORCHESTRATOR" request-changes "$RUN_DIR" \
  --review-sha256 "$CURRENT_BUNDLE_SHA256" \
  --text "$EXACT_USER_FEEDBACK" \
  [--repository <repo-id>] \
  --worker-runtime auto
```

Omit `--repository` when feedback affects the whole bundle. The graph creates a hash-pinned revision basis, returns the affected plans through the bounded planning path, reruns required challenges, emits a new complete bundle, and interrupts again. Any canonical contract, plan, or challenge hash change invalidates prior approval.

## Database-target safety gate

If the graph blocks because a plan contains a migration-capable validation, independently confirm that the target is disposable and isolated. Never print or record the database URL or credentials. Then record only safe classification evidence:

```bash
"$ORCHESTRATOR" database-target "$RUN_DIR" \
  --repository <repo-id> \
  --classification isolated-test \
  --description "Ephemeral database dedicated to this worktree"
```

Allowed classifications are `isolated-local` and `isolated-test`. The command rejects production, staging, shared, and ambiguous targets. Resume through the graph afterward. This evidence does not authorize an unplanned destructive migration, reset, fresh migration, seed, or drop operation.

## Deterministic policy

The initializer applies:

```bash
python3 "$SKILL_DIR/scripts/workflow_tools.py" policy \
  --repository-count <N> \
  [--risk authorization] [--risk database-migration] \
  [--profile auto|fast|standard|full] [--report]
```

`fast` is opt-in. `standard` is the automatic ordinary-work default, including coordinated multi-repository changes. Authorization, security, concurrency, migration, backfill, background processing, new storage, public-interface changes, or another high-cost mechanism force `full`. Planning can escalate before implementation when it discovers risk. Repository count and the `cross-repository` flag alone do not force full.

| Gate | Fast | Standard | Full |
|---|---|---|---|
| Shared contract | embedded in plan | multi-repository only | multi-repository only |
| Design challenge | none unless discovery escalates | risk-only | risk-only |
| Complete-plan user approval | policy-accepted | policy-accepted | explicit user approval |
| Implementation packet | ≤4 tasks | ≤3 tasks | ≤3 tasks |
| Independent full review | one | one | one |
| Targeted second review | never | never | never |
| Cross-repository integration | no | multi-repository only | multi-repository only |
| Deterministic HTML report | requested only | requested only | requested only |

New runs use these hard stage limits:

```json
{
  "worker_replacements_per_stage": 1,
  "artifact_repairs_per_action": 1,
  "contract_revisions": 1,
  "plan_revision_cycles": 1,
  "validation_fix_cycles": 1,
  "review_rounds": 1,
  "pipeline_fix_cycles": 1
}
```

A review may produce one compatible `fix-1` batch, but that fix never starts another review. A validation or required-check failure may produce one compatible fix batch and one check afterward; another failure blocks with preserved evidence. Never modify limits during an active run. Existing durable runs retain their pinned limits when resumed.

The graph checks `coordinator_attempt_budget` after each atomic batch. When reached, it checkpoints at `reconcile`; when `auto_resume` is true the CLI starts a fresh bounded graph invocation from that checkpoint, otherwise it returns `outcome: budget-checkpoint` for a supported later resume. Neither path can cross a pending plan-review interrupt.

## Executable phase behavior

The compiled graph contains these phase nodes, with `reconcile` between every transition:

1. `bootstrap`, auto-detecting and pinning the worker backend/runtime, then verifying Git worktrees, forge remotes, and forge CLI authentication
2. `contract` when policy requires it
3. `plan`, including conditional challenge and one bounded revision
4. `plan-review`, implemented with LangGraph `interrupt()` only for full; fast/standard records a policy decision and proceeds
5. `implement`, scheduling topologically eligible work packets
6. `validate`, with at most one validation-fix batch
7. `review-1`
8. `fix-1` when must-fix findings exist, with no follow-up review cycle
9. `integrate` when policy requires it
10. `deliver`, with at most one pipeline-fix batch for change-related failures
11. post-delivery content-evidence confirmation
12. `report` when required
13. `complete`, with final audit and deterministic metrics

The graph retains `review-2` and `fix-2` nodes only so older durable runs with a pinned two-round limit can resume safely. New runs never schedule them.

Repository IDs and stable IDs sort lexicographically. Independent repositories launch together through one supervisor batch. Contract dependency evidence is the only reason to serialize repositories.

### Worker routing

The graph constructs immutable assignments and invokes the supervisor internally. Users do not configure a terminal manager. Bootstrap selects the first positively detected active environment in this order: a reachable Paseo parent from `PASEO_AGENT_ID`, a compatible Herdr server from `HERDR_ENV`, the active tmux session from `TMUX`, then the always-available direct headless backend. `PASEO_HOST` alone never selects remote workers because remote paths may not match the coordinator's hash-pinned paths. The selected backend and evidence are pinned in `run.json` for recovery.

`--worker-runtime auto` inherits a Paseo parent's Pi/Codex provider when present, otherwise follows the coordinator: Codex when `CODEX_THREAD_ID` is present and Pi by default. `E2E_COORDINATOR_RUNTIME` remains an internal diagnostic override, not required user setup.

Workers keep `gpt-6-astra`. New runs pin `worker_reasoning_policy: stage-v1`: `xhigh` for full-profile contract/planning/challenge/review/integration; `high` for ordinary planning/review and all source-writing implementation/fixes; `medium` for artifact-only repair, validation-only work, and fallback delivery. Launchers honor the actual level across every backend. Legacy runs without a pinned stage policy retain xhigh, and surviving handles retain their recorded configuration. Unsupported configuration blocks; never silently substitute a model.

Workers never spawn nested agents. A Paseo coordinator creates Paseo subagents, Herdr creates non-focused workspaces, tmux creates detached windows, and direct mode runs non-interactively without a terminal manager. The supervisor archives or closes each settled handle immediately after capturing its artifact result, including rejected artifacts; working, blocked, and timed-out workers are retained for diagnosis.

### Artifact-only recovery

Workers should use the typed `artifact_guard.py block` command and [blocker schema](schemas/blockers.md). In runs with a pinned repair allowance, a parseable result with only missing `blockers[*].kind` and/or an oversized advisory `next_action` receives at most one five-minute, medium-reasoning artifact-only repair. `next_action` must be null or at most 300 characters; only an originally oversized value may be shortened or cleared. Graph routing never depends on this text. It has a new immutable assignment/output, no project/Git/forge write permission, and pinned original semantics, logs, content, HEAD, branch, and index. It cannot manufacture a pass, rewrite evidence, or start another source writer. Ambiguous/invalid repair and stale evidence block with an actionable explanation. Missing files or process failures remain distinct from eligible schema repair. Resume never resets the allowance; legacy runs retain their existing policy.

### Work packets and bounded deviations

The plan defines the packet, not individual task, as the implementation unit. A worker may record a bounded deviation only when it preserves accepted requirements and contract, adds no risk or mechanism, follows repository precedent, remains within the packet concern, and records evidence. A new behavior, contract/interface change, migration, dependency edge, or high-cost mechanism is material and blocks rather than silently replans.

### Validation and review

The graph computes a content fingerprint independent of commit identity. The final implementation/fix writer runs the complete planned suite, and the graph reuses that evidence only when validation ID, exact command hash, and content fingerprint match. A delivery-only commit therefore causes no duplicate validation; any source change invalidates the evidence. Compatible failures are fixed in one batch and checked once afterward.

`not-run` is pending evidence, not a failed test, and never spends a source-fix allowance. When every other planned check has current passing evidence and only the exact `git diff --check` remains pending, the graph records it through a bounded read-only command assignment. All other pending commands block for execution/ownership resolution. No arbitrary shell command, migration, source edit, or unbound coordinator assertion is authorized by this path.

One fresh worker independently reviews the complete baseline-to-worktree state. Critical/high actionable findings always block; medium correctness/spec findings normally block; low findings remain advisory. Compatible must-fix findings are resolved in one repository batch, affected checks run once, and the workflow proceeds without a second review. An incompatible or still-failing correction blocks instead of opening another remediation loop.

### Delivery and completion

New GitHub.com runs pin a deterministic command executor using [scripts/delivery_tools.py](scripts/delivery_tools.py), not a delivery agent. It audits the explicit task inventory, preserves unrelated work, commits/pushes without force, reconciles the existing PR, and checks CI against the local/pushed/PR head. Command intents are durable and recovered without worker handles; independent repositories can execute delivery concurrently. Other forges and legacy runs retain their pinned worker path.

Version-2 delivery evidence requires positive required-check policy discovery, the final checked head, and every required identity passing. An empty rollup is not a waiver: verified absence is `not-configured`, never "CI passed." Pending/missing/timed-out, skipped/cancelled, changed-head/policy, or unknown-policy results cannot complete. Authentication, permission, and infrastructure failures block rather than churn. Only compatible change-related failures get one pipeline-fix batch; pending checks do not spend it. Bootstrap can set a repository's `delivery_check_timeout_seconds` from 0 (observe once) to 1800 (default). This is a CI polling limit, not a whole-run deadline.

After delivery, the graph verifies that the committed content still matches passing evidence rather than invalidating it merely because `HEAD` changed. Completion then verifies the policy-selected plan decision, canonical hashes, current validation, required integration/report evidence, delivery artifacts, no unresolved must-fix finding, no unexplained writer lease, no open workflow worker handle, empty actions, and empty blockers. Metrics are generated deterministically, counting command attempts separately from agent launches. Do not infer elapsed-time improvements from mocked worker counts.

## Final response

Use the orchestrator JSON output. Keep the final response concise:

- status;
- absolute run directory;
- PR URLs;
- report path/URL when present.

For WSL local HTML, convert the absolute report path to a `file://wsl.localhost/Ubuntu-Shared...` URL on its own line.
