from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config_loader import PolicyConfig, SessionConfig
from .security import assert_prompt_allowed


class CodexRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexResult:
    returncode: int
    final_message: str
    stdout: str
    stderr: str


class CodexRunner:
    def __init__(self, codex_cmd: str | None = None, timeout_seconds: int = 420):
        appdata = os.environ.get("APPDATA", "")
        self.codex_cmd = expand_vars(codex_cmd or r"%APPDATA%\npm\codex.cmd")
        self.node_dir = r"C:\Program Files\nodejs"
        self.npm_dir = str(Path(appdata) / "npm") if appdata else ""
        self.timeout_seconds = timeout_seconds
        self.root = Path(__file__).resolve().parents[1]
        self.approval_hook = self.root / "src" / "approval_hook.py"

    def run(
        self,
        session: SessionConfig,
        prompt: str,
        policy: PolicyConfig,
        task_id: str | None = None,
        openid: str | None = None,
        message_id: str | None = None,
        display_ref: str | None = None,
    ) -> CodexResult:
        if session.sandbox not in {"read-only", "workspace-write"}:
            raise CodexRunError(f"Unsupported sandbox: {session.sandbox}")
        if not Path(session.cwd).exists():
            raise CodexRunError(f"Session cwd does not exist: {session.cwd}")
        assert_prompt_allowed(prompt, policy)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as handle:
            output_path = Path(handle.name)

        args = [
            self.codex_cmd,
            "exec",
        ]
        if self.use_internal_approval_hook(session):
            args.extend(
                [
                    "--enable",
                    "codex_hooks",
                    "-c",
                    self.internal_approval_hooks_config(),
                    "-c",
                    'approval_policy="on-request"',
                ]
            )
        args.extend(
            [
            "--sandbox",
            session.sandbox,
            "--cd",
            session.cwd,
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "resume",
            session.session_id,
            prompt,
            ]
        )

        env = os.environ.copy()
        prefix = [self.node_dir]
        if self.npm_dir:
            prefix.append(self.npm_dir)
        env["Path"] = ";".join(prefix + [env.get("Path", "")])
        env["PYTHONUTF8"] = "1"
        if self.use_internal_approval_hook(session):
            env["CODEX_QQ_INTERNAL_APPROVALS"] = "1"
            env["CODEX_QQ_TASK_ID"] = task_id or ""
            env["CODEX_QQ_OPENID"] = openid or ""
            env["CODEX_QQ_MESSAGE_ID"] = message_id or ""
            env["CODEX_QQ_DISPLAY_REF"] = display_ref or session.alias

        try:
            completed = subprocess.run(
                args,
                cwd=session.cwd,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexRunError(f"Codex timed out after {self.timeout_seconds}s") from exc
        finally:
            final_message = read_text_if_exists(output_path)
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise CodexRunError(f"Codex failed with code {completed.returncode}: {detail}")

        if not final_message.strip():
            final_message = extract_fallback_message(completed.stdout)

        return CodexResult(
            returncode=completed.returncode,
            final_message=final_message.strip(),
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def use_internal_approval_hook(self, session: SessionConfig) -> bool:
        return session.sandbox == "workspace-write" and session.source == "vscode" and self.approval_hook.exists()

    def internal_approval_hooks_config(self) -> str:
        command = f'"{sys.executable}" "{self.approval_hook}"'
        return (
            "hooks.PermissionRequest="
            "[{hooks=[{type=\"command\", "
            f"command={toml_string(command)}, "
            "timeout=900}]}]"
        )


def expand_vars(value: str) -> str:
    return os.path.expandvars(value)


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_fallback_message(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1]
