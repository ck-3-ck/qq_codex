from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


@dataclass(frozen=True)
class DiscoveredSession:
    session_id: str
    cwd: str
    title: str
    updated: float
    archived: bool
    source: str

    @property
    def short_id(self) -> str:
        return self.session_id[:8]

    @property
    def project_name(self) -> str:
        if not self.cwd:
            return "<unknown>"
        cwd = normalize_cwd(self.cwd)
        return PureWindowsPath(cwd).name or cwd


def discover_sessions(
    codex_home: Path | None = None,
    limit: int = 30,
    include_archived: bool = False,
) -> list[DiscoveredSession]:
    root = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    indexed = discover_sessions_from_sqlite(root, limit, include_archived)
    if indexed:
        return indexed

    sessions: list[DiscoveredSession] = []
    locations = [(root / "sessions", False)]
    if include_archived:
        locations.append((root / "archived_sessions", True))
    for base, archived in locations:
        if not base.exists():
            continue
        for path in base.rglob("*.jsonl"):
            found = parse_session_file(path, archived)
            if found:
                sessions.append(found)
    sessions.sort(key=lambda item: item.updated, reverse=True)
    return sessions[:limit]


def discover_sessions_from_sqlite(root: Path, limit: int, include_archived: bool = False) -> list[DiscoveredSession]:
    db_path = root / "state_5.sqlite"
    if not db_path.exists():
        return []
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return []
    try:
        where = "" if include_archived else "where coalesce(archived, 0) = 0"
        rows = con.execute(
            f"""
            select id, cwd, title, updated_at, updated_at_ms, archived, source
            from threads
            {where}
            order by coalesce(updated_at_ms, updated_at * 1000) desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    sessions: list[DiscoveredSession] = []
    for session_id, cwd, title, updated_at, updated_at_ms, archived, source in rows:
        updated = float(updated_at_ms / 1000 if updated_at_ms else updated_at)
        sessions.append(
            DiscoveredSession(
                session_id=str(session_id),
                cwd=normalize_cwd(str(cwd or "")),
                title=clean_title(str(title or "")) or "<no title>",
                updated=updated,
                archived=bool(archived),
                source=str(source or ""),
            )
        )
    return sessions


def parse_session_file(path: Path, archived: bool) -> DiscoveredSession | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first_line = handle.readline()
        first = json.loads(first_line)
        if first.get("type") != "session_meta":
            return None
        meta = first.get("payload", {})
        session_id = str(meta.get("id", ""))
        if not session_id:
            return None
        title = read_last_user_message(path)
        return DiscoveredSession(
            session_id=session_id,
            cwd=normalize_cwd(str(meta.get("cwd", ""))),
            title=clean_title(title) or "<no recent user message>",
            updated=path.stat().st_mtime,
            archived=archived,
            source=str(meta.get("source", "")),
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def read_last_user_message(path: Path, tail_bytes: int = 512_000) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - tail_bytes))
        data = handle.read().decode("utf-8", errors="replace")
    last_user = ""
    for line in data.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "event_msg" and item.get("payload", {}).get("type") == "user_message":
            last_user = str(item.get("payload", {}).get("message", "") or "")
    return last_user


def clean_title(value: str, max_len: int = 28) -> str:
    text = " ".join(value.split())
    if text.startswith("User request:"):
        text = text.removeprefix("User request:").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def normalize_cwd(value: str) -> str:
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def format_session_listing(
    sessions: list[DiscoveredSession],
    alias_by_id: dict[str, str] | None = None,
    hidden_ids: set[str] | None = None,
) -> str:
    alias_by_id = alias_by_id or {}
    hidden_ids = hidden_ids or set()
    if not sessions:
        return "No Codex sessions found."

    lines: list[str] = []
    count = 0
    grouped: dict[str, list[DiscoveredSession]] = {}
    project_order: list[str] = []
    for session in sessions:
        project = session.project_name
        if project not in grouped:
            grouped[project] = []
            project_order.append(project)
        grouped[project].append(session)

    for project in project_order:
        if lines:
            lines.append("")
        lines.append(f"[{project}]")
        for session in grouped[project]:
            count += 1
            alias = alias_by_id.get(session.session_id)
            alias_text = f" @{alias}" if alias else ""
            archived_text = " archived" if session.archived else ""
            hidden_text = " hidden" if session.session_id in hidden_ids else ""
            source_text = " exec" if session.source == "exec" else ""
            meta = f"{session.short_id}{alias_text}{archived_text}{hidden_text}{source_text}"
            lines.append(f"{count}. {session.title} ({meta})")
    lines.append("")
    lines.append("Use: /codex <short_id|alias> <prompt>")
    lines.append("Hide: /codex hide <short_id|alias>")
    return "\n".join(lines)
