import unittest

from src.command_parser import ParseError, parse_message


class CommandParserTests(unittest.TestCase):
    def test_codex_list(self):
        command = parse_message("/codex list")
        self.assertEqual(command.name, "codex_list")
        self.assertEqual(command.args["mode"], "active")

    def test_codex_list_all(self):
        command = parse_message("/codex list all")
        self.assertEqual(command.name, "codex_list")
        self.assertEqual(command.args["mode"], "all")

    def test_codex_hide(self):
        command = parse_message("/codex hide 019e1625")
        self.assertEqual(command.name, "codex_hide")
        self.assertEqual(command.args["ref"], "019e1625")

    def test_codex_unhide(self):
        command = parse_message("/codex unhide paper")
        self.assertEqual(command.name, "codex_unhide")
        self.assertEqual(command.args["ref"], "paper")

    def test_codex_run(self):
        command = parse_message("/codex paper summarize requirements")
        self.assertEqual(command.name, "codex_run")
        self.assertEqual(command.args["alias"], "paper")
        self.assertEqual(command.args["prompt"], "summarize requirements")

    def test_bridge_storage(self):
        command = parse_message("/bridge storage")
        self.assertEqual(command.name, "bridge_storage")

    def test_approve_always(self):
        command = parse_message("/approve-always ui-123")
        self.assertEqual(command.name, "approve_always")
        self.assertEqual(command.args["task_id"], "ui-123")

    def test_unknown_command(self):
        with self.assertRaises(ParseError):
            parse_message("/unknown")


if __name__ == "__main__":
    unittest.main()
