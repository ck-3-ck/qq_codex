from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.internal_approval import (  # noqa: E402
    InternalApprovalRequest,
    format_internal_approval_message,
    load_decision,
    new_internal_approval_id,
    request_path,
    save_request,
)
from src.qq_client import QQBotClient  # noqa: E402


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            payload = {}
        approval_id = build_request(payload)
        decision = wait_for_decision(approval_id)
        emit_decision(decision)
        return 0
    except Exception as exc:
        print(f"approval hook failed: {exc}", file=sys.stderr)
        emit_decision(False, f"QQ approval hook failed: {exc}")
        return 0


def build_request(payload: dict[str, Any]) -> str:
    task_id = os.environ.get("CODEX_QQ_TASK_ID", "").strip() or "unknown"
    approval_id = new_internal_approval_id(task_id)
    request = InternalApprovalRequest(
        approval_id=approval_id,
        task_id=task_id,
        openid=os.environ.get("CODEX_QQ_OPENID", "").strip(),
        display_ref=os.environ.get("CODEX_QQ_DISPLAY_REF", "").strip() or task_id,
        message_id=os.environ.get("CODEX_QQ_MESSAGE_ID", "").strip(),
        cwd=str(payload.get("cwd") or ""),
        tool_name=str(payload.get("tool_name") or ""),
        tool_input=payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {},
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    save_request(request)
    maybe_send_qq_request(request)
    return approval_id


def maybe_send_qq_request(request: InternalApprovalRequest) -> None:
    if os.environ.get("CODEX_QQ_DISABLE_SEND") == "1":
        return
    app_id = os.environ.get("QQ_APP_ID", "").strip()
    app_secret = os.environ.get("QQ_APP_SECRET", "").strip()
    if not app_id or not app_secret or not request.openid:
        return

    content = format_internal_approval_message(request)
    try:
        msg_seq = int(os.environ.get("CODEX_QQ_APPROVAL_MSG_SEQ", "50"))
    except ValueError:
        msg_seq = 50
    try:
        QQBotClient(app_id, app_secret).send_c2c_message(
            request.openid,
            content,
            request.message_id or None,
            msg_seq,
        )
    except Exception as exc:
        print(f"failed to send QQ approval request: {exc}", file=sys.stderr)


def wait_for_decision(approval_id: str) -> bool:
    auto = os.environ.get("CODEX_QQ_AUTO_DECISION", "").strip().lower()
    if auto in {"allow", "approve", "yes", "true", "1"}:
        return True
    if auto in {"deny", "cancel", "no", "false", "0"}:
        return False

    timeout = int(os.environ.get("CODEX_QQ_APPROVAL_TIMEOUT_SECONDS", "600"))
    deadline = time.time() + max(timeout, 1)
    while time.time() < deadline:
        decision = load_decision(approval_id)
        if decision is not None:
            return bool(decision.get("approved"))
        time.sleep(1)
    request_file = request_path(approval_id)
    print(f"approval timed out for {approval_id}; request_file={request_file}", file=sys.stderr)
    return False


def emit_decision(approved: bool, message: str | None = None) -> None:
    behavior = "allow" if approved else "deny"
    output = {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": behavior,
                "message": message or ("Approved via QQ." if approved else "Denied via QQ."),
            },
        },
    }
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
