from __future__ import annotations

from pathlib import Path


def main() -> int:
    path = Path("mcp/server_v61.py")
    source = path.read_text(encoding="utf-8")
    if '"name": "get_mutation_wal_audit"' in source:
        raise SystemExit("WAL audit MCP descriptor already present; refusing duplicate patch")

    descriptor_anchor = "        if name in _LEGACY_COMPATIBILITY_TOOLS:\n            tool[\"description\"] = \"[LEGACY_COMPATIBILITY_ONLY] \" + str(\n                tool.get(\"description\") or \"\"\n            )\n    return tools\n"
    if descriptor_anchor not in source:
        raise SystemExit("expected hardened_tool_descriptors anchor not found")
    descriptor_replacement = "        if name in _LEGACY_COMPATIBILITY_TOOLS:\n            tool[\"description\"] = \"[LEGACY_COMPATIBILITY_ONLY] \" + str(\n                tool.get(\"description\") or \"\"\n            )\n\n    tools.append(\n        {\n            \"name\": \"get_mutation_wal_audit\",\n            \"description\": (\n                \"Read-only sanitized audit of terminal production mutation WAL records. \"\n                \"Returns allowlisted metadata only; never raw arguments, idempotency keys, \"\n                \"resource snapshots, or result payloads.\"\n            ),\n            \"inputSchema\": {\n                \"type\": \"object\",\n                \"additionalProperties\": False,\n                \"properties\": {\n                    \"status\": {\n                        \"type\": \"string\",\n                        \"enum\": [\"COMMITTED_ERROR\", \"COMMITTED\"],\n                        \"default\": \"COMMITTED_ERROR\",\n                        \"description\": \"Terminal WAL status to audit; defaults to committed errors.\",\n                    },\n                    \"limit\": {\n                        \"type\": \"integer\",\n                        \"minimum\": 1,\n                        \"maximum\": 500,\n                        \"default\": 100,\n                        \"description\": \"Maximum number of latest matching sanitized rows to return.\",\n                    },\n                },\n            },\n        }\n    )\n    return tools\n"
    source = source.replace(descriptor_anchor, descriptor_replacement, 1)

    handler_anchor = '_server.TOOL_HANDLERS["get_runtime_health"] = _health_with_adapter_wal\n'
    if handler_anchor not in source:
        raise SystemExit("expected handler registration anchor not found")
    source = source.replace(
        handler_anchor,
        handler_anchor + '_server.TOOL_HANDLERS["get_mutation_wal_audit"] = _mutation_wal_audit\n',
        1,
    )
    path.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
