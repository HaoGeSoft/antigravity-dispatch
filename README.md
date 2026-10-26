# Antigravity Dispatch

A Codex skill and Python helper for dispatching task reports to Google Antigravity through its local `agentapi` interface.

## Contents

- `SKILL.md`: instructions for using the skill from Codex.
- `scripts/dispatch.py`: helper for selecting conversations and sending task reports.

## Requirements

- Windows with Antigravity installed and running.
- Python 3.8 or newer.
- The Antigravity language server's `agentapi` command.

The helper resolves per-user Antigravity paths from standard Windows environment variables and the current user's home directory. It does not include user-specific paths or credentials. The CSRF token is discovered at runtime from the local Antigravity process when needed; do not share command output or logs that contain credentials.

## Use

Install the folder as a Codex skill, or invoke the helper directly:

```powershell
python .\scripts\dispatch.py --status
python .\scripts\dispatch.py --file .\task-report.md --workspace "<project-directory>" --title "Task title"
```

Review task reports before dispatching. The helper includes a short excerpt and a local file URI in the message sent to Antigravity.

## Sponsor

由 凌梦AI平台 ai.vpszx.eu 强力驱动

