#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED_ORIGIN_SLUG = "Scorp96/customs-buyer-intelligence-ledger"
C279_TEST_NAME = "test_c279_canonical_route_can_prepare_outreach_full_runtime"
C279_BRIDGE_SCHEMA = "cbi.v64-c279-authoritative-regression-bridge.v1"
C279_BRIDGE_ENV = "CBI_V64_C279_BRIDGE_EVIDENCE"
C279_SOURCE_ROOT_ENV = "CBI_V64_C279_SOURCE_RUNTIME_ROOT"


class VerificationError(RuntimeError):
    pass


def _sha256_file(path: Path | str) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise VerificationError(f"COMMAND_FAILED:{argv[0]}:RC={completed.returncode}")
    return completed


def _git(repo: Path, *args: str) -> str:
    return _run(["git", *args], cwd=repo).stdout.strip()


def _normalize_origin(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("git@github.com:"):
        slug = text[len("git@github.com:") :]
    else:
        parsed = urlsplit(text)
        if parsed.scheme not in {"https", "ssh"} or (parsed.hostname or "").lower() != "github.com":
            return ""
        slug = parsed.path
    slug = slug.strip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.split("/")
    if len(parts) != 2 or not all(parts):
        return ""
    return "/".join(parts)


def _require_origin_ref(value: str) -> str:
    ref = str(value or "").strip()
    if not ref.startswith("origin/") or len(ref) <= len("origin/"):
        raise VerificationError("AUTHORITATIVE_REMOTE_REF_REQUIRED")
    if any(token in ref for token in ("..", "~", "^", " ", "\t", "\n")):
        raise VerificationError("AUTHORITATIVE_REMOTE_REF_REQUIRED")
    return ref


def validate_remote_refs(source_ref: str, production_ref: str) -> dict[str, str]:
    source = _require_origin_ref(source_ref)
    production = _require_origin_ref(production_ref)
    if source == production:
        raise VerificationError("SOURCE_AND_PRODUCTION_REFS_MUST_DIFFER")
    return {"source_ref": source, "production_ref": production}


def refresh_origin(repo: Path | str) -> None:
    root = Path(repo).resolve()
    completed = _run(["git", "fetch", "origin", "--prune"], cwd=root, check=False)
    if completed.returncode != 0:
        raise VerificationError("ORIGIN_FETCH_FAILED")


def verify_checkout(
    repo: Path | str,
    *,
    source_ref: str,
    production_ref: str,
    fetch_origin: bool,
) -> dict[str, str]:
    root = Path(repo).resolve()
    refs = validate_remote_refs(source_ref, production_ref)
    if not root.is_dir() or not (root / ".git").exists():
        raise VerificationError("AUTHORITATIVE_CHECKOUT_REQUIRED")
    if fetch_origin:
        refresh_origin(root)
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        raise VerificationError("AUTHORITATIVE_CHECKOUT_REQUIRED")
    if _normalize_origin(_git(root, "remote", "get-url", "origin")) != EXPECTED_ORIGIN_SLUG:
        raise VerificationError("UNEXPECTED_ORIGIN")
    if _git(root, "status", "--porcelain"):
        raise VerificationError("WORKTREE_NOT_CLEAN")

    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise VerificationError("DETACHED_HEAD_NOT_ALLOWED")
    forbidden = {
        "main",
        "master",
        refs["source_ref"].split("/", 1)[1],
        refs["production_ref"].split("/", 1)[1],
    }
    if branch in forbidden:
        raise VerificationError("ISOLATED_FEATURE_BRANCH_REQUIRED")

    head = _git(root, "rev-parse", "HEAD")
    source_sha = _git(root, "rev-parse", refs["source_ref"])
    production_sha = _git(root, "rev-parse", refs["production_ref"])

    source_to_head = _run(
        ["git", "merge-base", "--is-ancestor", source_sha, head],
        cwd=root,
        check=False,
    )
    if source_to_head.returncode != 0:
        raise VerificationError("CANDIDATE_NOT_DESCENDED_FROM_AUTHORITATIVE_SOURCE")
    source_to_production = _run(
        ["git", "merge-base", "--is-ancestor", source_sha, production_sha],
        cwd=root,
        check=False,
    )
    if source_to_production.returncode != 0:
        raise VerificationError("PRODUCTION_NOT_DESCENDED_FROM_AUTHORITATIVE_SOURCE")

    return {
        "branch": branch,
        "head": head,
        "source_sha": source_sha,
        "production_sha": production_sha,
    }


def load_c279_bridge(path: Path | str) -> dict:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise VerificationError("C279_BRIDGE_REQUIRED")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError("C279_BRIDGE_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("schema") != C279_BRIDGE_SCHEMA:
        raise VerificationError("C279_BRIDGE_SCHEMA_INVALID")

    investigation_id = str(payload.get("investigation_id") or "").strip()
    durable = payload.get("durable_state")
    durable = dict(durable) if isinstance(durable, dict) else {}
    seq = durable.get("last_safe_seq")
    event_hash = str(durable.get("last_safe_event_hash") or "").strip().lower()
    if not investigation_id:
        raise VerificationError("C279_BRIDGE_INVESTIGATION_REQUIRED")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise VerificationError("C279_BRIDGE_DURABLE_TAIL_INVALID")
    if len(event_hash) != 64 or any(ch not in "0123456789abcdef" for ch in event_hash):
        raise VerificationError("C279_BRIDGE_DURABLE_TAIL_INVALID")

    pre = payload.get("pre_patch")
    pre = dict(pre) if isinstance(pre, dict) else {}
    blockers = pre.get("block_reasons")
    blockers = list(blockers) if isinstance(blockers, list) else []
    expected = payload.get("post_patch_expectation")
    expected = dict(expected) if isinstance(expected, dict) else {}
    if (
        pre.get("outreach_readiness") != "IDENTITY_ONLY"
        or "VERIFIED_ACCOUNT_OWNED_ROUTE_REQUIRED" not in blockers
        or expected.get("minimum_outreach_readiness") != "COMPANY_ROUTE_READY"
        or expected.get("prepare_outreach_succeeds") is not True
        or expected.get("sends_message") is not False
    ):
        raise VerificationError("C279_BRIDGE_EXPECTATION_INVALID")

    result = dict(payload)
    result["_bridge_sha256"] = _sha256_file(target)
    return result


def verify_c279_source_tail(source_root: Path | str, bridge: dict) -> dict[str, str]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise VerificationError("C279_SOURCE_RUNTIME_ROOT_REQUIRED")
    investigation_id = str(bridge.get("investigation_id") or "")
    durable = dict(bridge.get("durable_state") or {})
    expected_seq = int(durable["last_safe_seq"])
    expected_hash = str(durable["last_safe_event_hash"]).lower()
    session = root / "sessions" / f"{investigation_id}.jsonl"
    if not session.is_file():
        raise VerificationError("C279_SOURCE_SESSION_REQUIRED")

    tail = None
    try:
        with session.open("r", encoding="utf-8-sig") as handle:
            for raw in handle:
                if raw.strip():
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise VerificationError("C279_SOURCE_SESSION_INVALID")
                    tail = row
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError("C279_SOURCE_SESSION_INVALID") from exc
    if not isinstance(tail, dict):
        raise VerificationError("C279_SOURCE_SESSION_EMPTY")
    if tail.get("seq") != expected_seq:
        raise VerificationError("C279_SOURCE_SEQ_MISMATCH")
    if str(tail.get("event_hash") or "").lower() != expected_hash:
        raise VerificationError("C279_SOURCE_EVENT_HASH_MISMATCH")

    bridge_sha = str(bridge.get("_bridge_sha256") or "")
    if len(bridge_sha) != 64:
        raise VerificationError("C279_BRIDGE_DIGEST_REQUIRED")
    return {
        "bridge_sha256": bridge_sha,
        "session_sha256": _sha256_file(session),
    }


def require_c279_integration_test(repo: Path | str) -> Path:
    root = Path(repo).resolve()
    path = root / "tests" / "test_v64_c279_full_runtime.py"
    if not path.is_file():
        raise VerificationError("C279_INTEGRATION_TEST_REQUIRED")
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise VerificationError("C279_INTEGRATION_TEST_REQUIRED") from exc

    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == C279_TEST_NAME:
            target = node
            break
    if target is None:
        raise VerificationError("C279_INTEGRATION_TEST_REQUIRED")
    called_attrs = {
        child.func.attr
        for child in ast.walk(target)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }
    if "evaluate_outreach_readiness" not in called_attrs:
        raise VerificationError("C279_READINESS_ASSERTION_REQUIRED")
    if "prepare_outreach" not in called_attrs:
        raise VerificationError("C279_PREPARE_OUTREACH_ASSERTION_REQUIRED")
    for marker, error in (
        ("TemporaryDirectory", "C279_TEMPORARY_ISOLATION_REQUIRED"),
        ("copytree", "C279_SOURCE_COPY_REQUIRED"),
        ("sends_message", "C279_NO_SEND_ASSERTION_REQUIRED"),
    ):
        if marker not in source:
            raise VerificationError(error)
    return path


def _mro_owner_code() -> str:
    return (
        "from unified_runtime import UnifiedRuntime; "
        "from unified_runtime.research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin as M; "
        "m=list(UnifiedRuntime.__mro__); "
        "assert M in m and m.index(M)==1, [c.__name__ for c in m]; "
        "targets=['get_next_research_objectives','evaluate_outreach_readiness','evaluate_decision_saturation',"
        "'plan_public_source_calls','get_account_state','get_runtime_contract']; "
        "owners={n:next((c for c in m if n in c.__dict__),None) for n in targets}; "
        "bad={n:(o.__name__ if o else None) for n,o in owners.items() if o is not M}; "
        "assert not bad, bad; "
        "p=next((c for c in m if 'prepare_outreach' in c.__dict__),None); "
        "assert p is not None and p is not M; print('MRO_OWNER_PASS')"
    )


def build_verification_commands(python: str = sys.executable) -> list[dict[str, object]]:
    return [
        {
            "name": "canonical-route-prepare",
            "argv": [
                python,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_v61_outreach_hardening.py",
                "-k",
                "test_information_record_route_can_prepare_after_canonical_readiness",
                "-q",
            ],
            "private_c279_env": False,
        },
        {
            "name": "c279-full-runtime",
            "argv": [
                python,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_v64_c279_full_runtime.py",
                "-k",
                C279_TEST_NAME,
                "-q",
            ],
            "private_c279_env": True,
        },
        {
            "name": "mro-owner",
            "argv": [python, "-c", _mro_owner_code()],
            "private_c279_env": False,
        },
        {
            "name": "v6-protocol",
            "argv": [python, "mcp/v6_protocol_test.py"],
            "private_c279_env": False,
        },
        {
            "name": "v61-protocol",
            "argv": [python, "mcp/v61_hardening_protocol_test.py"],
            "private_c279_env": False,
        },
        {
            "name": "full-unittest-suite",
            "argv": [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            "private_c279_env": False,
        },
    ]


def run_verification_commands(
    repo: Path | str,
    *,
    python: str,
    bridge_path: Path | str,
    source_root: Path | str,
) -> list[dict[str, object]]:
    root = Path(repo).resolve()
    base_env = os.environ.copy()
    base_env.pop(C279_BRIDGE_ENV, None)
    base_env.pop(C279_SOURCE_ROOT_ENV, None)
    results: list[dict[str, object]] = []
    for command in build_verification_commands(python):
        env = base_env.copy()
        if command["private_c279_env"]:
            env[C279_BRIDGE_ENV] = str(Path(bridge_path).expanduser().resolve())
            env[C279_SOURCE_ROOT_ENV] = str(Path(source_root).expanduser().resolve())
        completed = _run(list(command["argv"]), cwd=root, env=env, check=False)
        row = {"name": str(command["name"]), "returncode": int(completed.returncode)}
        results.append(row)
        if completed.returncode != 0:
            raise VerificationError(f"GATE_FAILED:{command['name']}")
    return results


def build_public_report(
    *,
    checkout: dict[str, str],
    source_binding: dict[str, str],
    gate_results: list[dict[str, object]],
    verified: bool,
) -> dict[str, object]:
    return {
        "schema": "cbi.v64-authoritative-semantic-forward-port-verification.v1",
        "verified": bool(verified),
        "status": "LOCAL_FORWARD_PORT_VERIFIED" if verified else "GATES_PENDING",
        "semantic_forward_port": True,
        "patch_replay_required": False,
        "checkout": {
            "branch": checkout.get("branch"),
            "head": checkout.get("head"),
            "source_sha": checkout.get("source_sha"),
            "production_sha": checkout.get("production_sha"),
        },
        "c279_source_binding": {
            "bridge_sha256": source_binding.get("bridge_sha256"),
            "session_sha256": source_binding.get("session_sha256"),
        },
        "gates": [
            {"name": str(row.get("name") or ""), "returncode": int(row.get("returncode", -1))}
            for row in gate_results
        ],
        "production_mutation_performed": False,
        "source_runtime_mutation_performed": False,
    }


def _write_report(path: str | None, report: dict[str, object]) -> None:
    if not path:
        return
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed verifier for the CBI v6.4 semantic forward-port candidate."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--production-ref", required=True)
    parser.add_argument("--fetch-origin", action="store_true")
    parser.add_argument("--run-gates", action="store_true")
    parser.add_argument("--c279-bridge")
    parser.add_argument("--c279-source-runtime-root")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "schema": "cbi.v64-authoritative-semantic-forward-port-verification.v1",
        "verified": False,
        "semantic_forward_port": True,
        "patch_replay_required": False,
    }
    try:
        if args.run_gates and not args.fetch_origin:
            raise VerificationError("GATES_REQUIRE_FRESH_ORIGIN")
        checkout = verify_checkout(
            args.repo,
            source_ref=args.source_ref,
            production_ref=args.production_ref,
            fetch_origin=args.fetch_origin,
        )
        report["checkout"] = checkout
        report["status"] = "PREFLIGHT_VERIFIED"

        if not args.run_gates:
            _write_report(args.report, report)
            print(json.dumps(report, sort_keys=True))
            return 0

        bridge_value = args.c279_bridge or os.environ.get(C279_BRIDGE_ENV)
        source_value = args.c279_source_runtime_root or os.environ.get(C279_SOURCE_ROOT_ENV)
        if not bridge_value:
            raise VerificationError("C279_BRIDGE_REQUIRED")
        if not source_value:
            raise VerificationError("C279_SOURCE_RUNTIME_ROOT_REQUIRED")

        bridge = load_c279_bridge(bridge_value)
        source_binding = verify_c279_source_tail(source_value, bridge)
        require_c279_integration_test(args.repo)
        gate_results = run_verification_commands(
            args.repo,
            python=args.python,
            bridge_path=bridge_value,
            source_root=source_value,
        )
        report = build_public_report(
            checkout=checkout,
            source_binding=source_binding,
            gate_results=gate_results,
            verified=True,
        )
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except VerificationError as exc:
        report["blocker"] = str(exc)
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
