# Outcome specs and slices

These examples are hypothetical prompt-quality fixtures, not evidence about the target repository. Reuse the shape, not the invented requirements or decisions. A reference spec supplies context, not permission to publish.

## Small, settled idea: synthesize without confirmation

Input: the user wants archived Rates hidden from the existing selector. The glossary defines **Rate** and **archived** (not deleted); an applicable ADR preserves existing selections. The existing selector query is already tested through its caller-facing interface. Discovery and duplicate checking are complete; no material decision remains. The user requested a draft, not publication.

A concise ticket body:

```markdown
# Hide archived Rates from new selections

## Problem Statement
Operators can accidentally choose an archived Rate for a new selection.

## Solution
Keep archived Rates out of the selector while preserving existing selections.

## User Stories
- US-001: As an operator, I want only selectable Rates offered, so that I cannot start a new selection with an archived Rate. [AC-001]
- US-002: As an operator, I want existing selections retained, so that archiving a Rate does not rewrite past choices. [AC-002]

## Acceptance Criteria
- [ ] AC-001: Archived Rates are absent; active Rates remain selectable. An all-archived result shows the existing empty state.
- [ ] AC-002: Existing selections keep their archived Rate, consistent with the recorded ADR.

## Implementation Decisions
- Preserve the existing Rate selector interface and selection-retention behavior.
- Agent recommendation: extend the existing selection rule rather than introduce another module; this follows repository precedent.

## Testing Decisions
Exercise the current selector interface, covering mixed active/archived results, the empty result, and preservation of existing selections. Reuse the established selector integration tests; assert returned/retained behavior rather than private helper calls. Keep required UI interaction checks if the rendered selector is affected.

## Out of Scope
Deleting Rates, changing archiving permissions, or rewriting past selections.

## Further Notes
Use the glossary's Rate/archived terminology; preserve the existing retention ADR.
```

Keep actual baseline-bound paths, symbols, ADR/test locators, and question history in the local evidence/handoff ledger, not a speculative file-edit list in the published spec. There are **zero questions**, no test-seam confirmation round, and no exhaustive story list. Return `ready` with publication authorization absent; do not create or label an issue.

## Larger unticketed idea: proposed vertical slices

Input: agreed scope is browse/filter/sort an existing published Rate catalog through a new operator view. Each slice can exercise the existing data interface; no new storage is needed. Filtering and sorting both need the new browsing path, not each other.

| Slice | What to build | Acceptance / verification | Blocked by |
| --- | --- | --- | --- |
| S-01 — Browse published Rates | A complete read path to the operator view, including its empty state and tests | Only published Rates appear; the existing empty-state behavior is preserved | None |
| S-02 — Filter by date | Date selection through the view and read path to filtered results, including tests | The agreed date rule changes the visible results correctly | S-01 |
| S-03 — Sort by amount | Operator sorting through the view and read path to ordered results, including tests | Both agreed sort directions return the expected order | S-01 |

After S-01, S-02 and S-03 are on the frontier. Do not invent an S-02 → S-03 dependency, split these into unrelated API/UI/test tickets, add storage, or ask a routine breakdown-approval quiz. This is a local proposal; publication of multiple tickets/native relationships is outside the default one-ticket authorization.

## Wide refactor: the slicing exception

Input: an already-scoped internal type replacement affects many packages, and changing a single declaration immediately breaks callers. A compatibility form is feasible.

- **Expand:** add the compatible new form without breaking existing callers; verify compatibility.
- **Migrate A / Migrate B:** move callers in bounded package batches, each blocked by expand, not necessarily by each other. Keep checks passing.
- **Contract:** remove the old form only when **all** migration batches and no-remaining-caller evidence are complete.

A required behavior-preserving prefactor may lead this sequence if its need and tests are explicit. It is not permission for a new public contract, database change, or unrelated cleanup. If green intermediate batches are not feasible, record the integration/verification prerequisite rather than promise independent delivery; execution must honor its actual packet limits, risk gates, and supported integration path.

## Bounded clarification still wins

With nine questions already asked and two remaining material choices, ask at most one next question, prioritizing safety and decision prerequisites. Explain its consequence and give a recommendation only when evidence supports one. The other choice remains blocked unless resolved by evidence or volunteered input. Do not hide both choices in a single question or reopen them under Testing Decisions. With no-more-interview, preserve all earlier answers and ask nothing further.

## Existing Jira ticket

Given an existing ticket with settled stories, decisions, and test guidance, read it and the relevant comments, preserve original acceptance IDs, and return its canonical reference plus the evidence/question ledger for execution. Do not create a new parent, split it into tracker children, edit its status, or add a `ready-for-agent` label. The execution skill develops baseline-bound implementation slices internally.
