import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.codex_runner import CodexRunner
from src.config_loader import PolicyConfig, SessionConfig


class CodexRunnerTests(unittest.TestCase):
    def test_workspace_ui_session_enables_internal_approval_hook(self):
        policy = PolicyConfig("read-only", {"openid"}, [], "")
        session = SessionConfig(
            "test",
            "sid",
            "E:\\codex-qq-bridge",
            "workspace-write",
            "vscode",
        )
        runner = CodexRunner("codex", 30)
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs["env"]
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        with patch("src.codex_runner.subprocess.run", fake_run):
            result = runner.run(
                session,
                "只回复 OK",
                policy,
                "task",
                "openid",
                "message",
                "测试对话",
            )

        self.assertEqual(result.final_message, "OK")
        self.assertIn("--enable", captured["args"])
        self.assertIn("codex_hooks", captured["args"])
        self.assertIn("hooks.PermissionRequest=", " ".join(captured["args"]))
        self.assertIn('approval_policy="on-request"', captured["args"])
        self.assertEqual(captured["env"]["CODEX_QQ_TASK_ID"], "task")
        self.assertEqual(captured["env"]["CODEX_QQ_DISPLAY_REF"], "测试对话")

    def test_read_only_session_does_not_enable_internal_approval_hook(self):
        session = SessionConfig("test", "sid", "E:\\codex-qq-bridge", "read-only", "exec")
        runner = CodexRunner("codex", 30)
        self.assertFalse(runner.use_internal_approval_hook(session))


if __name__ == "__main__":
    unittest.main()
