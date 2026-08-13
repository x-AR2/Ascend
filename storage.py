"""
storage.py
----------
Simple JSON persistence. Kept deliberately dumb (single file, load-all /
save-all) so it's trivial to later swap for SQLite or a real DB once this
is wrapped behind Flask/FastAPI — nothing above this layer needs to change,
only the AppData.load()/save() implementations.
"""
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from models import Semester
from cgpa import CGPACalculator

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "app_data.json")


@dataclass
class AppData:
    semesters: List[Semester] = field(default_factory=list)
    active_semester_index: Optional[int] = None
    cgpa: CGPACalculator = field(default_factory=CGPACalculator)

    def active_semester(self) -> Optional[Semester]:
        if self.active_semester_index is None:
            return None
        if 0 <= self.active_semester_index < len(self.semesters):
            return self.semesters[self.active_semester_index]
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "semesters": [s.to_dict() for s in self.semesters],
            "active_semester_index": self.active_semester_index,
            "cgpa": self.cgpa.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppData":
        return cls(
            semesters=[Semester.from_dict(s) for s in d.get("semesters", [])],
            active_semester_index=d.get("active_semester_index"),
            cgpa=CGPACalculator.from_dict(d.get("cgpa", {})),
        )

    def save(self, path: str = DEFAULT_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "AppData":
        if not os.path.exists(path):
            return cls()
        with open(path, "r") as f:
            raw = json.load(f)
        return cls.from_dict(raw)
