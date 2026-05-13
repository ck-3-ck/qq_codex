from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionConfig:
    alias: str
    session_id: str
    cwd: str
    sandbox: str = "read-only"
    source: str = ""


@dataclass(frozen=True)
class PolicyConfig:
    default_sandbox: str
    allowed_openids: set[str]
    blocked_terms: list[str]
    safety_prompt: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a JSON object: {path}")
    return data


def load_sessions(path: Path) -> dict[str, SessionConfig]:
    data = load_json(path)
    sessions: dict[str, SessionConfig] = {}
    for alias, raw in data.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"Session {alias!r} must be an object")
        try:
            session_id = str(raw["session_id"])
            cwd = str(raw["cwd"])
        except KeyError as exc:
            raise ConfigError(f"Session {alias!r} missing {exc.args[0]}") from exc
        sandbox = str(raw.get("sandbox", "read-only"))
        source = str(raw.get("source", ""))
        sessions[alias] = SessionConfig(alias, session_id, cwd, sandbox, source)
    return sessions


def load_policy(path: Path) -> PolicyConfig:
    data = load_json(path)
    env_openids = [
        item.strip()
        for item in os.environ.get("QQ_ALLOWED_OPENIDS", "").split(",")
        if item.strip()
    ]
    json_openids = data.get("allowed_openids", [])
    if not isinstance(json_openids, list):
        raise ConfigError("policy.allowed_openids must be a list")
    blocked_terms = data.get("blocked_terms", [])
    if not isinstance(blocked_terms, list):
        raise ConfigError("policy.blocked_terms must be a list")
    return PolicyConfig(
        default_sandbox=str(data.get("default_sandbox", "read-only")),
        allowed_openids={str(item) for item in json_openids} | set(env_openids),
        blocked_terms=[str(item) for item in blocked_terms],
        safety_prompt=str(data.get("safety_prompt", "")),
    )
