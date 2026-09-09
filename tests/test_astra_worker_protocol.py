from __future__ import annotations

import unittest

from astra_worker.protocol import (
    ProtocolError,
    canonical_json_v1,
    decode_signed_envelope,
    encode_signed_envelope,
    hmac_sha256_hex,
    parse_strict_json,
    verify_hmac_sha256,
)


class CanonicalProtocolTests(unittest.TestCase):
    def test_duplicate_key_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1,"a":2}')

    def test_float_and_non_finite_numbers_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":1.5}')
        with self.assertRaises(ProtocolError):
            parse_strict_json('{"a":NaN}')

    def test_canonical_bytes_are_stable_utf8(self) -> None:
        left = parse_strict_json('{"z":"越南","a":1}')
        right = parse_strict_json('{"a":1,"z":"越南"}')
        self.assertEqual(canonical_json_v1(left), canonical_json_v1(right))
        self.assertEqual(
            canonical_json_v1(left),
            b'{"a":1,"z":"\xe8\xb6\x8a\xe5\x8d\x97"}',
        )

    def test_out_of_range_integer_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            canonical_json_v1({"n": 2**63})

    def test_changed_payload_invalidates_hmac(self) -> None:
        key = b"k" * 32
        value = {"task_id": "t1", "n": 1}
        signature = hmac_sha256_hex(key, value)
        verify_hmac_sha256(key, value, signature)
        with self.assertRaises(ProtocolError):
            verify_hmac_sha256(key, {"task_id": "t1", "n": 2}, signature)

    def test_signed_envelope_round_trip_and_strict_shape(self) -> None:
        payload = {"task_id": "t1", "n": 1}
        signature = "a" * 64
        encoded = encode_signed_envelope("task", payload, signature)
        decoded_payload, decoded_signature = decode_signed_envelope(encoded, "task")
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(decoded_signature, signature)

        with self.assertRaises(ProtocolError):
            decode_signed_envelope(encoded, "receipt")
        with self.assertRaises(ProtocolError):
            decode_signed_envelope(
                'ASTRA_TASK_V1 {"payload":{},"signature":"' + signature + '","extra":1}',
                "task",
            )


if __name__ == "__main__":
    unittest.main()
