"""
cgpa.py
-------
Standalone CGPA module. Takes a list of (semester name, SGPA, credit hours)
entries — whether they came from this app's own Semester tracking or were
typed in manually for past semesters — and computes CGPA.

    CGPA = Sum(Semester GPA x Semester Credit Hours) / Total Credit Hours (all semesters)
    Percentage = (CGPA / 4.0) * 100
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class SemesterResult:
    name: str
    sgpa: float
    credit_hours: float

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "sgpa": self.sgpa, "credit_hours": self.credit_hours}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SemesterResult":
        return cls(name=d["name"], sgpa=d["sgpa"], credit_hours=d["credit_hours"])


@dataclass
class CGPACalculator:
    semesters: List[SemesterResult] = field(default_factory=list)

    def add(self, name: str, sgpa: float, credit_hours: float):
        self.semesters.append(SemesterResult(name=name, sgpa=sgpa, credit_hours=credit_hours))

    def remove(self, name: str):
        self.semesters = [s for s in self.semesters if s.name != name]

    def total_credit_hours(self) -> float:
        return sum(s.credit_hours for s in self.semesters)

    def cgpa(self) -> Optional[float]:
        tch = self.total_credit_hours()
        if tch == 0:
            return None
        return sum(s.sgpa * s.credit_hours for s in self.semesters) / tch

    def percentage_equivalent(self) -> Optional[float]:
        c = self.cgpa()
        if c is None:
            return None
        return (c / 4.0) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {"semesters": [s.to_dict() for s in self.semesters]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CGPACalculator":
        return cls(semesters=[SemesterResult.from_dict(s) for s in d.get("semesters", [])])
