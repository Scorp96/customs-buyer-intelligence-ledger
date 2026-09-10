from __future__ import annotations

import re


V62_IMPORT = "from .research_orchestration_hardening import V61ResearchOrchestrationHardeningMixin"
V63_IMPORT = "from .demand_expansion import V63DemandExpansionMixin"
V62_MIXIN = "V61ResearchOrchestrationHardeningMixin"
V63_MIXIN = "V63DemandExpansionMixin"


def adapt_runtime_init_text(text: str) -> str:
    """Idempotently place the v6.3 mixin in front of an already-v6.2 runtime.

    This helper deliberately refuses a pre-v6.2 baseline. It is intended for the
    real production checkout only after the v6.2 orchestration overlay is present.
    """
    if V62_IMPORT not in text or re.search(
        rf"(?m)^\s*{re.escape(V62_MIXIN)}\s*,\s*$",
        text,
    ) is None:
        raise RuntimeError("V6.2 orchestration baseline is required before v6.3 integration")

    all_declarations = list(re.finditer(r"(?m)^class\s+UnifiedRuntime\s*\(", text))
    if len(all_declarations) != 1:
        raise RuntimeError(f"expected exactly one UnifiedRuntime declaration, found {len(all_declarations)}")
    declarations = list(re.finditer(r"(?m)^class\s+UnifiedRuntime\s*\(\s*$", text))
    if len(declarations) != 1:
        raise RuntimeError("UnifiedRuntime declaration must remain multi-line for safe MRO insertion")

    nl = "\r\n" if "\r\n" in text else "\n"

    if V63_IMPORT not in text:
        idx = text.find(V62_IMPORT)
        text = text[:idx] + V63_IMPORT + nl + text[idx:]
    elif text.count(V63_IMPORT) != 1:
        raise RuntimeError("ambiguous v6.3 import state")

    if re.search(rf"(?m)^\s*{re.escape(V63_MIXIN)}\s*,\s*$", text) is None:
        declarations = list(re.finditer(r"(?m)^class\s+UnifiedRuntime\s*\(\s*$", text))
        if len(declarations) != 1:
            raise RuntimeError("UnifiedRuntime declaration drifted during adaptation")
        insert_at = declarations[0].end()
        text = text[:insert_at] + nl + f"    {V63_MIXIN}," + text[insert_at:]

    if text.count(V63_IMPORT) != 1:
        raise RuntimeError("expected exactly one v6.3 import")
    if len(re.findall(rf"(?m)^\s*{re.escape(V63_MIXIN)}\s*,\s*$", text)) != 1:
        raise RuntimeError("expected exactly one v6.3 MRO base")

    class_start = text.find("class UnifiedRuntime")
    class_tail = text[class_start:]
    if class_tail.find(f"{V63_MIXIN},") < 0 or class_tail.find(f"{V62_MIXIN},") < 0:
        raise RuntimeError("cannot prove v6.3/v6.2 MRO placement")
    if class_tail.find(f"{V63_MIXIN},") > class_tail.find(f"{V62_MIXIN},"):
        raise RuntimeError("v6.3 mixin is not in front of v6.2 orchestration mixin")

    return text
