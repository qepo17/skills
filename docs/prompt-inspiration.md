# Prompt inspiration and deliberate adaptations

The execution and idea-preparation prompts draw on the installed `to-spec`, `to-tickets`, and `grill-with-docs` skills, read in full along with the latter's `grilling` and `domain-modeling` dependencies (including the glossary and ADR formats). The three installed entrypoints matched these source snapshots byte-for-byte:

| Reference | Source snapshot | SHA-256 of SKILL.md |
| --- | --- | --- |
| `to-spec` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/to-spec/SKILL.md) | `267638edd513b5918de626ad5605d261952abb7428cb308869c663ca924e93e7` |
| `to-tickets` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/to-tickets/SKILL.md) | `1846d215e24ec1219b199a708329ca915db93138d4f3675af29db4d32ee41391` |
| `grill-with-docs` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/grill-with-docs/SKILL.md) | `610d091047bcfb9db0f75c057d15538481a721111579fc5ec7f83ad9131a2165` |

These are inspirations, not runtime dependencies or verbatim orchestration imports. Each installable skill contains its own operational guidance. Users do not need the reference skills or their setup command installed.

## What transfers

| Source idea | Adaptation here |
| --- | --- |
| `to-spec`: synthesize conversation and codebase understanding without another interview | Once discovery settles the work, compose the draft/implementation contract directly; do not reopen decisions to fill headings. |
| Problem Statement, Solution, User Stories, Implementation Decisions, Testing Decisions, Out of Scope, Further Notes | Preserve these useful concerns in the idea ticket and existing execution plan. Scale story/detail coverage to the feature; relate stories to original acceptance IDs. |
| Domain glossary and ADR awareness | Read applicable context/glossary and ADRs, use canonical terminology, cross-check claims against code, and record rationale. |
| Prefer high existing test seams; test external behavior; identify prior art | Explicitly explain behavior, chosen seam(s), modules exercised, and comparable tests. Prefer a small seam set, not new interfaces solely to mock private helpers. |
| Avoid stale file paths/code in long-lived specs, with a narrow prototype exception | Product prose stays at module/interface level. Local baseline-bound evidence and required execution files/commands remain available. Only supplied, decision-rich prototype snippets with provenance are an exception. |
| `to-tickets`: tracer-bullet vertical slices, fresh-context sizing, blocking edges, frontier | Use independently verifiable behavior slices with genuine prerequisites. Default to local proposals/internal work packets, not new tracker issues or a mandatory ticket stage. Cross-repository work retains repository-local writers and shared-contract coordination. |
| Necessary prefactoring first | Only a justified, tested, behavior-preserving prerequisite within scope—not speculative cleanup or a new mechanism. |
| Wide-refactor expand–contract exception | Compatible form → bounded caller migrations → removal blocked by every migration batch. Keep risk/validation gates. Unsupported non-green intermediate sequences require explicit integration/replanning, not a silently created integration branch. |
| Preserve parent issues and make delivery/blockers explicit | Ticket drafts distinguish user-visible delivery and prerequisite issues from unresolved decisions. Existing parents are not automatically modified, closed, relabelled, or split. |
| `grilling`: investigate facts, recommend answers, resolve dependent decisions sequentially | Resolve facts through tools, adopt safe routine recommendations, and ask a single high-impact unresolved question at a time; batch at most three independent choices. |
| `domain-modeling`: crystallize language and meaningful trade-offs | Capture resolved terms/decisions in the existing record. A glossary is not a spec. Suggest ADRs sparingly for hard-to-reverse, surprising real trade-offs; project-file updates occur only through scoped authorized writers. |

## What intentionally does not transfer

- Relentless interviews, asking about every decision, or waiting for blanket shared-understanding confirmation. The task-wide cap remains ten, including inherited/follow-up questions; zero or no-more-interview is respected.
- An extremely long user-story quota. Coverage should be meaningful, not a reason to invent scope or produce filler.
- Routine confirmation of test seams, repeated granularity/dependency/merge/split quizzes, or an unbounded approval loop. Genuine material unknowns use the existing shared budget; high-risk approval gates remain mandatory.
- Automatic tracker publication, `ready-for-agent` labels, child issues, or native relationship writes. `idea-to-ticket` drafts by default and publishes one exact authorized ticket; multi-ticket publication requires a separately scoped workflow. Execution does not publish source-tracker changes.
- Immediate glossary/ADR writes during read-only discovery/planning, or automatic context-clearing/per-ticket worker orchestration. Existing writer leases, packet limits, and graph scheduling retain control.

## Verification boundaries

The engine test checks that source-inspired synthesis/testing/slicing/review guidance reaches actual immutable worker assignments while stage counts and existing gates remain unchanged. Packaging checks validate standalone skills and matching discovery copies. The idea skill's bundled examples support read-only behavioral smoke cases. Neither substring assertions nor mocked workers prove a model's semantic coverage or question counting; record such evaluations separately and do not claim live tracker publication was tested.
