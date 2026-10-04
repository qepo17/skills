---
name: end-to-end-development
description: Orchestrate bounded workers to implement and verify repository changes across one or more repositories through open pull requests watched until green and mergeable.
---

# End-to-End Development

**Default completion for repository changes: implement → locally verify → independently review as required → commit task-scoped changes → push to the established appropriate task branch and remote → create or update an open task PR → have a fresh PR watcher keep it green until mergeable → return its URL and actual merge state.** The orchestrator owns this final external outcome; worker completion, local changes, a commit, a pushed branch, or a created PR alone is not normal completion.

Requesting this skill for a repository change requests that full PR workflow without a separate reminder or “want me to create a PR?” question. Honor explicit local-only/no-push/no-PR instructions, repository policy and exact-approval requirements, and tool/sandbox permissions. Establish an unambiguous destination and keep publication task-scoped. This does not authorize merge, auto-merge, deployment, migrations, permissions changes, tracker writes, creating a remote repository, or destructive work.

Follow [DEVELOPMENT.md](DEVELOPMENT.md). The current agent owns understanding, decomposition, consequential decisions, coordination, integration, final acceptance, and authorized delivery. Default to bounded workers for substantive independently executable implementation, useful tests, research or inspection, independent review, and PR watching. Give a worker a coherent change to own; supervise its result rather than every edit. Scale the process to the actual change.

Use native runtime collaboration or launch facilities with the runtime's configured workers and honor explicit model requirements. Direct execution is sensible for tiny reversible tasks, unavailable workers, or genuinely inseparable integration and decisions. Report unavailable independent review honestly and respect repository-required review.

Keep one active source writer per repository across all worktrees, including the orchestrator. Settle and release writer ownership before taking over integration or repair. Independent repositories and safe read-only investigations may progress concurrently. When persistence helps, reuse one concise optional task record with repository baselines, settled decisions, worker targets, scopes, ownership, dependencies, pending results, checks, delivery receipts, and the next useful action. Reconcile existing workers before launching duplicates.

Read [DELIVERY.md](DELIVERY.md) whenever using normal GitHub PR completion, without waiting for a second request. Reuse an existing open task PR rather than duplicate it. Its `EffectGuard` persists external-effect intent and reconciles interrupted publication; it does not orchestrate development, supervise model workers, or grant authorization.

Creating or updating the PR starts the watch; it does not end the task. Launch one fresh bounded PR watcher per PR and hand it writer ownership of the task branch. It waits for every check on the current head; fixes red checks, conflicts and an out-of-date base within task scope; publishes each verified fix as a revised effect; and repeats until the PR is mergeable or genuinely blocked. Do not end the session while a watcher can still make progress, and confirm the PR's actual state before finishing. Mergeable is not merged: the watcher never merges, enables auto-merge, approves, or dismisses reviews.

No-change requests end with evidenced no-change results, without empty PRs. Explicit opt-outs end with the actual local result. Missing authentication or remote, ambiguous destination, denied permission, or failed required verification/review yields an explicit blocked or partial result and the next needed action. Continue useful local work when remote access is missing; never silently downgrade delivery or call blocked work complete. A PR with pending or failing checks, conflicts, or another unmet merge requirement is not complete. Report gates only a human can satisfy, such as a required approval, as the remaining blockers rather than as mergeable.

There is no durable workflow mode, phase engine, packet protocol, or automatic migration of historical orchestration state. Treat any old LangGraph run as read-only evidence and recover useful context from its repositories and artifacts without modifying or replaying its engine state.
