#!/usr/bin/env python3
"""Generate a self-contained guide containing the signed-in browser collector."""

import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHA256 = "0fb0c4692cf529380827746e5fe812e42ea82b6f6fdf97a71d1093677d963183"


def build_guide(target: str, build_sha: str) -> str:
    cases = json.loads((ROOT / "tests/sop_regression.json").read_text())
    cases.extend(json.loads(
        (ROOT / "tests/fixtures/sophia_issue_evals.json").read_text()
    )["cases"])
    cases.sort(key=lambda case: case["id"] != "trust-guaranty")
    config = {
        "target": target.rstrip("/"),
        "sha256": SHA256,
        "chunkCount": 395,
        "buildSha": build_sha,
        "cases": [{"id": case["id"], "question": case["question"]} for case in cases],
    }
    template = (ROOT / "scripts/sop_browser_runner.js").read_text()
    script = template.replace("__SOP_CAPTURE_CONFIG__", json.dumps(config))
    origin = html.escape(target.rstrip("/"), quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SOPhia production verification guide</title>
<style>
body{{font:16px/1.6 system-ui,sans-serif;color:#172e46;background:#f3f6fa;margin:0}}
main{{max-width:850px;margin:35px auto;padding:30px;background:white;border-radius:12px}}
h1{{line-height:1.2}} h2{{margin-top:28px}} a{{color:#174f85}}
.notice{{background:#edf3fa;border-left:4px solid #214b75;padding:15px}}
button{{background:#214b75;color:white;border:0;border-radius:7px;padding:12px 20px;font:inherit;cursor:pointer}}
textarea{{box-sizing:border-box;width:100%;height:240px;font:12px/1.4 monospace;padding:12px;margin-top:14px}}
code{{background:#edf3fa;padding:2px 5px;overflow-wrap:anywhere}}
li{{margin:10px 0}} @media(max-width:600px){{main{{margin:12px;padding:20px}}}}
</style></head><body><main>
<h1>SOPhia production verification</h1>
<p>Use your existing signed-in browser session to collect {len(cases)} regression responses.
The two-trust aggregation question runs first, followed by the regression and fact-changing counterexamples.
Publish the updated build before running this guide.
This guide is <strong>not a completed production verification</strong>.</p>
<p>Required source-content build SHA: <code>{html.escape(build_sha)}</code>.
The health endpoint's <code>git_commit_sha</code>, when available, is separate;
the content SHA identifies shipped code even if the published bundle has no Git metadata.</p>
<div class="notice"><strong>What this script does:</strong> checks the expected corpus
hash, 395 chunks, and exact build SHA before and after the run, verifies authorized sign-in and unsigned 401 rejection, then
sends the saved regression questions one at a time. These queries use the live
answer service and its normal query usage. It does not read or export cookies,
passwords, account details, or request headers. It does not change the corpus or configuration.
<br><strong>Collected responses are not a policy-test pass.</strong> Upload the report
for citation and answer auditing.</div>
<h2>Run the signed-in capture</h2><ol>
<li>Open <a href="{origin}" target="_blank" rel="noopener noreferrer">{origin}</a>
and sign in with an allowed account.</li>
<li>On that SOPhia tab, open your browser's developer tools and select
<strong>Console</strong>. In Chrome or Edge use <strong>Ctrl+Shift+J</strong>
(Windows/Linux) or <strong>Cmd+Option+J</strong> (Mac).</li>
<li>Review the script below, click <strong>Copy test script</strong>, and paste it
into the Console on the SOPhia tab. Press Enter. If your browser blocks pasting,
follow its displayed instructions only after reviewing this script.</li>
<li>Keep the tab open until it finishes. It prints progress for every question and
downloads a <code>sophia-production-capture-…json</code> report, including partial
results if it stops. It can take several minutes.</li>
<li>Upload that JSON in the Replit chat so the responses can be audited. Do not
upload cookies, passwords, or a browser network/HAR export.</li></ol>
<button id="copy" type="button">Copy test script</button>
<span id="status" role="status" aria-live="polite"></span>
<textarea id="script" readonly aria-label="Browser test script">{html.escape(script)}</textarea>
<p>To stop safely, run <code>window.__sophiaProductionCapture.stop()</code>.
If the download was blocked, run <code>window.__sophiaProductionCapture.download()</code>
after the capture ends.</p>
<h2>Separate allowlist 403 check</h2>
<p>This needs a genuine authenticated account that is <strong>not</strong> on SOPhia's
allowlist. Use a separate private browser window so your permitted session stays intact.
Follow the normal SOPhia login flow with that account. The callback should return
HTTP <strong>403</strong> and <code>This account is not authorized.</code></p>
<p>Record the HTTP status and denial message only. A screenshot of those two values is
enough; hide account details and the callback URL's query string. Do not share credentials,
full network exports, or authorization codes. An unsigned <strong>401</strong> is not
evidence of this 403 test. If no such account is available, leave this check blocked.</p>
</main><script>
document.getElementById("copy").addEventListener("click",async()=>{{
 const field=document.getElementById("script");
 const status=document.getElementById("status");
 try{{await navigator.clipboard.writeText(field.value);status.textContent=" Copied.";}}
 catch{{field.focus();field.select();status.textContent=" Selected. Press Ctrl+C or Cmd+C to copy.";}}
}});
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-build-sha", required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_guide(args.target, args.expected_build_sha))
    print(f"Guide written to {args.output}")


if __name__ == "__main__":
    main()