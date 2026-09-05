from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from mcp import chatgpt_oauth_transport as transport


STATIC_TOKEN = "S" * 64


def _dispatch(method: str, params: dict):
    return {"method": method, "params": params}


def _health():
    return {"status": "ok"}


def _diagnostic_export():
    return {"schema": "cbi.v64-c279-single-session-export.v1"}


class V64C279TransportMainForwardingTests(unittest.TestCase):
    def test_main_forwards_diagnostic_bindings_to_serve(self):
        parser = mock.Mock()
        parser.parse_args.return_value = SimpleNamespace(host="127.0.0.1", port=18787)
        with mock.patch.object(transport.base, "_parser", return_value=parser), mock.patch.object(
            transport, "serve", return_value=0
        ) as serve:
            result = transport.main(
                _dispatch,
                health=_health,
                diagnostic_export=_diagnostic_export,
                diagnostic_static_bearer=STATIC_TOKEN,
            )

        self.assertEqual(result, 0)
        serve.assert_called_once_with(
            _dispatch,
            health=_health,
            host="127.0.0.1",
            port=18787,
            diagnostic_export=_diagnostic_export,
            diagnostic_static_bearer=STATIC_TOKEN,
        )


if __name__ == "__main__":
    unittest.main()
