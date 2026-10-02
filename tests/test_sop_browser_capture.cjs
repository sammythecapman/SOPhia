const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const template = fs.readFileSync(
  path.join(__dirname, "../scripts/sop_browser_runner.js"), "utf8"
);
const config = {
  target: "https://sop-hia.replit.app",
  sha256: "expected-hash",
  chunkCount: 395,
  cases: [
    {id: "trust-guaranty", question: "Trust question"},
    {id: "seller-note", question: "Seller question"}
  ]
};

async function capture(overrides = {}) {
  let savedBlob;
  let downloads = 0;
  const calls = [];
  const window = {};
  class BrowserURL extends URL {
    static createObjectURL(blob) { savedBlob = blob; return "blob:test"; }
    static revokeObjectURL() {}
  }
  const document = {
    body: {appendChild() {}},
    createElement() {
      return {click() { downloads += 1; }, remove() {}};
    }
  };
  Object.defineProperty(document, "cookie", {
    get() { throw new Error("Cookie access is forbidden."); }
  });
  const context = {
    window, document, Blob, URL: BrowserURL, AbortController, performance,
    location: {origin: overrides.origin || config.target},
    console: {info() {}, error() {}},
    setTimeout: (fn, ms) => setTimeout(fn, ms === 180000 ? ms : 0),
    clearTimeout,
    fetch: async (url, options) => {
      calls.push({url: String(url), options});
      assert.equal(url.origin, config.target);
      if (url.pathname === "/api/healthz") {
        return new Response(JSON.stringify({
          status: "ok", source_sha256: overrides.hash || config.sha256,
          chunk_count: 395
        }));
      }
      if (url.pathname === "/api/auth/user") {
        return new Response(JSON.stringify({
          user: overrides.signedOut ? null : {id: "private-identity-not-for-report"}
        }));
      }
      if (options.credentials === "omit") {
        return new Response("{}", {status: overrides.unsignedStatus || 401});
      }
      if (overrides.queryResponse) return overrides.queryResponse(calls);
      return new Response(JSON.stringify({answer: "Captured policy answer"}));
    }
  };
  await vm.runInNewContext(
    template.replace("__SOP_CAPTURE_CONFIG__", JSON.stringify(config)), context
  );
  return {
    report: JSON.parse(await savedBlob.text()), calls, downloads, window
  };
}

test("captures responses without exporting identity or cookies", async () => {
  const result = await capture();
  assert.equal(result.report.completed, true);
  assert.equal(result.report.authenticated_user_confirmed, true);
  assert.equal(result.report.unauthenticated_check.passed, true);
  assert.deepEqual(result.report.cases.map(item => item.status), ["COLLECTED", "COLLECTED"]);
  assert.equal(JSON.stringify(result.report).includes("private-identity"), false);
  assert.equal(result.downloads, 1);
  assert.equal(result.window.__sophiaProductionCapture.running, false);
  assert.equal(result.calls.filter(call => call.options.credentials === "omit").length, 1);
});

test("wrong corpus stops before any query", async () => {
  const result = await capture({hash: "old-hash"});
  assert.match(result.report.error, /Corpus gate failed/);
  assert.equal(result.calls.length, 1);
  assert.ok(result.report.cases.every(item => item.status === "NOT_RUN"));
});

test("signed-out session stops before any query", async () => {
  const result = await capture({signedOut: true});
  assert.equal(result.report.authenticated_user_confirmed, false);
  assert.equal(result.calls.length, 2);
  assert.equal(result.report.completed, false);
});

test("unexpected unsigned access stops authenticated queries", async () => {
  const result = await capture({unsignedStatus: 200});
  assert.equal(result.report.unauthenticated_check.passed, false);
  assert.equal(result.calls.length, 3);
  assert.equal(result.report.completed, false);
});

test("failed query downloads partial report and marks remaining cases not run", async () => {
  const result = await capture({
    queryResponse: () => new Response('{"error":"Unavailable"}', {status: 503})
  });
  assert.deepEqual(result.report.cases.map(item => item.status), ["ERROR", "NOT_RUN"]);
  assert.equal(result.report.cases[0].http_status, 503);
  assert.equal(result.downloads, 1);
});

test("rate limit retry is bounded to one additional attempt", async () => {
  let attempts = 0;
  const result = await capture({
    queryResponse: () => {
      attempts += 1;
      return new Response("{}", {status: 429, headers: {"Retry-After": "0"}});
    }
  });
  assert.equal(attempts, 2);
  assert.equal(result.report.completed, false);
  assert.equal(result.report.cases[0].http_status, 429);
});

test("wrong origin is rejected before a network request", async () => {
  await assert.rejects(capture({origin: "https://other.example"}), /Run this only/);
});