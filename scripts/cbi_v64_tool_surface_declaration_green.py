from __future__ import annotations

from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {source.count(old)}")
    return source.replace(old, new, 1)


def main() -> int:
    declaration = Path("unified_runtime/production_tool_surface_v64.py")
    if declaration.exists():
        raise SystemExit("production tool-surface declaration already exists")
    declaration.write_text(
        '"""Production-adapter-only MCP tool declarations for CBI v6.4.\n\n'
        'Core Runtime tools remain declared by ``V6_CBI_MCP_TOOL_NAMES`` and v6.3\n'
        'extension tools remain declared by ``mcp_schema_v63``.  This module owns\n'
        'only tools introduced by the production adapter layer so portable launchers\n'
        'can validate the composed surface without polluting the core contract.\n'
        '"""\n\n'
        'MUTATION_WAL_AUDIT_TOOL_NAME = "get_mutation_wal_audit"\n\n'
        'V64_PRODUCTION_ADAPTER_TOOL_NAMES = (\n'
        '    MUTATION_WAL_AUDIT_TOOL_NAME,\n'
        ')\n\n'
        '__all__ = [\n'
        '    "MUTATION_WAL_AUDIT_TOOL_NAME",\n'
        '    "V64_PRODUCTION_ADAPTER_TOOL_NAMES",\n'
        ']\n',
        encoding="utf-8",
    )

    server = Path("mcp/server_v61.py")
    source = server.read_text(encoding="utf-8")
    import_anchor = "from unified_runtime import ValidationError  # noqa: E402\n"
    source = replace_once(
        source,
        import_anchor,
        import_anchor
        + "from unified_runtime.production_tool_surface_v64 import MUTATION_WAL_AUDIT_TOOL_NAME  # noqa: E402\n",
        "server import",
    )
    source = replace_once(
        source,
        '            "name": "get_mutation_wal_audit",\n',
        '            "name": MUTATION_WAL_AUDIT_TOOL_NAME,\n',
        "descriptor name",
    )
    source = replace_once(
        source,
        '_server.TOOL_HANDLERS["get_mutation_wal_audit"] = _mutation_wal_audit\n',
        '_server.TOOL_HANDLERS[MUTATION_WAL_AUDIT_TOOL_NAME] = _mutation_wal_audit\n',
        "handler name",
    )
    server.write_text(source, encoding="utf-8")

    portability = Path("tests/test_v6_windows_portability.py")
    source = portability.read_text(encoding="utf-8")
    import_anchor = "from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors\n"
    source = replace_once(
        source,
        import_anchor,
        import_anchor
        + "from unified_runtime.production_tool_surface_v64 import V64_PRODUCTION_ADAPTER_TOOL_NAMES\n",
        "portability import",
    )
    old = "    names.update(\n        str(item.get(\"name\") or \"\")\n        for item in build_v63_tool_descriptors()\n        if isinstance(item, dict) and str(item.get(\"name\") or \"\")\n    )\n    return names\n"
    new = "    names.update(\n        str(item.get(\"name\") or \"\")\n        for item in build_v63_tool_descriptors()\n        if isinstance(item, dict) and str(item.get(\"name\") or \"\")\n    )\n    names.update(V64_PRODUCTION_ADAPTER_TOOL_NAMES)\n    return names\n"
    source = replace_once(source, old, new, "production declared set")
    portability.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
