# Principles

Required reading: read every URL before drafting. Each principle becomes one line in the generated file's Principles section.

| Principle | In one line | Source |
| --- | --- | --- |
| **KISS** | The simplest design that solves today's problem wins. | https://java-design-patterns.com/principles/ |
| **YAGNI** | Build only what a current requirement needs. | https://java-design-patterns.com/principles/ |
| **DRY** | Every piece of knowledge has one authoritative place; similar-looking code is not necessarily duplicated knowledge. | https://java-design-patterns.com/principles/ |
| **Separation of Concerns** | Each part owns one concern and hides how it does it. | https://java-design-patterns.com/principles/ |
| **SOLID** | Single responsibility, open/closed, Liskov substitution, interface segregation, dependency inversion. | https://java-design-patterns.com/principles/ and, for dependency inversion (missing from that page), https://en.wikipedia.org/wiki/SOLID |
| **Parse, don't validate** | Turn untrusted input into a type that cannot be invalid, once, at the boundary. | https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/ |
| **Fail fast** | Stop loudly where something goes wrong instead of continuing in a bad state. | https://martinfowler.com/ieeeSoftware/failFast.pdf |
| **Least privilege** | Every component, user and credential gets only the access it needs. | https://en.wikipedia.org/wiki/Principle_of_least_privilege |
| **Small batches** | Integrate small changes to mainline often, each verified by automated checks. | https://martinfowler.com/articles/continuousIntegration.html |

The java-design-patterns page also explains 21 related principles (coupling, cohesion, Law of Demeter, composition over inheritance, premature optimization, Boy-Scout Rule and more). Use them for Do/Don't items only where repository evidence calls for them.
