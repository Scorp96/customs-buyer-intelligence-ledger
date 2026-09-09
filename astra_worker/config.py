from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


class ConfigError(ValueError):
    """Raised when trusted local worker configuration is invalid."""


_PROTECTED_BRANCHES = {"main", "master", "production"}
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _exact_keys(payload: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ConfigError(
            f"{context} keys mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConfigError(f"{field} must be non-empty text without NUL")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _string_tuple(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{field} must be an array of strings")
    items = tuple(_text(item, field) for item in value)
    if not allow_empty and not items:
        raise ConfigError(f"{field} must not be empty")
    if len(set(items)) != len(items):
        raise ConfigError(f"{field} contains duplicates")
    return items


def _absolute_local_path(raw: Any, field: str) -> Path:
    value = _text(raw, field)
    if not (_WINDOWS_ABSOLUTE_RE.match(value) or Path(value).is_absolute()):
        raise ConfigError(f"{field} must be an absolute local path")
    normalized = value.replace("\\", "/")
    if "/../" in f"/{normalized}/" or normalized.endswith("/.."):
        raise ConfigError(f"{field} must not contain parent traversal")
    return Path(value)


def _validate_repository_name(value: Any, field: str) -> str:
    text = _text(value, field)
    if _GITHUB_REPOSITORY_RE.fullmatch(text) is None:
        raise ConfigError(f"{field} must be owner/repository")
    return text


def _safe_branch_prefix(value: Any, field: str) -> str:
    prefix = _text(value, field)
    if not prefix.endswith("/"):
        raise ConfigError(f"{field} must end with '/'")
    root = prefix.split("/", 1)[0].lower()
    if root in _PROTECTED_BRANCHES:
        raise ConfigError(f"{field} may not use a protected branch namespace")
    return prefix


@dataclass(frozen=True)
class RepositoryBinding:
    repository_id: str
    github_repository: str
    expected_origin: str
    mirror_root: Path
    allowed_base_refs_exact: tuple[str, ...]
    allowed_base_ref_prefixes: tuple[str, ...]
    ephemeral_branch_prefix: str

    @classmethod
    def from_mapping(cls, repository_id: str, payload: Mapping[str, Any]) -> "RepositoryBinding":
        if not isinstance(payload, Mapping):
            raise ConfigError("repository binding must be an object")
        expected = {
            "github_repository", "expected_origin", "mirror_root",
            "allowed_base_refs_exact", "allowed_base_ref_prefixes", "ephemeral_branch_prefix",
        }
        _exact_keys(payload, expected, f"repository[{repository_id}]")
        exact = _string_tuple(
            payload["allowed_base_refs_exact"],
            f"repository[{repository_id}].allowed_base_refs_exact",
            allow_empty=True,
        )
        prefixes = _string_tuple(
            payload["allowed_base_ref_prefixes"],
            f"repository[{repository_id}].allowed_base_ref_prefixes",
            allow_empty=True,
        )
        if not exact and not prefixes:
            raise ConfigError("repository must allow at least one exact ref or ref prefix")
        for ref in exact:
            if ref.lower() in _PROTECTED_BRANCHES:
                raise ConfigError("protected branches cannot be worker task bases")
        for prefix in prefixes:
            root = prefix.rstrip("/").lower()
            if not prefix or root in _PROTECTED_BRANCHES:
                raise ConfigError("protected/empty base-ref prefixes are not allowed")
        if set(exact).intersection(prefixes):
            raise ConfigError("exact and prefix ref rules must remain distinct")
        origin = _text(payload["expected_origin"], f"repository[{repository_id}].expected_origin")
        if not origin.startswith("https://github.com/") or not origin.endswith(
            _validate_repository_name(payload["github_repository"], "github_repository")
        ):
            raise ConfigError("expected_origin must pin the configured GitHub repository")
        return cls(
            repository_id=_text(repository_id, "repository_id"),
            github_repository=_validate_repository_name(payload["github_repository"], "github_repository"),
            expected_origin=origin,
            mirror_root=_absolute_local_path(payload["mirror_root"], "mirror_root"),
            allowed_base_refs_exact=exact,
            allowed_base_ref_prefixes=prefixes,
            ephemeral_branch_prefix=_safe_branch_prefix(
                payload["ephemeral_branch_prefix"], "ephemeral_branch_prefix"
            ),
        )

    def allows_base_ref(self, ref: str) -> bool:
        if not isinstance(ref, str) or not ref or ref.lower() in _PROTECTED_BRANCHES:
            return False
        if ref in self.allowed_base_refs_exact:
            return True
        return any(ref.startswith(prefix) for prefix in self.allowed_base_ref_prefixes)


@dataclass(frozen=True)
class WorkerConfig:
    schema_version: str
    worker_id: str
    queue_repository: str
    repositories: Mapping[str, RepositoryBinding]
    poll_interval_seconds: int
    max_task_age_seconds: int
    max_task_payload_bytes: int
    max_operations: int
    max_changed_files: int
    max_diff_bytes: int
    max_command_output_bytes: int

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "WorkerConfig":
        if not isinstance(payload, Mapping):
            raise ConfigError("worker config must be an object")
        expected = {
            "schema_version", "worker_id", "queue_repository", "repositories",
            "poll_interval_seconds", "max_task_age_seconds", "max_task_payload_bytes",
            "max_operations", "max_changed_files", "max_diff_bytes", "max_command_output_bytes",
        }
        _exact_keys(payload, expected, "worker config")
        if payload["schema_version"] != "astra.worker.config.v1":
            raise ConfigError("unsupported worker config schema_version")
        queue_repository = _validate_repository_name(payload["queue_repository"], "queue_repository")
        raw_repositories = payload["repositories"]
        if not isinstance(raw_repositories, Mapping) or not raw_repositories:
            raise ConfigError("repositories must be a non-empty object")
        bindings: dict[str, RepositoryBinding] = {}
        mirror_keys: set[str] = set()
        for repository_id, raw_binding in raw_repositories.items():
            repository_id = _text(repository_id, "repository_id")
            binding = RepositoryBinding.from_mapping(repository_id, raw_binding)
            if binding.github_repository != queue_repository:
                raise ConfigError("Phase 2A repository binding must match queue_repository")
            mirror_key = str(binding.mirror_root).replace("\\", "/").casefold()
            if mirror_key in mirror_keys:
                raise ConfigError("repository mirror roots must be unique")
            mirror_keys.add(mirror_key)
            bindings[repository_id] = binding
        return cls(
            schema_version="astra.worker.config.v1",
            worker_id=_text(payload["worker_id"], "worker_id"),
            queue_repository=queue_repository,
            repositories=bindings,
            poll_interval_seconds=_positive_int(payload["poll_interval_seconds"], "poll_interval_seconds"),
            max_task_age_seconds=_positive_int(payload["max_task_age_seconds"], "max_task_age_seconds"),
            max_task_payload_bytes=_positive_int(payload["max_task_payload_bytes"], "max_task_payload_bytes"),
            max_operations=_positive_int(payload["max_operations"], "max_operations"),
            max_changed_files=_positive_int(payload["max_changed_files"], "max_changed_files"),
            max_diff_bytes=_positive_int(payload["max_diff_bytes"], "max_diff_bytes"),
            max_command_output_bytes=_positive_int(payload["max_command_output_bytes"], "max_command_output_bytes"),
        )

    @classmethod
    def load(cls, path: Path) -> "WorkerConfig":
        try:
            raw = Path(path).read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot load worker config: {exc}") from exc
        return cls.from_mapping(payload)

    def repository(self, repository_id: str) -> RepositoryBinding:
        try:
            return self.repositories[repository_id]
        except KeyError as exc:
            raise ConfigError(f"unknown repository_id: {repository_id}") from exc
