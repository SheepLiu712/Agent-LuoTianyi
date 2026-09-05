# Agent refactor PR review automation

This automation reviews root pull requests targeting `refactor/agent` and
their same-repository stacked child PRs when they are linked to Issue #60-#89.
It reacts to new/updated/ready/reopened/retargeted PRs, review
submissions/edits/dismissals, PR conversation comments, and inline review
comments. A successful non-Draft review is squash merged; other verdicts are
published as a GitHub review.

The workflow is deliberately split into two privilege domains:

- the Codex job receives a read-only GitHub token and the OpenAI key through the
  official API-key proxy; it cannot review or merge on GitHub;
- the publish job receives no OpenAI key and is the only job allowed to publish
  a review or squash merge.

All jobs load policy, prompt, schema, and publisher checks from the immutable
`github.workflow_sha` for that run. A moving default branch therefore cannot
change the contract between resolution, review, and publication.

Only repository collaborators with `write`, `maintain`, or `admin` permission
can trigger a paid review, and the PR head must be a branch in this repository.
This intentionally excludes untrusted fork code from the execution environment
and prevents fork authors from spending the repository owner's API quota.
Results contain an event/action/head-SHA marker so reruns do not publish duplicate reviews. New
commits, Ready/Reopen transitions, and human replies have distinct keys and
therefore trigger fresh reviews.

The only bot exception is an internal `workflow_dispatch` created by the
publisher when the pinned target base becomes stale. It must pass the same PR,
branch, issue-range, and current-SHA gates before a new paid review starts.

## Review contract

The workflow accepts one eligible PR event and produces exactly one structured
verdict for a pinned immediate-base and PR-head pair. Before spending a model
call it resolves an acyclic chain of open, same-repository PRs whose root base
is `refactor/agent`. A stacked child is reviewed relative to its direct parent's
pinned head and can merge only into that parent; a root is reviewed relative to
`refactor/agent`. The review job constructs that exact candidate integration
tree before inspecting or testing it. The prompt and JSON schema define the
Codex-facing contract. The publishing job independently validates the complete
output contract, uses the trusted event marker, and validates the head SHA,
issue set, test evidence, current-head change requests, every parent current-head
approval, and both pinned SHAs before it performs any merge. If the target branch
advances during review, the publisher dispatches a fresh review instead of
merging stale evidence.

Verdicts have these effects:

- `PASS`: approve and squash merge only when at least one test or static check
  passed, no test is `FAIL`/`EXPECTED_RED`, no P0/P1 finding remains, the phase
  is not Red, and no human's latest review on the current head requests changes.
  A non-required long external check may be `NOT_RUN` only when its reason and
  unverified scope are recorded;
- `CHANGES_REQUESTED`: publish a request-changes review and do not merge;
- `WAITING`: publish a comment describing the external condition and do not
  merge. A later authorized human reply or PR update creates a fresh review;
- `BLOCKED`: publish a comment naming the unavailable external dependency or
  infrastructure and do not merge.

## Acceptance checks

- Events unrelated to a PR explicitly related only to issue #60-#89 are ignored
  before any paid model call. A related PR with an invalid target or stack is
  rejected with an actionable flow comment instead of being silently ignored.
- A stacked child enters review only while every parent current head has a
  trusted current-head approval and no trusted current-head change request;
  the publisher checks this gate again immediately before merging.
- External forks, untrusted actors, bot replies, duplicate events, and stale
  head results cannot publish or merge.
- PR conversation replies and inline review replies are both included in the
  review context and create distinct review events.
- A `PASS` without at least one successful test record cannot merge.
- A merge uses GitHub's squash method. A child targets only its direct parent
  branch; a root targets only `refactor/agent`. The workflow never merges to
  `dev`, `main`, or `master`.
- Merging a child changes the parent head and therefore requires a fresh parent
  review; a child PASS is never treated as approval of the complete root diff.
- Black-box review uses focused and affected-module offline tests. Real song
  learning, live Bilibili/VCPedia fetches, and other `slow`/`live`/`external`/
  `real_llm` paths are skipped by default and reported as unverified.

## Repository configuration

The following repository settings are required:

1. Actions enabled, with explicit per-workflow permissions retained.
2. GitHub Actions may create pull-request reviews.
3. Secret `OPENAI_API_KEY` contains a project-scoped OpenAI API key.
4. Variable `AGENT_PR_REVIEW_ENABLED` is `true` only after the secret is ready.

Keep the variable `false` while rotating or removing the key. Never store a
ChatGPT/Codex desktop login token or `auth.json` in GitHub Secrets.

## Verification

Run the policy tests with:

```console
node --test .github/codex/tests/review-policy.test.js
```

Run `actionlint` against `.github/workflows/agent-refactor-review.yml`, validate
the JSON Schema as Draft 2020-12, and syntax-check every embedded
`actions/github-script` block before changing the workflow.
