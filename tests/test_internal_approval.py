import tempfile
import unittest
from pathlib import Path

import src.internal_approval as internal_approval
from src.internal_approval import InternalApprovalRequest


class InternalApprovalTests(unittest.TestCase):
    def test_internal_approval_command_writes_decision(self):
        original_dir = internal_approval.INTERNAL_APPROVAL_DIR
        with tempfile.TemporaryDirectory() as tmp:
            internal_approval.INTERNAL_APPROVAL_DIR = Path(tmp)
            try:
                request = InternalApprovalRequest(
                    approval_id="perm-task-abc123",
                    task_id="task",
                    openid="openid",
                    display_ref="测试对话",
                    message_id="message",
                    cwd="E:\\codex-qq-bridge",
                    tool_name="Shell",
                    tool_input={"command": "python -c \"print(123)\""},
                    created_at="2026-05-12T10:00:00",
                )
                internal_approval.save_request(request)

                response = internal_approval.handle_internal_approval_command(
                    "perm-task-abc123",
                    "openid",
                    approved=True,
                )

                self.assertIn("已允许", response)
                decision = internal_approval.load_decision("perm-task-abc123")
                self.assertIsNotNone(decision)
                self.assertTrue(decision["approved"])
            finally:
                internal_approval.INTERNAL_APPROVAL_DIR = original_dir

    def test_non_internal_approval_id_is_ignored(self):
        self.assertIsNone(internal_approval.handle_internal_approval_command("task", "openid", True))


if __name__ == "__main__":
    unittest.main()
