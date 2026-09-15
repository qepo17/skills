---
name: end-to-end-development
description: Implement, verify, and deliver software requests. Supports explicit durable LangGraph orchestration and existing-run recovery.
disable-model-invocation: true
---

# End-to-End Development

For new work, follow [DEVELOPMENT.md](DEVELOPMENT.md). The current agent owns the development loop, including multiple repositories. Use the user's existing context and authorization; keep the process proportional to the change.

## Select durable mode only when needed

- For a supplied existing run directory, or a continuation of a LangGraph run, read [DURABLE.md](DURABLE.md) and resume the existing engine. Preserve its worktrees, artifacts, approvals, and policies.
- For an explicit request for LangGraph orchestration, use [DURABLE.md](DURABLE.md). Explain its persistent worker and phase constraints before initializing.
- Otherwise use coordinator-led development. A long task, multiple repositories, or a sensitive code path alone does not require durable mode. If the work needs independently supervised persistent workers, explain that trade-off before selecting it.

Do not load the durable artifact contracts, worker schemas, or incident recovery instructions for ordinary development. Do not bypass an active durable run by switching its work into the coordinator workflow.

Read [DELIVERY.md](DELIVERY.md) only when using the bundled GitHub helper. Use [DURABLE.md](DURABLE.md) for the optional durable report and recovery commands.
