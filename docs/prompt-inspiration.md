# Prompt inspiration and deliberate adaptations

These notes document influences on the agent-led development guide and the `idea-to-ticket` skill. They are design provenance, not runtime dependencies.

The source material was drawn from installed snapshots of `to-spec`, `to-tickets`, and `grill-with-docs`, including the latter's grilling and domain-modeling dependencies:

| Reference | Source snapshot | SHA-256 of SKILL.md |
| --- | --- | --- |
| `to-spec` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/to-spec/SKILL.md) | `267638edd513b5918de626ad5605d261952abb7428cb308869c663ca924e93e7` |
| `to-tickets` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/to-tickets/SKILL.md) | `1846d215e24ec1219b199a708329ca915db93138d4f3675af29db4d32ee41391` |
| `grill-with-docs` | [qepo17/dotfiles, d1246da](https://github.com/qepo17/dotfiles/blob/d1246dae7a0250490e81944fa50158cf9dccd236/agents/skills/grill-with-docs/SKILL.md) | `610d091047bcfb9db0f75c057d15538481a721111579fc5ec7f83ad9131a2165` |

Planning presentation also drew on the installed `show-me` skill snapshot (`bea6da70a58096730b9aeb0bae293ddf4726103a98efc9ce13c481619942a810`): prefer the smallest useful view and adjacent prose rather than compulsory diagrams or HTML.

## What transfers

| Source idea | Adaptation here |
| --- | --- |
| Synthesize conversation and codebase understanding without another interview | Compose a ticket or concise task record directly from settled evidence; do not reopen decisions merely to fill headings. |
| Problem, solution, stories, decisions, testing, exclusions, and notes | Preserve these concerns in idea tickets, scaled to the actual work. |
| Domain glossary and ADR awareness | Read applicable context and decisions, use canonical terminology, and cross-check claims against code. |
| Prefer high existing test seams and external behavior | Explain the chosen seam and comparable tests; do not add interfaces solely to mock private helpers. |
| Avoid stale paths and implementation snippets in long-lived specs | Keep product prose at module/interface level while retaining local baseline-bound evidence in task records. |
| Tracer-bullet slices and real dependency edges | Implement independently verifiable outcomes in actual dependency order, including repository-local writers for multi-repository work. |
| Necessary prefactoring | Permit only justified, verified prerequisites rather than speculative cleanup. |
| Investigate facts before asking | Resolve facts through tools, adopt safe routine choices, and ask only consequential unresolved questions. |
| Crystallize language and durable trade-offs | Record settled terms and decisions concisely; suggest ADRs only for surprising, hard-to-reverse choices. |

## What intentionally does not transfer

- Relentless interviews, filler stories, repeated granularity quizzes, or blanket confirmation loops.
- Mandatory tracker publication, ticket splitting, diagrams, HTML, or stage artifacts.
- A global workflow engine, fixed development phases, packet scheduling, retry budgets, or persistence of model reasoning.
- Automatic project-file changes during read-only research or publication without explicit authorization.

## Verification

Repository checks validate standalone skill packaging, local links, `EffectGuard` behavior, its GitHub adapter, and ticket-rendering resources. Qualitative prompt behavior needs an isolated development scenario; substring assertions do not prove semantic coverage or truthful execution.
