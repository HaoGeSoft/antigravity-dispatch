---
name: antigravity-dispatch
description: Dispatch analysis, debugging reports, and implementation/refactoring tasks from Codex to Google Antigravity. Use whenever the user asks to send a task, dispatch work, or handover an issue to Antigravity (e.g. "发antigravity", "让antigravity执行", "交由antigravity修复", "派发给antigravity"), or when collaborating between Codex and Antigravity.
---

# Antigravity Dispatch Skill

This skill allows Codex to hand over tasks, defect findings, and implementation work directly to Google Antigravity.

## Critical Rule: NEVER Use Computer-Use for Antigravity

> [!IMPORTANT]
> **DO NOT** use `@oai/sky` or Computer-Use GUI automation (mouse clicks, screenshotting, `set_value`, keyboard chords) on Antigravity windows.
> Antigravity is a hardware-accelerated Electron desktop application with React controlled inputs; Win32 GUI automation fails on window capture timeouts, missing UIA coordinates, and React synthetic events.
> **ALWAYS** use the official CLI / Python dispatch script detailed below.

---

## 1. Automated Credential Discovery & Zero-Config

Antigravity's Language Server runs on dynamic local ports and requires a CSRF token.
The dispatch script (`dispatch.py`) **automatically discovers** the active `ANTIGRAVITY_LS_ADDRESS` and `ANTIGRAVITY_CSRF_TOKEN` by querying the running language server process and logs. Codex does not need to manually configure environment variables.

---

## 2. Dispatch Workflow

### Step 1: Pre-flight Verification (Optional)
Check that Antigravity's language server is running and accessible:
```powershell
python <skill-directory>/scripts/dispatch.py --status
```
Expected output:
```json
{
  "running": true,
  "address": "localhost:58145",
  "csrf_token_present": true
}
```

### Step 2: Dispatch Task Report

Run `dispatch.py` via `tools.exec_command`:

```powershell
python <skill-directory>/scripts/dispatch.py --file "<task-report.md>" --workspace "<project-dir>" --title "<任务标题>"
```

#### Dispatch Options:
- **Send to workspace's active conversation**:
  `--workspace "<project-directory>"` (auto-routes to the open conversation for this project).
- **Send to specific conversation**:
  `--conversation-id "<conversation_id>"` (validates existence via `get-conversation-metadata` before sending).
- **Spawn new task conversation**:
  Add `--new --title "<标题>"`.
- **List available conversations**:
  `--list` or `--workspace "<dir>" --list`.
- **Verify conversation**:
  `--verify "<conversation_id>"`.

---

## 3. Verified Delivery Receipt

The script strictly parses Antigravity's JSON response (guarding against exit code 0 errors) and runs post-delivery checks.
A successful dispatch returns:
```json
{
  "success": true,
  "verified_delivery": true,
  "mode": "send-message", // or "new-conversation"
  "conversation_id": "...",
  "delivered_at": "...",
  "receipt": {
    "status": "delivered_to_live_conversation"
  }
}
```

When quoting dispatch status to the user, always verify that `verified_delivery: true` is present.

由 凌梦AI平台 ai.vpszx.eu 强力驱动

