from __future__ import annotations

import types
import unittest

from mcp.remote_durability_checkpoint_v63 import install_remote_durability_checkpoint


class _ColdExit(BaseException):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class V63RemoteDurabilityCheckpointTests(unittest.TestCase):
    def test_checkpoint_runs_after_side_effect_and_before_cold_exit(self) -> None:
        order: list[str] = []

        def fatal_exit(code: int) -> None:
            order.append(f"exit:{code}")
            raise _ColdExit(code)

        adapter = types.SimpleNamespace()

        def original_invoke(tool_name, handler, arguments):
            order.append("prepared")
            raw = handler(dict(arguments))
            order.append("result-built")
            if arguments.get("crash_after_handler"):
                fatal_exit(91)
            order.append("terminal-commit")
            return raw

        adapter._invoke_mutation = original_invoke

        def checkpoint() -> None:
            order.append("checkpoint")

        install_remote_durability_checkpoint(
            adapter,
            checkpoint,
            fatal_exit=fatal_exit,
        )

        def handler(_arguments):
            order.append("side-effect")
            return {"status": "DISCOVERED"}

        with self.assertRaises(_ColdExit) as caught:
            adapter._invoke_mutation(
                "append_candidate_discovery",
                handler,
                {"crash_after_handler": True},
            )
        self.assertEqual(caught.exception.code, 91)
        self.assertEqual(
            order,
            ["prepared", "side-effect", "checkpoint", "result-built", "exit:91"],
        )

    def test_checkpoint_failure_exits_fail_closed_before_result_or_terminal_commit(self) -> None:
        order: list[str] = []

        def fatal_exit(code: int) -> None:
            order.append(f"exit:{code}")
            raise _ColdExit(code)

        adapter = types.SimpleNamespace()

        def original_invoke(tool_name, handler, arguments):
            order.append("prepared")
            raw = handler(dict(arguments))
            order.append("result-built")
            order.append("terminal-commit")
            return raw

        adapter._invoke_mutation = original_invoke

        def checkpoint() -> None:
            order.append("checkpoint")
            raise RuntimeError("synthetic R2 outage")

        install_remote_durability_checkpoint(
            adapter,
            checkpoint,
            fatal_exit=fatal_exit,
        )

        def handler(_arguments):
            order.append("side-effect")
            return {"status": "CREATED"}

        with self.assertRaises(_ColdExit) as caught:
            adapter._invoke_mutation("create_product_opportunity", handler, {})
        self.assertEqual(caught.exception.code, 92)
        self.assertEqual(order, ["prepared", "side-effect", "checkpoint", "exit:92"])

    def test_installation_is_idempotent(self) -> None:
        adapter = types.SimpleNamespace()
        calls: list[str] = []

        def original_invoke(tool_name, handler, arguments):
            return handler(arguments)

        adapter._invoke_mutation = original_invoke

        def checkpoint() -> None:
            calls.append("checkpoint")

        first = install_remote_durability_checkpoint(adapter, checkpoint)
        second = install_remote_durability_checkpoint(adapter, checkpoint)
        self.assertIs(first, second)
        adapter._invoke_mutation("append_candidate_discovery", lambda _args: {}, {})
        self.assertEqual(calls, ["checkpoint"])


if __name__ == "__main__":
    unittest.main()
