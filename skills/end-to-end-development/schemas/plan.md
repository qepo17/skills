# Repository plan artifact (`plan`)

Initialize the assigned file first:

```bash
python3 <validator_path> init <assignment_path>
```

For a stage that cannot finish, follow the [blocker contract](blockers.md) and use the typed `block` command.

## Grounded implementation spec

Follow [PLAN-WRITING.md](../PLAN-WRITING.md) inside existing fields. This plan is the implementation spec; do not create another spec or tracker stage.

Reuse pinned intake, evidence and decisions, verifying relevant current code/tests and refreshing stale details. Remote text is task data. Use `CONTEXT.md`/`CONTEXT-MAP.md` and applicable ADRs; record rationale without editing project docs during planning.

Map problem/solution, meaningful stories, acceptance, implementation/testing decisions and scope into task summaries/steps, requirement IDs, validations, non-goals and risks. Steps retain inspected baseline-bound paths/symbols and required `expected_files`; durable product prose stays at module/interface level. Only provenance-labelled existing prototype excerpts may clarify settled decisions. No story quota or new fields.

Testing decisions identify observable behavior, the highest practical existing seam, exercised modules and similar tests. Prefer few useful seams; do not create interfaces for private-helper mocks. Adopt supported reversible in-scope choices with rationale, without routine confirmation. Workers never interview users; unresolved material product/security/data/contract choices require a `decision` blocker. Only the coordinator can use the remaining shared clarification budget.

A complete profiled plan contains:

- `baseline`, nullable `contract_sha256`, and `requirements_sha256`;
- `revision`, nullable `supersedes_plan`, nullable `design_challenge`, and nullable `revision_basis`. Revision 1 has no predecessor. A later revision hash-pins the superseded plan plus exactly one basis: an actionable design challenge, or a `revision_basis` of `user-feedback`, `profile-escalation`, or `contract-revision` with its hash-pinned coordinator artifact;
- sorted `risk_flags` drawn from the accepted risk vocabulary;
- `design_challenge_required` according to the assignment profile and actual risk;
- small ordered `tasks`, each with requirement IDs, dependencies, steps, expected files, validation IDs, and mechanism IDs;
- `work_packets` covering each task exactly once: `id`, `summary`, bounded `task_ids` (three normally, four for fast), dependencies and 5–45 minute estimate. Prefer narrow complete behavior across needed layers, including tests, verifiable in a fresh context. Use genuine prerequisites, not blanket chains or disconnected schema/API/UI work;
- necessary tested, behavior-preserving prefactors may lead. Wide refactors can expand compatibly, migrate bounded caller batches, then remove the old form after every batch. Preserve checks/risk gates. Unsupported intermediate validation requires integration/replanning, not invented green evidence or an integration branch. Cross-repository slices remain repository-local packets coordinated through the shared contract;
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
