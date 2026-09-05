# Agent refactor PR review automation

This automation reviews pull requests targeting `refactor/agent` and linked to
Issue #60-#89. It reacts to new/updated PRs, review submissions, PR conversation
comments, and inline review comments. A successful non-Draft review is squash
merged; other verdicts are published as a GitHub review.

The workflow is deliberately split into two privilege domains:

- the Codex job receives a read-only GitHub token and the OpenAI key through the
  official API-key proxy; it cannot review or merge on GitHub;
- the publish job receives no OpenAI key and is the only job allowed to publish
  a review or squash merge.

Only repository collaborators with `write`, `maintain`, or `admin` permission
can trigger a paid review. Results contain an event/head-SHA marker so reruns do
not publish duplicate reviews. New commits and new human replies have distinct
keys and therefore trigger fresh reviews.

## Repository configuration

The following repository settings are required:

1. Actions enabled, with explicit per-workflow permissions retained.
2. GitHub Actions may create pull-request reviews.
3. Secret `OPENAI_API_KEY` contains a project-scoped OpenAI API key.
4. Variable `AGENT_PR_REVIEW_ENABLED` is `true` only after the secret is ready.

Keep the variable `false` while rotating or removing the key. Never store a
ChatGPT/Codex desktop login token or `auth.json` in GitHub Secrets.
