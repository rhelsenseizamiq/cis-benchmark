from abc import ABC, abstractmethod
from .models import CheckResult, Status, Severity

class BaseCheck(ABC):
    def __init__(self, rule_id: str, section: str, title: str, severity: Severity, rationale: str, remediation: str):
        self.rule_id = rule_id
        self.section = section
        self.title = title
        self.severity = severity
        self.rationale = rationale
        self.remediation = remediation

    @abstractmethod
    def execute(self) -> CheckResult:
        """Executes the check and returns a CheckResult."""
        pass
