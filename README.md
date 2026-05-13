# qq_codex

QQ single-chat bridge for controlling local Codex sessions on Windows.

The bridge lets a QQ official bot receive commands from an allowlisted single-chat user, run or resume a configured Codex session, and reply with status/results. It also includes an experimental Windows UIAutomation watcher for forwarding visible Codex Desktop approval prompts to QQ.

## Features

- QQ official bot single-chat command gateway.
- Session listing from local Codex session metadata.
- Run prompts against a session by alias, title, or short session id.
- Task status tracking with `/status <task_id>`.
- Local storage report with `/bridge storage`.
- Hide/unhide noisy sessions from `/codex list`.
- Experimental Codex Desktop UI approval forwarding:
  - `/approve ui-...`
  - `/approve-always ui-...`
  - `/cancel ui-...`

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
