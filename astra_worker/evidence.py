from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Mapping

from astra_supervisor.local_executor import ExecutionResult
from .compiler import intended_final_hashes
from .models import ReceiptEnvelope, TaskEnvelope


class EvidenceError(RuntimeError):
    """Raised when final-state evidence cannot prove exact signed confinement."""


_MAX_PATCH_CHUNK_BYTES = 48 * 1024
_DANGEROUS_ENV_PREFIXES = ("GIT_", "SSH_", "GCM_")
_DANGEROUS_ENV_NAMES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\r\n\t\"'<>|]*")
_UNIX_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9_:])/(?:[^\s/\"']+/)*[^\s\"']*")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|authorization)\s*[:=]\s*([^\s]+)"
)
_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)([^\s]+)")


@dataclass(frozen=True)
class EvidenceLimits:
    max_changed_files: int
    max_diff_bytes: int
    max_command_output_bytes: int

    def __post_init__(self) -> None:
        for field_name in ("max_changed_files", "max_diff_bytes", "max_command_output_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise EvidenceError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class ChangeEvidence:
    changed_paths: tuple[str, ...]
    observed_final_hashes: Mapping[str, str | None]
    patch_sha256: str
    diff_bytes: int


@dataclass(frozen=True)
class PatchChunk:
    index: int
    total: int
    text: str
    sha256: str
    patch_sha256: str


def _trusted_git() -> str:
    resolved = shutil.which("git")
    if not resolved or not Path(resolved).is_file():
        raise EvidenceError("trusted Git executable was not found")
    return str(Path(resolved).resolve())


def _git_env(home: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper.startswith(_DANGEROUS_ENV_PREFIXES) or upper in _DANGEROUS_ENV_NAMES:
            continue
        env[key] = value
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / "xdg")
    if os.name == "nt":
        env["USERPROFILE"] = str(home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    return env


def _run_git(root: Path, *args: str, check: bool = True) -> bytes:
    git = _trusted_git()
    try:
        with tempfile.TemporaryDirectory(prefix="astra-evidence-git-") as temporary_home:
            home = Path(temporary_home)
            (home / "xdg").mkdir()
            completed = subprocess.run(
                [
                    git,
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.quotePath=false",
                    *args,
                ],
                cwd=str(root),
                env=_git_env(home),
                capture_output=True,
                timeout=60,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("trusted Git evidence subprocess could not be executed") from exc
    if check and completed.returncode != 0:
        raise EvidenceError(f"Git evidence command failed with exit code {completed.returncode}")
    return completed.stdout


def _decode_git_utf8(raw: bytes, context: str) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"{context} is not unambiguous UTF-8") from exc


def _status_paths(root: Path) -> tuple[tuple[str, str], ...]:
    raw = _run_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignored=matching",
        "--no-renames",
        "--ignore-submodules=none",
    )
    if not raw:
        return ()
    records: list[tuple[str, str]] = []
    for item in raw.split(b"\x00"):
        if not item:
            continue
        if len(item) < 4 or item[2:3] != b" ":
            raise EvidenceError("Git status record has an unexpected shape")
        code = _decode_git_utf8(item[:2], "Git status code")
        path = _decode_git_utf8(item[3:], "Git status path").replace("\\", "/")
        if not path:
            raise EvidenceError("Git status reported an empty path")
        records.append((code, path))
    return tuple(records)


def _changed_paths_from_status(status: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    ignored = [path for code, path in status if code == "!!"]
    if ignored:
        raise EvidenceError("ignored worktree artifacts are not allowed in final evidence")
    return tuple(sorted({path for _code, path in status}, key=str.casefold))


def _numstat(root: Path) -> tuple[tuple[str, str, str], ...]:
    raw = _run_git(
        root,
        "diff",
        "--numstat",
        "-z",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "HEAD",
        "--",
    )
    if not raw:
        return ()
    result: list[tuple[str, str, str]] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise EvidenceError("Git numstat record has an unexpected shape")
        added = _decode_git_utf8(fields[0], "Git numstat added count")
        deleted = _decode_git_utf8(fields[1], "Git numstat deleted count")
        path = _decode_git_utf8(fields[2], "Git numstat path").replace("\\", "/")
        result.append((added, deleted, path))
    return tuple(result)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EvidenceError("final-state file could not be read") from exc
    return digest.hexdigest()


def _resolve_repo_path(root: Path, relative_path: str) -> Path:
    parts = relative_path.replace("\\", "/").split("/")
    lexical = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                raise EvidenceError(f"final-state path traverses a symlink: {relative_path}")
        except OSError as exc:
            raise EvidenceError("final-state symlink state could not be proven") from exc
    try:
        resolved = lexical.resolve(strict=False)
        common = os.path.commonpath([str(root), str(resolved)])
    except (OSError, ValueError) as exc:
        raise EvidenceError("final-state path could not be confined to worktree") from exc
    if common != str(root):
        raise EvidenceError("final-state path escaped worktree")
    if os.path.normcase(os.path.normpath(str(lexical))) != os.path.normcase(os.path.normpath(str(resolved))):
        raise EvidenceError("final-state path resolves through a filesystem alias")
    return resolved


def _assert_final_hashes(
    root: Path,
    intended_hashes: Mapping[str, str | None],
) -> dict[str, str | None]:
    observed: dict[str, str | None] = {}
    for path in sorted(intended_hashes, key=str.casefold):
        expected = intended_hashes[path]
        target = _resolve_repo_path(root, path)
        if expected is None:
            if target.exists() or target.is_symlink():
                raise EvidenceError(f"signed delete target survived execution: {path}")
            observed[path] = None
            continue
        if not isinstance(expected, str) or len(expected) != 64:
            raise EvidenceError("intended final hash is malformed")
        if not target.is_file():
            raise EvidenceError(f"signed final file is missing or non-regular: {path}")
        actual = _sha256_file(target)
        if actual != expected.lower():
            raise EvidenceError(f"signed final SHA-256 mismatch: {path}")
        observed[path] = actual
    return observed


def _signed_intended_hashes(
    task: TaskEnvelope,
    supplied: Mapping[str, str | None] | None = None,
) -> dict[str, str | None]:
    try:
        trusted = intended_final_hashes(task)
    except ValueError as exc:
        raise EvidenceError("signed mutation authority could not be derived") from exc
    if supplied is not None:
        try:
            candidate = dict(supplied)
        except (TypeError, ValueError) as exc:
            raise EvidenceError("caller supplied intended hashes are malformed") from exc
        if candidate != trusted:
            raise EvidenceError("caller supplied intended hashes do not match the signed task")
    return trusted


def _is_tracked(root: Path, path: str) -> bool:
    raw = _run_git(
        root,
        "ls-files",
        "--error-unmatch",
        "--",
        path,
        check=False,
    )
    return bool(raw)


def _new_file_patch(root: Path, path: str) -> bytes:
    target = _resolve_repo_path(root, path)
    try:
        raw = target.read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"new file is not readable UTF-8 text: {path}") from exc
    if b"\x00" in raw:
        raise EvidenceError(f"binary new file is not allowed in patch evidence: {path}")
    lines = text.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            [],
            lines,
            fromfile="/dev/null",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    header = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
    return (header + "".join(diff)).encode("utf-8")


def _build_patch_bytes(root: Path, changed_paths: tuple[str, ...]) -> bytes:
    tracked_patch = _run_git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--full-index",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "HEAD",
        "--",
    )
    try:
        tracked_patch.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError("Git unified diff is not UTF-8 text") from exc
    if b"Binary files " in tracked_patch or b"GIT binary patch" in tracked_patch:
        raise EvidenceError("binary diff is not allowed")

    additions: list[bytes] = []
    for path in changed_paths:
        target = root.joinpath(*path.split("/"))
        if target.exists() and not _is_tracked(root, path):
            additions.append(_new_file_patch(root, path))
    patch = tracked_patch + b"".join(additions)
    try:
        patch.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError("complete patch is not UTF-8") from exc
    return patch


def verify_final_state(
    task: TaskEnvelope,
    worktree: Path,
    intended_hashes: Mapping[str, str | None],
    limits: EvidenceLimits,
) -> ChangeEvidence:
    if not isinstance(task, TaskEnvelope):
        raise EvidenceError("typed task envelope is required")
    if not isinstance(limits, EvidenceLimits):
        raise EvidenceError("trusted local evidence limits are required")
    trusted_hashes = _signed_intended_hashes(task, intended_hashes)
    root = Path(worktree).resolve()
    if not root.is_dir():
        raise EvidenceError("worktree root does not exist")

    head = _decode_git_utf8(_run_git(root, "rev-parse", "HEAD"), "Git HEAD").strip().lower()
    if head != task.base_commit_sha:
        raise EvidenceError("worktree HEAD no longer matches signed base commit")

    signed_paths = tuple(sorted(trusted_hashes, key=str.casefold))
    if len({path.casefold() for path in signed_paths}) != len(signed_paths):
        raise EvidenceError("intended final paths are ambiguous")

    status_before = _status_paths(root)
    changed_paths = _changed_paths_from_status(status_before)
    signed_identity = {path.casefold() for path in signed_paths}
    undeclared = [path for path in changed_paths if path.casefold() not in signed_identity]
    if undeclared:
        raise EvidenceError(f"undeclared changed path detected: {undeclared[0]}")

    effective_files = min(limits.max_changed_files, task.acceptance.max_changed_files)
    if len(changed_paths) > effective_files:
        raise EvidenceError("changed-file count exceeds effective task/local limit")

    observed = _assert_final_hashes(root, trusted_hashes)
    for added, deleted, path in _numstat(root):
        if added == "-" or deleted == "-":
            raise EvidenceError(f"binary tracked diff is not allowed: {path}")

    patch = _build_patch_bytes(root, changed_paths)
    effective_diff = min(limits.max_diff_bytes, task.acceptance.max_diff_bytes)
    if len(patch) > effective_diff:
        raise EvidenceError("unified diff exceeds effective task/local byte limit")

    observed_after = _assert_final_hashes(root, trusted_hashes)
    status_after = _status_paths(root)
    if status_after != status_before or observed_after != observed:
        raise EvidenceError("worktree changed while final evidence was being collected")

    return ChangeEvidence(
        changed_paths=changed_paths,
        observed_final_hashes=observed,
        patch_sha256=hashlib.sha256(patch).hexdigest(),
        diff_bytes=len(patch),
    )


def build_text_patch(
    task: TaskEnvelope,
    worktree: Path,
    evidence: ChangeEvidence,
) -> bytes:
    if not isinstance(task, TaskEnvelope) or not isinstance(evidence, ChangeEvidence):
        raise EvidenceError("typed task and change evidence are required")
    root = Path(worktree).resolve()
    trusted_hashes = _signed_intended_hashes(task)
    if dict(evidence.observed_final_hashes) != trusted_hashes:
        raise EvidenceError("change evidence final hashes are not bound to the signed task")

    status_before = _status_paths(root)
    changed_before = _changed_paths_from_status(status_before)
    if changed_before != evidence.changed_paths:
        raise EvidenceError("worktree changed after final-state verification")
    observed_before = _assert_final_hashes(root, trusted_hashes)
    if observed_before != dict(evidence.observed_final_hashes):
        raise EvidenceError("worktree final hashes drifted after verification")

    patch = _build_patch_bytes(root, evidence.changed_paths)
    if len(patch) != evidence.diff_bytes or hashlib.sha256(patch).hexdigest() != evidence.patch_sha256:
        raise EvidenceError("worktree patch drifted after final-state verification")

    status_after = _status_paths(root)
    observed_after = _assert_final_hashes(root, trusted_hashes)
    if status_after != status_before or observed_after != observed_before:
        raise EvidenceError("worktree changed while patch evidence was being packaged")
    return patch


def chunk_patch(patch: bytes, *, max_payload_bytes: int = _MAX_PATCH_CHUNK_BYTES) -> tuple[PatchChunk, ...]:
    if not isinstance(patch, bytes):
        raise EvidenceError("patch must be UTF-8 bytes")
    if isinstance(max_payload_bytes, bool) or not isinstance(max_payload_bytes, int) or max_payload_bytes <= 0:
        raise EvidenceError("patch chunk byte limit must be positive")
    if max_payload_bytes > _MAX_PATCH_CHUNK_BYTES:
        raise EvidenceError("patch chunk byte limit may not exceed 48 KiB")
    try:
        text = patch.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError("patch is not UTF-8") from exc
    if not text:
        return ()

    parts: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for character in text:
        encoded = character.encode("utf-8")
        if len(encoded) > max_payload_bytes:
            raise EvidenceError("one UTF-8 code point exceeds patch chunk limit")
        if current and current_bytes + len(encoded) > max_payload_bytes:
            parts.append("".join(current))
            current = []
            current_bytes = 0
        current.append(character)
        current_bytes += len(encoded)
    if current:
        parts.append("".join(current))

    patch_sha = hashlib.sha256(patch).hexdigest()
    total = len(parts)
    return tuple(
        PatchChunk(
            index=index,
            total=total,
            text=part,
            sha256=hashlib.sha256(part.encode("utf-8")).hexdigest(),
            patch_sha256=patch_sha,
        )
        for index, part in enumerate(parts, start=1)
    )


def _sanitize_excerpt(text: str) -> str:
    text = _BEARER_RE.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: match.group(1) + "=[REDACTED]", text)
    text = _WINDOWS_ABSOLUTE_RE.sub("[LOCAL_PATH]", text)
    text = _UNIX_ABSOLUTE_RE.sub("[LOCAL_PATH]", text)
    return text


def _bounded_output(text: str, max_bytes: int) -> dict[str, object]:
    raw = text.encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) <= max_bytes:
        return {
            "truncated": False,
            "byte_count": len(raw),
            "sha256": digest,
            "text": _sanitize_excerpt(text),
        }
    half = max(1, max_bytes // 2)
    prefix = raw[:half].decode("utf-8", errors="replace")
    suffix = raw[-half:].decode("utf-8", errors="replace")
    return {
        "truncated": True,
        "byte_count": len(raw),
        "sha256": digest,
        "prefix": _sanitize_excerpt(prefix),
        "suffix": _sanitize_excerpt(suffix),
    }


def build_signed_receipt(
    task: TaskEnvelope,
    *,
    status: str,
    change_evidence: ChangeEvidence,
    patch_chunks: tuple[PatchChunk, ...],
    cleanup_success: bool,
    execution_result: ExecutionResult,
    max_command_output_bytes: int,
) -> ReceiptEnvelope:
    if not isinstance(task, TaskEnvelope):
        raise EvidenceError("typed task envelope is required")
    if not isinstance(change_evidence, ChangeEvidence):
        raise EvidenceError("typed change evidence is required")
    if not isinstance(execution_result, ExecutionResult):
        raise EvidenceError("typed execution result is required")
    if not isinstance(cleanup_success, bool):
        raise EvidenceError("cleanup_success must be boolean")
    if isinstance(max_command_output_bytes, bool) or not isinstance(max_command_output_bytes, int) or max_command_output_bytes <= 0:
        raise EvidenceError("max_command_output_bytes must be positive")

    trusted_hashes = _signed_intended_hashes(task)
    if dict(change_evidence.observed_final_hashes) != trusted_hashes:
        raise EvidenceError("receipt change evidence is not bound to the signed task")

    expected_patch_sha = change_evidence.patch_sha256
    expected_total = len(patch_chunks)
    reconstructed_parts: list[str] = []
    for expected_index, chunk in enumerate(patch_chunks, start=1):
        if not isinstance(chunk, PatchChunk):
            raise EvidenceError("patch_chunks must contain PatchChunk values")
        if chunk.index != expected_index or chunk.total != expected_total:
            raise EvidenceError("patch chunks are not in one complete ordered sequence")
        if chunk.patch_sha256 != expected_patch_sha:
            raise EvidenceError("patch chunk is bound to a different complete patch")
        encoded_chunk = chunk.text.encode("utf-8")
        if len(encoded_chunk) > _MAX_PATCH_CHUNK_BYTES:
            raise EvidenceError("patch chunk exceeds the 48 KiB payload limit")
        if hashlib.sha256(encoded_chunk).hexdigest() != chunk.sha256:
            raise EvidenceError("patch chunk hash mismatch")
        reconstructed_parts.append(chunk.text)

    reconstructed = "".join(reconstructed_parts).encode("utf-8")
    if hashlib.sha256(reconstructed).hexdigest() != expected_patch_sha:
        raise EvidenceError("ordered patch chunks do not reconstruct the complete patch")
    if len(reconstructed) != change_evidence.diff_bytes:
        raise EvidenceError("reconstructed patch byte count does not match change evidence")

    steps: list[dict[str, object]] = []
    for step in execution_result.steps:
        steps.append(
            {
                "index": step.index,
                "kind": step.kind,
                "success": step.success,
                "returncode": step.returncode,
                "path": step.path,
                "stdout": _bounded_output(step.stdout, max_command_output_bytes),
                "stderr": _bounded_output(step.stderr, max_command_output_bytes),
            }
        )

    evidence_payload = {
        "changed_paths": list(change_evidence.changed_paths),
        "observed_final_hashes": dict(change_evidence.observed_final_hashes),
        "diff_bytes": change_evidence.diff_bytes,
        "patch_sha256": expected_patch_sha,
        "patch_chunk_sha256": [chunk.sha256 for chunk in patch_chunks],
        "cleanup_success": cleanup_success,
        "execution": {
            "success": execution_result.success,
            "applied": execution_result.applied,
            "steps": steps,
        },
    }
    try:
        return ReceiptEnvelope.from_mapping(
            {
                "schema_version": "astra.receipt.v1",
                "task_id": task.task_id,
                "worker_id": task.worker_id,
                "repository_id": task.repository_id,
                "base_ref": task.base_ref,
                "base_commit_sha": task.base_commit_sha,
                "status": status,
                "evidence": evidence_payload,
            }
        )
    except ValueError as exc:
        raise EvidenceError("receipt payload failed schema validation") from exc
