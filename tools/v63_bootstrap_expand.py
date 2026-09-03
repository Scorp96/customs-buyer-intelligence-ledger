from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
from pathlib import Path

EXPECTED_BASE = "ba3bffdae13cef186b20b50335c3207fb3390ec6"
EXPECTED_FEATURE_BRANCH = "cbi-v6-3-demand-expansion"
EXPECTED_TRANSPORT_SHA256 = "dd0c202bcbbf03654a7329a0c5b21cfb9c90a90597294de27db93bc93861b835"
SOURCE_STAGING_ZIP_SHA256 = "ccec597fff10ced2ec1b024c55fe14325a297302f878240f54dee30da953fd0c"
PAYLOAD_SCHEMA = "cbi.v63-staging-durable-bridge-rebuilt.v1"
V63_TOOLS = {
    "append_candidate_discovery",
    "create_product_opportunity",
    "promote_opportunity_anchor",
}


def run(args: list[str], *, cwd: Path, capture: bool = False) -> str:
    cp = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"COMMAND_FAILED({cp.returncode}): {' '.join(args)}\n{cp.stdout or ''}"
        )
    return (cp.stdout or "").strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reconstruct_payload(root: Path) -> Path:
    chunk_dir = root / "tools" / "v63_payload"
    chunks = sorted(chunk_dir.glob("chunk-*.b64"))
    if not chunks:
        raise RuntimeError("V63_PAYLOAD_CHUNKS_MISSING")
    import base64
    encoded = b"".join(path.read_bytes().strip() for path in chunks)
    raw = base64.b64decode(encoded, validate=True)
    if sha256_bytes(raw) != EXPECTED_TRANSPORT_SHA256:
        raise RuntimeError("V63_TRANSPORT_SHA256_MISMATCH")
    target = root / ".v63-staging-payload.tar.xz"
    target.write_bytes(raw)
    return target


def verify_and_extract(payload_xz: Path, out: Path) -> dict:
    out = out.resolve()
    with tarfile.open(payload_xz, mode="r:xz") as tf:
        members = tf.getmembers()
        names = [member.name for member in members if member.isfile()]
        if any(not name.isascii() for name in names):
            raise RuntimeError("V63_PAYLOAD_NON_ASCII_PATH")
        for member in members:
            if not member.isfile():
                raise RuntimeError(f"V63_PAYLOAD_NON_FILE_ENTRY:{member.name}")
            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError(f"V63_PAYLOAD_UNSAFE_PATH:{member.name}")
            target = (out / rel).resolve()
            if out not in target.parents:
                raise RuntimeError(f"V63_PAYLOAD_PATH_ESCAPE:{member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                raise RuntimeError(f"V63_PAYLOAD_MEMBER_UNREADABLE:{member.name}")
            target.write_bytes(source.read())

    manifest_path = out / "MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError("V63_PAYLOAD_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != PAYLOAD_SCHEMA:
        raise RuntimeError("V63_PAYLOAD_SCHEMA_MISMATCH")
    if manifest.get("production_ready") is not False:
        raise RuntimeError("V63_PAYLOAD_MUST_BE_STAGING_ONLY")
    files = dict(manifest.get("files") or {})
    actual = {
        path.relative_to(out).as_posix()
        for path in out.rglob("*")
        if path.is_file() and path.name != "MANIFEST.json"
    }
    if set(files) != actual:
        raise RuntimeError("V63_PAYLOAD_ENTRY_SET_MISMATCH")
    for rel, meta in files.items():
        data = (out / rel).read_bytes()
        raw_size = meta.get("size_bytes")
        expected_size = int(raw_size) if raw_size is not None else -1
        if len(data) != expected_size:
            raise RuntimeError(f"V63_PAYLOAD_SIZE_MISMATCH:{rel}")
        if sha256_bytes(data) != str(meta.get("sha256") or ""):
            raise RuntimeError(f"V63_PAYLOAD_HASH_MISMATCH:{rel}")
    return manifest


def repo_payload_paths(payload_root: Path) -> list[Path]:
    selected: list[Path] = []
    for path in sorted((payload_root / "unified_runtime").glob("*.py")):
        if path.name.startswith("v62_"):
            continue
        selected.append(path)
    selected.extend(sorted((payload_root / "tests").glob("test_v63_*.py")))
    selected.extend(sorted((payload_root / "scripts").glob("run_v63_*.py")))
    selected.extend(sorted((payload_root / "release_ops_v63").glob("*.py")))
    return selected


def copy_new_payload_files(repo: Path, payload_root: Path) -> list[str]:
    copied: list[str] = []
    for source in repo_payload_paths(payload_root):
        rel = source.relative_to(payload_root)
        target = repo / rel
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                raise RuntimeError(f"V63_PAYLOAD_CONFLICT:{rel.as_posix()}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(rel.as_posix())
    return copied


def exact_integration(repo: Path) -> dict:
    sys.path.insert(0, str(repo))
    from unified_runtime.mro_integration_patch import adapt_runtime_init_text
    from unified_runtime.production_binding_plan import build_v63_production_binding_plan
    from unified_runtime.production_source_snapshot_v63 import build_v63_production_source_snapshot
    from unified_runtime.adapter_patch_compiler_v63 import compile_v63_adapter_patch_candidate
    from unified_runtime.recovery_overlay_patch_compiler_v63 import compile_v63_recovery_overlay_patch_candidate
    from unified_runtime.production_correlation_source_probe_v63 import inspect_v63_production_correlation_bridge
    from unified_runtime.reference_backend_correlation_runner_v63 import run_v63_reference_backend_correlation_acceptance

    pre = build_v63_production_binding_plan(repo)
    if not pre.get("can_apply_patch"):
        raise RuntimeError("V63_PREPATCH_BLOCKED:" + ",".join(pre.get("blockers") or []))

    init_path = repo / "unified_runtime" / "__init__.py"
    init_path.write_text(
        adapt_runtime_init_text(init_path.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="",
    )

    phase_b_snapshot = build_v63_production_source_snapshot(repo)
    if phase_b_snapshot.get("status") != "READY":
        raise RuntimeError("V63_PHASE_B_SNAPSHOT_BLOCKED:" + ",".join(phase_b_snapshot.get("blockers") or []))

    adapter = compile_v63_adapter_patch_candidate(
        repo,
        expected_production_snapshot=phase_b_snapshot,
    )
    if adapter.get("status") != "PATCH_CANDIDATE_READY":
        raise RuntimeError("V63_ADAPTER_CANDIDATE_BLOCKED:" + ",".join(adapter.get("blockers") or []))
    if adapter.get("adapter_codegen_mode") != "DELEGATED_SERVER_OVERLAY":
        raise RuntimeError("V63_EXACT_DELEGATED_ADAPTER_NOT_PROVEN")
    if adapter.get("runtime_durable_backend_binding_candidate_proven") is not True:
        raise RuntimeError("V63_BACKEND_CANDIDATE_BINDING_NOT_PROVEN")
    (repo / "mcp" / "server_v61.py").write_text(
        str(adapter["candidate_source"]), encoding="utf-8", newline=""
    )

    post_adapter = build_v63_production_source_snapshot(repo)
    if post_adapter.get("status") != "READY":
        raise RuntimeError("V63_POST_ADAPTER_SNAPSHOT_BLOCKED")
    recovery = compile_v63_recovery_overlay_patch_candidate(
        repo,
        expected_production_snapshot=post_adapter,
    )
    if recovery.get("status") != "RECOVERY_OVERLAY_PATCH_CANDIDATE_READY":
        raise RuntimeError("V63_RECOVERY_CANDIDATE_BLOCKED:" + ",".join(recovery.get("blockers") or []))
    if dict(recovery.get("probe") or {}).get("recovery_codegen_mode") != "SYNC_RECOVERY_EXTENSION":
        raise RuntimeError("V63_EXACT_SYNC_RECOVERY_NOT_PROVEN")
    target = repo / str(recovery["target_file"])
    target.write_text(str(recovery["candidate_source"]), encoding="utf-8", newline="")

    final_snapshot = build_v63_production_source_snapshot(repo)
    correlation = inspect_v63_production_correlation_bridge(repo)
    if correlation.get("static_correlation_bridge_proven") is not True:
        raise RuntimeError("V63_STATIC_MUTATION_CORRELATION_NOT_PROVEN")
    reference = run_v63_reference_backend_correlation_acceptance(
        production_source_snapshot_sha256=str(final_snapshot.get("snapshot_sha256") or "")
    )
    scenarios = list(reference.get("scenarios") or [])
    if len(scenarios) != 10 or any(
        row.get("status") != "PASS" or row.get("reexecute_side_effect") is not False
        for row in scenarios
    ):
        raise RuntimeError("V63_REFERENCE_NO_REEXECUTION_ACCEPTANCE_FAILED")

    return {
        "prepatch_status": pre.get("status"),
        "adapter_status": adapter.get("status"),
        "adapter_codegen_mode": adapter.get("adapter_codegen_mode"),
        "recovery_status": recovery.get("status"),
        "recovery_codegen_mode": dict(recovery.get("probe") or {}).get("recovery_codegen_mode"),
        "production_source_snapshot_sha256": final_snapshot.get("snapshot_sha256"),
        "static_correlation_bridge_proven": True,
        "reference_scenario_count": len(scenarios),
        "live_acceptance_still_required": True,
        "production_ready": False,
    }


def validate_scope(repo: Path) -> list[str]:
    rows = run(["git", "status", "--porcelain", "-uall"], cwd=repo, capture=True).splitlines()
    allowed_exact = {
        "unified_runtime/__init__.py",
        "mcp/server_v61.py",
        "mcp/server_v61_sync_recovery.py",
        ".github/workflows/cbi-v63-bootstrap.yml",
    }
    allowed_prefixes = (
        "unified_runtime/",
        "tests/test_v63_",
        "scripts/run_v63_",
        "release_ops_v63/",
        "tools/v63_payload/",
        "tools/v63_bootstrap_expand.py",
        ".v63-staging-payload.tar.xz",
    )
    bad: list[str] = []
    for row in rows:
        path = row[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path in allowed_exact or path.startswith(allowed_prefixes):
            continue
        bad.append(path)
    if bad:
        raise RuntimeError("V63_UNEXPECTED_GIT_SCOPE:" + ",".join(sorted(set(bad))))
    return rows


def secret_scan(repo: Path) -> None:
    pat = re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")
    pem = re.compile(rb"-----BEGIN (?:OPENSSH )?PRIVATE KEY-----\r?\n")
    for base in (repo / "unified_runtime", repo / "release_ops_v63", repo / "scripts", repo / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            data = path.read_bytes()
            if pat.search(data):
                raise RuntimeError(f"V63_PAT_LIKE_SECRET:{path.relative_to(repo)}")
            if pem.search(data):
                raise RuntimeError(f"V63_PRIVATE_KEY_MATERIAL:{path.relative_to(repo)}")


def main() -> int:
    repo = Path(os.environ.get("GITHUB_WORKSPACE") or ".").resolve()
    ref_name = str(os.environ.get("GITHUB_REF_NAME") or "").strip()
    if ref_name != EXPECTED_FEATURE_BRANCH:
        raise RuntimeError(f"V63_FEATURE_BRANCH_MISMATCH:{ref_name}")
    actual = run(["git", "rev-parse", "HEAD"], cwd=repo, capture=True)
    parent = run(["git", "rev-parse", "HEAD^"], cwd=repo, capture=True)
    if parent.lower() != EXPECTED_BASE:
        raise RuntimeError(f"V63_BOOTSTRAP_BASE_MISMATCH:{parent}")

    payload_transport = reconstruct_payload(repo)
    with tempfile.TemporaryDirectory(prefix="cbi-v63-payload-") as td:
        payload_root = Path(td)
        verify_and_extract(payload_transport, payload_root)
        copied = copy_new_payload_files(repo, payload_root)

    integration = exact_integration(repo)
    validate_scope(repo)
    secret_scan(repo)

    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"], cwd=repo)
    run([sys.executable, "mcp/v6_protocol_test.py"], cwd=repo)
    run([sys.executable, "mcp/v61_hardening_protocol_test.py"], cwd=repo)
    run([sys.executable, "-m", "py_compile", *[str(p.relative_to(repo)) for p in sorted((repo / "unified_runtime").glob("*.py"))]], cwd=repo)
    run(["git", "diff", "--check"], cwd=repo)

    report = {
        "schema": "cbi.v63-github-bootstrap-attestation.v1",
        "expected_production_base": EXPECTED_BASE,
        "bootstrap_head": actual,
        "source_staging_zip_sha256": SOURCE_STAGING_ZIP_SHA256,
        "transport_sha256": EXPECTED_TRANSPORT_SHA256,
        "copied_files": copied,
        "integration": integration,
        "tests": "PASS",
        "v6_protocol": "PASS",
        "v61_hardening_protocol": "PASS",
        "production_ready": False,
        "next_gate": "FEATURE_BRANCH_CI_THEN_LIVE_BACKEND_RECOVERY_RENDER_R2_PVC_ACCEPTANCE",
    }
    (repo / "V63_FEATURE_ATTESTATION.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="ascii"
    )

    shutil.rmtree(repo / "tools" / "v63_payload")
    (repo / "tools" / "v63_bootstrap_expand.py").unlink()
    payload_transport.unlink()

    validate_scope(repo)
    run(["git", "add", "--all"], cwd=repo)
    run(["git", "diff", "--cached", "--check"], cwd=repo)
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=repo)
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=repo)
    run(["git", "commit", "-m", "feat(v63): expand exact durable demand bridge [skip ci]"], cwd=repo)
    run(["git", "push", "origin", f"HEAD:{EXPECTED_FEATURE_BRANCH}"], cwd=repo)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
