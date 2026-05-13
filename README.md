# qq_codex

QQ single-chat bridge for controlling local Codex sessions on Windows.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

The bridge lets a QQ official bot receive commands from an allowlisted single-chat user, run or resume a configured Codex session, and reply with status/results. It also includes an experimental Windows UIAutomation watcher for forwarding visible Codex Desktop approval prompts to QQ.

## Features

- QQ official bot single-chat command gateway.
- Session listing from local Codex session metadata.
- Run prompts against a session by alias, title, or short session id.
- Task status tracking with `/status <task_id>`.
- Local storage report with `/bridge storage`.
- Hide/unhide noisy sessions from `/codex list`.
- Experimental Codex Desktop UI approval forwarding with short replies:
  - `A` allows the current UI approval once.
  - `B` allows the current UI approval and remembers the same command pattern when Codex Desktop exposes that option.
  - `C` rejects or skips the current UI approval.
  - When multiple approvals are visible, reply with numbered choices such as `A1`, `B1`, `C1`, `A2`, `B2`, `C2`.

## UI approval flow

When Codex Desktop shows a visible approval prompt, the bridge polls it with Windows UIAutomation and sends a QQ message like:

```text
Codex UI approval: Engineering work

<approval prompt and command>

A = allow once
B = allow once and remember similar commands
C = reject / skip
```

If multiple approval prompts are visible at the same time, the bridge adds stable in-memory numbers:

```text
Codex UI approval: Engineering work #1

A1 = allow once
B1 = allow once and remember similar commands
C1 = reject / skip
```

```text
Codex UI approval: Paper writing #2

A2 = allow once
B2 = allow once and remember similar commands
C2 = reject / skip
```

Unnumbered `A`, `B`, or `C` only works when there is exactly one visible approval. If there are multiple pending approvals, the bridge asks for a numbered reply so the wrong window is not approved by accident.

The older explicit commands still work for compatibility:

```text
/approve ui-...
/approve-always ui-...
/cancel ui-...
```

## Safety

Do not commit local credentials or runtime state.

Ignored by default:

- `.env`
- `config/*.json`
- `logs/*`
- generated `.docx`, `.pptx`, and preview files

Commit only the example config files:

- `.env.example`
- `config/sessions.example.json`
- `config/policy.example.json`

## Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Copy local config files:

```powershell
Copy-Item .env.example .env
Copy-Item config\sessions.example.json config\sessions.json
Copy-Item config\policy.example.json config\policy.json
```

Fill `.env` locally:

```text
QQ_APP_ID=
QQ_APP_SECRET=
QQ_ALLOWED_OPENIDS=

SESSIONS_FILE=config/sessions.json
POLICY_FILE=config/policy.json
CODEX_CMD=%APPDATA%\npm\codex.cmd
CODEX_TIMEOUT_SECONDS=420
```

## Commands

```text
/help
/codex list
/codex list all
/codex <alias|title|short_id> <prompt>
/codex last <prompt>
/codex hide <alias|short_id>
/codex unhide <alias|short_id>
/status <task_id>
/status ui
/approve <task_id>
/approve ui-...
/approve-always ui-...
/cancel <task_id>
/cancel ui-...
/bridge storage
A
B
C
A1
B1
C1
```

## Run

Listen for one message and print your QQ single-chat openid:

```powershell
python -m src.main --listen-openid
```

Run the bridge:

```powershell
python -u -m src.main --serve
```

Run local command parsing without QQ:

```powershell
python -m src.main --local "/codex list"
```

## Tests

```powershell
python -m unittest discover -s tests
```
