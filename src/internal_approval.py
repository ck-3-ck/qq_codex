from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INTERNAL_APPROVAL_DIR = ROOT / "logs" / "internal_approvals"


@dataclass(frozen=True)
class InternalApprovalRequest:
    approval_id: str
    task_id: str
    openid: str
    display_ref: str
    message_id: str
    cwd: str
    tool_name: str
    tool_input: dict[str, Any]
    created_at: str


def new_internal_approval_id(task_id: str) -> str:
    return f"perm-{task_id}-{uuid.uuid4().hex[:6]}"


def request_path(approval_id: str) -> Path:
    return INTERNAL_APPROVAL_DIR / f"{approval_id}.request.json"


def decision_path(approval_id: str) -> Path:
    return INTERNAL_APPROVAL_DIR / f"{approval_id}.decision.json"


def save_request(request: InternalApprovalRequest) -> None:
    INTERNAL_APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    request_path(request.approval_id).write_text(
        json.dumps(request.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_request(approval_id: str) -> InternalApprovalRequest | None:
    path = request_path(approval_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return InternalApprovalRequest(
            approval_id=str(data["approval_id"]),
            task_id=str(data["task_id"]),
            openid=str(data["openid"]),
            display_ref=str(data["display_ref"]),
            message_id=str(data["message_id"]),
            cwd=str(data["cwd"]),
            tool_name=str(data["tool_name"]),
            tool_input=data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {},
            created_at=str(data["created_at"]),
        )
    except KeyError:
        return None


def write_decision(approval_id: str, approved: bool, openid: str) -> None:
    INTERNAL_APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "approval_id": approval_id,
        "approved": approved,
        "openid": openid,
        "decided_at": datetime.now().isoformat(timespec="seconds"),
    }
    decision_path(approval_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_decision(approval_id: str) -> dict[str, Any] | None:
    path = decision_path(approval_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def handle_internal_approval_command(approval_id: str, openid: str, approved: bool) -> str | None:
    if not approval_id.startswith("perm-"):
        return None

    request = load_request(approval_id)
    if not request or request.openid != openid:
        return f"未找到内部审批：{approval_id}"

    if load_decision(approval_id):
        return f"/codex {request.display_ref}\n这个内部审批已经处理过。"

    write_decision(approval_id, approved, openid)
    if approved:
        return f"/codex {request.display_ref}\n已允许，Codex 会继续执行。"
    return f"/codex {request.display_ref}\n已拒绝，Codex 会收到拒绝结果。"


def format_internal_approval_message(request: InternalApprovalRequest) -> str:
    detail = summarize_tool_input(request.tool_input)
    lines = [
        f"/codex {request.display_ref}",
        "Codex 请求执行需要确认的操作：",
        f"类型：{request.tool_name or 'unknown'}",
    ]
    if request.cwd:
        lines.append(f"目录：{request.cwd}")
    if detail:
        lines.append(detail)
    lines.extend(
        [
            f"/approve {request.approval_id} 允许",
            f"/cancel {request.approval_id} 拒绝",
        ]
    )
    return "\n".join(lines)


def summarize_tool_input(tool_input: dict[str, Any]) -> str:
    command = tool_input.get("command")
    if isinstance(command, str) and command.strip():
        return f"命令：{command.strip()[:1000]}"
    file_changes = tool_input.get("fileChanges") or tool_input.get("file_changes")
    if isinstance(file_changes, dict) and file_changes:
        names = ", ".join(str(name) for name in list(file_changes)[:8])
        return f"文件变更：{names}"
    path = tool_input.get("path") or tool_input.get("file_path")
    if isinstance(path, str) and path.strip():
        return f"目标：{path.strip()[:1000]}"
    reason = tool_input.get("reason")
    if isinstance(reason, str) and reason.strip():
        return f"原因：{reason.strip()[:1000]}"
    if not tool_input:
        return ""
    return "参数：" + json.dumps(tool_input, ensure_ascii=False)[:1000]
