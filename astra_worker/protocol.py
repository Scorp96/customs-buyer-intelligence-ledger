from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any


class ProtocolError(ValueError):
    """Raised when an ASTRA worker protocol payload is malformed or unverifiable."""


_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PREFIXES = {
    "task": "ASTRA_TASK_V1 ",
    "receipt": "ASTRA_RECEIPT_V1 ",
}


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> Any:
    raise ProtocolError(f"floats are not allowed: {value}")


def _reject_constant(token: str) -> Any:
    raise ProtocolError(f"non-finite JSON value is not allowed: {token}")


def parse_strict_json(raw: str) -> Any:
    if not isinstance(raw, str):
        raise ProtocolError("JSON input must be text")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_object_pairs_no_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except ProtocolError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProtocolError(str(exc)) from exc


def _validate_canonical_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if not (-(2**63) <= value <= 2**63 - 1):
            raise ProtocolError("integer outside signed 64-bit range")
        return
    if isinstance(value, list):
        for item in value:
            _validate_canonical_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError("object keys must be strings")
            _validate_canonical_value(item)
        return
    raise ProtocolError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json_v1(value: Any) -> bytes:
    _validate_canonical_value(value)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(str(exc)) from exc
    return text.encode("utf-8")


def _validate_hmac_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or not key:
        raise ProtocolError("HMAC key must be non-empty bytes")
    return key


def hmac_sha256_hex(key: bytes, value: Any) -> str:
    return hmac.new(
        _validate_hmac_key(key),
        canonical_json_v1(value),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac_sha256(key: bytes, value: Any, expected_hex: str) -> None:
    if not isinstance(expected_hex, str) or _SIGNATURE_RE.fullmatch(expected_hex) is None:
        raise ProtocolError("HMAC signature must be 64 hexadecimal characters")
    actual = hmac_sha256_hex(key, value)
    if not hmac.compare_digest(actual, expected_hex.lower()):
        raise ProtocolError("HMAC verification failed")


def _prefix_for_kind(kind: str) -> str:
    try:
        return _PREFIXES[kind]
    except KeyError as exc:
        raise ProtocolError(f"unsupported signed envelope kind: {kind!r}") from exc


def encode_signed_envelope(kind: str, payload: dict[str, Any], signature: str) -> str:
    prefix = _prefix_for_kind(kind)
    if not isinstance(payload, dict):
        raise ProtocolError("signed envelope payload must be an object")
    if not isinstance(signature, str) or _SIGNATURE_RE.fullmatch(signature) is None:
        raise ProtocolError("signed envelope signature must be 64 hexadecimal characters")
    envelope = {"payload": payload, "signature": signature.lower()}
    return prefix + canonical_json_v1(envelope).decode("utf-8")


def decode_signed_envelope(text: str, expected_kind: str) -> tuple[dict[str, Any], str]:
    prefix = _prefix_for_kind(expected_kind)
    if not isinstance(text, str) or not text.startswith(prefix):
        raise ProtocolError(f"signed envelope prefix does not match {expected_kind!r}")
    parsed = parse_strict_json(text[len(prefix) :])
    if not isinstance(parsed, dict) or set(parsed) != {"payload", "signature"}:
        raise ProtocolError("signed envelope must contain only payload and signature")
    payload = parsed["payload"]
    signature = parsed["signature"]
    if not isinstance(payload, dict):
        raise ProtocolError("signed envelope payload must be an object")
    if not isinstance(signature, str) or _SIGNATURE_RE.fullmatch(signature) is None:
        raise ProtocolError("signed envelope signature must be 64 hexadecimal characters")
    return payload, signature.lower()
