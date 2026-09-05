---
name: code-review
description: Review a fixed PR diff on separate Standards and Spec axes.
---

# Two-axis code review

Review the three-dot diff between the fixed `base_sha` and `head_sha` supplied
by the trusted runtime context. Resolve both SHAs and confirm the diff is
non-empty before delegating.

## Standards track

Run a dedicated sub-agent using the repository's `AGENTS.md`, development
rules, applicable interface documents, test rules, and the smell baseline
below. Report documented-rule violations separately from judgment-call smells.
Repository rules override the smell baseline; skip formatting or mechanical
checks already enforced by tooling.

Smell baseline:

- Mysterious Name: a name does not reveal the value or behavior.
- Duplicated Code: the same logic shape appears in multiple changed locations.
- Feature Envy: code reaches into another object's data more than its own.
- Data Clumps: the same fields repeatedly travel together without a type.
- Primitive Obsession: primitives stand in for a domain concept.
- Repeated Switches: repeated branching on the same type appears in the diff.
- Shotgun Surgery: one behavior requires scattered edits.
- Divergent Change: one module changes for unrelated reasons.
- Speculative Generality: an abstraction exists without a current requirement.
- Message Chains: callers navigate through another module's internals.
- Middle Man: a type merely delegates without hiding meaningful complexity.
- Refused Bequest: inheritance is used while most inherited behavior is ignored.

For each hard violation, cite the governing file/rule and the changed hunk. For
each smell, label it as a judgment call and quote the relevant hunk. Keep this
track under 400 words before conversion to structured findings.

## Spec track

Run a second dedicated sub-agent in parallel with the Standards track. Give it
the linked Issue contents, Agent handle/realize SPEC, PRD, progress document,
fixed diff command, and commit list. It must report:

1. requested requirements that are missing or partial;
2. behavior or public surface that was not requested;
3. requirements that appear implemented incorrectly;
4. conflicts with the SPEC-first source priority.

Quote the exact requirement or line for each finding and keep this track under
400 words before conversion to structured findings.

## Aggregation

Keep the two reports independent. Do not merge or rerank their findings across
axes. A PR passes only when both axes pass and the separate flow and black-box
checks also pass. Convert each report into the corresponding arrays required by
the workflow output schema.
