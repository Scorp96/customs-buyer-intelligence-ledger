from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".txt"}
FORBIDDEN_FILES = {".xlsx", ".xls", ".csv", ".tsv", ".sqlite", ".sqlite3", ".db"}
PRODUCTION_DENYLIST = {
    "ninghang tarde agency",
    "ferretería elefante",
    "rude cosmetics",
    "impec ecuador",
    "tri trien",
    "embeex ventures",
    "phoenix plywood",
    "south florida lumber",
    "corsair marine",
    "sea bridge mexico",
    "kim tuong",
    "travel service trading company limited",
    "zibo kaichuang plastic",
    "uptown premier concepts",
    "raquel borja espiritu",
    "sittagdv636981",
    "dwchsqins0049183",
    "segu7601738",
    "tscw18724842",
    "220536156000",
    "108221973420",
}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "example.invalid", "synthetic.invalid", "examplebuyer.com", "synth-buyer.example"}
EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Z0-9.-]+\.[A-Z]{2,63})", re.I)


def main() -> None:
    issues: list[str] = []
    scanned = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.suffix.casefold() in FORBIDDEN_FILES:
            issues.append(f"production-data file type forbidden: {relative}")
        if path.suffix.casefold() not in TEXT_EXTENSIONS:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        folded = text.casefold()
        for token in sorted(PRODUCTION_DENYLIST):
            if token in folded:
                issues.append(f"production-derived token {token!r}: {relative}")
        for domain in EMAIL_RE.findall(text):
            normalized = domain.casefold()
            if normalized not in ALLOWED_EMAIL_DOMAINS:
                issues.append(f"non-synthetic email domain {normalized}: {relative}")
    if issues:
        raise SystemExit("\n".join(issues))
    print(json.dumps({"status": "PASS", "files_scanned": scanned, "forbidden_data_files": 0, "production_tokens": 0, "non_synthetic_test_emails": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
