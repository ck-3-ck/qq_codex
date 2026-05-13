import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import src.main as main
from src.config_loader import SessionConfig
from src.main import TaskRecord, chunk_text
from src.session_scanner import DiscoveredSession
from src.ui_approval import UIApprovalRecord, format_ui_approval_message


class MainHelperTests(unittest.TestCase):
    def test_chunk_text_short(self):
        self.assertEqual(chunk_text("abc", 10), ["abc"])

    def test_chunk_text_long(self):
        self.assertEqual(chunk_text("abcdef", 2), ["ab", "cd", "ef"])

    def test_hidden_sessions_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = main.HIDDEN_SESSIONS_FILE
            main.HIDDEN_SESSIONS_FILE = Path(tmp) / "hidden_sessions.json"
            try:
                main.save_hidden_session_ids({"abc", "def"})
                self.assertEqual(main.load_hidden_session_ids(), {"abc", "def"})
            finally:
                main.HIDDEN_SESSIONS_FILE = original

    def test_format_task_result_uses_display_ref(self):
        record = TaskRecord(
            task_id="task",
            openid="openid",
            alias="019e1784",
            display_ref="测试对话",
            prompt="question",
            status="done",
            created_at=datetime(2026, 5, 12, 10, 0, 0),
            updated_at=datetime(2026, 5, 12, 10, 0, 1),
            result="225",
        )
        self.assertEqual(main.format_task_result(record), "/codex 测试对话\n225")

    def test_task_record_from_old_json_uses_alias_as_display_ref(self):
        record = TaskRecord.from_json(
            {
                "task_id": "task",
                "openid": "openid",
                "alias": "019e1784",
                "prompt": "question",
                "status": "done",
                "created_at": "2026-05-12T10:00:00",
                "updated_at": "2026-05-12T10:00:01",
                "result": "225",
                "error": "",
            }
        )
        self.assertEqual(record.display_ref, "019e1784")

    def test_looks_like_write_prompt(self):
        self.assertTrue(main.looks_like_write_prompt("给我生成一个word文档"))
        self.assertFalse(main.looks_like_write_prompt("总结一下，不要修改任何文件"))

    def test_ui_workspace_write_session_uses_codex_internal_approval(self):
        session = SessionConfig("test", "sid", "E:\\codex-qq-bridge", "workspace-write", "vscode")
        self.assertEqual(main.write_approval_reason("生成一个 docx 文件", session), "")

    def test_non_ui_workspace_write_session_uses_bridge_approval(self):
        session = SessionConfig("test", "sid", "E:\\codex-qq-bridge", "workspace-write", "manual")
        self.assertEqual(main.write_approval_reason("生成一个 docx 文件", session), "这条指令可能会写入或修改文件。")

    def test_write_request_blocked_for_read_only_session(self):
        session = SessionConfig("test", "sid", "E:\\codex-qq-bridge", "read-only", "exec")
        self.assertEqual(
            main.write_approval_reason("生成一个 docx 文件", session),
            "这个会话当前是只读，不能执行写入或修改文件的任务。",
        )

    def test_create_approval_message_creates_pending_task(self):
        session = SessionConfig("test", "sid", "E:\\codex-qq-bridge", "workspace-write", "manual")
        tasks: dict[str, TaskRecord] = {}
        original_tasks_file = main.TASKS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            main.TASKS_FILE = Path(tmp) / "tasks.json"
            try:
                message = main.approval_prompt_message("openid", "test", "测试对话", "生成一个 docx 文件", session, tasks)
                self.assertIn("/codex 测试对话", message)
                self.assertIn("/approve", message)
                self.assertEqual(len(tasks), 1)
                record = next(iter(tasks.values()))
                self.assertEqual(record.status, "pending_approval")
            finally:
                main.TASKS_FILE = original_tasks_file

    def test_resolve_session_ref_by_title(self):
        discovered = [
            DiscoveredSession(
                session_id="12345678-aaaa",
                cwd="E:\\codex-qq-bridge",
                title="测试对话",
                updated=1,
                archived=False,
                source="vscode",
            )
        ]
        original_discover = main.discover_sessions
        original_hidden = main.HIDDEN_SESSIONS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            main.HIDDEN_SESSIONS_FILE = Path(tmp) / "hidden_sessions.json"
            main.discover_sessions = lambda *args, **kwargs: discovered
            sessions: dict[str, SessionConfig] = {}
            try:
                alias = main.resolve_session_ref("测试对话", sessions)
                self.assertEqual(alias, "12345678")
                self.assertEqual(sessions[alias].session_id, "12345678-aaaa")
                self.assertEqual(sessions[alias].sandbox, "workspace-write")
                self.assertEqual(sessions[alias].source, "vscode")
            finally:
                main.discover_sessions = original_discover
                main.HIDDEN_SESSIONS_FILE = original_hidden

    def test_resolve_session_ref_duplicate_title(self):
        discovered = [
            DiscoveredSession("12345678-aaaa", "E:\\one", "测试对话", 2, False, "vscode"),
            DiscoveredSession("87654321-bbbb", "E:\\two", "测试对话", 1, False, "vscode"),
        ]
        original_discover = main.discover_sessions
        original_hidden = main.HIDDEN_SESSIONS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            main.HIDDEN_SESSIONS_FILE = Path(tmp) / "hidden_sessions.json"
            main.discover_sessions = lambda *args, **kwargs: discovered
            try:
                with self.assertRaises(main.SessionResolveError) as ctx:
                    main.resolve_session_ref("测试对话", {})
                self.assertIn("Multiple sessions match", str(ctx.exception))
                self.assertIn("12345678", str(ctx.exception))
                self.assertIn("87654321", str(ctx.exception))
            finally:
                main.discover_sessions = original_discover
                main.HIDDEN_SESSIONS_FILE = original_hidden

    def test_resolve_exec_session_stays_read_only(self):
        discovered = [
            DiscoveredSession(
                session_id="99999999-aaaa",
                cwd="E:\\codex-qq-bridge",
                title="background",
                updated=1,
                archived=False,
                source="exec",
            )
        ]
        original_discover = main.discover_sessions
        main.discover_sessions = lambda *args, **kwargs: discovered
        sessions: dict[str, SessionConfig] = {}
        try:
            alias = main.resolve_session_ref("99999999", sessions)
            self.assertEqual(alias, "99999999")
            self.assertEqual(sessions[alias].sandbox, "read-only")
            self.assertEqual(sessions[alias].source, "exec")
        finally:
            main.discover_sessions = original_discover

    def test_refresh_configured_alias_uses_ui_policy(self):
        discovered = [
            DiscoveredSession(
                session_id="12345678-aaaa",
                cwd="E:\\codex-qq-bridge",
                title="configured",
                updated=1,
                archived=False,
                source="vscode",
            )
        ]
        original_discover = main.discover_sessions
        main.discover_sessions = lambda *args, **kwargs: discovered
        sessions = {"paper": SessionConfig("paper", "12345678-aaaa", "E:\\old", "read-only")}
        try:
            main.refresh_session_policy("paper", sessions)
            self.assertEqual(sessions["paper"].sandbox, "workspace-write")
            self.assertEqual(sessions["paper"].cwd, "E:\\codex-qq-bridge")
            self.assertEqual(sessions["paper"].source, "vscode")
        finally:
            main.discover_sessions = original_discover

    def test_ui_approval_message_includes_three_desktop_choices(self):
        record = UIApprovalRecord(
            approval_id="ui-test",
            signature="sig",
            prompt=(
                "工程git2 周\n"
                "需要读取 G 盘 rerun2 输出目录，核对 512 GiB baseline 数据文件。 "
                "Get-ChildItem 'G:\\data' -Force | Select-Object Name 3。 "
                "否，请告知 Codex 如何调整 跳过 提交 ⏎\n"
                "是\n"
                "是，且对于以 'powershell.exe' 开头的命令不再询问\n"
                "GitHub CLI 不可用"
            ),
            openid="openid",
            message_id="message",
            created_at=datetime(2026, 5, 12, 10, 0, 0),
            can_approve_always=True,
        )
        message = format_ui_approval_message(record)
        self.assertIn("Codex UI 审批：工程git", message)
        self.assertIn("需要读取 G 盘 rerun2 输出目录", message)
        self.assertIn("/approve ui-test", message)
        self.assertIn("/approve-always ui-test", message)
        self.assertIn("/cancel ui-test", message)
        self.assertNotIn("(window", message)
        self.assertNotIn("GitHub CLI", message)
        self.assertNotIn("含义：", message)
        self.assertNotIn("是，且对于以", message)

    def test_record_ui_approval_keeps_distinct_windows_separate(self):
        approvals: dict[str, UIApprovalRecord] = {}

        first = main.record_ui_approval(
            {
                "signature": "sig-window-1",
                "prompt": "cmd.exe /c echo 1",
                "window_handle": 111,
                "can_approve_always": True,
            },
            "openid",
            "message",
            approvals,
        )
        second = main.record_ui_approval(
            {
                "signature": "sig-window-2",
                "prompt": "cmd.exe /c echo 2",
                "window_handle": 222,
                "can_approve_always": True,
            },
            "openid",
            "message",
            approvals,
        )

        self.assertEqual(len(approvals), 2)
        self.assertNotEqual(first.approval_id, second.approval_id)
        self.assertEqual(first.window_handle, 111)
        self.assertEqual(second.window_handle, 222)


if __name__ == "__main__":
    unittest.main()
