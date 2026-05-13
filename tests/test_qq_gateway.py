import unittest

from src.qq_gateway import GROUP_AND_C2C_EVENT, parse_c2c_message


class QQGatewayTests(unittest.TestCase):
    def test_c2c_intent(self):
        self.assertEqual(GROUP_AND_C2C_EVENT, 1 << 25)

    def test_parse_c2c_message(self):
        message = parse_c2c_message(
            {
                "id": "event-id",
                "op": 0,
                "s": 1,
                "t": "C2C_MESSAGE_CREATE",
                "d": {
                    "author": {"user_openid": "OPENID"},
                    "content": "hello",
                    "id": "message-id",
                    "timestamp": "2026-05-11T21:30:00+08:00",
                },
            }
        )
        self.assertEqual(message.openid, "OPENID")
        self.assertEqual(message.content, "hello")
        self.assertEqual(message.message_id, "message-id")


if __name__ == "__main__":
    unittest.main()
