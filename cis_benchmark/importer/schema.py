import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImportedRule:
    id: str
    title: str
    scored: bool
    profile_level: str
    section: str
    description: str = ""
    rationale: str = ""
    impact: Optional[str] = None
    audit: str = ""
    remediation: str = ""
    references: List[str] = field(default_factory=list)
    cis_controls: str = ""
    incomplete: bool = False
    missing_sections: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkCatalog:
    benchmark_name: str
    benchmark_version: str
    source_filename: str
    extracted_at: str
    rules: List[ImportedRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "benchmark_version": self.benchmark_version,
            "source_filename": self.source_filename,
            "extracted_at": self.extracted_at,
            "total_rules": len(self.rules),
            "incomplete_rules": sum(1 for r in self.rules if r.incomplete),
            "rules": [r.to_dict() for r in self.rules],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write(self, path: str) -> str:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path
