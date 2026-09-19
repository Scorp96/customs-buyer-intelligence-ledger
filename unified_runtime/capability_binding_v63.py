from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .capability_profile import build_capability_profile


def _sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bind_private_capability_bundle(runtime: Any, bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("capability bundle must be an object")
    if bundle.get("public_git_allowed") is not False:
        raise ValueError("PRIVATE_CAPABILITY_BUNDLE_MUST_NOT_BE_PUBLIC_GIT_ALLOWED")
    raw_profiles = bundle.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("PRIVATE_CAPABILITY_BUNDLE_PROFILES_REQUIRED")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_profile in raw_profiles.items():
        profile = build_capability_profile(copy.deepcopy(raw_profile))
        key = str(profile["product_profile_id"]).upper()
        if str(raw_key).upper() != key:
            raise ValueError("PRIVATE_CAPABILITY_PROFILE_KEY_MISMATCH")
        if key in normalized:
            raise ValueError("PRIVATE_CAPABILITY_PROFILE_DUPLICATE:" + key)
        normalized[key] = profile

    existing = getattr(runtime, "_v63_capability_profiles", None)
    if existing:
        existing_digest = _sha256(existing)
        new_digest = _sha256(normalized)
        if existing_digest != new_digest:
            raise RuntimeError("V63_CAPABILITY_PROFILE_ALREADY_BOUND_DIFFERENT_CONTENT")
    else:
        setattr(runtime, "_v63_capability_profiles", normalized)

    bundle_digest = _sha256(bundle)
    setattr(runtime, "_v63_capability_bundle_sha256", bundle_digest)
    return {
        "status": "BOUND_PRIVATE_CAPABILITY_SOURCE",
        "product_profile_ids": sorted(normalized),
        "bundle_sha256": bundle_digest,
        "public_git_allowed": False,
        "persistent_mutation_performed": False,
    }
