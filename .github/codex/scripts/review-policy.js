"use strict";

const RELATIONSHIP_PATTERN =
  /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|implement(?:s|ed)?|part\s+of)\s+(?:#(\d+)|https:\/\/github\.com\/([^/\s]+\/[^/\s]+)\/issues\/(\d+))/gi;

const RESULT_KEYS = [
  "flow_findings",
  "head_sha",
  "issue_numbers",
  "phase",
  "spec_findings",
  "standards_findings",
  "summary",
  "target_branch",
  "tests",
  "verdict",
];
const FINDING_KEYS = ["detail", "file", "line", "required_change", "severity", "title"];
const TEST_KEYS = ["command", "details", "status"];

function sameKeys(value, expected) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort())
  );
}

function nonEmptyString(value) {
  return typeof value === "string" && value.length > 0;
}

function collectRelatedIssueNumbers(title, body, closingIssues = [], repository = null) {
  const numbers = new Set(closingIssues.map((issue) => Number(issue.number)));
  const text = `${title || ""}\n${body || ""}`;
  for (const match of text.matchAll(RELATIONSHIP_PATTERN)) {
    if (match[1]) numbers.add(Number(match[1]));
    if (match[3] && repository && match[2].toLowerCase() === repository.toLowerCase()) {
      numbers.add(Number(match[3]));
    }
  }
  return [...numbers].sort((left, right) => left - right);
}

function buildEventKey(eventName, payload, headSha) {
  let triggerId = `${payload.action || "event"}-${headSha}`;
  if (payload.comment?.id) triggerId = `comment-${payload.comment.id}`;
  if (payload.review?.id) triggerId = `review-${payload.action || "event"}-${payload.review.id}`;
  return `${eventName}:${headSha}:${triggerId}`;
}

function assertValidReviewResult(result) {
  if (!sameKeys(result, RESULT_KEYS)) throw new Error("result fields do not match the contract");
  if (!new Set(["design", "red_test", "implementation", "acceptance"]).has(result.phase)) {
    throw new Error("invalid phase");
  }
  if (!new Set(["PASS", "CHANGES_REQUESTED", "WAITING", "BLOCKED"]).has(result.verdict)) {
    throw new Error("invalid verdict");
  }
  if (!nonEmptyString(result.summary) || result.target_branch !== "refactor/agent") {
    throw new Error("invalid summary or target branch");
  }
  if (
    !Array.isArray(result.issue_numbers) ||
    result.issue_numbers.length === 0 ||
    new Set(result.issue_numbers).size !== result.issue_numbers.length ||
    result.issue_numbers.some((number) => !Number.isInteger(number) || number < 60 || number > 89)
  ) {
    throw new Error("invalid issue numbers");
  }
  if (typeof result.head_sha !== "string" || !/^[0-9a-f]{40}$/.test(result.head_sha)) {
    throw new Error("invalid head SHA");
  }
  for (const field of ["flow_findings", "standards_findings", "spec_findings"]) {
    if (!Array.isArray(result[field])) throw new Error(`${field} must be an array`);
    for (const finding of result[field]) {
      if (!sameKeys(finding, FINDING_KEYS)) throw new Error(`invalid ${field} fields`);
      if (!new Set(["P0", "P1", "P2", "P3"]).has(finding.severity)) {
        throw new Error(`invalid ${field} severity`);
      }
      if (
        !nonEmptyString(finding.title) ||
        !nonEmptyString(finding.detail) ||
        !nonEmptyString(finding.required_change) ||
        !(finding.file === null || typeof finding.file === "string") ||
        !(finding.line === null || (Number.isInteger(finding.line) && finding.line >= 1))
      ) {
        throw new Error(`invalid ${field} finding`);
      }
    }
  }
  if (!Array.isArray(result.tests)) throw new Error("tests must be an array");
  for (const test of result.tests) {
    if (!sameKeys(test, TEST_KEYS)) throw new Error("invalid test fields");
    if (
      !nonEmptyString(test.command) ||
      !nonEmptyString(test.details) ||
      !new Set(["PASS", "FAIL", "EXPECTED_RED", "NOT_RUN"]).has(test.status)
    ) {
      throw new Error("invalid test record");
    }
  }
}

function passViolation(result) {
  if (result.verdict !== "PASS") return null;
  const findings = [
    ...result.flow_findings,
    ...result.standards_findings,
    ...result.spec_findings,
  ];
  if (result.phase === "red_test") return "a Red-stage PR cannot pass";
  if (findings.some((finding) => finding.severity === "P0" || finding.severity === "P1")) {
    return "a PASS result cannot contain P0/P1 findings";
  }
  if (result.tests.length === 0) return "a PASS result must contain test evidence";
  if (result.tests.some((test) => test.status !== "PASS")) {
    return "every test record in a PASS result must pass";
  }
  return null;
}

function latestHumanChangeRequest(reviews, headSha) {
  const latestByUser = new Map();
  for (const review of reviews) {
    if (review.user?.type !== "Bot" && review.commit_id === headSha) {
      latestByUser.set(review.user.login, review);
    }
  }
  return [...latestByUser.values()].find((review) => review.state === "CHANGES_REQUESTED");
}

module.exports = {
  assertValidReviewResult,
  buildEventKey,
  collectRelatedIssueNumbers,
  latestHumanChangeRequest,
  passViolation,
};
