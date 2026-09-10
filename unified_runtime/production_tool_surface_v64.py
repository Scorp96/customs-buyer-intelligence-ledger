"""Production-adapter-only MCP tool declarations for CBI v6.4.

Core Runtime tools remain declared by ``V6_CBI_MCP_TOOL_NAMES`` and v6.3
extension tools remain declared by ``mcp_schema_v63``.  This module owns
only tools introduced by the production adapter layer so portable launchers
can validate the composed surface without polluting the core contract.
"""

MUTATION_WAL_AUDIT_TOOL_NAME = "get_mutation_wal_audit"

V64_PRODUCTION_ADAPTER_TOOL_NAMES = (
    MUTATION_WAL_AUDIT_TOOL_NAME,
)

__all__ = [
    "MUTATION_WAL_AUDIT_TOOL_NAME",
    "V64_PRODUCTION_ADAPTER_TOOL_NAMES",
]
