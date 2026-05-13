import tempfile
import time
import unittest
from pathlib import Path

from src.session_scanner import clean_title, discover_sessions, format_session_listing, normalize_cwd


class SessionScannerTests(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(clean_title("User request: hello world"), "hello world")
        self.assertTrue(clean_title("x" * 40).endswith("..."))

    def test_normalize_cwd(self):
        self.assertEqual(normalize_cwd("\\\\?\\C:\\Users\\kaius\\Desktop"), "C:\\Users\\kaius\\Desktop")

    def test_discover_and_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "sessions" / "2026" / "05" / "11"
            session_dir.mkdir(parents=True)
            path = session_dir / "rollout-test.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"id":"12345678-aaaa","cwd":"E:\\\\codex-qq-bridge","source":"vscode"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","message":"hello session"}}',
                    ]
                ),
                encoding="utf-8",
            )
            archived_dir = root / "archived_sessions" / "2026" / "05" / "11"
            archived_dir.mkdir(parents=True)
            archived_path = archived_dir / "rollout-archived.jsonl"
            archived_path.write_text(
                "\n".join(
                    [
                        '{"type":"session_meta","payload":{"id":"99999999-aaaa","cwd":"E:\\\\old-project","source":"vscode"}}',
                        '{"type":"event_msg","payload":{"type":"user_message","message":"old session"}}',
                    ]
                ),
                encoding="utf-8",
            )
            now = time.time()
            path.touch()
            sessions = discover_sessions(root)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].short_id, "12345678")
            all_sessions = discover_sessions(root, include_archived=True)
            self.assertEqual(len(all_sessions), 2)
            text = format_session_listing(sessions, {"12345678-aaaa": "bridge"})
            self.assertIn("[codex-qq-bridge]", text)
            self.assertIn("@bridge", text)
            self.assertIn("hello session", text)
            self.assertIn("(12345678 @bridge)", text)


if __name__ == "__main__":
    unittest.main()
