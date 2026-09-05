"use strict";

const RELATIONSHIP_PATTERN =
  /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|implement(?:s|ed)?|part\s+of)\s+(?:#(\d+)|https:\/\/github\.com\/([^/\s]+\/[^/\s]+)\/issues\/(\d+))/gi;
const ISSUE_LABEL_PATTERN = /\bissue\s+#(\d+)\b/gi;

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
  for (const match of text.matchAll(ISSUE_LABEL_PATTERN)) {
    numbers.add(Number(match[1]));
  }
  return [...numbers].sort((left, right) => left - right);
}

function pullChainEntry(pull) {
  return {
    number: pull.number,
    state: pull.state,
    base_ref: pull.base?.ref,
    base_sha: pull.base?.sha,
    head_ref: pull.head?.ref,
    head_sha: pull.head?.sha,
    head_repository: pull.head?.repo?.full_name,
  };
}

async function resolvePullChain(
  startPull,
  loadOpenParentsByHead,
  repository,
  integrationBranch = "refactor/agent",
) {
  if (typeof loadOpenParentsByHead !== "function") {
    throw new Error("a parent PR loader is required");
  }

  const chain = [];
  const seenNumbers = new Set();
  const seenHeads = new Set();
  let pull = startPull;

  for (let depth = 0; depth < 20; depth += 1) {
    const entry = pullChainEntry(pull);
    if (entry.state !== "open") throw new Error(`PR #${entry.number} is not open`);
    if (entry.head_repository !== repository) {
      throw new Error(`PR #${entry.number} head must be in the same repository`);
    }
    if (!entry.head_ref || !entry.base_ref || !entry.head_sha || !entry.base_sha) {
      throw new Error(`PR #${entry.number} has an incomplete branch identity`);
    }
    if (seenNumbers.has(entry.number) || seenHeads.has(entry.head_ref)) {
      throw new Error(`pull-request chain contains a cycle at PR #${entry.number}`);
    }

    seenNumbers.add(entry.number);
    seenHeads.add(entry.head_ref);
    chain.push(entry);

    if (entry.base_ref === integrationBranch) {
      return chain.map((item, index) => ({
        ...item,
        role: index === chain.length - 1 ? "root" : "child",
      }));
    }
    if (new Set(["dev", "main", "master"]).has(entry.base_ref)) {
      throw new Error(`stacked PRs cannot target protected branch ${entry.base_ref}`);
    }

    const parents = await loadOpenParentsByHead(entry.base_ref);
    if (!Array.isArray(parents) || parents.length !== 1) {
      throw new Error(
        `base ${entry.base_ref} must be the head of exactly one open parent PR`,
      );
    }
    [pull] = parents;
  }

  throw new Error("pull-request chain exceeds the maximum depth");
}

function buildEventKey(eventName, payload, baseSha, headSha) {
  let triggerId = `${payload.action || "event"}-${headSha}`;
  if (payload.comment?.id) triggerId = `comment-${payload.comment.id}`;
  if (payload.review?.id) triggerId = `review-${payload.action || "event"}-${payload.review.id}`;
  return `${eventName}:${baseSha}:${headSha}:${triggerId}`;
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
  resolvePullChain,
};
