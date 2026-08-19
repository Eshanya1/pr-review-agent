from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Category(str, Enum):
    SQL_INJECTION = "sql_injection"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    PII_LOGGING = "pii_logging"
    OFF_BY_ONE = "off_by_one"
    MISSING_AUTH = "missing_auth"
    TIMEZONE_BUG = "timezone_bug"
    SHELL_INJECTION = "shell_injection"
    SESSION_EXPIRY = "session_expiry"
    RACE_CONDITION = "race_condition"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


@dataclass
class Finding:
    category: Category
    severity: Severity
    file: str
    line: int
    summary: str
    evidence: str
    confidence: float = 1.0
    verified: bool = False
    verifier_note: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "summary": self.summary,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "verified": self.verified,
            "verifier_note": self.verifier_note,
        }

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        return Finding(
            category=Category(d["category"]),
            severity=Severity(d["severity"]),
            file=d["file"],
            line=int(d["line"]),
            summary=d["summary"],
            evidence=d["evidence"],
            confidence=float(d.get("confidence", 1.0)),
        )


@dataclass
class ReviewResult:
    findings: list[Finding] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "escalate": self.escalate,
            "escalation_reason": self.escalation_reason,
        }
