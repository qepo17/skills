# Repository plan artifact (`plan`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a stage that cannot finish, follow the [blocker contract](blockers.md) and use the typed `block` command.

A complete profiled plan contains:

- `baseline`, nullable `contract_sha256`, and `requirements_sha256`;
- `revision`, nullable `supersedes_plan`, nullable `design_challenge`, and nullable `revision_basis`. Revision 1 has no predecessor. A later revision hash-pins the superseded plan plus exactly one basis: an actionable design challenge, or a `revision_basis` of `user-feedback`, `profile-escalation`, or `contract-revision` with its hash-pinned coordinator artifact;
- sorted `risk_flags` drawn from the accepted risk vocabulary;
- `design_challenge_required` according to the assignment profile and actual risk;
- small ordered `tasks`, each with requirement IDs, dependencies, steps, expected files, validation IDs, and mechanism IDs;
- `work_packets` covering every task exactly once. A packet has `id`, `summary`, the profile-bounded `task_ids` (three normally, four for fast), packet dependencies, and a 5–45 minute estimate. Group consecutive tasks sharing one concern; do not create a packet per trivial task;
- validations with a unique exact command, absolute cwd, scope, and `migration_capable`. For policy version 1, cwd is the assigned worktree or a directory within it. When the assignment carries `validation_policy_version: 1`, each validation also declares `purpose` (`acceptance`, `repository-required`, or `supplemental`), `gate` (`blocking` or `advisory`), and a concise `rationale` explaining relevance and citing the applicable requirement/repository instruction;
- the complete `complexity_mechanisms` ledger, preferably empty;
- non-goals, risks, and blockers.

A plan cannot waive the design challenge when it declares a high-cost mechanism or a high-risk flag; structural `cross-repository` scope alone is not high risk. Revision N binds the prior plan and challenge and resolves exactly their actionable findings. Do not prescribe incidental implementation details: bounded low-risk deviations are allowed during implementation.

For validation-policy version 1, `scope` describes breadth only and grants no waiver authority. Acceptance covers task correctness, contracted prerequisites, security, and integration obligations; repository-required covers commands mandated by repository policy. Both purposes must be blocking. Migration-capable checks remain protected regardless of purpose/gate. Only supplemental non-migration checks may be advisory or later explicitly excluded. Every task's `validation_ids` must include at least one blocking acceptance check. Do not disguise a mixed mandatory command as optional or rely on schema validation alone: inspect whether each command's semantic classification and rationale match what it actually verifies. Purpose, gate, and rationale appear in the hash-pinned review bundle.

An accepted plan or challenge is not permission to implement. After every repository plan is canonical, the LangGraph control plane builds one hash-pinned decision bundle. Full interrupts for explicit whole-bundle user approval; fast/standard records a policy approval and proceeds. User-requested changes to a pending full bundle become a durable revision basis and always produce a new complete bundle/hash.

Validate before returning:

```bash
python3 <validator_path> plan <output_artifact>
```
