"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  assertValidReviewResult,
  buildEventKey,
  collectRelatedIssueNumbers,
  latestHumanChangeRequest,
  passViolation,
} = require("../scripts/review-policy");

const SHA = "a".repeat(40);

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

test("event keys distinguish lifecycle actions and individual replies", () => {
  assert.notEqual(
    buildEventKey("pull_request_target", {action: "ready_for_review"}, SHA),
    buildEventKey("pull_request_target", {action: "reopened"}, SHA),
  );
  assert.notEqual(
    buildEventKey("issue_comment", {comment: {id: 1}}, SHA),
    buildEventKey("issue_comment", {comment: {id: 2}}, SHA),
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
