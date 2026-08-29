from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .errors import ValidationError


ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
PENDING_ID_RE = re.compile(r"PEND-[0-9TZ-]+-[0-9a-f]{12}")


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    material = value if isinstance(value, (bytes, bytearray)) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    # Preserve letters and digits from every script.  The previous range-based
    # expression silently discarded combining marks used by some Vietnamese and
    # South/Southeast Asian names, weakening canonical matching.
    return "".join(
        character
        for character in text
        if unicodedata.category(character)[:1] in {"L", "N", "M"}
    )


def normalized_values(value: Any) -> set[str]:
    if value is None:
        return set()
    items: Iterable[Any]
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    return {normalized for item in items if (normalized := normalize_scalar(item))}


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable liveness probe on Windows.  A
        # query-only process handle does not mutate the target process.
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Access denied means the process exists but is protected.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _recover_stale_lock(path: Path) -> bool:
    """Remove an abandoned sentinel lock only after an identity recheck."""

    try:
        before = path.stat()
        content = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return True
    except PermissionError:
        # The owner may still be flushing the newly-created sentinel on
        # Windows.  Treat it as active and retry normally.
        return False
    match = re.search(r"\bpid=(\d+)\b", content)
    if match:
        stale = not _pid_is_alive(int(match.group(1)))
    else:
        # An unparseable lock could be in the middle of creation.  Only recover
        # it after a conservative age threshold.
        stale = time.time() - before.st_mtime > 60.0
    if not stale:
        return False
    try:
        after = path.stat()
        current = path.read_text(encoding="utf-8", errors="replace")
        if (
            before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or content != current
        ):
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        return False


@contextmanager
def exclusive_file_lock(path: Path, *, timeout_seconds: float = 5.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    token = secrets.token_hex(16)
    owner = f"pid={os.getpid()} created={iso_utc()} token={token}"
    while descriptor is None:
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, owner.encode("utf-8"))
            os.fsync(descriptor)
        except (FileExistsError, PermissionError):
            if _recover_stale_lock(path):
                continue
            if time.monotonic() >= deadline:
                raise ValidationError(f"runtime lock timeout: {path.name}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Windows can briefly deny deletion while a waiter is reading the
        # sentinel.  Retry the ownership-checked cleanup instead of leaving a
        # live-PID lock that would block the process indefinitely.
        for _ in range(200):
            try:
                if path.read_text(encoding="utf-8", errors="replace") != owner:
                    break
                path.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.01)


class HashChainLog:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"{self.path.name}: corrupt JSONL at line {line_number}") from exc
            if event.get("seq") != line_number or event.get("prev_hash") != previous:
                raise ValidationError(f"{self.path.name}: hash chain broken at line {line_number}")
            claimed = event.get("event_hash")
            unsigned = {key: value for key, value in event.items() if key != "event_hash"}
            if claimed != digest(unsigned):
                raise ValidationError(f"{self.path.name}: event hash mismatch at line {line_number}")
            previous = claimed
            events.append(event)
        return events

    def read(self) -> list[dict[str, Any]]:
        with exclusive_file_lock(self.lock_path, timeout_seconds=15.0):
            return self._read_unlocked()

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with exclusive_file_lock(self.lock_path):
            events = self._read_unlocked()
            event = {
                "seq": len(events) + 1,
                "prev_hash": events[-1]["event_hash"] if events else "0" * 64,
                "event_type": event_type,
                "recorded_at": iso_utc(),
                "payload": payload,
            }
            event["event_hash"] = digest(event)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event


class CanonicalRegistry:
    """Append-only local account resolver; production data never enters plugin source."""

    def __init__(self, root: Path, session_root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = HashChainLog(self.root / "accounts.jsonl")
        self.session_root = session_root

    @staticmethod
    def _keys(account: dict[str, Any]) -> dict[str, set[str]]:
        aliases = account.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        elif not isinstance(aliases, list):
            raise ValidationError("account.aliases: string array required")
        return {
            "names": normalized_values([account.get("name"), *aliases]),
            "tax_ids": normalized_values(account.get("tax_ids") or account.get("tax_id")),
            "addresses": normalized_values(account.get("addresses") or account.get("address")),
            "external_ids": normalized_values(account.get("external_ids")),
            "countries": normalized_values(account.get("country")),
        }

    def _session_accounts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.session_root.glob("INV-*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    first_line = handle.readline()
                event = json.loads(first_line)
                payload = event.get("payload") or {}
                account = payload.get("account") or {}
                account_id = str(account.get("account_id") or "").strip()
                if account_id:
                    rows.append({
                        "account_id": account_id,
                        "account": account,
                        "origin": "SESSION_HEADER",
                        "investigation_id": payload.get("investigation_id"),
                    })
            except (OSError, IndexError, json.JSONDecodeError):
                continue
        return rows

    def entries(self) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for event in self.log.read():
            payload = event["payload"]
            rows[payload["account_id"]] = {
                "account_id": payload["account_id"],
                "account": payload["account"],
                "origin": "CANONICAL_REGISTRY",
                "registry_seq": event["seq"],
            }
        for row in self._session_accounts():
            rows.setdefault(row["account_id"], row)
        return list(rows.values())

    @staticmethod
    def _match_score(candidate: dict[str, set[str]], row: dict[str, set[str]], requested_id: str, row_id: str) -> tuple[int, list[str]]:
        reasons: list[str] = []
        score = 0
        if requested_id and requested_id.casefold() == row_id.casefold():
            score, reasons = 100, ["EXACT_ACCOUNT_ID"]
        if candidate["tax_ids"] & row["tax_ids"]:
            score, reasons = max(score, 95), reasons + ["TAX_ID"]
        same_country = not candidate["countries"] or not row["countries"] or bool(candidate["countries"] & row["countries"])
        if same_country and candidate["names"] & row["names"]:
            score, reasons = max(score, 85), reasons + ["NAME_COUNTRY"]
        if same_country and candidate["addresses"] & row["addresses"]:
            score, reasons = max(score, 80), reasons + ["ADDRESS_COUNTRY"]
        if candidate["external_ids"] & row["external_ids"]:
            score, reasons = max(score, 90), reasons + ["EXTERNAL_ID"]
        return score, sorted(set(reasons))

    def resolve(self, candidate: dict[str, Any], *, requested_account_id: str = "") -> dict[str, Any]:
        requested_account_id = requested_account_id.strip()
        if requested_account_id and not ACCOUNT_ID_RE.fullmatch(requested_account_id):
            raise ValidationError("requested_account_id: invalid")
        candidate_keys = self._keys(candidate)
        if not requested_account_id and not any(
            candidate_keys[key] for key in ("names", "tax_ids", "addresses", "external_ids")
        ):
            raise ValidationError("candidate requires a name, tax ID, address, or external ID")
        matches: list[dict[str, Any]] = []
        for row in self.entries():
            score, reasons = self._match_score(candidate_keys, self._keys(row["account"]), requested_account_id, row["account_id"])
            if score:
                matches.append({
                    "account_id": row["account_id"],
                    "score": score,
                    "reasons": reasons,
                    "origin": row["origin"],
                })
        matches.sort(key=lambda item: (-item["score"], item["account_id"].casefold()))
        if not matches:
            return {"status": "NOT_FOUND", "match": None, "candidates": []}
        top_score = matches[0]["score"]
        top = [item for item in matches if item["score"] == top_score]
        unique_ids = {item["account_id"].casefold() for item in top}
        if len(unique_ids) > 1:
            return {"status": "AMBIGUOUS_MATCH", "match": None, "candidates": top}
        return {"status": "MATCHED", "match": top[0], "candidates": matches}

    def resolve_or_create(
        self,
        candidate: dict[str, Any],
        *,
        requested_account_id: str = "",
        create_if_missing: bool = True,
    ) -> dict[str, Any]:
        with exclusive_file_lock(self.root / "registry-write.lock"):
            resolved = self.resolve(candidate, requested_account_id=requested_account_id)
            if resolved["status"] != "NOT_FOUND":
                return resolved
            if not create_if_missing:
                return resolved
            entries = self.entries()
            account_id = requested_account_id.strip()
            if not account_id:
                numbers = [int(match.group(1)) for row in entries if (match := re.fullmatch(r"C(\d+)", row["account_id"], flags=re.I))]
                account_id = f"C{max(numbers, default=0) + 1:03d}"
            if any(row["account_id"].casefold() == account_id.casefold() for row in entries):
                raise ValidationError("requested_account_id already belongs to another canonical account")
            account = {**candidate, "account_id": account_id}
            self.log.append("CANONICAL_ACCOUNT_CREATED", {
                "account_id": account_id,
                "account": account,
                "identity_keys_sha256": digest({key: sorted(value) for key, value in self._keys(account).items()}),
                "created_at": iso_utc(),
            })
            return {
                "status": "CREATED",
                "match": {"account_id": account_id, "score": 100, "reasons": ["ATOMIC_ALLOCATION"], "origin": "CANONICAL_REGISTRY"},
                "candidates": [],
            }


class PendingReceiptJournal:
    ALLOWED_TARGETS = {
        "append_information_record",
        "append_execution_receipt",
        "append_provider_receipt",
        "append_peer_receipt",
        "append_crm_writeback_receipt",
    }

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = HashChainLog(self.root / "journal-events.jsonl")

    def path(self, journal_id: str) -> Path:
        if not PENDING_ID_RE.fullmatch(journal_id):
            raise ValidationError("journal_id: invalid")
        return self.root / f"{journal_id}.json"

    def queue(self, target_tool: str, payload: dict[str, Any], journal_id: str = "") -> dict[str, Any]:
        if target_tool not in self.ALLOWED_TARGETS:
            raise ValidationError("target_tool is not a journal-safe append operation")
        if not isinstance(payload, dict):
            raise ValidationError("payload: object required")
        investigation_id = str(payload.get("investigation_id") or "").strip()
        if not investigation_id:
            raise ValidationError("payload.investigation_id required")
        journal_id = journal_id.strip() or f"PEND-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
        request_sha256 = digest({"target_tool": target_tool, "payload": payload})
        with exclusive_file_lock(self.root / "journal-write.lock"):
            for row in self.entries():
                if row["request_sha256"] == request_sha256:
                    existing = self.load(row["journal_id"])
                    return {
                        **existing,
                        "status": row["status"],
                        "queued": False,
                        "deduplicated": True,
                        "path": row["path"],
                    }
            envelope = {
                "schema": "cbi.pending-receipt.v5.4",
                "journal_id": journal_id,
                "investigation_id": investigation_id,
                "target_tool": target_tool,
                "payload": payload,
                "queued_at": iso_utc(),
                "request_sha256": request_sha256,
                "status": "PENDING",
            }
            path = self.path(journal_id)
            try:
                descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, (canonical_json(envelope) + "\n").encode("utf-8"))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except FileExistsError:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("request_sha256") != request_sha256:
                    raise ValidationError("journal_id collision with different payload")
                return {**existing, "queued": False, "deduplicated": True, "path": str(path)}
            self.events.append("PENDING_RECEIPT_QUEUED", {
                "journal_id": journal_id,
                "investigation_id": investigation_id,
                "target_tool": target_tool,
                "request_sha256": request_sha256,
            })
            return {**envelope, "queued": True, "deduplicated": False, "path": str(path)}

    def entries(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self.events.read():
            payload = event["payload"]
            journal_id = payload.get("journal_id")
            if journal_id:
                latest[journal_id] = {
                    "journal_id": journal_id,
                    "event_type": event["event_type"],
                    "recorded_at": event["recorded_at"],
                    **payload,
                }
        output: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("PEND-*.json")):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"{path.name}: corrupt pending receipt envelope") from exc
            expected = digest({"target_tool": envelope.get("target_tool"), "payload": envelope.get("payload")})
            if envelope.get("request_sha256") != expected:
                raise ValidationError(f"{path.name}: pending receipt hash mismatch")
            status = latest.get(envelope["journal_id"], {})
            output.append({
                "journal_id": envelope["journal_id"],
                "investigation_id": envelope["investigation_id"],
                "target_tool": envelope["target_tool"],
                "request_sha256": envelope["request_sha256"],
                "queued_at": envelope["queued_at"],
                "status": status.get("status", "PENDING"),
                "last_event_type": status.get("event_type", "PENDING_RECEIPT_QUEUED"),
                "last_recorded_at": status.get("recorded_at", envelope["queued_at"]),
                "path": str(path),
            })
        return output

    def load(self, journal_id: str) -> dict[str, Any]:
        path = self.path(journal_id)
        if not path.is_file():
            raise ValidationError("pending journal entry not found")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        expected = digest({"target_tool": envelope["target_tool"], "payload": envelope["payload"]})
        if envelope.get("request_sha256") != expected:
            raise ValidationError(f"{journal_id}: pending receipt hash mismatch")
        return envelope

    def record_sync(self, envelope: dict[str, Any], *, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
        self.events.append("PENDING_RECEIPT_SYNC_RESULT", {
            "journal_id": envelope["journal_id"],
            "investigation_id": envelope["investigation_id"],
            "target_tool": envelope["target_tool"],
            "request_sha256": envelope["request_sha256"],
            "status": status,
            "result_digest": digest(result or {}),
            "error": error,
        })

    def sync(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        *,
        investigation_id: str = "",
        limit: int = 100,
        dry_run: bool = False,
        equivalent: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 1000:
            raise ValidationError("limit must be between 1 and 1000")
        # Selecting a pending row and recording its terminal sync result is one
        # recovery transaction.  Without a cross-process lock, two repair jobs
        # can observe the same PENDING row and invoke the handler twice before
        # either one records SYNCED.  The downstream append methods are normally
        # idempotent, but recovery itself must not depend on that assumption.
        with exclusive_file_lock(self.root / "journal-sync.lock", timeout_seconds=60.0):
            rows = [row for row in self.entries() if row["status"] not in {"SYNCED", "DEDUPLICATED"}]
            if investigation_id:
                rows = [row for row in rows if row["investigation_id"] == investigation_id]
            rows = rows[:limit]
            outcomes: list[dict[str, Any]] = []
            for row in rows:
                envelope = self.load(row["journal_id"])
                if dry_run:
                    outcomes.append({"journal_id": row["journal_id"], "status": "WOULD_SYNC", "target_tool": row["target_tool"]})
                    continue
                handler = handlers.get(envelope["target_tool"])
                if handler is None:
                    self.record_sync(envelope, status="FAILED_VALIDATION", error="handler unavailable")
                    outcomes.append({"journal_id": row["journal_id"], "status": "FAILED_VALIDATION", "error": "handler unavailable"})
                    continue
                try:
                    result = handler(envelope["payload"])
                    self.record_sync(envelope, status="SYNCED", result=result)
                    outcomes.append({"journal_id": row["journal_id"], "status": "SYNCED", "result": result})
                except ValidationError as exc:
                    if equivalent and equivalent(envelope["target_tool"], envelope["payload"]):
                        self.record_sync(envelope, status="DEDUPLICATED", error=str(exc))
                        outcomes.append({"journal_id": row["journal_id"], "status": "DEDUPLICATED", "reason": str(exc)})
                    else:
                        self.record_sync(envelope, status="FAILED_VALIDATION", error=str(exc))
                        outcomes.append({"journal_id": row["journal_id"], "status": "FAILED_VALIDATION", "error": str(exc)})
                except Exception as exc:  # Preserve the receipt for a later recovery attempt.
                    error = f"{type(exc).__name__}: {exc}"
                    self.record_sync(envelope, status="RETRYABLE_FAILURE", error=error)
                    outcomes.append({"journal_id": row["journal_id"], "status": "RETRYABLE_FAILURE", "error": error})
        counts: dict[str, int] = {}
        for outcome in outcomes:
            counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
        return {"dry_run": dry_run, "processed": len(outcomes), "counts": counts, "outcomes": outcomes}
