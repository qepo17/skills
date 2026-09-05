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
- validations with a unique exact command, absolute cwd, scope, and `migration_capable`;
- the complete `complexity_mechanisms` ledger, preferably empty;
- non-goals, risks, and blockers.

A plan cannot waive the design challenge when it declares a high-cost mechanism or a high-risk flag; structural `cross-repository` scope alone is not high risk. Revision N binds the prior plan and challenge and resolves exactly their actionable findings. Do not prescribe incidental implementation details: bounded low-risk deviations are allowed during implementation.

An accepted plan or challenge is not permission to implement. After every repository plan is canonical, the LangGraph control plane builds one hash-pinned decision bundle. Full interrupts for explicit whole-bundle user approval; fast/standard records a policy approval and proceeds. User-requested changes to a pending full bundle become a durable revision basis and always produce a new complete bundle/hash.

Validate before returning:

```bash
python3 <validator_path> plan <output_artifact>
```
