# Simplicity challenge

Apply before implementation when the candidate plan declares high risk or high-cost mechanisms. Low-risk plans waive this worker under `workflow_policy`. Seek the least powerful design satisfying accepted requirements, contract and repository conventions.

Use the pinned `codebase-design` guidance for interface depth, deletion tests, locality and seams. Design It Twice is warranted only for a consequential interface choice unresolved by evidence.

## Review

- Trace every task to a requirement. Remove speculative flexibility, duplicate layers and future-only mechanisms; prefer existing conventions.
- Include side effects, ordering, errors, configuration and performance in interface analysis. Delete a module when necessary complexity would not reappear at callers.
- One production adapter alone does not justify a seam; a justified test adapter may. Challenge contracts that mandate accidental implementation complexity.
- Merge microscopic tasks sharing a concern; split unrelated work or oversized packets. Add work only for demonstrated correctness, safety, compatibility or validation gaps.
- Assess every declared mechanism and inspect steps/files for omissions. Accept only with no actionable finding.

## Mechanism ledger

`complexity_mechanisms` declares triggers/functions/procedures, backfills, multi-release migrations, background/event flows, caches, seams/adapters, storage and comparable costs. Empty is valid.

Each entry links requirements/tasks, necessity, repository evidence, simpler alternatives, operational consequences and checks. Retain only when needed now, simpler choices fail required constraints, deployment/failure/recovery/observability/testing are understood, and precedent or a justified new convention supports it. An undeclared mechanism is a finding.

## Database and migration decisions

Prefer declarative constraints/indexes for expressible data invariants, then application transactions when the application owns all writes. Triggers/functions/procedures require independent writers or atomic enforcement that constraints cannot supply; cleaner application code or hypothetical future writers are insufficient.

For retained database mechanisms, document activating writers/operations, side effects/errors, ordering, recursion, idempotency, concurrency, lock/query cost, deployment/recovery and interface-level tests.

For material migrations, check isolated target evidence, volume/lock duration, old/new version compatibility, transaction boundaries, backfill retries, deployment order, rollback/forward-fix and resulting data/constraint validation. Split schema/backfill/enforcement/cleanup when rollout requires it; do not split safe cohesive transactions merely by line count. Combining unrelated concerns without an atomicity rationale is a finding.

## Findings and verdicts

Findings name target (`plan`/`contract`), requirement/task IDs, evidence, simpler alternative and exact change while preserving accepted scope.

| Verdict | Meaning |
| --- | --- |
| `accept` | Ready to become canonical; no actionable findings |
| `revise-plan` | Planner must address actionable plan findings |
| `revise-contract` | Revise the complexity-mandating contract before affected plans |
| `blocked` | Evidence cannot resolve a material product/safety/environment decision |

A fresh critic verifies material revisions against prior findings and this rubric. Bounded deviations preserving scope/contract, adding no risk/mechanism and following packet-local precedent do not reopen planning. Exhausted revisions block. After required acceptance, full pauses for approval; fast/standard records policy approval.
