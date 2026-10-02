(async () => {
  "use strict";
  const config = __SOP_CAPTURE_CONFIG__;
  if (location.origin !== new URL(config.target).origin) {
    throw new Error("Run this only in the Console on " + config.target);
  }
  if (window.__sophiaProductionCapture?.running) {
    throw new Error("A capture is already running. Wait for it or call its stop() method.");
  }
  const controller = new AbortController();
  const control = {running: true, stop: () => controller.abort()};
  window.__sophiaProductionCapture = control;
  const report = {
    format: "sophia-browser-capture-v1",
    recorded_at_utc: new Date().toISOString(),
    target: config.target,
    expected_source_sha256: config.sha256,
    expected_chunk_count: config.chunkCount,
    authenticated_user_confirmed: false,
    corpus: null,
    unauthenticated_check: null,
    cases: [],
    completed: false,
    error: null,
    note: "COLLECTED means a response was captured, not that its policy claims passed audit."
  };
  const pause = ms => new Promise((resolve, reject) => {
    if (controller.signal.aborted) return reject(new Error("Capture stopped."));
    const onAbort = () => {
      clearTimeout(timer);
      reject(new Error("Capture stopped."));
    };
    const timer = setTimeout(() => {
      controller.signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    controller.signal.addEventListener("abort", onAbort, {once: true});
  });
  async function request(path, options = {}) {
    if (controller.signal.aborted) throw new Error("Capture stopped.");
    const requestController = new AbortController();
    const abort = () => requestController.abort();
    controller.signal.addEventListener("abort", abort, {once: true});
    const timer = setTimeout(abort, 180000);
    try {
      const response = await fetch(new URL(path, location.origin), {
        cache: "no-store",
        credentials: "same-origin",
        ...options,
        signal: requestController.signal
      });
      const text = await response.text();
      let body;
      try { body = JSON.parse(text); }
      catch { throw new Error("Non-JSON response (HTTP " + response.status + ")."); }
      return {
        status: response.status,
        body,
        retryAfter: response.headers.get("Retry-After")
      };
    } finally {
      clearTimeout(timer);
      controller.signal.removeEventListener("abort", abort);
    }
  }
  function download() {
    const blob = new Blob([JSON.stringify(report, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "sophia-production-capture-" +
      new Date().toISOString().replace(/[:.]/g, "-") + ".json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  try {
    console.info("SOPhia capture started. Keep this tab open. Responses require policy auditing.");
    const health = await request("/api/healthz");
    report.corpus = health.body;
    if (health.status !== 200 || health.body.source_sha256 !== config.sha256 ||
        health.body.chunk_count !== config.chunkCount || health.body.status !== "ok") {
      throw new Error("Corpus gate failed. No regression queries were sent.");
    }
    const auth = await request("/api/auth/user");
    // Save only a boolean, never identity data or session information.
    report.authenticated_user_confirmed = auth.status === 200 && Boolean(auth.body.user);
    if (!report.authenticated_user_confirmed) {
      throw new Error("Sign in with an authorized account, then rerun. No regression queries were sent.");
    }
    const unsigned = await request("/api/sop/query", {
      method: "POST", credentials: "omit",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: "What guaranty requirements apply?"})
    });
    report.unauthenticated_check = {
      expected_status: 401,
      actual_status: unsigned.status,
      passed: unsigned.status === 401
    };
    if (unsigned.status !== 401) {
      throw new Error("Unsigned access was not rejected with 401. Stopping for review.");
    }
    for (const [index, test] of config.cases.entries()) {
      await pause(2500);
      const started = performance.now();
      const item = {id: test.id, question: test.question, status: "ERROR"};
      report.cases.push(item);
      try {
        const options = {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({question: test.question})
        };
        let response = await request("/api/sop/query", options);
        if (response.status === 429) {
          const seconds = Number(response.retryAfter);
          await pause((Number.isFinite(seconds) ? Math.min(300, Math.max(3, seconds)) : 60) * 1000);
          response = await request("/api/sop/query", options);
        }
        item.http_status = response.status;
        item.response = response.body;
        item.elapsed_ms = Math.round(performance.now() - started);
        if (response.status !== 200) {
          throw new Error("HTTP " + response.status + " for " + test.id);
        }
        item.status = "COLLECTED";
        console.info("SOPhia [" + (index + 1) + "/" + config.cases.length + "] " +
          test.id + ": collected");
      } catch (error) {
        item.error = String(error.message || error);
        throw error;
      }
    }
    report.completed = true;
    console.info("SOPhia responses collected. Upload the downloaded JSON for policy/citation audit.");
  } catch (error) {
    report.error = String(error.message || error);
    console.error("SOPhia capture stopped:", report.error);
  } finally {
    const collectedIds = new Set(report.cases.map(item => item.id));
    for (const test of config.cases) {
      if (!collectedIds.has(test.id)) {
        report.cases.push({id: test.id, question: test.question, status: "NOT_RUN"});
      }
    }
    report.finished_at_utc = new Date().toISOString();
    control.running = false;
    control.download = download;
    download();
    console.info("If the download was blocked, run window.__sophiaProductionCapture.download()");
  }
})();