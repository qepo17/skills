---
name: end-to-end-development
description: Implement, verify, and deliver software requests directly with the current agent across one or more repositories.
---

# End-to-End Development

Follow [DEVELOPMENT.md](DEVELOPMENT.md). The current agent owns understanding, planning, implementation, verification, review, and requested delivery. Scale the process to the actual change instead of selecting a workflow profile.

When an independent coding-agent worker is useful and TypeSafe plus Herdr are
available, read the optional [worker-routing guidance](WORKER_ROUTING.md) before
launch. The current agent must understand and bound the subtask first; Jev may
only select an approved execution profile, while host policy resolves the
profile to a model and reasoning effort.

Use the agent runtime's native tools and collaboration facilities. Keep one source writer per repository; independent repositories may progress concurrently. When persistence helps, keep one concise task record with repository baselines, settled decisions, current checks, delivery receipts, and the next useful action.

Read [DELIVERY.md](DELIVERY.md) only when the requested outcome includes a GitHub pull request. Its `EffectGuard` persists external-effect intent and reconciles interrupted publication. It does not orchestrate development, supervise model workers, or authorize publication.

There is no durable workflow mode, phase engine, packet protocol, or automatic migration of historical orchestration state. Treat any old LangGraph run as read-only evidence and recover useful context from its repositories and artifacts without modifying or replaying its engine state.
