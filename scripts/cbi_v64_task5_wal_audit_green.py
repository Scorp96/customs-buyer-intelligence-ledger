from __future__ import annotations

from pathlib import Path


def main() -> int:
    path = Path("mcp/server_v61.py")
    source = path.read_text(encoding="utf-8")
    if "def _mutation_wal_audit(" in source:
        raise SystemExit("WAL audit already implemented; refusing duplicate patch")
    anchor = "\n\ndef _normalize_start_contract(arguments: dict[str, Any]) -> dict[str, Any]:\n"
    if anchor not in source:
        raise SystemExit("expected server_v61 insertion anchor not found")
    block = r'''

_WAL_AUDIT_ALLOWED_STATUSES = {"COMMITTED_ERROR", "COMMITTED"}
_WAL_AUDIT_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_WAL_AUDIT_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_WAL_AUDIT_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_WAL_AUDIT_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)\s*[:=]\s*[^\s,;]+"
)
_WAL_AUDIT_ERROR_CODE_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,63})(?=[:\s]|$)")


def _sanitize_wal_error_message(value: Any) -> str:
    message = str(value or "").replace("\r", " ").replace("\n", " ")
    message = _WAL_AUDIT_EMAIL_RE.sub("[REDACTED_EMAIL]", message)
    message = _WAL_AUDIT_PHONE_RE.sub("[REDACTED_PHONE]", message)
    message = _WAL_AUDIT_BEARER_RE.sub("Bearer [REDACTED]", message)
    message = _WAL_AUDIT_SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)
    message = " ".join(message.split())
    return message[:240]


def _wal_terminal_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").upper()
    if not status and isinstance(row.get("result"), dict):
        return "COMMITTED"
    return status


def _mutation_wal_audit(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValidationError("mutation WAL audit arguments must be an object")
    status_filter = str(arguments.get("status") or "COMMITTED_ERROR").strip().upper()
    if status_filter not in _WAL_AUDIT_ALLOWED_STATUSES:
        raise ValidationError("status must be COMMITTED_ERROR or COMMITTED")
    limit = arguments.get("limit", 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValidationError("limit must be an integer from 1 to 500")

    root = _journal_path()
    invalid_record_count = 0
    projected: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                invalid_record_count += 1
                continue
            if not isinstance(row, dict) or row.get("schema") != _WAL_SCHEMA:
                invalid_record_count += 1
                continue
            terminal_status = _wal_terminal_status(row)
            if terminal_status not in _WAL_AUDIT_ALLOWED_STATUSES:
                if terminal_status not in {"PREPARED"}:
                    invalid_record_count += 1
                continue
            if terminal_status != status_filter:
                continue

            error = row.get("error") if isinstance(row.get("error"), dict) else {}
            raw_message = str(error.get("message") or "") if terminal_status == "COMMITTED_ERROR" else ""
            safe_message = _sanitize_wal_error_message(raw_message)
            code_match = _WAL_AUDIT_ERROR_CODE_RE.match(raw_message.strip())
            raw_before = row.get("state_version_before")
            state_before = (
                int(raw_before)
                if isinstance(raw_before, int) and not isinstance(raw_before, bool)
                else None
            )
            projected.append(
                {
                    "tool": str(row.get("tool") or ""),
                    "request_sha256": str(row.get("request_sha256") or ""),
                    "state_version_before": state_before,
                    "prepared_at": str(row.get("prepared_at") or ""),
                    "completed_at": str(row.get("completed_at") or ""),
                    "terminal_status": terminal_status,
                    "error_type": (
                        (str(error.get("type") or "") or None)
                        if terminal_status == "COMMITTED_ERROR"
                        else None
                    ),
                    "error_code": code_match.group(1) if code_match else None,
                    "error_message": safe_message if terminal_status == "COMMITTED_ERROR" else "",
                }
            )

    projected.sort(
        key=lambda row: (
            str(row.get("completed_at") or ""),
            str(row.get("prepared_at") or ""),
            str(row.get("tool") or ""),
            str(row.get("request_sha256") or ""),
        ),
        reverse=True,
    )
    matched_count = len(projected)
    rows = projected[:limit]
    return {
        "schema": "cbi.mutation-wal-audit.v6.4",
        "read_only": True,
        "status_filter": status_filter,
        "limit": limit,
        "count": len(rows),
        "matched_count": matched_count,
        "invalid_record_count": invalid_record_count,
        "rows": rows,
        "contains_raw_arguments": False,
        "contains_idempotency_keys": False,
        "contains_raw_results": False,
        "contains_resource_snapshots": False,
    }
'''
    path.write_text(source.replace(anchor, block + anchor, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
