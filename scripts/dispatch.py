#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Dispatcher for Codex.
Allows Codex to dispatch analysis, bugs, or implementation tasks to Google Antigravity
via Antigravity's official CLI (`agentapi`), with automatic credential discovery,
strict JSON validation, and verified receipt generation.
"""

import argparse
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from pathlib import Path

def antigravity_paths():
    """Resolve Antigravity files from standard per-user Windows locations."""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    home = Path.home()
    return {
        "language_server": local / "Programs" / "antigravity" / "resources" / "bin" / "language_server.exe",
        "database": home / ".gemini" / "antigravity" / "conversation_summaries.db",
        "log": roaming / "Antigravity" / "logs" / "language_server.log",
    }


PATHS = antigravity_paths()
LANGUAGE_SERVER_EXE = PATHS["language_server"]
DB_PATH = PATHS["database"]
LS_LOG_PATH = PATHS["log"]


def discover_credentials():
    """
    Auto-discovers ANTIGRAVITY_LS_ADDRESS and ANTIGRAVITY_CSRF_TOKEN.
    Falls back to querying the running language_server.exe process if env vars are unset.
    """
    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS")
    token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
    if addr and token:
        return {"ANTIGRAVITY_LS_ADDRESS": addr, "ANTIGRAVITY_CSRF_TOKEN": token}

    # Query running language_server.exe process
    try:
        ps_cmd = [
            "powershell", "-NoProfile", "-Command",
            'Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "language_server.exe" } | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress'
        ]
        res = subprocess.run(ps_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        raw = res.stdout.strip()
        if raw:
            data = json.loads(raw)
            if isinstance(data, list):
                data = data[0]
            pid = data.get("ProcessId")
            cline = data.get("CommandLine", "")
            token_match = re.search(r"--csrf_token\s+([a-zA-Z0-9_-]+)", cline)
            token = token_match.group(1) if token_match else None

            # Read HTTP port from log file
            port = None
            if LS_LOG_PATH.exists():
                try:
                    lines = LS_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in reversed(lines):
                        m = re.search(r"Language server listening on random port at (\d+) for HTTP", line)
                        if m:
                            port = m.group(1)
                            break
                except Exception:
                    pass

            # Fallback to listening TCP ports of the process
            if not port and pid:
                net_cmd = [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-NetTCPConnection -OwningProcess {pid} -State Listen).LocalPort"
                ]
                nres = subprocess.run(net_cmd, stdout=subprocess.PIPE, text=True, timeout=5)
                ports = [p.strip() for p in nres.stdout.split() if p.strip()]
                if ports:
                    port = max(ports, key=int)

            if port and token:
                return {
                    "ANTIGRAVITY_LS_ADDRESS": f"localhost:{port}",
                    "ANTIGRAVITY_CSRF_TOKEN": token,
                }
    except Exception:
        pass

    return None


def run_agentapi(subcommand_args, env=None):
    """
    Executes language_server.exe agentapi <args> with credentials and returns (code, stdout_str, stderr_str).
    """
    cmd = [str(LANGUAGE_SERVER_EXE), "agentapi"] + subcommand_args
    call_env = dict(os.environ)
    if env:
        call_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=call_env,
            timeout=15,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out after 15 seconds"
    except Exception as e:
        return -1, "", str(e)


def parse_and_validate_response(stdout_str, stderr_str, expected_key=None):
    """
    Strictly validates the agentapi JSON output.
    Returns (is_valid, parsed_data_or_error_string).
    """
    if not stdout_str:
        return False, stderr_str or "Empty output from agentapi"

    try:
        data = json.loads(stdout_str)
    except Exception as e:
        return False, f"Invalid JSON returned: {stdout_str[:200]} ({e})"

    if "error" in data and data["error"]:
        return False, data["error"]

    resp = data.get("response")
    if resp is None:
        return False, f"Missing 'response' in JSON: {stdout_str[:200]}"

    if expected_key and expected_key not in resp:
        return False, f"Expected key '{expected_key}' not in response: {json.dumps(resp)}"

    return True, data


def get_conversation_metadata(conversation_id, env=None):
    """
    Retrieves and validates metadata for an Antigravity conversation.
    """
    code, out, err = run_agentapi(["get-conversation-metadata", conversation_id], env=env)
    valid, res = parse_and_validate_response(out, err, expected_key="conversationMetadata")
    if not valid:
        return False, res
    return True, res["response"]["conversationMetadata"]


def find_active_conversations(workspace_path=None, limit=10):
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT conversation_id, title, workspace_uris, last_modified_time "
        "FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT ?",
        (limit * 3,),
    )
    results = []
    ws_norm = workspace_path.replace("\\", "/").lower().rstrip("/") if workspace_path else None

    for cid, title, uris, lmt in cur.fetchall():
        matched = True
        if ws_norm:
            matched = False
            if uris:
                try:
                    arr = json.loads(uris)
                    for u in arr:
                        u_dec = urllib.parse.unquote(u).replace("\\", "/").lower().rstrip("/")
                        if ws_norm in u_dec:
                            matched = True
                            break
                except Exception:
                    pass
        if matched:
            results.append({
                "conversation_id": cid,
                "title": title or "(Untitled)",
                "last_modified_time": lmt,
            })
            if len(results) >= limit:
                break
    conn.close()
    return results


def dispatch(file_path=None, prompt=None, conversation_id=None, workspace=None, title=None, force_new=False):
    # 1. Credentials Auto-Discovery
    env = discover_credentials()
    if not env:
        return {
            "success": False,
            "error": "Antigravity Language Server is not running or credentials (address/token) could not be discovered.",
            "verified_delivery": False,
        }

    # 2. Format task content
    task_text = ""
    abs_file = None
    if file_path:
        p = Path(file_path).resolve()
        if not p.exists():
            return {"success": False, "error": f"Task file not found: {file_path}", "verified_delivery": False}
        abs_file = str(p)
        content = p.read_text(encoding="utf-8", errors="ignore")
        summary_prompt = prompt or "请完整读取上述任务文档，严格按照文中的根因分析、返修范围与验收条件执行代码修改与测试验证。"
        task_text = (
            f"【来自 Codex 的任务派发】\n"
            f"任务文档：file:///{abs_file.replace(os.sep, '/')}\n\n"
            f"指令要求：\n{summary_prompt}\n\n"
            f"任务文档摘录：\n{content[:600]}..."
        )
    elif prompt:
        task_text = prompt
    else:
        return {"success": False, "error": "Either --file or --prompt must be provided.", "verified_delivery": False}

    # 3. Target Selection & Pre-verification
    target_cid = conversation_id
    target_title = title
    if not target_cid and not force_new and workspace:
        matches = find_active_conversations(workspace_path=workspace, limit=1)
        if matches:
            target_cid = matches[0]["conversation_id"]
            if not target_title:
                target_title = matches[0]["title"]

    timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 4. Delivery
    if target_cid and not force_new:
        # Verify target conversation exists before sending
        meta_ok, meta_data = get_conversation_metadata(target_cid, env=env)
        if not meta_ok:
            return {
                "success": False,
                "error": f"Target conversation {target_cid} validation failed: {meta_data}",
                "verified_delivery": False,
            }

        cmd_args = ["send-message"]
        if target_title:
            cmd_args.append(f"--title={target_title}")
        cmd_args.extend([target_cid, task_text])
        code, out, err = run_agentapi(cmd_args, env=env)
        valid, resp_data = parse_and_validate_response(out, err, expected_key="sendMessage")
        if not valid:
            return {
                "success": False,
                "error": f"send-message failed: {resp_data}",
                "raw_output": out or err,
                "verified_delivery": False,
            }

        send_receipt = resp_data["response"]["sendMessage"]
        return {
            "success": True,
            "verified_delivery": True,
            "mode": "send-message",
            "conversation_id": target_cid,
            "title": target_title,
            "delivered_at": timestamp_iso,
            "receipt": {
                "recipientId": send_receipt.get("recipientId"),
                "status": "delivered_to_live_conversation",
            },
        }

    else:
        # Create new conversation
        cmd_args = ["new-conversation"]
        if target_title:
            cmd_args.append(f"--title={target_title}")
        cmd_args.append(task_text)
        code, out, err = run_agentapi(cmd_args, env=env)
        valid, resp_data = parse_and_validate_response(out, err, expected_key="newConversation")
        if not valid:
            return {
                "success": False,
                "error": f"new-conversation failed: {resp_data}",
                "raw_output": out or err,
                "verified_delivery": False,
            }

        new_conv = resp_data["response"]["newConversation"]
        new_cid = new_conv.get("conversationId")

        # Post-verify new conversation exists
        meta_ok, _ = get_conversation_metadata(new_cid, env=env)

        return {
            "success": True,
            "verified_delivery": meta_ok,
            "mode": "new-conversation",
            "conversation_id": new_cid,
            "title": target_title,
            "delivered_at": timestamp_iso,
            "receipt": {
                "conversationId": new_cid,
                "verified_by_metadata_check": meta_ok,
                "status": "spawned_and_active",
            },
        }


def main():
    parser = argparse.ArgumentParser(description="Dispatch tasks from Codex to Google Antigravity.")
    parser.add_argument("--file", "-f", help="Path to markdown task file.")
    parser.add_argument("--prompt", "-p", help="Task prompt or description.")
    parser.add_argument("--conversation-id", "-c", help="Target Antigravity conversation ID.")
    parser.add_argument("--workspace", "-w", help="Workspace path to find matching Antigravity conversation.")
    parser.add_argument("--title", "-t", help="Title for the task or message.")
    parser.add_argument("--new", "-n", action="store_true", help="Force creating a new Antigravity conversation.")
    parser.add_argument("--list", "-l", action="store_true", help="List recent Antigravity conversations.")
    parser.add_argument("--verify", "-v", help="Verify connection and check metadata for a conversation ID.")
    parser.add_argument("--status", "-s", action="store_true", help="Check Antigravity server connection status.")

    args = parser.parse_args()

    if args.status:
        env = discover_credentials()
        if not env:
            print(json.dumps({"running": False, "error": "Antigravity language server not found"}, indent=2))
            sys.exit(1)
        print(json.dumps({
            "running": True,
            "address": env["ANTIGRAVITY_LS_ADDRESS"],
            "csrf_token_present": bool(env["ANTIGRAVITY_CSRF_TOKEN"]),
        }, indent=2))
        return

    if args.verify:
        env = discover_credentials()
        if not env:
            print(json.dumps({"verified": False, "error": "Connection credentials unavailable"}, indent=2))
            sys.exit(1)
        ok, data = get_conversation_metadata(args.verify, env=env)
        print(json.dumps({"verified": ok, "conversation_id": args.verify, "metadata": data if ok else None, "error": None if ok else data}, ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)

    if args.list:
        convs = find_active_conversations(workspace_path=args.workspace)
        print(json.dumps(convs, ensure_ascii=False, indent=2))
        return

    res = dispatch(
        file_path=args.file,
        prompt=args.prompt,
        conversation_id=args.conversation_id,
        workspace=args.workspace,
        title=args.title,
        force_new=args.new,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()


