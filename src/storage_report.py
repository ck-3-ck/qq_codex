from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageEntry:
    label: str
    path: str
    file_count: int
    size_bytes: int
    exists: bool


def build_storage_report(project_root: Path, codex_home: Path | None = None) -> str:
    codex_root = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    codex_entries = [
        scan_path("Codex home total", codex_root),
        scan_path("Codex sessions", codex_root / "sessions"),
        scan_path("Codex archived sessions", codex_root / "archived_sessions"),
        scan_glob("Codex state files", codex_root, "state_*.sqlite*"),
        scan_path("Codex session index", codex_root / "session_index.jsonl"),
    ]
    bridge_entries = [
        scan_path("Bridge project total", project_root),
        scan_path("Bridge logs", project_root / "logs"),
        scan_path("Bridge audit log", project_root / "logs" / "audit.log"),
        scan_path("Bridge task cache", project_root / "logs" / "tasks.json"),
        scan_path("Bridge config", project_root / "config"),
        scan_path("Bridge hidden list", project_root / "config" / "hidden_sessions.json"),
        scan_path("Bridge environment file", project_root / ".env"),
    ]

    lines = ["Storage usage", "", "[Codex]"]
    lines.extend(format_entry(entry) for entry in codex_entries)
    lines.extend(["", "[Bridge]"])
    lines.extend(format_entry(entry) for entry in bridge_entries)
    lines.extend(
        [
            "",
            "Read-only report. Do not manually delete files under .codex unless you intentionally want to remove Codex history.",
        ]
    )
    return "\n".join(lines)


def scan_path(label: str, path: Path) -> StorageEntry:
    exists = path.exists()
    file_count, size_bytes = path_size(path) if exists else (0, 0)
    return StorageEntry(label, str(path), file_count, size_bytes, exists)


def scan_glob(label: str, base: Path, pattern: str) -> StorageEntry:
    paths = sorted(base.glob(pattern)) if base.exists() else []
    file_count = 0
    size_bytes = 0
    for path in paths:
        count, size = path_size(path)
        file_count += count
        size_bytes += size
    return StorageEntry(label, str(base / pattern), file_count, size_bytes, bool(paths))


def path_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 0, 0
    if not path.is_dir():
        return 0, 0

    file_count = 0
    size_bytes = 0
    for root, _, files in os.walk(path):
        root_path = Path(root)
        for name in files:
            file_path = root_path / name
            try:
                size_bytes += file_path.stat().st_size
                file_count += 1
            except OSError:
                continue
    return file_count, size_bytes


def format_entry(entry: StorageEntry) -> str:
    status = "" if entry.exists else " missing"
    return (
        f"- {entry.label}: {format_bytes(entry.size_bytes)}, "
        f"{entry.file_count} files{status}\n"
        f"  {entry.path}"
    )


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
