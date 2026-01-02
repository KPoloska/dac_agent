from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime, timezone

Status = Literal["MET", "PARTIALLY_MET", "NOT_MET", "SKIPPED", "UNKNOWN"]
Severity = Literal["critical", "major", "minor", "info"]

@dataclass
class CheckResult:
    check_id: str
    name: str
    status: Status
    severity: Severity = "major"
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SectionResult:
    section_id: str
    name: str
    status: Status
    checks: List[CheckResult] = field(default_factory=list)

@dataclass
class ReviewResult:
    dac_file: str
    generated_at: str
    overall_status: Status
    sections: List[SectionResult]
    recommendations: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
