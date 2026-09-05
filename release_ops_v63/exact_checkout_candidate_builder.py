from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

EXPECTED_REPO_FRAGMENT = "Scorp96/customs-buyer-intelligence-ledger"
EXPECTED_V62_PRODUCTION_COMMIT = "ba3bffdae13cef186b20b50335c3207fb3390ec6"

_SECRET_PATTERNS = (
    b"github_pat_",
    b"CBI_REMOTE_BEARER_TOKEN=",
    b"CBI_OBJECT_STORE_SECRET_ACCESS_KEY=",
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


def _run(args: list[str], *, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _output(args: list[str], *, cwd: Path | None = None) -> str:
    cp = _run(args, cwd=cwd)
    if cp.returncode != 0:
        raise RuntimeError(
            f"COMMAND_FAILED:{' '.join(args)}\nstdout:\n{cp.stdout or ''}\nstderr:\n{cp.stderr or ''}"
        )
    return (cp.stdout or "").strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_exact_source_commit(
    repo_root: str | Path,
    *,
    expected_commit: str = EXPECTED_V62_PRODUCTION_COMMIT,
    expected_repo_fragment: str = EXPECTED_REPO_FRAGMENT,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        return {
            "status": "BLOCKED_REPOSITORY_MISSING",
            "ready": False,
            "repo_root": str(root),
            "network_required": False,
            "modifies_git_refs": False,
        }
    try:
        top = Path(_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"])).resolve()
        origin = _output(["git", "-C", str(top), "remote", "get-url", "origin"])
    except RuntimeError as exc:
        return {
            "status": "BLOCKED_GIT_REPOSITORY_INVALID",
            "ready": False,
            "repo_root": str(root),
            "error": str(exc),
            "network_required": False,
            "modifies_git_refs": False,
        }
    normalized = origin.replace("\\", "/").replace(".git", "")
    if expected_repo_fragment not in normalized:
        return {
            "status": "BLOCKED_UNEXPECTED_ORIGIN",
            "ready": False,
            "repo_root": str(top),
            "origin": origin,
            "network_required": False,
            "modifies_git_refs": False,
        }
    probe = _run(["git", "-C", str(top), "cat-file", "-e", f"{expected_commit}^{{commit}}"])
    if probe.returncode != 0:
        return {
            "status": "BLOCKED_EXACT_COMMIT_MISSING",
            "ready": False,
            "repo_root": str(top),
            "origin": origin,
            "expected_commit": expected_commit,
            "network_required": False,
            "modifies_git_refs": False,
        }
    actual = _output(["git", "-C", str(top), "rev-parse", f"{expected_commit}^{{commit}}"])
    return {
        "status": "EXACT_COMMIT_READY",
        "ready": actual.lower() == expected_commit.lower(),
        "repo_root": str(top),
        "origin": origin,
        "commit_sha": actual,
        "expected_commit": expected_commit,
        "network_required": False,
        "modifies_git_refs": False,
    }


def export_exact_commit(
    repo_root: str | Path,
    commit_sha: str,
    destination: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    dest = Path(destination).resolve()
    if dest.exists():
        if any(dest.iterdir()) if dest.is_dir() else True:
            raise RuntimeError(f"EXPORT_DESTINATION_NOT_EMPTY:{dest}")
    else:
        dest.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="cbi-v63-git-archive-") as td:
        archive = Path(td) / "source.zip"
        cp = _run([
            "git", "-C", str(root), "archive", "--format=zip", "-o", str(archive), commit_sha,
        ])
        if cp.returncode != 0:
            raise RuntimeError(
                f"GIT_ARCHIVE_FAILED\nstdout:\n{cp.stdout or ''}\nstderr:\n{cp.stderr or ''}"
            )
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)

    return {
        "status": "EXPORTED_EXACT_COMMIT",
        "commit_sha": commit_sha,
        "destination": str(dest),
        "file_count": sum(1 for path in dest.rglob("*") if path.is_file()),
        "modifies_source_repo": False,
        "network_required": False,
        "git_refs_modified": False,
    }


def _assert_ascii_relative_path(name: str) -> None:
    if not name or not name.isascii() or "\\" in name or name.startswith("/") or ".." in Path(name).parts:
        raise RuntimeError(f"UNSAFE_ARTIFACT_PATH:{name}")


def _scan_secret_material(blobs: list[bytes]) -> None:
    joined = b"\n".join(blobs)
    for pattern in _SECRET_PATTERNS:
        if pattern in joined:
            raise RuntimeError(f"SECRET_MATERIAL_DETECTED:{pattern.decode('ascii', errors='replace')}")


def write_candidate_artifact(
    output_zip: str | Path,
    *,
    report: dict[str, Any],
    text_files: dict[str, str] | None = None,
    binary_files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    target = Path(output_zip).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    text_files = dict(text_files or {})
    binary_files = dict(binary_files or {})

    report_bytes = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    payloads: dict[str, bytes] = {"report.json": report_bytes}
    for name, value in text_files.items():
        _assert_ascii_relative_path(name)
        payloads[name] = value.encode("utf-8")
    for name, value in binary_files.items():
        _assert_ascii_relative_path(name)
        payloads[name] = bytes(value)
    for name in payloads:
        _assert_ascii_relative_path(name)

    _scan_secret_material(list(payloads.values()))

    manifest_files = {
        name: {"sha256": _sha256(data), "size_bytes": len(data)}
        for name, data in sorted(payloads.items())
    }
    manifest = {
        "schema": "cbi.v63-exact-checkout-candidate-artifact.v1",
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2).encode("ascii")

    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in sorted(payloads.items()):
                zf.writestr(name, data)
            zf.writestr("MANIFEST.json", manifest_bytes)
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()

    return {
        "status": "ARTIFACT_READY",
        "path": str(target),
        "sha256": _sha256(target.read_bytes()),
        "file_count": len(payloads) + 1,
        "contains_secret_material": False,
    }


def build_static_candidate_on_export(export_root: str | Path) -> dict[str, Any]:
    """Build the mechanically safe v6.3 patch candidate on a disposable export.

    The caller must pass a throwaway `git archive` extraction, never a live Git
    checkout. This function applies Phase A and the two source-pinned candidate
    compilers only to that disposable directory. It deliberately stops before
    any live backend/recovery acceptance, commit, push, Render deploy, or R2
    mutation.
    """
    from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot
    from unified_runtime.production_integration_runner import apply_v63_runtime_phase
    from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
    from unified_runtime.recovery_overlay_patch_compiler_v63 import compile_v63_recovery_overlay_patch_candidate
    from unified_runtime.production_binding_plan import build_v63_production_binding_plan
    from unified_runtime.runtime_event_primitive_probe_v63 import probe_v63_runtime_event_primitives
    from unified_runtime.production_correlation_source_probe_v63 import inspect_v63_production_correlation_bridge
    from unified_runtime.reference_backend_correlation_runner_v63 import run_v63_reference_backend_correlation_acceptance

    root = Path(export_root).resolve()
    if not root.is_dir() or (root / ".git").exists():
        return {
            "status": "BLOCKED_EXPORT_ROOT_INVALID",
            "production_ready": False,
            "remaining_gates": ["DISPOSABLE_GIT_ARCHIVE_EXPORT_REQUIRED"],
        }

    prepatch_snapshot = build_v63_production_source_snapshot(root)
    if prepatch_snapshot.get("status") != "READY":
        return {
            "status": "BLOCKED_PREPATCH_SOURCE_SNAPSHOT",
            "production_ready": False,
            "prepatch_source_snapshot": prepatch_snapshot,
            "remaining_gates": list(prepatch_snapshot.get("blockers") or []),
        }

    primitive_before = probe_v63_runtime_event_primitives(root)
    phase_a = apply_v63_runtime_phase(root, dry_run=False)
    if str(phase_a.get("status") or "").startswith("BLOCKED"):
        return {
            "status": "BLOCKED_PHASE_A",
            "production_ready": False,
            "prepatch_source_snapshot": prepatch_snapshot,
            "primitive_before": primitive_before,
            "phase_a": phase_a,
            "remaining_gates": list(phase_a.get("blockers") or []),
        }

    phase_b_snapshot = dict(phase_a.get("phase_b_source_snapshot") or {})
    adapter = compile_v63_adapter_patch_candidate(
        root,
        expected_production_snapshot=phase_b_snapshot,
    )
    if adapter.get("status") != "PATCH_CANDIDATE_READY":
        return {
            "status": "BLOCKED_ADAPTER_CANDIDATE",
            "production_ready": False,
            "prepatch_source_snapshot": prepatch_snapshot,
            "primitive_before": primitive_before,
            "phase_a": phase_a,
            "adapter": adapter,
            "remaining_gates": list(adapter.get("blockers") or ["BASE_ADAPTER_CANDIDATE_NOT_READY"]),
        }

    adapter_path = root / "mcp" / "server_v61.py"
    adapter_path.write_text(str(adapter["candidate_source"]), encoding="utf-8", newline="")
    post_adapter_snapshot = build_v63_production_source_snapshot(root)

    recovery = compile_v63_recovery_overlay_patch_candidate(
        root,
        expected_production_snapshot=post_adapter_snapshot,
    )
    if recovery.get("status") != "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY":
        return {
            "status": "BLOCKED_RECOVERY_CANDIDATE",
            "production_ready": False,
            "prepatch_source_snapshot": prepatch_snapshot,
            "primitive_before": primitive_before,
            "phase_a": phase_a,
            "adapter": adapter,
            "adapter_candidate_applied_to_export": True,
            "post_adapter_source_snapshot": post_adapter_snapshot,
            "recovery": recovery,
            "remaining_gates": list(recovery.get("blockers") or ["RECOVERY_OVERLAY_CANDIDATE_NOT_READY"]),
        }

    recovery_path = root / str(recovery["target_file"])
    recovery_path.write_text(str(recovery["candidate_source"]), encoding="utf-8", newline="")
    post_patch_snapshot = build_v63_production_source_snapshot(root)
    primitive_after = probe_v63_runtime_event_primitives(root)
    final_plan = build_v63_production_binding_plan(
        root,
        expected_production_source_snapshot_sha256=post_patch_snapshot.get("snapshot_sha256"),
    )
    correlation_source_probe = inspect_v63_production_correlation_bridge(root)
    reference_backend_correlation = run_v63_reference_backend_correlation_acceptance(
        production_source_snapshot_sha256=str(post_patch_snapshot.get("snapshot_sha256") or ""),
    )
    reference_pass = bool(reference_backend_correlation.get("scenarios")) and all(
        row.get("status") == "PASS" and row.get("reexecute_side_effect") is False
        for row in reference_backend_correlation.get("scenarios") or []
    )
    backend_candidate_proven = bool(
        correlation_source_probe.get("static_correlation_bridge_proven")
        and dict(final_plan.get("runtime_backend_binding_plan") or {}).get("runtime_durable_backend_binding_candidate_proven")
        and reference_pass
    )
    if not reference_pass:
        return {
            "status": "BLOCKED_REFERENCE_BACKEND_CORRELATION",
            "production_ready": False,
            "prepatch_source_snapshot": prepatch_snapshot,
            "phase_a": phase_a,
            "adapter": adapter,
            "recovery": recovery,
            "post_patch_source_snapshot": post_patch_snapshot,
            "correlation_source_probe": correlation_source_probe,
            "reference_backend_correlation": reference_backend_correlation,
            "remaining_gates": ["V63_REFERENCE_BACKEND_CORRELATION_NOT_PROVEN"],
        }

    remaining = [
        "V63_RUNTIME_DURABLE_BACKEND_LIVE_ACCEPTANCE_REQUIRED" if backend_candidate_proven else "V63_RUNTIME_DURABLE_BACKEND_NOT_BOUND",
        "V63_BACKEND_CORRELATION_LIVE_ACCEPTANCE_REQUIRED",
        "V63_RECOVERY_OVERLAY_LIVE_ACCEPTANCE_REQUIRED",
        "V63_EXACT_RECOVERY_LIVE_ACCEPTANCE_REQUIRED",
        "V63_RENDER_R2_REAL_PVC_ACCEPTANCE_REQUIRED",
    ]
    return {
        "status": "STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING",
        "production_ready": False,
        "prepatch_source_snapshot": prepatch_snapshot,
        "primitive_before": primitive_before,
        "phase_a": phase_a,
        "adapter": adapter,
        "adapter_candidate_applied_to_export": True,
        "post_adapter_source_snapshot": post_adapter_snapshot,
        "recovery": recovery,
        "recovery_candidate_applied_to_export": True,
        "post_patch_source_snapshot": post_patch_snapshot,
        "primitive_after": primitive_after,
        "final_binding_plan": final_plan,
        "correlation_source_probe": correlation_source_probe,
        "reference_backend_correlation": reference_backend_correlation,
        "runtime_durable_backend_binding_candidate_proven": backend_candidate_proven,
        "remaining_gates": remaining,
        "safety": {
            "source_repo_modified": False,
            "git_ref_modified": False,
            "git_push_performed": False,
            "render_mutated": False,
            "r2_mutated": False,
            "disposable_export_only": True,
        },
    }


def _json_safe_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _json_safe_result(v)
            for k, v in value.items()
            if str(k) not in {"candidate_source", "backend"}
        }
    if isinstance(value, list):
        return [_json_safe_result(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe_result(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def collect_source_authority(
    export_root: str | Path,
    snapshot: dict[str, Any],
    primitive_probe: dict[str, Any] | None = None,
) -> dict[str, bytes]:
    root = Path(export_root).resolve()
    rels = set(str(rel) for rel in dict(snapshot.get("files") or {}))
    for rel in dict((primitive_probe or {}).get("method_sources") or {}).values():
        if rel:
            rels.add(str(rel))
    blobs: dict[str, bytes] = {}
    for rel in sorted(rels):
        path = root / rel
        if path.is_file():
            normalized_rel = rel.replace("\\", "/")
            artifact_name = "source_authority/" + normalized_rel
            _assert_ascii_relative_path(artifact_name)
            blobs[artifact_name] = path.read_bytes()
    return blobs


def _run_logged_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    import os
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    cp = subprocess.run(
        args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merged_env,
        timeout=timeout_seconds,
        check=False,
    )
    output = cp.stdout or ""
    return {
        "args": args,
        "cwd": str(cwd),
        "returncode": cp.returncode,
        "passed": cp.returncode == 0,
        "output": output,
    }


def run_exact_checkout_validation_suite(
    export_root: str | Path,
    *,
    payload_root: str | Path,
    python_executable: str,
) -> dict[str, Any]:
    import os
    root = Path(export_root).resolve()
    payload = Path(payload_root).resolve()
    pythonpath = os.pathsep.join([str(root), str(payload)])
    env = {"PYTHONPATH": pythonpath}
    checks: dict[str, dict[str, Any]] = {}

    if (root / "tests").is_dir():
        checks["production_repository_tests"] = _run_logged_command(
            [python_executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=root,
            env=env,
        )
    else:
        checks["production_repository_tests"] = {
            "passed": False,
            "returncode": 127,
            "output": "PRODUCTION_TEST_DIRECTORY_MISSING",
            "args": [],
            "cwd": str(root),
        }

    checks["v63_staging_tests"] = _run_logged_command(
        [python_executable, "-m", "unittest", "discover", "-s", str(payload / "tests"), "-p", "test_v63_*.py"],
        cwd=root,
        env=env,
    )

    for name in ("v6_protocol", "v61_hardening_protocol"):
        rel = "mcp/v6_protocol_test.py" if name == "v6_protocol" else "mcp/v61_hardening_protocol_test.py"
        path = root / rel
        if path.is_file():
            checks[name] = _run_logged_command([python_executable, rel], cwd=root, env=env)

    v63_protocol = payload / "mcp" / "v63_protocol_test.py"
    if v63_protocol.is_file():
        checks["v63_protocol"] = _run_logged_command(
            [python_executable, str(v63_protocol)], cwd=root, env=env
        )

    runtime_files = [str(path) for path in sorted((root / "unified_runtime").glob("*.py"))]
    checks["py_compile_runtime"] = _run_logged_command(
        [python_executable, "-m", "py_compile", *runtime_files], cwd=root, env=env
    )

    passed = all(bool(check.get("passed")) for check in checks.values())
    return {
        "status": "PASS" if passed else "BLOCKED",
        "passed": passed,
        "checks": checks,
        "modifies_production": False,
    }


def build_exact_checkout_candidate_artifact(
    repo_root: str | Path,
    output_zip: str | Path,
    *,
    payload_root: str | Path,
    python_executable: str,
    expected_commit: str = EXPECTED_V62_PRODUCTION_COMMIT,
    run_validation: bool = True,
) -> dict[str, Any]:
    verification = verify_exact_source_commit(repo_root, expected_commit=expected_commit)
    if not verification.get("ready"):
        return {
            "status": str(verification.get("status") or "BLOCKED"),
            "production_ready": False,
            "source_verification": verification,
            "artifact_written": False,
        }

    with tempfile.TemporaryDirectory(prefix="cbi-v63-exact-export-") as td:
        export_root = Path(td) / "checkout"
        export_result = export_exact_commit(repo_root, expected_commit, export_root)

        from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot
        from unified_runtime.runtime_event_primitive_probe_v63 import probe_v63_runtime_event_primitives

        pre_snapshot = build_v63_production_source_snapshot(export_root)
        primitive_before = probe_v63_runtime_event_primitives(export_root)
        authority = collect_source_authority(export_root, pre_snapshot, primitive_before)
        original_init = (export_root / "unified_runtime" / "__init__.py").read_text(encoding="utf-8", errors="replace")

        pipeline = build_static_candidate_on_export(export_root)
        adapter = dict(pipeline.get("adapter") or {})
        recovery = dict(pipeline.get("recovery") or {})

        validation = {
            "status": "SKIPPED",
            "passed": False,
            "checks": {},
            "reason": "VALIDATION_DISABLED",
        }
        if run_validation and pipeline.get("status") == "STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING":
            validation = run_exact_checkout_validation_suite(
                export_root,
                payload_root=payload_root,
                python_executable=python_executable,
            )

        candidate_init = (export_root / "unified_runtime" / "__init__.py").read_text(encoding="utf-8", errors="replace")
        import difflib
        init_diff = "".join(difflib.unified_diff(
            original_init.splitlines(keepends=True),
            candidate_init.splitlines(keepends=True),
            fromfile="a/unified_runtime/__init__.py",
            tofile="b/unified_runtime/__init__.py",
        ))

        static_ready = pipeline.get("status") == "STATIC_CANDIDATE_READY_LIVE_ACCEPTANCE_PENDING"
        tests_passed = bool(validation.get("passed")) if run_validation else False
        final_status = (
            "EXACT_CHECKOUT_STATIC_CANDIDATE_VERIFIED_LIVE_BINDING_PENDING"
            if static_ready and tests_passed
            else "BLOCKED_EXACT_CHECKOUT_CANDIDATE"
        )
        report = {
            "schema": "cbi.v63-exact-checkout-candidate-report.v1",
            "status": final_status,
            "expected_production_commit": expected_commit,
            "source_verification": verification,
            "export": export_result,
            "pipeline": _json_safe_result(pipeline),
            "validation": {
                "status": validation.get("status"),
                "passed": validation.get("passed"),
                "check_summary": {
                    name: {
                        "passed": bool(check.get("passed")),
                        "returncode": int(check.get("returncode", -1)),
                    }
                    for name, check in dict(validation.get("checks") or {}).items()
                },
            },
            "production_ready": False,
            "next_gate": "DESIGN_EXACT_RUNTIME_BACKEND_BRIDGE_FROM_SOURCE_AUTHORITY",
            "safety": {
                "git_network_required": False,
                "git_refs_modified": False,
                "git_push_performed": False,
                "render_mutated": False,
                "r2_mutated": False,
                "source_repo_modified": False,
            },
        }

        text_files: dict[str, str] = {
            "runtime_mro.diff": init_diff,
            "adapter.diff": str(adapter.get("unified_diff") or ""),
            "recovery.diff": str(recovery.get("unified_diff") or ""),
            "prepatch_source_snapshot.json": json.dumps(pre_snapshot, ensure_ascii=False, sort_keys=True, indent=2),
            "postpatch_source_snapshot.json": json.dumps(
                pipeline.get("post_patch_source_snapshot") or {}, ensure_ascii=False, sort_keys=True, indent=2
            ),
        }
        for name, check in dict(validation.get("checks") or {}).items():
            safe_name = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in name)
            text_files[f"logs/{safe_name}.log"] = str(check.get("output") or "")

        binary_files = dict(authority)
        if adapter.get("candidate_source"):
            binary_files["candidate/mcp/server_v61.py"] = str(adapter["candidate_source"]).encode("utf-8")
        if recovery.get("candidate_source") and recovery.get("target_file"):
            rel = str(recovery["target_file"]).replace("\\", "/")
            binary_files[f"candidate/{rel}"] = str(recovery["candidate_source"]).encode("utf-8")
        binary_files["candidate/unified_runtime/__init__.py"] = candidate_init.encode("utf-8")

        artifact = write_candidate_artifact(
            output_zip,
            report=report,
            text_files=text_files,
            binary_files=binary_files,
        )
        return {
            **report,
            "artifact": artifact,
            "artifact_written": True,
        }
