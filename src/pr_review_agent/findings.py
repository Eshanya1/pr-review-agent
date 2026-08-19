from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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


class Finding(BaseModel):
    """A single reviewer claim about the diff.

    This is a pydantic model, not a plain dataclass, because it's the schema
    an LLM's raw JSON output gets validated against (see reviewer.py) --
    malformed shape (wrong types, missing fields, an invented category) is
    rejected here rather than trusted blindly.
    """

    category: Category
    severity: Severity
    file: str
    line: int
    summary: str
    evidence: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verified: bool = False
    verifier_note: str = ""

    def to_dict(self) -> dict:
        d = self.model_dump(mode="json")
        d["confidence"] = round(d["confidence"], 3)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Finding":
        return Finding.model_validate(d)


class ReviewResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    escalate: bool = False
    escalation_reason: str = ""
    input_flagged: bool = False

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "escalate": self.escalate,
            "escalation_reason": self.escalation_reason,
            "input_flagged": self.input_flagged,
        }
