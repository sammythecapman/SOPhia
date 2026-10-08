"""Identify the actual shipped source content without depending on deployed .git."""

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_build_info() -> dict:
    inputs = set((ROOT / "artifacts/api-server").glob("*.py"))
    for directory in ("artifacts/sop-query-tool/src", "artifacts/sop-query-tool/public"):
        inputs.update(path for path in (ROOT / directory).rglob("*") if path.is_file())
    for name in (
        "artifacts/sop-query-tool/package.json", "artifacts/sop-query-tool/index.html",
        "artifacts/sop-query-tool/vite.config.ts", "pnpm-lock.yaml", "uv.lock", "pyproject.toml",
    ):
        path = ROOT / name
        if path.is_file():
            inputs.add(path)
    digest = hashlib.sha256()
    for path in sorted(inputs):
        content = path.read_bytes()
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(str(len(content)).encode() + b"\0" + content)
    commit = None
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, timeout=2, check=True,
        ).stdout.strip()
        if re.fullmatch(r"[0-9a-f]{40,64}", value):
            commit = value
    except (OSError, subprocess.SubprocessError):
        pass  # Published bundles need not include .git; the content SHA is authoritative.
    return {
        "build_sha": digest.hexdigest(),
        "build_sha_kind": "source-content-sha256",
        "git_commit_sha": commit,
    }
