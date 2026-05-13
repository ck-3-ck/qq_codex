import unittest

from src.config_loader import PolicyConfig
from src.security import assert_prompt_allowed


class SecurityTests(unittest.TestCase):
    def test_prompt_policy_blocks_terms(self):
        policy = PolicyConfig(
            default_sandbox="read-only",
            allowed_openids=set(),
            blocked_terms=["danger"],
            safety_prompt="safety rule",
        )
        with self.assertRaises(PermissionError):
            assert_prompt_allowed("do danger thing", policy)


if __name__ == "__main__":
    unittest.main()
