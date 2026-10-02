# Contributing

## Skill structure

- Put distributable skills under `skills/<skill-name>/`.
- Keep the directory name and the `name` in `SKILL.md` identical.
- Include a specific description that says what the skill does and when it should be used.
- Keep supporting files inside the skill directory and reference them with relative links.
- Add product-specific metadata under `agents/`; keep portable instructions in `SKILL.md`.
- Do not commit virtual environments, caches, logs, credentials, or generated effect state.

## Validation

Before opening a pull request, run:

```bash
./scripts/check.sh
```

For a quick installability check:

```bash
npx skills add . --list
```

The development skill is orchestrator-first: the current agent owns understanding, decomposition, consequential decisions, coordination, integration, final acceptance and authorized delivery. Default to bounded workers owning coherent substantive changes, useful tests or investigations, and independent review through available native launch facilities. Direct execution fits tiny reversible work, unavailable workers, or genuinely inseparable integration and decisions; report review gaps honestly and preserve required independent review.

For repository changes, requesting the development skill includes default completion through implementation, local verification, independent review as required, task-scoped commit and push to the established appropriate task branch/remote, and creation or update of an open task PR without another invitation or approval. The orchestrator owns that outcome; worker completion, local changes, a commit, or a pushed branch alone is insufficient. Reuse an existing open task PR and return its URL with actual check/review status. Honor explicit local-only/no-push/no-PR instructions, repository policy, exact-approval requirements, and tool/sandbox permissions; establish an unambiguous destination and read the skill's [delivery guidance](skills/end-to-end-development/DELIVERY.md). This does not authorize merge, deployment, migrations, permissions changes, tracker writes, creating a remote repository, or destructive work.

No-change requests require evidence, not empty PRs; explicit opt-outs require actual local results. Missing authentication or remote, ambiguous destinations, denied permissions, or failed required verification/review require a truthful blocked or partial result and next needed action. Continue useful local work where possible without silently downgrading delivery or claiming completion; a PR with pending or failing CI is not verified success.

Keep one active source writer per repository across all worktrees, including the orchestrator. Settle and release ownership before taking over integration or repair. Bind checks and independent reviews to stable exact content; related source mutations invalidate that evidence. Workers report consequential unresolved choices, broader scope, missing evidence or ownership conflicts, and do not delegate recursively without explicit parent authorization.

Use compact assignments covering goal/acceptance, repository/worktree/baseline, exact scope and owner, constraints/interfaces/dependencies, evidence/checks, and expected changed files or revisions, actual checks and unresolved issues. Do not add phase routing, workflow profiles, worker packet schemas, model-thought persistence, runtime dependencies, automatic retries or needless artifacts. Keep task records concise and optional, including active worker targets, scopes, ownership, dependencies and pending results; reconcile existing workers before launching duplicates.

Optional worker routing may select an ephemeral, host-defined launch profile
for an already-bounded delegation. TypeSafe and Herdr are optional; their absence
must not force root execution when another worker launcher is available. Safely
delegable work may use a conservative ordinary worker after routing uncertainty
or failure. Routing must not decompose the task, become durable workflow state,
or introduce a worker-packet protocol.

`EffectGuard` is the only durable development module. Its public interface is `ensure` and `inspect`; test external behavior through that interface. Keep GitHub-specific execution and reconciliation inside the delivery adapter. Use temporary Git repositories and fake forge responses for automated tests; real GitHub smoke tests are opt-in against an authorized disposable repository.

New effect kinds need:

- An externally observable postcondition.
- Durable intent before mutation.
- Reconcile-before-retry behavior.
- A stable target identity and idempotency strategy.
- Fail-closed handling of indeterminate outcomes.
- Focused interface tests covering interruption and conflicting retries.

Substantial prompt changes should be checked with an independent, isolated development scenario. Verify that the agent delegates coherent bounded work through native facilities without TypeSafe or Herdr, supervises and accepts inspected results, reconciles workers on resume, completes useful local work, preserves pre-existing changes, handles multiple repositories and worktrees without conflicting writers, reports partial outcomes and unavailable review truthfully, and avoids unnecessary questions or artifacts. Also check default PR completion with no reminder, existing open PR reuse, explicit local-only behavior, and truthful delivery blockers and pending/failing checks. Use isolated Git repositories and fake forge fixtures, or explicitly authorized disposable repositories; never publish to unintended live destinations. Prose substring assertions are not behavioral validation.

## Pull requests

Keep each pull request focused. Describe the behavior changed, list actual validation commands, and call out new runtime dependencies or compatibility breaks.
