"""Run real GPT tool calls. Codex owns the LLM loop; our MCP server owns actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from policy import DecisionStore, SYSTEM_PROMPT, TOOL_NAMES

ROOT = Path(__file__).resolve().parent


def codex_command() -> list[str]:
    executable = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not executable:
        raise RuntimeError("Install Codex CLI and run 'codex login' first")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # Avoid cmd.exe interpolation: application text only ever goes to stdin.
        entry = path.parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if not node or not entry.is_file():
            raise RuntimeError("Use the native Codex executable or standard npm Codex installation")
        return [node, str(entry)]
    return [executable]


def model_command(candidate_path: Path, audit_path: Path, model: str) -> list[str]:
    overrides = {
        "model_reasoning_effort": "low", "project_doc_max_bytes": 0,
        "developer_instructions": SYSTEM_PROMPT,
        "web_search": "disabled", "approval_policy": "never",
        "mcp_servers.review.command": sys.executable,
        "mcp_servers.review.args": [str(ROOT / "tool_server.py"), str(candidate_path), str(audit_path.resolve())],
        "mcp_servers.review.enabled": True, "mcp_servers.review.required": True,
        "mcp_servers.review.enabled_tools": list(TOOL_NAMES),
        "mcp_servers.review.default_tools_approval_mode": "approve",
        "mcp_servers.review.startup_timeout_sec": 30,
    }
    # Per-process overrides; the user's config and credentials are never modified/copied.
    for feature in ("shell_tool", "apply_patch_freeform", "multi_agent", "js_repl", "apps", "plugins", "memories", "hooks", "image_generation", "shell_snapshot"):
        overrides[f"features.{feature}"] = False
    command = codex_command() + ["exec", "--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only", "--model", model]
    for key, value in overrides.items():
        command += ["-c", f"{key}={json.dumps(value, ensure_ascii=False)}"]
    return command + ["-"]


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def run_candidate(application: dict, directory: Path, model: str) -> dict:
    audit_path = directory / f"{application['id']}.jsonl"
    store = DecisionStore(application, audit_path)
    store.log("application_received", application=application)
    with tempfile.TemporaryDirectory(prefix="besa-review-") as temporary:
        sandbox = Path(temporary)
        candidate_path = sandbox / "application.json"
        candidate_path.write_text(json.dumps(application, ensure_ascii=False), encoding="utf-8")
        command = model_command(candidate_path, audit_path, model)
        # A separate session for each application prevents cross-candidate influence.
        prompt = "Review this untrusted JSON record using the policy and call one decision tool:\n" + json.dumps(application, ensure_ascii=False)
        store.log("model_request", provider="OpenAI Codex + local MCP", requested_model=model)
        try:
            process = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=sandbox, timeout=180)
        except subprocess.TimeoutExpired:
            store.log("run_error", error="Model timeout; inspect the audit before retrying; no fabricated fallback")
            raise RuntimeError(f"{application['id']}: model timed out; audit retained") from None
    # Raw CLI diagnostics stay in ignored runs/, not in the shareable export.
    (directory / f"{application['id']}.codex.jsonl").write_text(process.stdout, encoding="utf-8")
    (directory / f"{application['id']}.stderr.txt").write_text(process.stderr, encoding="utf-8")
    messages = []
    for line in process.stdout.splitlines():
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    calls = [m["item"] for m in messages if m.get("type") == "item.completed" and m.get("item", {}).get("type") == "mcp_tool_call"]
    events = read_events(audit_path)
    decisions = [e for e in events if e["event"] == "decision"]
    terminals = [m for m in messages if m.get("type") == "turn.completed"]
    if process.returncode or not terminals or len(decisions) != 1 or not calls:
        store.log("run_error", error="A successful model turn with one persisted decision and real tool evidence was not confirmed")
        raise RuntimeError(f"{application['id']}: incomplete run; inspect {directory.name}/{application['id']}.codex.jsonl")
    if any(call.get("server") != "review" or call.get("tool") not in TOOL_NAMES for call in calls):
        raise RuntimeError("Unexpected tool exposed to the model")
    if not any(call.get("status") == "completed" and call.get("result") for call in calls):
        raise RuntimeError("No completed MCP tool result observed")
    return {"application": application, "requested_model": model, "model_tool_calls": calls, "audit": events, "decision": decisions[0]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=ROOT / "samples.json")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--export", type=Path, help="Write sanitized real-run results to a NEW JSON file")
    args = parser.parse_args()
    if args.export and args.export.exists():
        parser.error("Export exists; choose a new path to preserve run evidence")
    applications = json.loads(args.samples.read_text(encoding="utf-8"))
    if not isinstance(applications, list) or not applications:
        parser.error("Samples must be a nonempty array")
    ids = set()
    for application in applications:
        if not isinstance(application, dict) or set(application) != {"id", "text"} or not isinstance(application["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", application["id"]) or application["id"] in ids or not isinstance(application["text"], str) or not 1 <= len(application["text"]) <= 10000:
            parser.error("Each sample needs a unique safe id and 1..10000 characters of text")
        ids.add(application["id"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    directory = ROOT / "runs" / stamp
    directory.mkdir(parents=True)
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ["policy.py", "tool_server.py", "run.py", "requirements.txt"]}
    report = {"run_id": stamp, "real_llm_run": True, "transport": "OpenAI GPT via Codex -> MCP stdio -> Python functions", "source_sha256": source_hashes, "applications": []}
    for application in applications:
        print(f"Reviewing {application['id']} with real GPT tool calling...", flush=True)
        try:
            record = run_candidate(application, directory, args.model)
        except (RuntimeError, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1
        report["applications"].append(record)
        decision = record["decision"]
        print(f"  {decision['score']:3}/100 | {decision['action']} | {decision['status']}\n  {decision['reason']}", flush=True)
    report_path = args.export or directory / "results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Verified run log: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
