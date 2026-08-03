from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from .models import utc_now_iso


Document = dict[str, Any]
T = TypeVar("T")
Mutator = Callable[[Document], T | Awaitable[T]]


def empty_document() -> Document:
    return {
        "schema_version": "2.1",
        "updated_at": utc_now_iso(),
        "buyers": {},
    }


class StorageError(RuntimeError):
    pass


class LedgerStore(ABC):
    @abstractmethod
    async def read(self) -> Document:
        raise NotImplementedError

    @abstractmethod
    async def atomic_update(self, mutator: Mutator[T]) -> tuple[T, Document]:
        raise NotImplementedError


class LocalJsonStore(LedgerStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    def _read_sync(self) -> Document:
        if not self.path.exists():
            return empty_document()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"local ledger cannot be read: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("buyers"), dict):
            raise StorageError("local ledger has an invalid structure")
        return data

    async def read(self) -> Document:
        async with self._lock:
            return copy.deepcopy(self._read_sync())

    async def atomic_update(self, mutator: Mutator[T]) -> tuple[T, Document]:
        async with self._lock:
            document = self._read_sync()
            result = mutator(document)
            if asyncio.iscoroutine(result):
                result = await result
            document["updated_at"] = utc_now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            return result, copy.deepcopy(document)


class GitHubContentsStore(LedgerStore):
    api_base = "https://api.github.com"

    def __init__(
        self,
        repository: str,
        token: str,
        branch: str,
        path: str,
        max_retries: int = 4,
    ) -> None:
        if repository.count("/") != 1:
            raise StorageError("GITHUB_REPOSITORY must use owner/repository format")
        if not token:
            raise StorageError("GITHUB_TOKEN is required in github store mode")
        self.repository = repository
        self.token = token
        self.branch = branch
        self.path = path.lstrip("/")
        self.max_retries = max_retries
        self._branch_lock = asyncio.Lock()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "customs-buyer-intelligence-ledger/2.1",
        }

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
            try:
                return await client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                raise StorageError(f"GitHub ledger network error: {exc.__class__.__name__}") from exc

    async def _ensure_branch(self) -> None:
        async with self._branch_lock:
            ref_url = f"{self.api_base}/repos/{self.repository}/git/ref/heads/{self.branch}"
            response = await self._request("GET", ref_url)
            if response.status_code == 200:
                return
            if response.status_code != 404:
                raise StorageError(f"cannot inspect GitHub ledger branch: HTTP {response.status_code}")

            repo_url = f"{self.api_base}/repos/{self.repository}"
            repo_response = await self._request("GET", repo_url)
            if repo_response.status_code != 200:
                raise StorageError(f"cannot inspect GitHub repository: HTTP {repo_response.status_code}")
            default_branch = repo_response.json().get("default_branch")
            if not default_branch:
                raise StorageError("GitHub repository has no default branch")
            default_ref = await self._request(
                "GET",
                f"{self.api_base}/repos/{self.repository}/git/ref/heads/{default_branch}",
            )
            if default_ref.status_code != 200:
                raise StorageError(f"cannot read default branch: HTTP {default_ref.status_code}")
            sha = default_ref.json().get("object", {}).get("sha")
            create_response = await self._request(
                "POST",
                f"{self.api_base}/repos/{self.repository}/git/refs",
                json={"ref": f"refs/heads/{self.branch}", "sha": sha},
            )
            if create_response.status_code not in {201, 422}:
                raise StorageError(f"cannot create GitHub ledger branch: HTTP {create_response.status_code}")

    async def _read_with_sha(self) -> tuple[Document, str | None]:
        await self._ensure_branch()
        url = f"{self.api_base}/repos/{self.repository}/contents/{self.path}"
        response = await self._request("GET", url, params={"ref": self.branch})
        if response.status_code == 404:
            return empty_document(), None
        if response.status_code != 200:
            raise StorageError(f"cannot read GitHub ledger: HTTP {response.status_code}")
        payload = response.json()
        try:
            raw = base64.b64decode(payload["content"]).decode("utf-8")
            document = json.loads(raw)
        except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StorageError("GitHub ledger is not valid UTF-8 JSON") from exc
        if not isinstance(document, dict) or not isinstance(document.get("buyers"), dict):
            raise StorageError("GitHub ledger has an invalid structure")
        return document, payload.get("sha")

    async def read(self) -> Document:
        document, _ = await self._read_with_sha()
        return copy.deepcopy(document)

    async def atomic_update(self, mutator: Mutator[T]) -> tuple[T, Document]:
        for attempt in range(self.max_retries):
            document, sha = await self._read_with_sha()
            result = mutator(document)
            if asyncio.iscoroutine(result):
                result = await result
            document["updated_at"] = utc_now_iso()
            encoded = base64.b64encode(
                json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            ).decode("ascii")
            body: dict[str, Any] = {
                "message": "Update customs buyer intelligence ledger",
                "content": encoded,
                "branch": self.branch,
            }
            if sha:
                body["sha"] = sha
            response = await self._request(
                "PUT",
                f"{self.api_base}/repos/{self.repository}/contents/{self.path}",
                json=body,
            )
            if response.status_code in {200, 201}:
                return result, copy.deepcopy(document)
            if response.status_code in {409, 422} and attempt + 1 < self.max_retries:
                await asyncio.sleep(0.15 * (attempt + 1))
                continue
            raise StorageError(f"cannot write GitHub ledger: HTTP {response.status_code}")
        raise StorageError("GitHub ledger update conflict could not be resolved")


def build_store() -> LedgerStore:
    mode = os.getenv("STORE_MODE", "local").strip().lower()
    if mode == "local":
        return LocalJsonStore(os.getenv("LOCAL_LEDGER_PATH", "data/customs-buyer-ledger.json"))
    if mode == "github":
        return GitHubContentsStore(
            repository=os.getenv("GITHUB_REPOSITORY", ""),
            token=os.getenv("GITHUB_TOKEN", ""),
            branch=os.getenv("GITHUB_LEDGER_BRANCH", "ledger-data"),
            path=os.getenv("GITHUB_LEDGER_PATH", "data/customs-buyer-ledger.json"),
        )
    raise StorageError("STORE_MODE must be local or github")
