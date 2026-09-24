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

The development skill is agent-led. Do not add phase routing, workflow profiles, worker packet schemas, or model-thought persistence. Keep task records concise and optional.

Optional worker routing may select an ephemeral, host-defined launch profile
for an already-bounded delegation. It must not decompose the task, become
durable workflow state, or introduce a worker-packet protocol.

`EffectGuard` is the only durable development module. Its public interface is `ensure` and `inspect`; test external behavior through that interface. Keep GitHub-specific execution and reconciliation inside the delivery adapter. Use temporary Git repositories and fake forge responses for automated tests; real GitHub smoke tests are opt-in against an authorized disposable repository.

New effect kinds need:

- An externally observable postcondition.
- Durable intent before mutation.
- Reconcile-before-retry behavior.
- A stable target identity and idempotency strategy.
- Fail-closed handling of indeterminate outcomes.
- Focused interface tests covering interruption and conflicting retries.

Substantial prompt changes should be checked with an independent, isolated development scenario. Verify that the agent completes useful local work, preserves pre-existing changes, handles multiple repositories without conflicting writers, reports partial outcomes truthfully, and avoids unnecessary questions or artifacts. Prose substring assertions are not behavioral validation.

## Pull requests

Keep each pull request focused. Describe the behavior changed, list actual validation commands, and call out new runtime dependencies or compatibility breaks.
