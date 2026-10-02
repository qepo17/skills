# Optional worker routing

Use this guidance only after the current agent has understood the request and
determined that a bounded subtask is independently executable. This optional
step uses a System One model such as Jev to select an approved execution profile;
the host resolves it to a model and reasoning effort. Native runtime collaboration
or launch facilities work without TypeSafe or Herdr; if routing or Herdr is
unavailable, use an available ordinary worker launcher with an approved configuration.

The current agent still owns decomposition, repository understanding, risk,
authorization, write ownership, integration, validation, and final acceptance.
Jev does not plan the work, inspect a codebase, judge the overall task, or review
the final result.

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
| `root_only` | Not independently executable because it requires unresolved consequential decisions, resolution of conflicting ownership, genuinely inseparable integration or continuing context, final acceptance, or authorization. Ordinary implementation that can receive exclusive writer ownership remains delegable. |

These labels are ephemeral launch choices, not workflow modes or persisted task
state. Use a calibrated confidence threshold. Uncertainty or routing failure may
use a conservative approved ordinary worker when the work remains safely
delegable. Return unresolved decisions or ownership conflicts to the current
agent to re-bound the work; routing failure alone does not require root execution.
Never choose a cheaper worker merely because routing failed.

## Resolve with deterministic policy

The host maps `fast`, `standard`, and `deep` to an approved coding-agent kind,
model, and reasoning effort. `root_only` is a no-launch outcome. Jev never
returns literal model names or command-line arguments. Before launch, ordinary
code or the current agent must:

- Preserve an explicit user or repository model requirement.
- Verify that the selected model supports the resolved reasoning effort.
- Apply any configured minimum for security, data, migration, destructive, or
  otherwise consequential work.
- Refuse delegation that would violate one active source writer per repository
  across all worktrees, including the orchestrator.
- Use the normal configured worker and available launch facilities when
  TypeSafe or Herdr is unavailable or unusable.

The profile never grants permission, changes scope, or relaxes review,
verification, delivery, or sandbox policy.

## Launch and supervise

Follow [DEVELOPMENT.md](DEVELOPMENT.md) for the compact assignment, ownership,
supervision and acceptance rules regardless of launcher. Do not make a packet
schema, handoff artifact or durable routing state. Record active targets, scopes,
ownership, dependencies and pending results in the existing optional task record;
reconcile them before launching duplicate workers. Workers do not delegate
recursively without explicit parent authorization.

When using Herdr:

Use the current Herdr named session by default. Create a workspace for a
separate task, or an isolated worktree workspace for the repository's exclusive
source writer. Worktree isolation does not allow concurrent writers in the same
repository. A new named Herdr session is appropriate only when the worker needs a
separate server namespace, socket, and persisted runtime state.

Create or select an available shell pane, then use Herdr's agent launcher with
the resolved coding-agent kind and pass the approved model and reasoning
arguments to that agent.

For any launcher, inspect the worker's actual code and checks before accepting
its result. Checks and independent reviews must bind to stable, exact content;
later source mutations invalidate related evidence. Lifecycle state reports
readiness or attention; it does not prove task success. The worker should stop
and report when it discovers broader scope, missing evidence, conflicting
ownership, or a consequential unresolved decision. The current agent re-bounds
the work and directs fixes or selects an
appropriate worker, using optional routing when useful. Before taking over
integration or repair, settle and release the worker's writer ownership.
If workers are unavailable, explain direct execution and any missing independent
review honestly; repository-required independent review remains required. Retry
only when new evidence or a changed approach makes another attempt useful.

References: [TypeSafe primitives](https://docs.typesafe.ai/primitives),
[TypeSafe function calling](https://docs.typesafe.ai/cookbooks/function_calling),
[Herdr agent automation](https://herdr.dev/docs/agent-automation/), and
[Herdr concepts](https://herdr.dev/docs/concepts/).
