from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class GitHubOAuthError(RuntimeError):
    """Base class for GitHub OAuth validation failures."""


class GitHubOAuthInvalid(GitHubOAuthError):
    """The supplied OAuth token is invalid or revoked."""


class GitHubOAuthForbidden(GitHubOAuthError):
    """The supplied OAuth token belongs to a GitHub account not allowed here."""


class GitHubOAuthUnavailable(GitHubOAuthError):
    """GitHub identity verification could not be completed."""


@dataclass
class GitHubOAuthVerifier:
    allowed_logins: tuple[str, ...]
    api_url: str = "https://api.github.com/user"
    timeout_seconds: float = 5.0
    cache_ttl_seconds: float = 120.0
    _cache: dict[str, tuple[float, str]] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        normalized = tuple(sorted({value.strip().lower() for value in self.allowed_logins if value.strip()}))
        if not normalized:
            raise ValueError("at least one allowed GitHub login is required")
        self.allowed_logins = normalized

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _cached_login(self, token: str) -> str | None:
        now = time.monotonic()
        key = self._token_key(token)
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            expires_at, login = item
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return login

    def _remember(self, token: str, login: str) -> None:
        key = self._token_key(token)
        with self._lock:
            self._cache[key] = (time.monotonic() + self.cache_ttl_seconds, login)

    def verify(self, token: str) -> str:
        supplied = str(token or "").strip()
        if not supplied:
            raise GitHubOAuthInvalid("GitHub OAuth token is empty")

        cached = self._cached_login(supplied)
        if cached is not None:
            if cached.lower() not in self.allowed_logins:
                raise GitHubOAuthForbidden("GitHub account is not authorized for this CBI Runtime")
            return cached

        request = urllib.request.Request(
            self.api_url,
            headers={
                "Authorization": f"Bearer {supplied}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "cbi-v61-remote-mcp",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise GitHubOAuthInvalid("GitHub OAuth token was rejected") from exc
            raise GitHubOAuthUnavailable(f"GitHub OAuth verification failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise GitHubOAuthUnavailable("GitHub OAuth verification is temporarily unavailable") from exc

        login = str(payload.get("login") or "").strip()
        if not login:
            raise GitHubOAuthInvalid("GitHub OAuth identity response did not contain a login")
        if login.lower() not in self.allowed_logins:
            raise GitHubOAuthForbidden("GitHub account is not authorized for this CBI Runtime")
        self._remember(supplied, login)
        return login
