from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime, timezone

class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    MANUAL_CHECK = "MANUAL_CHECK"
    ERROR = "ERROR"

class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

@dataclass
class CheckResult:
    rule_id: str
    section: str
    title: str
    severity: Severity
    status: Status
    rationale: str
    remediation: str
    affected_resources: List[str] = field(default_factory=list)
    details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "section": self.section,
            "title": self.title,
            "severity": self.severity.value,
            "status": self.status.value,
            "rationale": self.rationale,
            "remediation": self.remediation,
            "affected_resources": self.affected_resources,
            "details": self.details,
            "timestamp": self.timestamp
        }
