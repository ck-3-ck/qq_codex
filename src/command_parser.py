from __future__ import annotations

import re
from dataclasses import dataclass


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    args: dict[str, str]
    raw: str


def parse_message(text: str) -> Command | None:
    raw = text.strip()
    if not raw:
        return None
    choice = re.fullmatch(r"([ABCabc])(\d*)", raw)
    if choice:
        return Command(
            "ui_choice",
            {"choice": choice.group(1).upper(), "index": choice.group(2)},
            raw,
        )
    if raw in {"/help", "help"}:
        return Command("help", {}, raw)
    if not raw.startswith("/"):
        return None

    parts = raw.split(maxsplit=2)
    head = parts[0].lower()

    if head == "/codex":
        if len(parts) == 1:
            return Command("help", {}, raw)
        sub = parts[1]
        if sub == "list":
            if len(parts) == 2:
                return Command("codex_list", {"mode": "active"}, raw)
            if parts[2].strip().lower() == "all":
                return Command("codex_list", {"mode": "all"}, raw)
            raise ParseError("Usage: /codex list [all]")
        if sub == "hide":
            if len(parts) < 3:
                raise ParseError("Usage: /codex hide <short_id|alias>")
            return Command("codex_hide", {"ref": parts[2]}, raw)
        if sub == "unhide":
            if len(parts) < 3:
                raise ParseError("Usage: /codex unhide <short_id|alias>")
            return Command("codex_unhide", {"ref": parts[2]}, raw)
        if sub == "last":
            if len(parts) < 3:
                raise ParseError("Usage: /codex last <prompt>")
            return Command("codex_last", {"prompt": parts[2]}, raw)
        if len(parts) < 3:
            raise ParseError("Usage: /codex <alias> <prompt>")
        return Command("codex_run", {"alias": sub, "prompt": parts[2]}, raw)

    if head == "/bridge":
        if len(parts) < 2:
            return Command("help", {}, raw)
        sub = parts[1].lower()
        if sub == "storage" and len(parts) == 2:
            return Command("bridge_storage", {}, raw)
        raise ParseError("Usage: /bridge storage")

    if head == "/status":
        if len(parts) < 2:
            raise ParseError("Usage: /status <task_id>")
        return Command("status", {"task_id": parts[1]}, raw)

    if head == "/approve":
        if len(parts) < 2:
            raise ParseError("Usage: /approve <task_id>")
        return Command("approve", {"task_id": parts[1]}, raw)

    if head == "/approve-always":
        if len(parts) < 2:
            raise ParseError("Usage: /approve-always <task_id>")
        return Command("approve_always", {"task_id": parts[1]}, raw)

    if head == "/cancel":
        if len(parts) < 2:
            raise ParseError("Usage: /cancel <task_id>")
        return Command("cancel", {"task_id": parts[1]}, raw)

    raise ParseError(f"Unknown command: {parts[0]}")


def help_text() -> str:
    return "\n".join(
        [
            "Commands:",
            "/help",
            "/codex list",
            "/codex list all",
            "/codex hide <short_id|alias>",
            "/codex unhide <short_id|alias>",
            "/codex <alias> <prompt>",
            "/codex last <prompt>",
            "/bridge storage",
            "/status <task_id>",
            "/status ui",
            "/approve <task_id>",
            "/approve ui",
            "/approve-always <ui_approval_id>",
            "/approve-always ui",
            "/cancel <task_id>",
            "/cancel ui",
            "A/B/C: answer the only visible Codex UI approval",
            "A1/B1/C1: answer a numbered Codex UI approval",
        ]
    )
