# Optional worker routing

Use this guidance only after the current agent has understood the request and
decided that an independent, bounded subtask is worth delegating. It requires a
System One model such as Jev and a launcher such as Herdr that can start a fresh
coding agent with its own model and reasoning configuration.

The current agent still owns decomposition, repository understanding, risk,
authorization, write ownership, validation, and final synthesis. Jev does not
plan the work, inspect a codebase, judge the overall task, or review the final
result.

## Route one bounded subtask

Give Jev only a concise, sanitized description of the subtask: its goal,
deliverable, fixed constraints, supplied evidence, and whether it can run
independently. Do not send credentials, secret-bearing files, unnecessary
private code, a repository dump, or unresolved decisions that require the
reasoning agent.

Ask one `Choice` question named `execution_profile`:

```text
Which approved execution profile best fits `subtask` as written? Judge the
reasoning and independence needed for this bounded work. Do not redesign,
expand, or plan the subtask.
```

Use these criteria:

| Profile | Criteria |
| --- | --- |
| `fast` | One known target and explicit output; narrow lookup, extraction, formatting, or mechanical inspection with little inference. |
| `standard` | Independently executable implementation, test, documentation, or review work with clear boundaries and ordinary cross-file reasoning. |
| `deep` | Independently executable but requires difficult debugging, architecture, security analysis, or synthesis across many interdependent artifacts. |
| `root_only` | Not independently executable because it depends on unresolved decisions, shared write ownership, final integration, authorization, or continuing context held by the current agent. |

These labels are ephemeral launch choices, not workflow modes or persisted task
state. Use a calibrated confidence threshold. When the answer is uncertain,
keep the work with the current agent or fall back to a conservative host
default; never choose a cheaper worker merely because routing failed.

## Resolve with deterministic policy

The host maps `fast`, `standard`, and `deep` to an approved coding-agent kind,
model, and reasoning effort. `root_only` is a no-launch outcome. Jev never
returns literal model names or command-line arguments. Before launch, ordinary
code or the current agent must:

- Preserve an explicit user or repository model requirement.
- Verify that the selected model supports the resolved reasoning effort.
- Apply any configured minimum for security, data, migration, destructive, or
  otherwise consequential work.
- Refuse delegation that would violate one-source-writer ownership.
- Use the normal configured worker when TypeSafe is unavailable or unusable.

The profile never grants permission, changes scope, or relaxes review,
verification, delivery, or sandbox policy.

## Launch and supervise with Herdr

Use the current Herdr named session by default. Create a workspace for a
separate task, or an isolated worktree workspace for an independent source
writer. A new named Herdr session is appropriate only when the worker needs a
separate server namespace, socket, and persisted runtime state.

Create or select an available shell pane, then use Herdr's agent launcher with
the resolved coding-agent kind and pass the approved model and reasoning
arguments to that agent. Give the worker the bounded subtask, repository
baseline, exact write scope, relevant evidence, and expected result. For a
persistent handoff, record only the Herdr target and write ownership in the
ordinary task record rather than persisting routing metadata or creating a
worker-packet artifact.

Wait for the worker, inspect its actual result, and validate its work before
using it. Herdr lifecycle state reports readiness or attention; it does not
prove task success. The worker should stop and report when it discovers broader
scope, missing evidence, conflicting ownership, or a consequential unresolved
decision. The current agent may continue itself or launch a fresh worker with a
stronger approved profile after it re-bounds the subtask and repeats Jev routing
and deterministic policy resolution. Retry only when new evidence or a changed
approach makes another attempt useful.

References: [TypeSafe primitives](https://docs.typesafe.ai/primitives),
[TypeSafe function calling](https://docs.typesafe.ai/cookbooks/function_calling),
[Herdr agent automation](https://herdr.dev/docs/agent-automation/), and
[Herdr concepts](https://herdr.dev/docs/concepts/).
