from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .product_profiles import get_product_profile


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_range(value: Any, field: str, *, positive: bool = True) -> list[float] | None:
    if value is None:
        return None
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise ValueError(f"{field} must be [min,max]")
    low, high = float(value[0]), float(value[1])
    if (positive and low <= 0) or high < low:
        raise ValueError(f"invalid {field} range")
    return [low, high]


def _normalize_sizes(value: Any) -> list[list[float]]:
    sizes: list[list[float]] = []
    for size in value or []:
        if not (isinstance(size, (list, tuple)) and len(size) == 2):
            raise ValueError("each supported size must be [width,length]")
        width, length = float(size[0]), float(size[1])
        if width <= 0 or length <= 0:
            raise ValueError("supported sizes must be positive")
        sizes.append([width, length])
    return sizes


def _normalize_options(value: Any) -> list[str]:
    return sorted({str(v).strip().upper() for v in (value or []) if str(v).strip()})


def _normalize_numeric_values(value: Any, field: str) -> list[float]:
    values: list[float] = []
    for item in value or []:
        number = float(item)
        if number <= 0:
            raise ValueError(f"{field} values must be positive")
        values.append(number)
    return sorted(set(values))




def _normalize_spec_combinations(value: Any) -> list[dict[str, Any]]:
    combinations: list[dict[str, Any]] = []
    allowed = {"thickness_mm", "density_g_cm3", "size_mm", "color", "surface", "lamination"}
    for raw in value or []:
        if not isinstance(raw, dict) or not raw:
            raise ValueError("verified_spec_combinations entries must be non-empty objects")
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("unsupported spec combination fields: " + ", ".join(sorted(unknown)))
        item: dict[str, Any] = {}
        for key, val in raw.items():
            if key in {"thickness_mm", "density_g_cm3"}:
                number = float(val)
                if number <= 0:
                    raise ValueError(f"{key} must be positive")
                item[key] = number
            elif key == "size_mm":
                if not (isinstance(val, (list, tuple)) and len(val) == 2):
                    raise ValueError("spec combination size_mm must be [width,length]")
                item[key] = [float(val[0]), float(val[1])]
            else:
                item[key] = str(val).strip().upper()
        combinations.append(item)
    return combinations

def _normalize_variant_capability(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("variant capability must be an object")
    result: dict[str, Any] = {
        "capability_status": str(value.get("capability_status") or "PARTIALLY_VERIFIED").strip().upper(),
        "inherit_family_specs": bool(value.get("inherit_family_specs", True)),
        "production_line": str(value.get("production_line") or "").strip().upper() or None,
        "supported_structure": str(value.get("supported_structure") or "").strip().upper() or None,
        "supported_thickness_mm": _normalize_range(value.get("supported_thickness_mm"), "supported_thickness_mm"),
        "supported_thickness_values_mm": _normalize_numeric_values(value.get("supported_thickness_values_mm"), "supported_thickness_values_mm"),
        "supported_sizes_mm": _normalize_sizes(value.get("supported_sizes_mm")),
        "density_g_cm3": _normalize_range(value.get("density_g_cm3"), "density_g_cm3"),
        "surface_options": _normalize_options(value.get("surface_options")),
        "lamination_options": _normalize_options(value.get("lamination_options")),
        "color_options": _normalize_options(value.get("color_options")),
        "machining_options": _normalize_options(value.get("machining_options")),
        "packing_options": _normalize_options(value.get("packing_options")),
        "verified_spec_combinations": _normalize_spec_combinations(value.get("verified_spec_combinations")),
        "verified_claims": _normalize_options(value.get("verified_claims")),
        "unverified_claims": _normalize_options(value.get("unverified_claims")),
        "known_limitations": copy.deepcopy(value.get("known_limitations", [])),
        "evidence_sources": copy.deepcopy(value.get("evidence_sources", [])),
    }
    overlap = set(result["verified_claims"]) & set(result["unverified_claims"])
    if overlap:
        raise ValueError("variant claim cannot be both verified and unverified: " + ", ".join(sorted(overlap)))
    return result


def build_capability_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("capability profile must be an object")
    required = ("capability_profile_id", "version", "product_profile_id")
    missing = [name for name in required if not str(payload.get(name) or "").strip()]
    if missing:
        raise ValueError("missing capability fields: " + ", ".join(missing))

    profile_id = str(payload["product_profile_id"]).strip().upper()
    product_profile = get_product_profile(profile_id)
    allowed_variants = set(product_profile.get("variants", [])) | set(product_profile.get("subfamilies", []))
    supported_variants = sorted({str(v).strip().upper() for v in payload.get("supported_variants", []) if str(v).strip()})
    unknown_variants = [v for v in supported_variants if v not in allowed_variants]
    if unknown_variants:
        raise ValueError("unknown supported variants: " + ", ".join(unknown_variants))

    verified_claims = _normalize_options(payload.get("verified_claims"))
    unverified_claims = _normalize_options(payload.get("unverified_claims"))
    overlap = set(verified_claims) & set(unverified_claims)
    if overlap:
        raise ValueError("claim cannot be both verified and unverified: " + ", ".join(sorted(overlap)))

    variant_capabilities: dict[str, dict[str, Any]] = {}
    raw_variant_capabilities = payload.get("variant_capabilities") or {}
    if not isinstance(raw_variant_capabilities, dict):
        raise ValueError("variant_capabilities must be an object")
    for raw_variant, raw_capability in raw_variant_capabilities.items():
        variant = str(raw_variant).strip().upper()
        if variant not in allowed_variants:
            raise ValueError(f"unknown variant capability: {variant}")
        if supported_variants and variant not in supported_variants:
            raise ValueError(f"variant capability not declared supported: {variant}")
        variant_capabilities[variant] = _normalize_variant_capability(raw_capability)

    result = {
        "capability_profile_id": str(payload["capability_profile_id"]).strip(),
        "version": str(payload["version"]).strip(),
        "product_profile_id": profile_id,
        "supported_variants": supported_variants,
        "production_line": str(payload.get("production_line") or "").strip().upper() or None,
        "supported_structure": str(payload.get("supported_structure") or "").strip().upper() or None,
        "supported_thickness_mm": _normalize_range(payload.get("supported_thickness_mm"), "supported_thickness_mm"),
        "supported_thickness_values_mm": _normalize_numeric_values(payload.get("supported_thickness_values_mm"), "supported_thickness_values_mm"),
        "supported_sizes_mm": _normalize_sizes(payload.get("supported_sizes_mm")),
        "density_g_cm3": _normalize_range(payload.get("density_g_cm3"), "density_g_cm3"),
        "surface_options": _normalize_options(payload.get("surface_options")),
        "lamination_options": _normalize_options(payload.get("lamination_options")),
        "color_options": _normalize_options(payload.get("color_options")),
        "machining_options": _normalize_options(payload.get("machining_options")),
        "packing_options": _normalize_options(payload.get("packing_options")),
        "verified_spec_combinations": _normalize_spec_combinations(payload.get("verified_spec_combinations")),
        "verified_claims": verified_claims,
        "unverified_claims": unverified_claims,
        "known_limitations": copy.deepcopy(payload.get("known_limitations", [])),
        "evidence_sources": copy.deepcopy(payload.get("evidence_sources", [])),
        "variant_capabilities": variant_capabilities,
        "validation_status": str(payload.get("validation_status") or "PARTIALLY_VERIFIED").strip().upper(),
    }
    result["sha256"] = _digest(result)
    return result


def _effective_capability(capability: dict[str, Any], variant: str) -> dict[str, Any]:
    effective = {
        "production_line": capability.get("production_line"),
        "supported_structure": capability.get("supported_structure"),
        "supported_thickness_mm": copy.deepcopy(capability.get("supported_thickness_mm")),
        "supported_thickness_values_mm": copy.deepcopy(capability.get("supported_thickness_values_mm") or []),
        "supported_sizes_mm": copy.deepcopy(capability.get("supported_sizes_mm") or []),
        "density_g_cm3": copy.deepcopy(capability.get("density_g_cm3")),
        "surface_options": copy.deepcopy(capability.get("surface_options") or []),
        "lamination_options": copy.deepcopy(capability.get("lamination_options") or []),
        "color_options": copy.deepcopy(capability.get("color_options") or []),
        "machining_options": copy.deepcopy(capability.get("machining_options") or []),
        "packing_options": copy.deepcopy(capability.get("packing_options") or []),
        "verified_spec_combinations": copy.deepcopy(capability.get("verified_spec_combinations") or []),
        "verified_claims": copy.deepcopy(capability.get("verified_claims") or []),
        "unverified_claims": copy.deepcopy(capability.get("unverified_claims") or []),
        "known_limitations": copy.deepcopy(capability.get("known_limitations") or []),
        "evidence_sources": copy.deepcopy(capability.get("evidence_sources") or []),
        "capability_status": capability.get("validation_status"),
    }
    variant_data = (capability.get("variant_capabilities") or {}).get(variant)
    if variant_data:
        if not bool(variant_data.get("inherit_family_specs", True)):
            effective.update({
                "supported_thickness_mm": None,
                "supported_thickness_values_mm": [],
                "supported_sizes_mm": [],
                "density_g_cm3": None,
                "surface_options": [],
                "lamination_options": [],
                "color_options": [],
                "machining_options": [],
                "packing_options": [],
                "verified_spec_combinations": [],
                "verified_claims": [],
            })
        for key in (
            "production_line", "supported_structure", "supported_thickness_mm", "density_g_cm3", "capability_status"
        ):
            if variant_data.get(key) is not None:
                effective[key] = copy.deepcopy(variant_data[key])
        for key in (
            "supported_thickness_values_mm", "supported_sizes_mm", "surface_options", "lamination_options", "color_options",
            "machining_options", "packing_options", "verified_spec_combinations"
        ):
            if variant_data.get(key):
                effective[key] = copy.deepcopy(variant_data[key])
        effective["verified_claims"] = sorted(set(effective["verified_claims"]) | set(variant_data.get("verified_claims") or []))
        effective["unverified_claims"] = sorted(set(effective["unverified_claims"]) | set(variant_data.get("unverified_claims") or []))
        effective["known_limitations"] += copy.deepcopy(variant_data.get("known_limitations") or [])
        effective["evidence_sources"] += copy.deepcopy(variant_data.get("evidence_sources") or [])
    return effective


def _requested_option(reasons: list[str], value: Any, options: list[str], label: str) -> None:
    if value is None or value == "":
        return
    requested = str(value).strip().upper()
    if not options:
        reasons.append(f"{label}_NOT_VERIFIED")
    elif requested not in set(options):
        reasons.append(f"{label}_NOT_LISTED")




def _spec_combination_matches_demand(combination: dict[str, Any], demand: dict[str, Any]) -> bool:
    constrained_fields = ("thickness_mm", "density_g_cm3", "size_mm", "color", "surface", "lamination")
    for field in constrained_fields:
        if demand.get(field) is None or demand.get(field) == "":
            continue
        if field not in combination:
            return False
        requested = demand[field]
        actual = combination[field]
        if field in {"thickness_mm", "density_g_cm3"}:
            if float(requested) != float(actual):
                return False
        elif field == "size_mm":
            if [float(requested[0]), float(requested[1])] != [float(actual[0]), float(actual[1])]:
                return False
        else:
            if str(requested).strip().upper() != str(actual).strip().upper():
                return False
    return True

def evaluate_capability_fit(capability: dict[str, Any], demand: dict[str, Any]) -> dict[str, Any]:
    if str(demand.get("product_profile_id") or "").upper() != str(capability.get("product_profile_id") or "").upper():
        return {
            "capability_fit": "UNSUPPORTED",
            "reasons": ["PRODUCT_PROFILE_MISMATCH"],
            "missing_verified_claims": list(demand.get("required_claims") or []),
        }

    reasons: list[str] = []
    variant = str(demand.get("product_variant") or "").upper()
    supported_variants = set(capability.get("supported_variants") or [])
    if variant and variant not in supported_variants:
        reasons.append("UNSUPPORTED_VARIANT")
    effective = _effective_capability(capability, variant)

    thickness = demand.get("thickness_mm")
    supported_range = effective.get("supported_thickness_mm")
    supported_values = effective.get("supported_thickness_values_mm") or []
    if thickness is not None:
        value = float(thickness)
        if supported_range and float(supported_range[0]) <= value <= float(supported_range[1]):
            pass
        elif supported_values and value in {float(v) for v in supported_values}:
            pass
        elif supported_range:
            reasons.append("THICKNESS_OUT_OF_RANGE")
        elif supported_values:
            reasons.append("THICKNESS_NOT_LISTED")
        else:
            reasons.append("THICKNESS_NOT_VERIFIED")

    density = demand.get("density_g_cm3")
    density_range = effective.get("density_g_cm3")
    if density is not None:
        if density_range:
            value = float(density)
            if not (float(density_range[0]) <= value <= float(density_range[1])):
                reasons.append("DENSITY_OUT_OF_RANGE")
        else:
            reasons.append("DENSITY_NOT_VERIFIED")

    size = demand.get("size_mm")
    supported_sizes = effective.get("supported_sizes_mm") or []
    if size is not None:
        if supported_sizes:
            normalized = [float(size[0]), float(size[1])]
            if normalized not in supported_sizes:
                reasons.append("SIZE_NOT_LISTED")
        else:
            reasons.append("SIZE_NOT_VERIFIED")

    _requested_option(reasons, demand.get("surface"), effective.get("surface_options") or [], "SURFACE")
    _requested_option(reasons, demand.get("lamination"), effective.get("lamination_options") or [], "LAMINATION")
    _requested_option(reasons, demand.get("color"), effective.get("color_options") or [], "COLOR")

    requested_machining = demand.get("machining") or []
    if isinstance(requested_machining, str):
        requested_machining = [requested_machining]
    machining_options = set(effective.get("machining_options") or [])
    for item in requested_machining:
        normalized = str(item).strip().upper()
        if not machining_options:
            reasons.append("MACHINING_NOT_VERIFIED")
            break
        if normalized not in machining_options:
            reasons.append(f"MACHINING_NOT_LISTED:{normalized}")

    combinations = effective.get("verified_spec_combinations") or []
    if combinations:
        has_constrained_demand = any(
            demand.get(field) is not None and demand.get(field) != ""
            for field in ("thickness_mm", "density_g_cm3", "size_mm", "color", "surface", "lamination")
        )
        if has_constrained_demand and not any(_spec_combination_matches_demand(combo, demand) for combo in combinations):
            reasons.append("SPEC_COMBINATION_NOT_VERIFIED")

    required_claims = sorted({str(v).strip().upper() for v in demand.get("required_claims", []) if str(v).strip()})
    verified_claims = set(effective.get("verified_claims") or [])
    missing_claims = [claim for claim in required_claims if claim not in verified_claims]

    hard_unsupported = {
        "UNSUPPORTED_VARIANT", "THICKNESS_OUT_OF_RANGE", "DENSITY_OUT_OF_RANGE"
    }
    if any(reason in hard_unsupported for reason in reasons):
        fit = "UNSUPPORTED"
    elif missing_claims or reasons:
        fit = "NEEDS_VERIFICATION"
    else:
        fit = "SUPPORTED"

    return {
        "capability_fit": fit,
        "reasons": reasons,
        "missing_verified_claims": missing_claims,
        "product_profile_id": capability.get("product_profile_id"),
        "product_variant": variant or None,
        "capability_status": effective.get("capability_status"),
        "production_line": effective.get("production_line"),
        "supported_structure": effective.get("supported_structure"),
        "evidence_sources": copy.deepcopy(effective.get("evidence_sources") or []),
    }
