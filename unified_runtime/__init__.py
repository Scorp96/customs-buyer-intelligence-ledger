"""Customs Buyer Intelligence v6 public runtime with v5 compatibility adapters."""

from .core import (
    BUILD_ID,
    CBI_MCP_TOOL_NAMES,
    COMMERCIAL_GATE_ORDER,
    COMMERCIAL_GATE_TAGS,
    CRM_WRITEBACK_REQUIRED,
    EVIDENCE_CLAIM_TYPES,
    EVIDENCE_FRESHNESS,
    EVIDENCE_GRADES,
    EVIDENCE_REFERENCE_TYPES,
    INFORMATION_CONFIDENCE,
    INFORMATION_ROUTE_SCOPES,
    INFORMATION_SOURCE_TYPES,
    INFORMATION_SUBJECT_TYPES,
    INFORMATION_TEMPORAL_STATUS,
    INFORMATION_TYPES,
    NETWORK_BRANCHES,
    PROVIDER_AVAILABILITY,
    PROVIDER_CLASSES,
    PROVIDER_MODES,
    REQUIRED_MODULES,
    RUNTIME_VERSION,
    SUPPLY_CHAIN_PARTY_ROLES,
    UnifiedRuntime as _CompatibilityRuntime,
    VALID_RESULTS,
    ValidationError,
)
from .v6 import (
    AUTHORITY_LEVELS,
    CLAIM_STATES,
    COMMERCIAL_VALUE_GRADES,
    FRESHNESS_LEVELS,
    NETWORK_BRANCHES_V6,
    OUTREACH_READINESS_STATES,
    PEER_STAGES,
    RESEARCH_CONFIDENCE_GRADES,
    V6_BUILD_ID,
    V6_CBI_MCP_TOOL_NAMES,
    V6_RUNTIME_VERSION,
    V6RuntimeMixin,
)
from .hardening import (
    V61_CUSTOMS_PARTY_ROLES,
    V61_FRESHNESS_LEVELS,
    V61_PIVOT_STATES,
    V61ProductionHardeningMixin,
)
from .resume_hardening import V61ResumeReadOnlyMixin
from .authority_hardening import (
    DECISION_RELEVANT_ROLES,
    V61CurrentAuthorityMixin,
)
from .commercial_hardening import (
    COMMERCIAL_OPPORTUNITY_FACTORS,
    OPPORTUNITY_LIFT_WEIGHTS,
    V61CommercialOpportunityMixin,
)
from .outreach_hardening import V61OutreachHardeningMixin
from .portfolio_hardening import (
    PORTFOLIO_ENVIRONMENTS,
    PORTFOLIO_LIFECYCLES,
    V61PortfolioHardeningMixin,
)
from .portfolio_state_hardening import V61PortfolioStateHardeningMixin
from .legacy_peer_projection_hardening import V61LegacyPeerProjectionMixin
from .migration_lineage_hardening import V61MigrationLineageHardeningMixin
from .brand_hardening import BRAND_RELATIONSHIPS, V61BrandHardeningMixin
from .canonical_identity_hardening import (
    EvidenceBoundCanonicalRegistry,
    V61CanonicalIdentityHardeningMixin,
)
from .country_identity_hardening import (
    COUNTRY_RELATION_CONFLICT,
    COUNTRY_RELATION_MISSING,
    COUNTRY_RELATION_SAME,
    COUNTRY_RELATION_UNRESOLVED,
    CountryAwareCanonicalRegistry,
    V61CountryIdentityHardeningMixin,
)

RUNTIME_VERSION = V6_RUNTIME_VERSION
BUILD_ID = V6_BUILD_ID
CBI_MCP_TOOL_NAMES = V6_CBI_MCP_TOOL_NAMES
FRESHNESS_LEVELS = V61_FRESHNESS_LEVELS


class UnifiedRuntime(
    V61CountryIdentityHardeningMixin,
    V61BrandHardeningMixin,
    V61LegacyPeerProjectionMixin,
    V61MigrationLineageHardeningMixin,
    V61PortfolioStateHardeningMixin,
    V61PortfolioHardeningMixin,
    V61OutreachHardeningMixin,
    V61CommercialOpportunityMixin,
    V61CurrentAuthorityMixin,
    V61ProductionHardeningMixin,
    V61ResumeReadOnlyMixin,
    V6RuntimeMixin,
    _CompatibilityRuntime,
):
    """v6 governance runtime layered over the stable v5 compatibility surface."""

    pass


__all__ = [
    "BUILD_ID",
    "CBI_MCP_TOOL_NAMES",
    "COMMERCIAL_GATE_ORDER",
    "COMMERCIAL_GATE_TAGS",
    "CRM_WRITEBACK_REQUIRED",
    "EVIDENCE_CLAIM_TYPES",
    "EVIDENCE_FRESHNESS",
    "EVIDENCE_GRADES",
    "EVIDENCE_REFERENCE_TYPES",
    "INFORMATION_CONFIDENCE",
    "INFORMATION_ROUTE_SCOPES",
    "INFORMATION_SOURCE_TYPES",
    "INFORMATION_SUBJECT_TYPES",
    "INFORMATION_TEMPORAL_STATUS",
    "INFORMATION_TYPES",
    "NETWORK_BRANCHES",
    "PROVIDER_AVAILABILITY",
    "PROVIDER_CLASSES",
    "PROVIDER_MODES",
    "REQUIRED_MODULES",
    "RUNTIME_VERSION",
    "SUPPLY_CHAIN_PARTY_ROLES",
    "UnifiedRuntime",
    "VALID_RESULTS",
    "ValidationError",
    "AUTHORITY_LEVELS",
    "CLAIM_STATES",
    "COMMERCIAL_VALUE_GRADES",
    "FRESHNESS_LEVELS",
    "NETWORK_BRANCHES_V6",
    "OUTREACH_READINESS_STATES",
    "PEER_STAGES",
    "RESEARCH_CONFIDENCE_GRADES",
    "V61_CUSTOMS_PARTY_ROLES",
    "V61_PIVOT_STATES",
    "V61ResumeReadOnlyMixin",
    "DECISION_RELEVANT_ROLES",
    "COMMERCIAL_OPPORTUNITY_FACTORS",
    "OPPORTUNITY_LIFT_WEIGHTS",
    "PORTFOLIO_ENVIRONMENTS",
    "PORTFOLIO_LIFECYCLES",
    "V61PortfolioStateHardeningMixin",
    "V61LegacyPeerProjectionMixin",
    "V61MigrationLineageHardeningMixin",
    "BRAND_RELATIONSHIPS",
    "V61BrandHardeningMixin",
    "EvidenceBoundCanonicalRegistry",
    "V61CanonicalIdentityHardeningMixin",
    "CountryAwareCanonicalRegistry",
    "V61CountryIdentityHardeningMixin",
    "COUNTRY_RELATION_SAME",
    "COUNTRY_RELATION_CONFLICT",
    "COUNTRY_RELATION_MISSING",
    "COUNTRY_RELATION_UNRESOLVED",
]
