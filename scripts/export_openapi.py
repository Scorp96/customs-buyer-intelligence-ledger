from __future__ import annotations

from pathlib import Path
import sys

import yaml

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from main import app  # noqa: E402


schema = app.openapi()
schema["servers"] = [{"url": "https://YOUR-SERVICE.onrender.com"}]

for path, methods in schema.get("paths", {}).items():
    for method, operation in methods.items():
        if method.lower() not in {"get", "post", "put", "patch", "delete"}:
            continue
        operation["x-openai-isConsequential"] = path in {"/ledger/merge", "/outreach/events"}

(root / "openapi-action.yaml").write_text(
    yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=120),
    encoding="utf-8",
)
