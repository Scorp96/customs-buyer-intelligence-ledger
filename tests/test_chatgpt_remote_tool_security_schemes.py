from __future__ import annotations

import copy
import unittest

from mcp.chatgpt_oauth_transport import decorate_tools_list_for_chatgpt


class ChatGPTRemoteToolSecuritySchemeTests(unittest.TestCase):
    def test_decorates_every_tool_with_oauth_and_compatibility_mirror(self) -> None:
        original = {
            "tools": [
                {
                    "name": "get_runtime_health",
                    "description": "health",
                    "inputSchema": {"type": "object"},
                    "_meta": {"ui": {"resourceUri": "ui://health"}},
                },
                {
                    "name": "start_investigation",
                    "description": "start",
                    "inputSchema": {"type": "object"},
                },
            ],
            "nextCursor": "cursor-1",
        }
        snapshot = copy.deepcopy(original)

        result = decorate_tools_list_for_chatgpt(original)

        expected = [{"type": "oauth2", "scopes": ["read:user", "offline_access"]}]
        self.assertEqual(result["nextCursor"], "cursor-1")
        self.assertEqual(len(result["tools"]), 2)
        for tool in result["tools"]:
            self.assertEqual(tool["securitySchemes"], expected)
            self.assertEqual(tool["_meta"]["securitySchemes"], expected)
        self.assertEqual(result["tools"][0]["_meta"]["ui"], {"resourceUri": "ui://health"})
        self.assertEqual(original, snapshot)

    def test_non_tools_payload_is_left_unchanged(self) -> None:
        payload = {"status": "ok"}
        self.assertIs(decorate_tools_list_for_chatgpt(payload), payload)


if __name__ == "__main__":
    unittest.main()
