from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "ui_approval.ps1"


class UIApprovalError(RuntimeError):
    pass


@dataclass
class UIApprovalRecord:
    approval_id: str
    signature: str
    prompt: str
    openid: str
    message_id: str
    created_at: datetime
    window_handle: int = 0
    window_name: str = ""
    conversation_title: str = ""
    can_approve_always: bool = False
    choice_index: int = 0
    resolved: bool = False


def detect_ui_approval() -> dict:
    return run_script("detect")


def detect_ui_approvals() -> list[dict]:
    data = detect_ui_approval()
    approvals = data.get("approvals")
    if isinstance(approvals, list):
        return [item for item in approvals if isinstance(item, dict)]
    if data.get("found"):
        return [data]
    return []


def approve_ui_approval(signature: str = "") -> dict:
    return run_script("approve", signature)


def approve_always_ui_approval(signature: str = "") -> dict:
    return run_script("approve-always", signature)


def cancel_ui_approval(signature: str = "") -> dict:
    return run_script("cancel", signature)


def run_script(mode: str, signature: str = "") -> dict:
    args = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-Mode",
            mode,
    ]
    if signature:
        args.extend(["-Signature", signature])
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=20,
        shell=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise UIApprovalError(detail)
    try:
        data = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise UIApprovalError(f"UI approval script returned non-JSON: {completed.stdout[:300]}") from exc
    return data if isinstance(data, dict) else {}


def format_ui_approval_message(record: UIApprovalRecord, numbered: bool = False) -> str:
    has_detected_title = bool(record.conversation_title.strip())
    title = clean_display_title(record.conversation_title)
    prompt = clean_approval_prompt(record.prompt, remove_heuristic_title=has_detected_title)
    if len(prompt) > 800:
        prompt = prompt[:800] + "\n..."
    index = record.choice_index if numbered and record.choice_index > 0 else 0
    title_suffix = f" #{index}" if index else ""
    choice_suffix = str(index) if index else ""
    lines = [
        f"Codex UI 审批：{title}{title_suffix}",
        "",
        prompt,
        "",
        f"A{choice_suffix} = 允许本次",
        f"B{choice_suffix} = 允许本次，并记住同类命令",
        f"C{choice_suffix} = 拒绝/跳过",
    ]
    return "\n".join(lines)


def clean_display_title(title: str) -> str:
    title = title.strip()
    return title if title else "未知对话"


CONVERSATION_SUFFIX_RE = re.compile(r"(?:\s*\d+\s*(?:秒|分钟|小时|天|周|月)|\s*等待批准)+$")
OPTION_PREFIXES = (
    "是，且对于以",
    "否，请告知",
    "3。",
    "3.",
)
OPTION_EXACT = {
    "是",
    "跳过",
    "提交",
    "提交 ⏎",
    "Git 操作",
    "GitHub CLI 不可用",
}
NOISE_MARKERS = (
    " 3。",
    " 3.",
    " 否，请告知 Codex 如何调整",
    " 跳过",
    " 提交",
)


def clean_conversation_title(prompt: str) -> str:
    for line in normalized_prompt_lines(prompt):
        if is_noise_line(line):
            continue
        if line.startswith("需要") or looks_like_command(line):
            continue
        candidate = CONVERSATION_SUFFIX_RE.sub("", line).strip()
        if candidate and len(candidate) <= 60:
            return candidate
    return "Codex"


def clean_approval_prompt(prompt: str, remove_heuristic_title: bool = True) -> str:
    title = clean_conversation_title(prompt) if remove_heuristic_title else ""
    cleaned: list[str] = []
    for line in normalized_prompt_lines(prompt):
        if is_noise_line(line):
            continue
        candidate = CONVERSATION_SUFFIX_RE.sub("", line).strip()
        if title and candidate == title:
            continue
        line = strip_trailing_options(line)
        if not line:
            continue
        if line not in cleaned:
            cleaned.append(line)
    return "\n".join(cleaned) if cleaned else "需要你审批 Codex UI 中的请求。"


def normalized_prompt_lines(prompt: str) -> list[str]:
    return [line.strip() for line in prompt.splitlines() if line.strip()]


def is_noise_line(line: str) -> bool:
    if line in OPTION_EXACT:
        return True
    return any(line.startswith(prefix) for prefix in OPTION_PREFIXES)


def strip_trailing_options(line: str) -> str:
    for marker in NOISE_MARKERS:
        index = line.find(marker)
        if index >= 0:
            line = line[:index]
    return line.strip()


def looks_like_command(line: str) -> bool:
    lowered = line.lower()
    command_terms = (
        "powershell",
        "get-childitem",
        "new-item",
        "remove-item",
        "curl",
        "python",
        "cmd.exe",
        "git ",
        "npm ",
        "cmake",
        "ninja",
        "invoke-webrequest",
    )
    return any(term in lowered for term in command_terms)
