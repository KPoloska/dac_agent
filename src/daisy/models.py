from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class CheckResult:
    check_id: str
    name: str
    status: str
    severity: str = "major"
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "evidence": dict(self.evidence or {}),
        }


@dataclass
class SectionResult:
    section_id: str
    name: str
    status: str
    checks: List[CheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "name": self.name,
            "status": self.status,
            "checks": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.checks],
        }


@dataclass
class ReviewResult:
    dac_file: str
    generated_at: str
    overall_status: str
    sections: List[SectionResult] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dac_file": self.dac_file,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "sections": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.sections],
            "recommendations": list(self.recommendations or []),
            "stats": dict(self.stats or {}),
        }

    # --- mapping protocol so dict(ReviewResult(...)) works in tests ---
    def keys(self):
        return self.to_dict().keys()

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]
