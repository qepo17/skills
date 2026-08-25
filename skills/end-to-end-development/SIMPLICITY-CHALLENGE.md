# Simplicity Challenge

Use this rubric only when the candidate plan or selected full profile requires a design challenge, and always before project-file implementation. Low-risk fast/standard plans with an empty risk list and mechanism ledger may waive this worker according to `run.json.workflow_policy`. The critic's job is **subtraction**, not architectural embellishment: find the least powerful design that completely satisfies the accepted requirements and canonical contract while following repository conventions.

The critic also applies the vocabulary and principles in the installed `codebase-design` skill, especially interface depth, the deletion test, locality, seam placement, and "one adapter means a hypothetical seam." Do not run Design It Twice by default. Use it only when the plan exposes a genuinely consequential interface choice that cannot be resolved from requirements and repository evidence.

## Critic mandate

1. Trace every plan task to an accepted requirement.
2. Remove speculative flexibility, premature generalization, duplicate layers, and mechanisms justified only by possible future work.
3. Prefer an existing repository convention over a novel pattern when both satisfy the requirements.
4. Treat hidden side effects, ordering, error modes, configuration, and performance characteristics as part of a module's interface.
5. Apply the deletion test. If deleting a proposed module or mechanism does not make necessary complexity reappear at callers, remove it.
6. Do not introduce a seam for one production adapter. A production adapter plus a justified test adapter may establish a real seam; otherwise prefer direct code.
7. Challenge the canonical contract when it mandates accidental implementation complexity rather than observable cross-repository behavior.
8. Give an `accept` verdict only when every declared high-cost mechanism has been assessed and no actionable simplicity finding remains.
9. Review work-packet shape as well as design shape: merge microscopic tasks that share one concern and repository context, but split packets that combine unrelated changes or exceed the configured task/time bounds.

A critic may recommend adding work only to close a demonstrated correctness, safety, compatibility, or validation gap. It must not expand product scope.

## High-cost mechanism ledger

Candidate plans declare every proposed high-cost mechanism in `complexity_mechanisms`. This includes:

- database triggers, database functions, and stored procedures;
- data backfills or multi-release data migrations;
- background jobs and event-driven flows;
- caches;
- new seams or adapters;
- new storage systems;
- another mechanism with material operational or cognitive cost.

For each mechanism, the plan must identify the requirements and tasks it serves, why it is necessary, concrete repository precedent or evidence, simpler alternatives considered, operational consequences, and validations. An empty ledger is valid and preferred when no such mechanism is needed.

The critic assesses every declared mechanism and also inspects task steps and expected files for undeclared mechanisms. Omitting a mechanism from the ledger is an actionable plan finding; it is not evidence that the plan is simple.

Retain a mechanism only when all of these are true:

- an accepted requirement or contract rule needs it now;
- a simpler mechanism cannot meet the same correctness and rollout constraints;
- its failure, deployment, rollback or forward-fix, observability, and test implications are understood;
- the repository either has supporting precedent or the plan explains why a new convention is warranted.

## Database decision order

Use the least powerful database mechanism that preserves the required invariant:

1. Prefer declarative constraints and structures such as `NOT NULL`, foreign keys, unique constraints, check constraints, and indexes for data invariants they can express.
2. Prefer an application transaction for business workflow when the application owns all writes and the invariant does not need independent database enforcement.
3. Use a database trigger, database function, or stored procedure only when the invariant must hold across independent writers or requires atomic database enforcement that declarative constraints cannot express.

A retained trigger or database function must document:

- every writer and operation that activates it;
- visible side effects and returned database errors;
- ordering, recursion, idempotency, and concurrency behavior;
- lock and query-cost risks;
- deployment ordering and rollback or forward-fix strategy;
- observability and tests through the owning module's interface.

"Keeps the application code clean" and "may support another writer later" are not sufficient justifications.

## Migration review

Migration line count alone is not the target. Challenge migrations that mix unrelated deployment concerns or hide risky runtime behavior.

Prefer separately deployable schema, backfill, enforcement, and cleanup steps when data volume, compatibility, or rollout requires them. Do not split an otherwise cohesive and safely transactional migration merely to create smaller files.

For every material migration, verify that the plan covers:

- target database safety before migration-capable commands;
- expected data volume and lock duration;
- compatibility with old and new application versions;
- transaction boundaries;
- retry and idempotency behavior for backfills;
- deployment ordering;
- rollback safety or an explicit forward-fix strategy;
- focused validation of resulting data and constraints.

A migration that combines schema changes, a large backfill, business workflow, and enforcement without explaining why they must be atomic is an actionable finding.

## Finding rules

Every finding must name its target (`plan` or `contract`), affected requirement and task IDs, evidence, the simpler alternative, and the exact required change. Findings are actionable only when the proposed change preserves the accepted requirements and contract.

Verdicts mean:

- `accept`: the referenced plan is ready to become canonical;
- `revise-plan`: actionable plan findings require a fresh planner revision;
- `revise-contract`: accidental complexity is required by the current contract, so the bounded contract-revision path must run before affected plans are regenerated;
- `blocked`: repository evidence cannot resolve a material product, safety, or environment decision.

After a material plan revision, a fresh critic verifies the revised plan against the prior findings and this entire rubric. A bounded implementation deviation that preserves requirements/contract, adds no risk or mechanism, follows repository precedent, and stays inside its packet does not reopen planning. Verification is not permission to start an unbounded design loop or to implement: after all required challenges accept, the coordinator must still hard-stop for the user's explicit approval of the complete hash-pinned plan bundle. When the configured plan-revision cycle is exhausted without an `accept` verdict, record a blocker.
