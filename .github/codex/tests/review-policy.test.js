"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  assertValidReviewResult,
  buildEventKey,
  collectRelatedIssueNumbers,
  latestHumanChangeRequest,
  passViolation,
  resolvePullChain,
} = require("../scripts/review-policy");

const SHA = "a".repeat(40);
const BASE_SHA = "b".repeat(40);

function validResult(overrides = {}) {
  return {
    phase: "implementation",
    verdict: "PASS",
    summary: "reviewed",
    target_branch: "refactor/agent",
    issue_numbers: [60],
    head_sha: SHA,
    flow_findings: [],
    standards_findings: [],
    spec_findings: [],
    tests: [{command: "pytest", status: "PASS", details: "passed"}],
    ...overrides,
  };
}

test("collects only explicit issue relationships and preserves out-of-range links", () => {
  assert.deepEqual(
    collectRelatedIssueNumbers(
      "Implements #60",
      "Mentions #61. Part of https://github.com/a/b/issues/62. Part of https://github.com/x/y/issues/64. Closes #100.",
      [{number: 63}],
      "a/b",
    ),
    [60, 62, 63, 100],
  );
});

test("recognizes an explicit Issue label without treating casual mentions as relationships", () => {
  assert.deepEqual(
    collectRelatedIssueNumbers("Green slice", "- Issue #60\n- Mentions #61 for context", [], "a/b"),
    [60],
  );
});

function pull(number, headRef, baseRef, overrides = {}) {
  return {
    number,
    state: "open",
    base: {ref: baseRef, sha: `${number}`.padStart(40, "b").slice(-40)},
    head: {
      ref: headRef,
      sha: `${number}`.padStart(40, "a").slice(-40),
      repo: {full_name: "a/b"},
    },
    ...overrides,
  };
}

test("resolves a root PR directly targeting the integration branch", async () => {
  const root = pull(90, "test/contract", "refactor/agent");
  const chain = await resolvePullChain(root, async () => [], "a/b", "refactor/agent");

  assert.deepEqual(chain.map((item) => item.number), [90]);
  assert.equal(chain[0].role, "root");
});

test("resolves a stacked child through its open parent PR", async () => {
  const parent = pull(90, "test/contract", "refactor/agent");
  const child = pull(94, "impl/green", "test/contract");
  const chain = await resolvePullChain(
    child,
    async (headRef) => (headRef === "test/contract" ? [parent] : []),
    "a/b",
    "refactor/agent",
  );

  assert.deepEqual(chain.map((item) => [item.number, item.role]), [
    [94, "child"],
    [90, "root"],
  ]);
});

test("rejects a stacked chain with no unique open parent or wrong final branch", async () => {
  const child = pull(94, "impl/green", "test/contract");
  await assert.rejects(
    resolvePullChain(child, async () => [], "a/b", "refactor/agent"),
    /exactly one open parent/,
  );

  const wrongRoot = pull(90, "test/contract", "dev");
  await assert.rejects(
    resolvePullChain(
      child,
      async (headRef) => (headRef === "test/contract" ? [wrongRoot] : []),
      "a/b",
      "refactor/agent",
    ),
    /protected branch dev/,
  );
});

test("rejects foreign, closed, and cyclic PR chains", async () => {
  const child = pull(94, "impl/green", "test/contract");
  const foreignParent = pull(90, "test/contract", "refactor/agent", {
    head: {ref: "test/contract", sha: "c".repeat(40), repo: {full_name: "fork/repo"}},
  });
  await assert.rejects(
    resolvePullChain(child, async () => [foreignParent], "a/b", "refactor/agent"),
    /same repository/,
  );

  const closedParent = pull(90, "test/contract", "refactor/agent", {state: "closed"});
  await assert.rejects(
    resolvePullChain(child, async () => [closedParent], "a/b", "refactor/agent"),
    /open/,
  );

  const cycleParent = pull(90, "test/contract", "impl/green");
  await assert.rejects(
    resolvePullChain(
      child,
      async (headRef) => {
        if (headRef === "test/contract") return [cycleParent];
        if (headRef === "impl/green") return [child];
        return [];
      },
      "a/b",
      "refactor/agent",
    ),
    /cycle/,
  );
});

test("event keys distinguish lifecycle actions and individual replies", () => {
  assert.notEqual(
    buildEventKey("pull_request_target", {action: "ready_for_review"}, BASE_SHA, SHA),
    buildEventKey("pull_request_target", {action: "reopened"}, BASE_SHA, SHA),
  );
  assert.notEqual(
    buildEventKey("issue_comment", {comment: {id: 1}}, BASE_SHA, SHA),
    buildEventKey("issue_comment", {comment: {id: 2}}, BASE_SHA, SHA),
  );
  assert.notEqual(
    buildEventKey("pull_request_review", {action: "submitted", review: {id: 3}}, BASE_SHA, SHA),
    buildEventKey("pull_request_review", {action: "dismissed", review: {id: 3}}, BASE_SHA, SHA),
  );
  assert.notEqual(
    buildEventKey("workflow_dispatch", {}, BASE_SHA, SHA),
    buildEventKey("workflow_dispatch", {}, "c".repeat(40), SHA),
  );
});

test("validates the complete result contract", () => {
  assert.doesNotThrow(() => assertValidReviewResult(validResult()));
  assert.throws(
    () => assertValidReviewResult({...validResult(), unexpected: true}),
    /fields do not match/,
  );
  assert.throws(
    () => assertValidReviewResult(validResult({target_branch: "dev"})),
    /target branch/,
  );
});

test("PASS is rejected for Red, blocking findings, or incomplete test evidence", () => {
  assert.match(passViolation(validResult({phase: "red_test"})), /Red-stage/);
  assert.match(
    passViolation(validResult({flow_findings: [{severity: "P1"}]})),
    /P0\/P1/,
  );
  assert.match(passViolation(validResult({tests: []})), /test evidence/);
  assert.match(
    passViolation(validResult({tests: [{command: "pytest", status: "EXPECTED_RED"}]})),
    /must pass/,
  );
  assert.equal(
    passViolation(validResult({standards_findings: [{severity: "P2"}]})),
    null,
  );
});

test("only a reviewer's latest current-head state can block merge", () => {
  const request = {user: {login: "alice", type: "User"}, commit_id: SHA, state: "CHANGES_REQUESTED"};
  const approve = {user: {login: "alice", type: "User"}, commit_id: SHA, state: "APPROVED"};
  const otherRequest = {user: {login: "bob", type: "User"}, commit_id: SHA, state: "CHANGES_REQUESTED"};
  assert.equal(latestHumanChangeRequest([request, approve], SHA), undefined);
  assert.equal(latestHumanChangeRequest([request, approve, otherRequest], SHA), otherRequest);
  assert.equal(
    latestHumanChangeRequest([{...request, commit_id: "b".repeat(40)}], SHA),
    undefined,
  );
});
