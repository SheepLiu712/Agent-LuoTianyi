# Agent refactor PR review automation

This automation reviews pull requests targeting `refactor/agent` and linked to
Issue #60-#89. It reacts to new/updated/ready/reopened PRs, review submissions,
PR conversation comments, and inline review comments. A successful non-Draft
review is squash merged; other verdicts are published as a GitHub review.

The workflow is deliberately split into two privilege domains:

- the Codex job receives a read-only GitHub token and the OpenAI key through the
  official API-key proxy; it cannot review or merge on GitHub;
- the publish job receives no OpenAI key and is the only job allowed to publish
  a review or squash merge.

Only repository collaborators with `write`, `maintain`, or `admin` permission
can trigger a paid review, and the PR head must be a branch in this repository.
This intentionally excludes untrusted fork code from the execution environment
and prevents fork authors from spending the repository owner's API quota.
Results contain an event/action/head-SHA marker so reruns do not publish duplicate reviews. New
commits, Ready/Reopen transitions, and human replies have distinct keys and
therefore trigger fresh reviews.

## Review contract

The workflow accepts one eligible PR event and produces exactly one structured
verdict for the PR's current head SHA. The prompt and JSON schema define the
Codex-facing contract. The publishing job independently validates the complete
output contract, uses the trusted event marker, and validates the head SHA,
issue set, test evidence, and current-head human change requests before it
performs any GitHub write.

Verdicts have these effects:

- `PASS`: approve and squash merge only when every recorded test is `PASS`, no
  P0/P1 finding remains, the phase is not Red, and no human's latest review on
  the current head requests changes;
- `CHANGES_REQUESTED`: publish a request-changes review and do not merge;
- `WAITING`: publish a comment describing the external condition and do not
  merge. A later authorized human reply or PR update creates a fresh review;
- `BLOCKED`: publish a comment naming the unavailable external dependency or
  infrastructure and do not merge.

## Acceptance checks

- Events unrelated to an open `refactor/agent` PR explicitly related only to
  issue #60-#89 are ignored before any paid model call.
- External forks, untrusted actors, bot replies, duplicate events, and stale
  head results cannot publish or merge.
- PR conversation replies and inline review replies are both included in the
  review context and create distinct review events.
- A `PASS` without at least one successful test record cannot merge.
- A merge uses GitHub's squash method and targets `refactor/agent`; the workflow
  never merges to `dev`.

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
