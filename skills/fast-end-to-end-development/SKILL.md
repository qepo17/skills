---
name: fast-end-to-end-development
description: Implement software requests with a short plan, iterative fixes, proportionate review, and requested delivery across one or more repositories.
---

# Fast End-to-End Development

Follow [DEVELOPMENT.md](DEVELOPMENT.md). The current agent owns planning, implementation, fixes, and delivery. When persistence is useful, keep one concise task record; scale the process to the change.

Do not escalate merely because a change touches an API, permissions, a background job, or several repositories. Resolve the actual consequential decisions and verify the affected behavior.

For an existing LangGraph run, resume it with the installed `end-to-end-development` skill and its recorded policies. Do not recreate its task or modify engine-owned state through this workflow. If that skill is unavailable, preserve the run and report the missing resume capability.

Read [DELIVERY.md](DELIVERY.md) only when using the bundled GitHub helper. An optional requested HTML explainer can be rendered with `scripts/render_pr_explainer.py`; derive its input from the task record and actual results.
