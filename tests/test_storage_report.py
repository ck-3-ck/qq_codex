import tempfile
import unittest
from pathlib import Path

from src.storage_report import build_storage_report, format_bytes, scan_path


class StorageReportTests(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.50 KB")

    def test_scan_path_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("abc", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "b.txt").write_text("12345", encoding="utf-8")
            entry = scan_path("test", root)
            self.assertEqual(entry.file_count, 2)
            self.assertEqual(entry.size_bytes, 8)

    def test_build_storage_report_mentions_locations(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as codex_tmp:
            project = Path(project_tmp)
            codex = Path(codex_tmp)
            (project / "logs").mkdir()
            (project / "logs" / "audit.log").write_text("log", encoding="utf-8")
            (project / "config").mkdir()
            (codex / "sessions").mkdir()
            (codex / "sessions" / "session.jsonl").write_text("session", encoding="utf-8")
            (codex / "state_5.sqlite").write_text("db", encoding="utf-8")
            report = build_storage_report(project, codex)
            self.assertIn(str(project), report)
            self.assertIn(str(codex), report)
            self.assertIn("Codex sessions", report)
            self.assertIn("Bridge logs", report)


if __name__ == "__main__":
    unittest.main()
