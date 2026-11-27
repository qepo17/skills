# Start with laws

A law states what must hold for every case in an agreed scope. Write the law before choosing a proof technique or changing the behavior it describes.

## Settle intent and scope

Read the request, the relevant contract or domain decisions, and the existing proofs, code, and tests. Use them to discover candidate laws and current behavior. If the contract and implementation disagree, show the discrepancy and settle which behavior the task should preserve or change.

Propose the smallest boundary that can express the guarantee. Name the command or component, the applicable actors, inputs and starting states, and the promised result. Include rejection, persistent effects, retries, or concurrent operations when they affect the guarantee. Record exclusions that would otherwise make the claim sound broader than it is.

Ask about unresolved decisions one at a time. Start with the decision that determines the others. For each question, give a recommended answer and explain the trade-off in terms of observable behavior. For example, ask whether the rule applies to one confirmation command or to every way a record reaches the confirmed state. Wait for the answer before committing to the dependent law or implementation. Continue independent work while waiting. Reuse explicit requirements and settled decisions without interviewing the user again.

## Write the laws

State each agreed rule in plain language. Give it a stable name if it will have a proof or regression check. Specify any assumptions and what a violation would look like. Record the law in the repository's existing specification or in the task record before assigning dependent work. Review changes to an agreed law as changes to the specification.

For example, an approval command may succeed only for a record in `READY`. The command must reject a record in `AWAITING_PAYMENT` and preserve both the record and its open payment. An otherwise valid approval from `READY` must still succeed. The command and its effects are the scope of the law. Other ways the record can reach `APPROVED` may have their own rules.

## Carry the laws into verification

- Use the repository's proof tooling when it covers the law. Tie the model to executable source through shared definitions, generation, or a checked correspondence where practical. State exactly what the checker consumes, any bounds or assumptions, and which implementation paths remain outside the model.
- Verify that the evidence detects a violation. Reproduce an existing counterexample or make a small, temporary change in an isolated workspace and check that it fails for the expected reason. Include a valid case when a rule about allowed behavior could pass because every request is rejected.
- When a model covers only transition tables, follow the real command entry points and other write paths that can bypass the tables. Use behavioral checks for applicable guards, stored effects, and transaction or retry behavior beyond the proof. Keep those results distinct from the proof result.
- During review, trace each law to its evidence. Record which laws the checker accepted, which received behavioral checks, and which remain unverified. Run established or agreed proof checks locally. Use the same check in CI when CI enforcement is required or agreed. Bind the results to the verified revision. If a required proof fails or cannot run, report the blocker and preserve the law while diagnosing it.
