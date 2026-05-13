from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .codex_runner import CodexResult
from .config_loader import PolicyConfig, SessionConfig
from .security import assert_prompt_allowed


class AppServerRunError(RuntimeError):
    pass


ApprovalHandler = Callable[[str, dict[str, Any]], bool]


@dataclass
class AppServerState:
    next_id: int = 1
    thread_ready: bool = False
    turn_started: bool = False
    final_message: str = ""
    last_error: str = ""


class AppServerRunner:
    def __init__(self, codex_cmd: str | None = None, timeout_seconds: int = 420):
        appdata = os.environ.get("APPDATA", "")
        self.codex_cmd = os.path.expandvars(codex_cmd or r"%APPDATA%\npm\codex.cmd")
        self.node_dir = r"C:\Program Files\nodejs"
        self.npm_dir = str(Path(appdata) / "npm") if appdata else ""
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        session: SessionConfig,
        prompt: str,
        policy: PolicyConfig,
        approval_handler: ApprovalHandler,
    ) -> CodexResult:
        if session.sandbox != "workspace-write" or session.source != "vscode":
            raise AppServerRunError("App-server runner is only enabled for UI workspace-write sessions.")
        if not Path(session.cwd).exists():
            raise AppServerRunError(f"Session cwd does not exist: {session.cwd}")
        assert_prompt_allowed(prompt, policy)

        env = os.environ.copy()
        prefix = [self.node_dir]
        if self.npm_dir:
            prefix.append(self.npm_dir)
        env["Path"] = ";".join(prefix + [env.get("Path", "")])
        env["PYTHONUTF8"] = "1"

        proc = subprocess.Popen(
            [self.codex_cmd, "app-server", "--listen", "stdio://"],
            cwd=session.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(target=drain_stderr, args=(proc, stderr_lines), daemon=True)
        stderr_thread.start()

        state = AppServerState()
        pending: dict[int, str] = {}

        try:
            initialize_id = send_request(
                proc,
                state,
                "initialize",
                {
                    "clientInfo": {"name": "qq-bridge", "title": "QQ Bridge", "version": "0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            pending[initialize_id] = "initialize"
            deadline = time.time() + self.timeout_seconds
            while time.time() < deadline:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                event = json.loads(line)
                if "id" in event and "method" not in event:
                    handle_response(proc, state, pending, event, session, prompt)
                    continue
                method = event.get("method")
                if method in APPROVAL_METHODS:
                    approved = approval_handler(method, event.get("params") or {})
                    send_approval_response(proc, event, approved)
                    continue
                handle_notification(state, event)
                if method == "turn/completed":
                    return CodexResult(0, state.final_message.strip(), "", "\n".join(stderr_lines))
            raise AppServerRunError(f"Codex app-server timed out after {self.timeout_seconds}s")
        finally:
            if proc.poll() is None:
                proc.kill()


APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "execCommandApproval",
    "applyPatchApproval",
}


def drain_stderr(proc: subprocess.Popen, lines: list[str]) -> None:
    if not proc.stderr:
        return
    for line in proc.stderr:
        if len(lines) < 200:
            lines.append(line.rstrip("\n"))


def send_request(proc: subprocess.Popen, state: AppServerState, method: str, params: dict[str, Any]) -> int:
    request_id = state.next_id
    state.next_id += 1
    send_json(proc, {"id": request_id, "method": method, "params": params})
    return request_id


def send_json(proc: subprocess.Popen, payload: dict[str, Any]) -> None:
    if not proc.stdin:
        raise AppServerRunError("Codex app-server stdin is closed.")
    proc.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def handle_response(
    proc: subprocess.Popen,
    state: AppServerState,
    pending: dict[int, str],
    event: dict[str, Any],
    session: SessionConfig,
    prompt: str,
) -> None:
    request_id = event.get("id")
    label = pending.pop(request_id, "")
    if "error" in event:
        raise AppServerRunError(json.dumps(event["error"], ensure_ascii=False))
    if label == "initialize":
        resume_id = send_request(
            proc,
            state,
            "thread/resume",
            {
                "threadId": session.session_id,
                "cwd": session.cwd,
                "approvalPolicy": "untrusted",
                "approvalsReviewer": "user",
                "sandbox": session.sandbox,
                "excludeTurns": True,
                "persistExtendedHistory": False,
            },
        )
        pending[resume_id] = "thread_resume"
    elif label == "thread_resume":
        start_turn(proc, state, pending, session, prompt)
    elif label == "turn_start":
        state.turn_started = True


def start_turn(
    proc: subprocess.Popen,
    state: AppServerState,
    pending: dict[int, str],
    session: SessionConfig,
    prompt: str,
) -> None:
    if state.turn_started:
        return
    turn_id = send_request(
        proc,
        state,
        "turn/start",
        {
            "threadId": session.session_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
            "cwd": session.cwd,
            "approvalPolicy": "untrusted",
            "approvalsReviewer": "user",
        },
    )
    pending[turn_id] = "turn_start"
    state.turn_started = True


def handle_notification(state: AppServerState, event: dict[str, Any]) -> None:
    method = event.get("method")
    params = event.get("params") or {}
    if method == "item/agentMessage/delta":
        state.final_message += str(params.get("delta") or "")
    elif method == "item/completed":
        item = params.get("item") or {}
        if item.get("type") == "agentMessage" and item.get("text"):
            state.final_message = str(item["text"])
    elif method == "error":
        error = params.get("error") or {}
        state.last_error = str(error.get("message") or error)


def send_approval_response(proc: subprocess.Popen, event: dict[str, Any], approved: bool) -> None:
    method = event.get("method")
    request_id = event.get("id")
    if method == "item/commandExecution/requestApproval":
        decision: Any = "accept" if approved else "cancel"
    elif method == "item/fileChange/requestApproval":
        decision = "accept" if approved else "cancel"
    elif method == "item/permissions/requestApproval":
        params = event.get("params") or {}
        permissions = params.get("permissions") if approved else {"network": None, "fileSystem": None}
        send_json(proc, {"id": request_id, "result": {"permissions": permissions, "scope": "turn"}})
        return
    elif method == "execCommandApproval":
        decision = "approved" if approved else "denied"
    elif method == "applyPatchApproval":
        decision = "approved" if approved else "denied"
    else:
        decision = "cancel"
    send_json(proc, {"id": request_id, "result": {"decision": decision}})
