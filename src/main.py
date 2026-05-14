from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .app_server_runner import AppServerRunner
from .codex_runner import CodexRunError, CodexRunner
from .command_parser import ParseError, help_text, parse_message
from .config_loader import ConfigError, load_dotenv, load_policy, load_sessions
from .internal_approval import (
    INTERNAL_APPROVAL_DIR,
    InternalApprovalRequest,
    format_internal_approval_message,
    load_decision,
    new_internal_approval_id,
    save_request,
    handle_internal_approval_command,
)
from .qq_client import QQBotClient
from .qq_gateway import QQGateway
from .security import SecurityError, assert_prompt_allowed, assert_sender_allowed
from .session_scanner import discover_sessions, format_session_listing
from .storage_report import build_storage_report
from .ui_approval import (
    UIApprovalError,
    UIApprovalRecord,
    approve_always_ui_approval,
    approve_ui_approval,
    cancel_ui_approval,
    detect_ui_approval,
    detect_ui_approvals,
    format_ui_approval_message,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_LOG = ROOT / "logs" / "audit.log"
TASKS_FILE = ROOT / "logs" / "tasks.json"
HIDDEN_SESSIONS_FILE = ROOT / "config" / "hidden_sessions.json"
UI_CURRENT_REFS = {"ui", "ui-current", "ui-latest"}
UI_CHOICE_ACTIONS = {"A": "approve", "B": "approve_always", "C": "cancel"}


class SessionResolveError(ValueError):
    pass


WRITE_TERMS = [
    "新建",
    "创建",
    "生成",
    "写入",
    "保存",
    "修改",
    "改动",
    "编辑",
    "替换",
    "插入",
    "导出",
    "追加",
    "word文档",
    ".docx",
    ".xlsx",
    ".pptx",
    "create",
    "write",
    "save",
    "modify",
    "edit",
    "export",
    "generate",
]

READ_ONLY_PHRASES = [
    "不要修改",
    "不修改",
    "不要改动",
    "不改动",
    "不要写入",
    "不写入",
    "只读",
    "read-only",
    "do not modify",
    "don't modify",
    "no changes",
]


@dataclass
class TaskRecord:
    task_id: str
    openid: str
    alias: str
    display_ref: str
    prompt: str
    status: str
    created_at: datetime
    updated_at: datetime
    result: str = ""
    error: str = ""

    def to_json(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "openid": self.openid,
            "alias": self.alias,
            "display_ref": self.display_ref,
            "prompt": self.prompt,
            "status": self.status,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_json(cls, data: dict[str, str]) -> "TaskRecord":
        return cls(
            task_id=data["task_id"],
            openid=data["openid"],
            alias=data["alias"],
            display_ref=data.get("display_ref", data["alias"]),
            prompt=data.get("prompt", ""),
            status=data.get("status", "unknown"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            result=data.get("result", ""),
            error=data.get("error", ""),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="QQ to Codex bridge")
    parser.add_argument("--local", help="Run one local command, e.g. /codex list")
    parser.add_argument(
        "--listen-openid",
        action="store_true",
        help="Connect to QQ WebSocket and print the next C2C sender openid.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the QQ single-chat command bridge.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    sessions_path = ROOT / os.environ.get("SESSIONS_FILE", "config/sessions.json")
    policy_path = ROOT / os.environ.get("POLICY_FILE", "config/policy.json")

    try:
        sessions = load_sessions(sessions_path)
        policy = load_policy(policy_path)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        print("Create config/sessions.json and config/policy.json from the .example files.", file=sys.stderr)
        return 2

    if args.local:
        return run_local(args.local, sessions, policy)
    if args.listen_openid:
        return asyncio.run(listen_openid())
    if args.serve:
        return asyncio.run(serve(sessions, policy))

    print("Use --local, --listen-openid, or --serve.")
    return 0


def run_local(raw: str, sessions, policy) -> int:
    try:
        command = parse_message(raw)
    except ParseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if command is None or command.name == "help":
        print(help_text())
        return 0
    if command.name == "codex_list":
        print(build_session_listing(sessions, include_all=command.args.get("mode") == "all"))
        return 0
    if command.name == "codex_hide":
        print(update_hidden_session(command.args["ref"], sessions, hide=True))
        return 0
    if command.name == "codex_unhide":
        print(update_hidden_session(command.args["ref"], sessions, hide=False))
        return 0
    if command.name == "bridge_storage":
        print(build_storage_report(ROOT))
        return 0
    if command.name == "codex_run":
        alias = command.args["alias"]
        try:
            alias = resolve_session_ref(alias, sessions)
        except SessionResolveError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        refresh_session_policy(alias, sessions)
        if alias not in sessions:
            print(f"Unknown session alias: {alias}", file=sys.stderr)
            return 2
        timeout = int(os.environ.get("CODEX_TIMEOUT_SECONDS", "420"))
        runner = CodexRunner(os.environ.get("CODEX_CMD"), timeout)
        try:
            result = runner.run(sessions[alias], command.args["prompt"], policy)
        except CodexRunError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(result.final_message)
        return 0
    print(f"Command {command.name} is not implemented in local mode.", file=sys.stderr)
    return 2


async def listen_openid() -> int:
    client = make_qq_client()
    gateway = QQGateway(client)
    print("Connected setup starting. Send one single-chat message to the bot now.", flush=True)
    message = await gateway.listen_c2c_once()
    print("Received C2C message.", flush=True)
    print(f"openid={message.openid}", flush=True)
    print(f"message_id={message.message_id}", flush=True)
    print(f"content={message.content}", flush=True)
    return 0


async def serve(sessions, policy) -> int:
    client = make_qq_client()
    gateway = QQGateway(client)
    runner = CodexRunner(os.environ.get("CODEX_CMD"), int(os.environ.get("CODEX_TIMEOUT_SECONDS", "420")))
    last_alias_by_openid: dict[str, str] = {}
    last_message_id_by_openid: dict[str, str] = {}
    tasks = load_tasks()
    ui_approvals: dict[str, UIApprovalRecord] = {}
    asyncio.create_task(watch_ui_approvals(policy, client, ui_approvals, last_message_id_by_openid))
    print("QQ-Codex bridge is running. Send /help in the bot single chat.", flush=True)
    while True:
        try:
            async for message in gateway.iter_c2c_messages():
                audit(f"received openid={message.openid} message_id={message.message_id} content={message.content!r}")
                last_message_id_by_openid[message.openid] = message.message_id
                try:
                    assert_sender_allowed(message.openid, policy)
                    response = await handle_c2c_command(
                        message.content,
                        message.openid,
                        message.message_id,
                        sessions,
                        policy,
                        runner,
                        last_alias_by_openid,
                        tasks,
                        client,
                        ui_approvals,
                    )
                except SecurityError as exc:
                    response = f"Permission denied: {exc}"
                except ParseError as exc:
                    response = str(exc)
                except Exception as exc:
                    response = f"Error: {exc}"
                if response:
                    audit(f"replying openid={message.openid} chars={len(response)} preview={response[:120]!r}")
                    for seq, chunk in enumerate(chunk_text(response), start=1):
                        client.send_c2c_message(message.openid, chunk, message.message_id, seq)
                    audit(f"reply sent openid={message.openid} chunks={len(chunk_text(response))}")
        except Exception as exc:
            audit(f"gateway loop error={exc!r}; reconnecting")
            await asyncio.sleep(5)
    return 0


async def handle_c2c_command(
    raw: str,
    openid: str,
    message_id: str,
    sessions,
    policy,
    runner: CodexRunner,
    last_alias_by_openid: dict[str, str],
    tasks: dict[str, TaskRecord],
    client: QQBotClient,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str:
    command = parse_message(raw)
    if command is None:
        return "Send /help for available commands."
    if command.name == "help":
        return help_text()
    if command.name == "ui_choice":
        return handle_ui_approval_choice(
            command.args["choice"],
            command.args["index"],
            openid,
            message_id,
            ui_approvals,
        )
    if command.name == "codex_list":
        return build_session_listing(sessions, include_all=command.args.get("mode") == "all")
    if command.name == "codex_hide":
        return update_hidden_session(command.args["ref"], sessions, hide=True)
    if command.name == "codex_unhide":
        return update_hidden_session(command.args["ref"], sessions, hide=False)
    if command.name == "bridge_storage":
        return build_storage_report(ROOT)
    if command.name == "codex_last":
        alias = last_alias_by_openid.get(openid)
        if not alias:
            return "No previous Codex session alias for this chat."
        return schedule_codex_task(
            openid,
            message_id,
            alias,
            alias,
            command.args["prompt"],
            sessions,
            policy,
            runner,
            tasks,
            client,
        )
    if command.name == "codex_run":
        alias = command.args["alias"]
        try:
            alias = resolve_session_ref(alias, sessions)
        except SessionResolveError as exc:
            return str(exc)
        refresh_session_policy(alias, sessions)
        if alias not in sessions:
            return f"Unknown session alias: {alias}"
        last_alias_by_openid[openid] = alias
        return schedule_codex_task(
            openid,
            message_id,
            alias,
            command.args["alias"],
            command.args["prompt"],
            sessions,
            policy,
            runner,
            tasks,
            client,
        )
    if command.name == "status":
        if command.args["task_id"] in UI_CURRENT_REFS:
            return status_ui_approval_command(command.args["task_id"], openid, message_id, ui_approvals)
        return format_status(command.args["task_id"], openid, tasks)
    if command.name == "approve":
        ui_response = approve_ui_approval_command(command.args["task_id"], openid, message_id, ui_approvals)
        if ui_response is not None:
            return ui_response
        internal_response = handle_internal_approval_command(command.args["task_id"], openid, approved=True)
        if internal_response is not None:
            return internal_response
        return approve_pending_task(
            command.args["task_id"],
            openid,
            message_id,
            sessions,
            policy,
            runner,
            tasks,
            client,
        )
    if command.name == "approve_always":
        ui_response = approve_always_ui_approval_command(command.args["task_id"], openid, message_id, ui_approvals)
        if ui_response is not None:
            return ui_response
        return "Only Codex UI approvals support /approve-always."
    if command.name == "cancel":
        ui_response = cancel_ui_approval_command(command.args["task_id"], openid, message_id, ui_approvals)
        if ui_response is not None:
            return ui_response
        internal_response = handle_internal_approval_command(command.args["task_id"], openid, approved=False)
        if internal_response is not None:
            return internal_response
        return cancel_pending_task(command.args["task_id"], openid, tasks)
    return f"Command {command.name} is not implemented."


def schedule_codex_task(
    openid: str,
    message_id: str,
    alias: str,
    display_ref: str,
    prompt: str,
    sessions,
    policy,
    runner: CodexRunner,
    tasks: dict[str, TaskRecord],
    client: QQBotClient,
) -> str:
    assert_prompt_allowed(prompt, policy)
    session = sessions[alias]
    approval_message = approval_prompt_message(openid, alias, display_ref, prompt, session, tasks)
    if approval_message:
        return approval_message

    task_id = create_task_record(openid, alias, display_ref, prompt, "running", tasks)
    asyncio.create_task(run_codex_task(task_id, message_id, sessions, policy, runner, tasks, client))
    audit(f"task scheduled task_id={task_id} alias={alias} openid={openid}")
    return ""


def create_task_record(
    openid: str,
    alias: str,
    display_ref: str,
    prompt: str,
    status: str,
    tasks: dict[str, TaskRecord],
) -> str:
    task_id = new_task_id()
    now = datetime.now()
    tasks[task_id] = TaskRecord(
        task_id=task_id,
        openid=openid,
        alias=alias,
        display_ref=display_ref,
        prompt=prompt,
        status=status,
        created_at=now,
        updated_at=now,
    )
    save_tasks(tasks)
    return task_id


def approval_prompt_message(
    openid: str,
    alias: str,
    display_ref: str,
    prompt: str,
    session,
    tasks: dict[str, TaskRecord],
) -> str:
    reason = write_approval_reason(prompt, session)
    if not reason:
        return ""
    if session.sandbox != "workspace-write":
        return f"/codex {display_ref}\n{reason}"

    task_id = create_task_record(openid, alias, display_ref, prompt, "pending_approval", tasks)
    audit(f"task pending_approval task_id={task_id} alias={alias} openid={openid} reason={reason!r}")
    return (
        f"/codex {display_ref}\n"
        f"需要确认：{reason}\n"
        f"/approve {task_id} 继续\n"
        f"/cancel {task_id} 取消"
    )


def write_approval_reason(prompt: str, session) -> str:
    if not looks_like_write_prompt(prompt):
        return ""
    if session.sandbox == "workspace-write" and session.source == "vscode":
        return ""
    if session.sandbox != "workspace-write":
        return "这个会话当前是只读，不能执行写入或修改文件的任务。"
    return "这条指令可能会写入或修改文件。"


def looks_like_write_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    if any(phrase in lowered for phrase in READ_ONLY_PHRASES):
        return False
    return any(term in lowered for term in WRITE_TERMS)


def approve_pending_task(
    task_id: str,
    openid: str,
    message_id: str,
    sessions,
    policy,
    runner: CodexRunner,
    tasks: dict[str, TaskRecord],
    client: QQBotClient,
) -> str:
    record = tasks.get(task_id)
    if not record or record.openid != openid:
        return f"未找到任务：{task_id}"
    if record.status != "pending_approval":
        return f"任务 {task_id} 当前状态是 {record.status}，不能批准。"
    try:
        alias = resolve_session_ref(record.alias, sessions)
    except SessionResolveError as exc:
        return str(exc)
    refresh_session_policy(alias, sessions)
    if alias not in sessions:
        return f"Unknown session alias: {alias}"
    session = sessions[alias]
    if session.sandbox != "workspace-write":
        return "这个会话当前是只读，不能执行写入或修改文件的任务。"

    record.alias = alias
    record.status = "running"
    record.updated_at = datetime.now()
    save_tasks(tasks)
    asyncio.create_task(run_codex_task(task_id, message_id, sessions, policy, runner, tasks, client))
    audit(f"task approved task_id={task_id} alias={alias} openid={openid}")
    return ""


def cancel_pending_task(task_id: str, openid: str, tasks: dict[str, TaskRecord]) -> str:
    record = tasks.get(task_id)
    if not record or record.openid != openid:
        return f"未找到任务：{task_id}"
    if record.status != "pending_approval":
        return f"任务 {task_id} 当前状态是 {record.status}，不能取消。"
    record.status = "canceled"
    record.updated_at = datetime.now()
    save_tasks(tasks)
    audit(f"task canceled task_id={task_id} alias={record.alias} openid={openid}")
    return f"/codex {record.display_ref}\n已取消。"


async def watch_ui_approvals(
    policy,
    client: QQBotClient,
    ui_approvals: dict[str, UIApprovalRecord],
    last_message_id_by_openid: dict[str, str],
) -> None:
    if os.environ.get("CODEX_QQ_UI_APPROVAL_WATCH", "1") == "0":
        audit("ui approval watcher disabled")
        return
    if not policy.allowed_openids:
        audit("ui approval watcher disabled: no allowed openids")
        return
    poll_seconds = float(os.environ.get("CODEX_QQ_UI_APPROVAL_POLL_SECONDS", "3"))
    sent_signatures: set[str] = set()
    send_attempts: dict[str, float] = {}
    while True:
        try:
            approvals = await asyncio.to_thread(detect_ui_approvals)
            active_signatures = {str(item.get("signature") or "") for item in approvals}
            active_signatures.discard("")
            prune_stale_ui_approvals(ui_approvals, active_signatures)
            sent_signatures.intersection_update(active_signatures)
            send_attempts = {key: value for key, value in send_attempts.items() if key in active_signatures}
            if not approvals:
                await asyncio.sleep(poll_seconds)
                continue
            openid = sorted(policy.allowed_openids)[0]
            for data in approvals:
                signature = str(data.get("signature") or "")
                if not signature or signature in sent_signatures:
                    continue
                record = record_ui_approval(
                    data,
                    openid,
                    last_message_id_by_openid.get(openid, ""),
                    ui_approvals,
                )
                if record is None:
                    continue
                now = time.time()
                if now - send_attempts.get(signature, 0) < 15:
                    continue
                send_attempts[signature] = now
                audit(f"ui approval detected approval_id={record.approval_id} signature={signature[:12]}")
                try:
                    active_records = active_ui_approval_records(openid, ui_approvals)
                    await asyncio.to_thread(
                        client.send_c2c_message,
                        openid,
                        format_ui_approval_message(record, numbered=len(active_records) > 1),
                        record.message_id or None,
                        900 + len(ui_approvals),
                    )
                    sent_signatures.add(signature)
                    audit(f"ui approval sent approval_id={record.approval_id} openid={openid}")
                except Exception as exc:
                    audit(f"ui approval send failed approval_id={record.approval_id} error={exc!r}")
        except Exception as exc:
            audit(f"ui approval watcher error={exc!r}")
        await asyncio.sleep(poll_seconds)


def record_ui_approval(
    data: dict,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> UIApprovalRecord | None:
    signature = str(data.get("signature") or "")
    if not signature:
        return None
    for record in ui_approvals.values():
        if record.signature == signature and record.openid == openid and not record.resolved:
            if message_id:
                record.message_id = message_id
            record.prompt = str(data.get("prompt") or record.prompt)
            record.window_handle = int(data.get("window_handle") or record.window_handle or 0)
            record.window_name = str(data.get("window_name") or record.window_name)
            record.conversation_title = str(data.get("conversation_title") or record.conversation_title)
            record.can_approve_always = bool(data.get("can_approve_always"))
            ensure_ui_choice_index(record, ui_approvals)
            return record
    approval_id = "ui-" + new_task_id()
    record = UIApprovalRecord(
        approval_id=approval_id,
        signature=signature,
        prompt=str(data.get("prompt") or ""),
        openid=openid,
        message_id=message_id,
        created_at=datetime.now(),
        window_handle=int(data.get("window_handle") or 0),
        window_name=str(data.get("window_name") or ""),
        conversation_title=str(data.get("conversation_title") or ""),
        can_approve_always=bool(data.get("can_approve_always")),
    )
    ui_approvals[approval_id] = record
    ensure_ui_choice_index(record, ui_approvals)
    return record


def ensure_ui_choice_index(record: UIApprovalRecord, ui_approvals: dict[str, UIApprovalRecord]) -> None:
    if record.choice_index > 0:
        return
    used = {
        other.choice_index
        for other in ui_approvals.values()
        if other.approval_id != record.approval_id
        and other.openid == record.openid
        and not other.resolved
        and other.choice_index > 0
    }
    index = 1
    while index in used:
        index += 1
    record.choice_index = index


def active_ui_approval_records(openid: str, ui_approvals: dict[str, UIApprovalRecord]) -> list[UIApprovalRecord]:
    records = [
        record
        for record in ui_approvals.values()
        if record.openid == openid and not record.resolved
    ]
    for record in records:
        ensure_ui_choice_index(record, ui_approvals)
    return sorted(records, key=lambda item: (item.choice_index or 999999, item.created_at, item.approval_id))


def prune_stale_ui_approvals(ui_approvals: dict[str, UIApprovalRecord], active_signatures: set[str]) -> None:
    for record in ui_approvals.values():
        if record.resolved:
            continue
        if record.signature not in active_signatures:
            record.resolved = True
            audit(f"ui approval expired approval_id={record.approval_id} signature={record.signature[:12]}")


def format_ui_approval_messages(records: list[UIApprovalRecord]) -> str:
    numbered = len(records) > 1
    return "\n\n".join(format_ui_approval_message(record, numbered=numbered) for record in records)


def format_multiple_ui_choice_prompt(records: list[UIApprovalRecord]) -> str:
    choices = " 或 ".join(f"A{record.choice_index}/B{record.choice_index}/C{record.choice_index}" for record in records)
    return f"当前有多个待审批，请回复 {choices}。"


def handle_ui_approval_choice(
    choice: str,
    index: str,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str:
    if choice not in UI_CHOICE_ACTIONS:
        return "Unknown approval choice."
    try:
        records = current_ui_approval_records(openid, message_id, ui_approvals)
    except UIApprovalError as exc:
        return f"UI approval check failed: {exc}"
    records = [record for record in records if record.openid == openid and not record.resolved]
    if not records:
        return "No visible Codex UI approval request."
    for record in records:
        ensure_ui_choice_index(record, ui_approvals)

    if index:
        choice_index = int(index)
        record = next((item for item in records if item.choice_index == choice_index), None)
        if record is None:
            return f"审批 #{choice_index} 已不存在或已过期，请发送 /status ui 查看当前待审批。"
    else:
        if len(records) > 1:
            return format_multiple_ui_choice_prompt(records)
        record = records[0]

    action = UI_CHOICE_ACTIONS[choice]
    if action == "approve":
        return approve_ui_approval_command(record.approval_id, openid, message_id, ui_approvals) or ""
    if action == "approve_always":
        return approve_always_ui_approval_command(record.approval_id, openid, message_id, ui_approvals) or ""
    return cancel_ui_approval_command(record.approval_id, openid, message_id, ui_approvals) or ""


def current_ui_approval_record(
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> UIApprovalRecord | None:
    records = current_ui_approval_records(openid, message_id, ui_approvals)
    if not records:
        return None
    if len(records) > 1:
        raise UIApprovalError(format_multiple_ui_choice_prompt(records))
    return records[0]


def current_ui_approval_records(
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> list[UIApprovalRecord]:
    records: list[UIApprovalRecord] = []
    approvals = detect_ui_approvals()
    active_signatures = {str(item.get("signature") or "") for item in approvals}
    active_signatures.discard("")
    prune_stale_ui_approvals(ui_approvals, active_signatures)
    for data in approvals:
        record = record_ui_approval(data, openid, message_id, ui_approvals)
        if record is not None:
            records.append(record)
    return records


def status_ui_approval_command(
    approval_id: str,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str:
    if approval_id in UI_CURRENT_REFS:
        try:
            records = current_ui_approval_records(openid, message_id, ui_approvals)
        except UIApprovalError as exc:
            return f"UI approval check failed: {exc}"
        if not records:
            return "No visible Codex UI approval request."
        return format_ui_approval_messages(records)
    record = ui_approvals.get(approval_id)
    if not record or record.openid != openid:
        return f"UI approval not found: {approval_id}"
    if record.resolved:
        return f"UI approval already resolved: {approval_id}"
    return format_ui_approval_message(
        record,
        numbered=len(active_ui_approval_records(openid, ui_approvals)) > 1,
    )


def approve_ui_approval_command(
    approval_id: str,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str | None:
    if approval_id in UI_CURRENT_REFS:
        try:
            record = current_ui_approval_record(openid, message_id, ui_approvals)
        except UIApprovalError as exc:
            return f"UI approval check failed: {exc}"
        if record is None:
            return "No visible Codex UI approval request."
    elif approval_id.startswith("ui-"):
        record = ui_approvals.get(approval_id)
        if not record or record.openid != openid:
            return f"UI approval not found: {approval_id}"
    else:
        return None
    if record.resolved:
        return "这个 UI 审批已经处理过。"
    try:
        result = approve_ui_approval(record.signature)
    except UIApprovalError as exc:
        return f"UI 审批失败：{exc}"
    if not result.get("ok"):
        return f"UI 审批失败：{result.get('error') or '未知错误'}"
    record.resolved = True
    audit(f"ui approval approved approval_id={record.approval_id} openid={openid}")
    return f"Approved Codex UI request: {record.approval_id}"


def approve_always_ui_approval_command(
    approval_id: str,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str | None:
    if approval_id in UI_CURRENT_REFS:
        try:
            record = current_ui_approval_record(openid, message_id, ui_approvals)
        except UIApprovalError as exc:
            return f"UI approval check failed: {exc}"
        if record is None:
            return "No visible Codex UI approval request."
    elif approval_id.startswith("ui-"):
        record = ui_approvals.get(approval_id)
        if not record or record.openid != openid:
            return f"UI approval not found: {approval_id}"
    else:
        return None
    if record.resolved:
        return "This UI approval has already been handled."
    if not record.can_approve_always:
        return "This visible UI approval does not expose the remember option."
    try:
        result = approve_always_ui_approval(record.signature)
    except UIApprovalError as exc:
        return f"UI approval failed: {exc}"
    if not result.get("ok"):
        return f"UI approval failed: {result.get('error') or 'unknown error'}"
    record.resolved = True
    audit(f"ui approval approved_always approval_id={record.approval_id} openid={openid}")
    return f"Approved and remembered Codex UI request: {record.approval_id}"


def cancel_ui_approval_command(
    approval_id: str,
    openid: str,
    message_id: str,
    ui_approvals: dict[str, UIApprovalRecord],
) -> str | None:
    if approval_id in UI_CURRENT_REFS:
        try:
            record = current_ui_approval_record(openid, message_id, ui_approvals)
        except UIApprovalError as exc:
            return f"UI approval check failed: {exc}"
        if record is None:
            return "No visible Codex UI approval request."
    elif approval_id.startswith("ui-"):
        record = ui_approvals.get(approval_id)
        if not record or record.openid != openid:
            return f"UI approval not found: {approval_id}"
    else:
        return None
    if record.resolved:
        return "这个 UI 审批已经处理过。"
    try:
        result = cancel_ui_approval(record.signature)
    except UIApprovalError as exc:
        return f"UI 审批失败：{exc}"
    if not result.get("ok"):
        return f"UI 审批失败：{result.get('error') or '未知错误'}"
    record.resolved = True
    audit(f"ui approval canceled approval_id={record.approval_id} openid={openid}")
    return f"Canceled Codex UI request: {record.approval_id}"


async def run_codex_task(
    task_id: str,
    message_id: str,
    sessions,
    policy,
    runner: CodexRunner,
    tasks: dict[str, TaskRecord],
    client: QQBotClient,
) -> None:
    record = tasks[task_id]
    try:
        session = sessions[record.alias]
        if use_app_server_runner(session):
            app_runner = AppServerRunner(os.environ.get("CODEX_CMD"), int(os.environ.get("CODEX_TIMEOUT_SECONDS", "420")))
            result = await asyncio.to_thread(
                app_runner.run,
                session,
                record.prompt,
                policy,
                lambda method, params: wait_for_internal_approval(record, message_id, client, method, params),
            )
        else:
            result = await asyncio.to_thread(
                runner.run,
                session,
                record.prompt,
                policy,
                task_id,
                record.openid,
                message_id,
                record.display_ref,
            )
        record.result = result.final_message
        record.status = "done"
        record.updated_at = datetime.now()
        save_tasks(tasks)
        audit(f"task done task_id={task_id} chars={len(record.result)} preview={record.result[:120]!r}")
        response = format_task_result(record)
        chunks = chunk_text(response)
        if len(chunks) > 4:
            chunks = chunks[:4]
            chunks[-1] += f"\n\n结果较长，/status {task_id}"
        try:
            for offset, chunk in enumerate(chunks, start=1):
                await asyncio.to_thread(client.send_c2c_message, record.openid, chunk, message_id, offset)
            audit(f"task reply sent task_id={task_id} chunks={len(chunks)}")
        except Exception as send_exc:
            audit(f"task reply failed task_id={task_id} error={send_exc!r}")
    except Exception as exc:
        record.error = str(exc)
        record.status = "error"
        record.updated_at = datetime.now()
        save_tasks(tasks)
        audit(f"task error task_id={task_id} error={record.error!r}")
        try:
            await asyncio.to_thread(client.send_c2c_message, record.openid, record.error, message_id, 1)
        except Exception as send_exc:
            audit(f"task error reply failed task_id={task_id} error={send_exc!r}")


def use_app_server_runner(session) -> bool:
    return session.sandbox == "workspace-write" and session.source == "vscode"


def wait_for_internal_approval(
    record: TaskRecord,
    message_id: str,
    client: QQBotClient,
    method: str,
    params: dict,
) -> bool:
    approval_id = new_internal_approval_id(record.task_id)
    request = InternalApprovalRequest(
        approval_id=approval_id,
        task_id=record.task_id,
        openid=record.openid,
        display_ref=record.display_ref,
        message_id=message_id,
        cwd=str(params.get("cwd") or ""),
        tool_name=method,
        tool_input=params,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    save_request(request)
    audit(f"internal approval requested approval_id={approval_id} task_id={record.task_id} method={method}")
    try:
        seq = 50 + count_task_internal_approvals(record.task_id)
        client.send_c2c_message(record.openid, format_internal_approval_message(request), message_id, seq)
    except Exception as exc:
        audit(f"internal approval request send failed approval_id={approval_id} error={exc!r}")
        return False

    timeout = int(os.environ.get("CODEX_QQ_APPROVAL_TIMEOUT_SECONDS", "600"))
    deadline = time.time() + max(timeout, 1)
    while time.time() < deadline:
        decision = load_decision(approval_id)
        if decision is not None:
            approved = bool(decision.get("approved"))
            audit(f"internal approval decided approval_id={approval_id} approved={approved}")
            return approved
        time.sleep(1)
    audit(f"internal approval timed out approval_id={approval_id}")
    return False


def count_task_internal_approvals(task_id: str) -> int:
    if not INTERNAL_APPROVAL_DIR.exists():
        return 0
    return len(list(INTERNAL_APPROVAL_DIR.glob(f"perm-{task_id}-*.request.json")))


def format_task_result(record: TaskRecord) -> str:
    ref = record.display_ref or record.alias
    return f"/codex {ref}\n{record.result}"


def format_status(task_id: str, openid: str, tasks: dict[str, TaskRecord]) -> str:
    record = tasks.get(task_id)
    if not record or record.openid != openid:
        return f"未找到任务：{task_id}"
    if record.status == "running":
        elapsed = int((datetime.now() - record.created_at).total_seconds())
        return f"任务 {task_id} 正在执行，已用时 {elapsed} 秒。"
    if record.status == "pending_approval":
        return f"/codex {record.display_ref}\n等待确认：/approve {task_id} 或 /cancel {task_id}"
    if record.status == "canceled":
        return f"/codex {record.display_ref}\n已取消。"
    if record.status == "error":
        return record.error
    if record.status == "done":
        return format_task_result(record)
    return f"任务 {task_id} 状态：{record.status}"


def new_task_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def load_tasks() -> dict[str, TaskRecord]:
    if not TASKS_FILE.exists():
        return {}
    try:
        raw = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    tasks: dict[str, TaskRecord] = {}
    for task_id, item in raw.items():
        if not isinstance(item, dict):
            continue
        try:
            tasks[task_id] = TaskRecord.from_json(item)
        except (KeyError, ValueError):
            continue
    return tasks


def save_tasks(tasks: dict[str, TaskRecord]) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {task_id: task.to_json() for task_id, task in tasks.items()}
    TASKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_qq_client() -> QQBotClient:
    app_id = os.environ.get("QQ_APP_ID", "").strip()
    app_secret = os.environ.get("QQ_APP_SECRET", "").strip()
    if not app_id or not app_secret or app_secret == "PASTE_NEW_APP_SECRET_HERE":
        raise RuntimeError("Set QQ_APP_ID and QQ_APP_SECRET in .env first.")
    return QQBotClient(app_id, app_secret)


def chunk_text(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + limit])
        start += limit
    return chunks


def build_session_listing(sessions, include_all: bool = False) -> str:
    hidden_ids = load_hidden_session_ids()
    discovered = discover_sessions(limit=80 if include_all else 30, include_archived=include_all)
    if not include_all:
        discovered = [
            session
            for session in discovered
            if session.session_id not in hidden_ids and session.source != "exec"
        ]
    alias_by_id = {session.session_id: alias for alias, session in sessions.items()}
    shown_hidden_ids = hidden_ids if include_all else set()
    return format_session_listing(discovered, alias_by_id, shown_hidden_ids)


def update_hidden_session(ref: str, sessions, hide: bool) -> str:
    resolved = resolve_visibility_ref(ref, sessions)
    if isinstance(resolved, str):
        return resolved
    session_id, label = resolved
    hidden_ids = load_hidden_session_ids()
    short_id = session_id[:8]
    if hide:
        if session_id in hidden_ids:
            return f"Already hidden: {label} ({short_id})"
        hidden_ids.add(session_id)
        save_hidden_session_ids(hidden_ids)
        return f"Hidden from /codex list: {label} ({short_id})"
    if session_id not in hidden_ids:
        return f"Not hidden: {label} ({short_id})"
    hidden_ids.remove(session_id)
    save_hidden_session_ids(hidden_ids)
    return f"Shown in /codex list again: {label} ({short_id})"


def resolve_visibility_ref(ref: str, sessions) -> tuple[str, str] | str:
    value = ref.strip()
    discovered = discover_sessions(limit=200, include_archived=True)
    discovered_by_id = {session.session_id: session for session in discovered}
    matches: dict[str, str] = {}

    if value in sessions:
        session = sessions[value]
        found = discovered_by_id.get(session.session_id)
        matches[session.session_id] = found.title if found else session.alias

    for alias, session in sessions.items():
        if session.session_id.startswith(value):
            found = discovered_by_id.get(session.session_id)
            matches[session.session_id] = found.title if found else alias

    for session in discovered:
        if session.session_id.startswith(value):
            matches[session.session_id] = session.title

    if not matches:
        return f"No matching session: {ref}"
    if len(matches) > 1:
        choices = ", ".join(f"{session_id[:8]}:{label}" for session_id, label in sorted(matches.items())[:8])
        return f"Multiple sessions match {ref}: {choices}"
    session_id, label = next(iter(matches.items()))
    return session_id, label


def load_hidden_session_ids() -> set[str]:
    if not HIDDEN_SESSIONS_FILE.exists():
        return set()
    try:
        raw = json.loads(HIDDEN_SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(raw, list):
        return {str(item) for item in raw if str(item).strip()}
    if not isinstance(raw, dict):
        return set()
    values = raw.get("hidden_session_ids", [])
    if not isinstance(values, list):
        return set()
    return {str(item) for item in values if str(item).strip()}


def save_hidden_session_ids(hidden_ids: set[str]) -> None:
    HIDDEN_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"hidden_session_ids": sorted(hidden_ids)}
    HIDDEN_SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_session_ref(value: str, sessions) -> str:
    value = value.strip()
    if value in sessions:
        return value
    matches = [alias for alias, session in sessions.items() if session.session_id.startswith(value)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SessionResolveError(format_duplicate_session_message(value, []))

    discovered = discover_sessions(limit=200)
    discovered_matches = [item for item in discovered if item.session_id.startswith(value)]
    if len(discovered_matches) == 1:
        return add_dynamic_session_alias(discovered_matches[0], sessions)
    if len(discovered_matches) > 1:
        raise SessionResolveError(format_duplicate_session_message(value, discovered_matches))

    hidden_ids = load_hidden_session_ids()
    title_matches = [
        item
        for item in discovered
        if item.title == value
        and item.session_id not in hidden_ids
        and not item.archived
        and item.source != "exec"
    ]
    if len(title_matches) == 1:
        return add_dynamic_session_alias(title_matches[0], sessions)
    if len(title_matches) > 1:
        raise SessionResolveError(format_duplicate_session_message(value, title_matches))
    return value


def add_dynamic_session_alias(found, sessions) -> str:
    dynamic_alias = found.short_id
    if dynamic_alias not in sessions:
        from .config_loader import SessionConfig

        sessions[dynamic_alias] = SessionConfig(
            dynamic_alias,
            found.session_id,
            found.cwd,
            sandbox_for_source(found.source),
            found.source,
        )
    return dynamic_alias


def refresh_session_policy(alias: str, sessions) -> None:
    session = sessions.get(alias)
    if not session:
        return
    discovered = discover_sessions(limit=200, include_archived=True)
    found = next((item for item in discovered if item.session_id == session.session_id), None)
    if not found:
        return

    from .config_loader import SessionConfig

    sessions[alias] = SessionConfig(
        alias=session.alias,
        session_id=session.session_id,
        cwd=found.cwd or session.cwd,
        sandbox=sandbox_for_source(found.source),
        source=found.source,
    )


def sandbox_for_source(source: str) -> str:
    if source == "vscode":
        return "workspace-write"
    return "read-only"


def format_duplicate_session_message(value: str, matches) -> str:
    if not matches:
        return f"Multiple configured sessions match: {value}. Use a longer session id."
    lines = [f"Multiple sessions match {value}. Use short id instead:"]
    for item in matches[:8]:
        lines.append(f"- {item.title} ({item.short_id}) [{item.project_name}]")
    if len(matches) > 8:
        lines.append(f"... {len(matches) - 8} more")
    return "\n".join(lines)


def audit(line: str) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {line}\n")


if __name__ == "__main__":
    raise SystemExit(main())
