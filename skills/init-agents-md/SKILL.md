---
name: init-agents-md
description: Create or regenerate a project's AGENTS.md from repository evidence, core engineering principles and stack-specific Do/Don't sources. Use when asked to initialize, write, refresh or regenerate AGENTS.md.
---

# Init AGENTS.md

**Read the sources → inspect the repository → carry over existing rules → write → verify.**

Target the repository root `AGENTS.md` unless the user names another path. An existing target means **regeneration**; a missing one means **creation**. Write only the target file. Leave other instruction files (`CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`) as they are and report any that contradict the new file.

## 1. Read the principles

Read every URL in [PRINCIPLES.md](PRINCIPLES.md) before drafting anything. Fetch each page and read it in full; the page, not memory, is the source. Done when every URL is read or its failure (status or error) is recorded for the report.

## 2. Inspect the repository

Establish from files:

- **Purpose**: what the project is and who uses it (README, package metadata, docs).
- **Stack**: languages, frameworks and datastores, with pinned versions (manifests, lockfiles, `tsconfig.json`, migrations, Dockerfiles, compose files, CI workflows).
- **Commands**: build, test, lint, format and the gate run before commit or in CI, taken from scripts, Makefiles, task runners and CI definitions.
- **Conventions**: what the code already does consistently (layout, naming, error handling, test style, generated files, migration rules) and the gotchas no config states (CONTRIBUTING, ADRs, existing instruction files).

Read configuration to learn database versions and targets; connecting to a database or running migrations is outside this skill. Done when every detected stack and every command traces to a file.

## 3. Read the stack sources (optional per stack)

[STACKS.md](STACKS.md) lists Do/Don't sources per stack. Read a stack's section only when step 2 found that stack; skip every other section. For a detected stack STACKS.md does not list, read its official style guide or best-practice docs when one exists. Match every recommendation to the version the project pins: a feature newer than the pinned version is not a Do. Done when every detected stack's URLs are read or their failures recorded.

## 4. Carry over existing Do/Don't (regeneration only)

Read the current file in full. **Keep** every Do and Don't rule: items under Do/Don't (or Always/Never) headings, plus standalone directives elsewhere ("Always…", "Never…", "Do not…", "Use X, not Y", "MUST"). Copy each verbatim into the matching Do or Don't group; these are the project's own rules and outrank generated ones. **Drop** everything else; steps 1–3 regenerate it.

Keep a carried rule even when it names a path, command or tool that no longer exists, and list it in the report as possibly stale. When a generated item duplicates a carried one, keep the carried wording.

## 5. Write

Fill the shape below. Every line must change what an agent would do in this repository; cut what any competent agent does by default. Ground each Do/Don't in repository evidence, a principle, or a stack source. Phrase each as one concrete action, and give each Don't its alternative ("Don't X; Y instead"). Stay under about 150 lines.

```markdown
# AGENTS.md

<What the project is and who uses it, in 1–3 sentences.>

## Commands

- `<command>`: <when to run it>

## Principles

- **KISS / YAGNI**: <how it applies here> (source: <url from PRINCIPLES.md>)
- **DRY**: …
- **Separation of Concerns**: …
- **SOLID**: …
- **Parse, don't validate**: …
- **Fail fast**: …
- **Least privilege**: …
- **Small batches**: …

## Do

### General
- <carried rules first, then generated>

### <Detected stack>
- …

## Don't

### General
- …

### <Detected stack>
- …

## Notes

<Conventions and gotchas that are neither a command nor a rule; omit when empty.>
```

Tie each principle line to a concrete seam in this codebase where evidence exists (the parsing boundary, the module split, the credential scope, the CI gate). Add a stack subsection only for detected stacks.

## 6. Verify

- Every command traces to a script, task, Makefile target or CI step.
- Every carried rule appears verbatim.
- Every URL in the file comes from PRINCIPLES.md, STACKS.md, an official doc read in step 3, or the repository.
- No stack subsection exists for a stack the project lacks.

Report the mode, target path, sources read and failures, stacks detected with versions, carried rules with stale flags, and conflicting instruction files.
