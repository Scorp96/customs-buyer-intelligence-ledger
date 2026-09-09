from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class GitHubApiError(RuntimeError):
    """Raised for bounded GitHub Issues/ref API failures without leaking credentials."""


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class GitHubIssueClient:
    """Narrow GitHub client: Issues read/write plus branch-head read only."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        api_base: str = "https://api.github.com",
        timeout_seconds: int = 20,
    ) -> None:
        if not isinstance(repository, str) or _REPOSITORY_RE.fullmatch(repository) is None:
            raise GitHubApiError("repository must be owner/name")
        if not isinstance(token, str) or not token.strip() or "\x00" in token:
            raise GitHubApiError("GitHub token must be non-empty")
        parsed = urlparse(api_base)
        if parsed.scheme != "https" or not parsed.netloc or parsed.params or parsed.query or parsed.fragment:
            raise GitHubApiError("GitHub API base must be an HTTPS origin")
        if timeout_seconds <= 0:
            raise GitHubApiError("GitHub API timeout must be positive")
        self.repository = repository
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._api_origin = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_seconds = int(timeout_seconds)

    def _safe_error(self, message: str, _exc: BaseException | None = None) -> GitHubApiError:
        # Deliberately exclude exception/body text: HTTP libraries may echo Authorization data.
        return GitHubApiError(message)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or "\x00" in path:
            raise GitHubApiError("GitHub API path must be repository-relative")
        url = self._api_base + path
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "astra-phase2-worker/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                final = urlparse(response.geturl())
                if f"{final.scheme}://{final.netloc}" != self._api_origin:
                    raise GitHubApiError("GitHub API redirected to a different origin")
                raw = response.read()
        except HTTPError as exc:
            raise self._safe_error(f"GitHub API returned HTTP {exc.code}", exc) from None
        except (URLError, OSError, TimeoutError) as exc:
            raise self._safe_error("GitHub API request failed", exc) from None

        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise self._safe_error("GitHub API returned invalid JSON", exc) from None

    def get_issue(self, issue_number: int) -> dict[str, Any]:
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
            raise GitHubApiError("issue number must be positive")
        result = self._request("GET", f"/repos/{self.repository}/issues/{issue_number}")
        if not isinstance(result, dict):
            raise GitHubApiError("GitHub issue response is not an object")
        return result

    def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
            raise GitHubApiError("issue number must be positive")
        result = self._request(
            "GET", f"/repos/{self.repository}/issues/{issue_number}/comments?per_page=100"
        )
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise GitHubApiError("GitHub issue comments response is invalid")
        return result

    def post_issue_comment(self, issue_number: int, body: str) -> None:
        if not isinstance(body, str) or not body:
            raise GitHubApiError("issue comment body must be non-empty")
        self._request(
            "POST",
            f"/repos/{self.repository}/issues/{issue_number}/comments",
            {"body": body},
        )

    def replace_astra_labels(self, issue_number: int, labels: set[str]) -> None:
        if not isinstance(labels, set) or any(
            not isinstance(item, str) or not item.startswith("astra-task/") for item in labels
        ):
            raise GitHubApiError("replacement ASTRA labels are invalid")
        issue = self.get_issue(issue_number)
        raw_labels = issue.get("labels", [])
        if not isinstance(raw_labels, list):
            raise GitHubApiError("GitHub issue labels are invalid")
        preserved: list[str] = []
        for item in raw_labels:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and not name.startswith("astra-task/"):
                preserved.append(name)
        final_labels = sorted(set(preserved).union(labels))
        self._request(
            "PUT",
            f"/repos/{self.repository}/issues/{issue_number}/labels",
            {"labels": final_labels},
        )

    def resolve_branch_head(self, repository: str, ref: str) -> str:
        if repository != self.repository:
            raise GitHubApiError("cross-repository ref lookup is not allowed")
        if not isinstance(ref, str) or not ref or "\x00" in ref:
            raise GitHubApiError("branch ref must be non-empty")
        encoded = quote(ref, safe="")
        result = self._request("GET", f"/repos/{self.repository}/git/ref/heads/{encoded}")
        obj = result.get("object") if isinstance(result, dict) else None
        sha = obj.get("sha") if isinstance(obj, dict) else None
        if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
            raise GitHubApiError("GitHub branch ref did not resolve to a 40-hex object SHA")
        return sha.lower()
