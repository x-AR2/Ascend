"""
models.py
---------
Data model + calculation engine.

Layout of a course:
  Course
    ├── theory: Portion            (always present)
    │     ├── Component("Assignments", weight=10)
    │     ├── Component("Quizzes",     weight=15)
    │     ├── Component("Midterm",     weight=25)
    │     └── Component("Final",       weight=50)
    └── lab: Portion | None         (only if has_lab)
          ├── Component("Lab Assignments", weight=25)
          ├── Component("Lab Midterm",     weight=25)
          └── Component("Lab Final",       weight=50)

A Component holds one or more AssessmentItems (e.g. Quiz 1, Quiz 2) that
split its weight evenly by default (matches "2 quizzes @ 7.5% each" but
adapts automatically if there are 1, 3, 4... quizzes instead).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from grading import percentage_to_grade, min_percentage_for_grade_point


# --------------------------------------------------------------------------- #
# Assessment item
# --------------------------------------------------------------------------- #
@dataclass
class AssessmentItem:
    name: str
    max_marks: float
    obtained_marks: Optional[float] = None

    @property
    def is_completed(self) -> bool:
        return self.obtained_marks is not None

    @property
    def percent_score(self) -> Optional[float]:
        if self.obtained_marks is None or not self.max_marks:
            return None
        return (self.obtained_marks / self.max_marks) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "max_marks": self.max_marks, "obtained_marks": self.obtained_marks}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AssessmentItem":
        return cls(name=d["name"], max_marks=d["max_marks"], obtained_marks=d.get("obtained_marks"))


# --------------------------------------------------------------------------- #
# Component (Assignments / Quizzes / Midterm / Final / Lab ... )
# --------------------------------------------------------------------------- #
@dataclass
class Component:
    name: str
    total_weight: float  # % of the portion's total grade
    items: List[AssessmentItem] = field(default_factory=list)

    def add_item(self, name: str, max_marks: float, obtained_marks: Optional[float] = None) -> AssessmentItem:
        item = AssessmentItem(name=name, max_marks=max_marks, obtained_marks=obtained_marks)
        self.items.append(item)
        return item

    def _item_weight(self, item: AssessmentItem) -> float:
        """Each item's slice of this component's weight (evenly split by default)."""
        if not self.items:
            return 0.0
        return self.total_weight / len(self.items)

    def contribution(self) -> float:
        """Percentage points (of the portion total) already banked from completed items."""
        total = 0.0
        for it in self.items:
            if it.is_completed:
                total += (it.percent_score / 100) * self._item_weight(it)
        return total

    def completed_weight(self) -> float:
        return sum(self._item_weight(it) for it in self.items if it.is_completed)

    def remaining_weight(self) -> float:
        return sum(self._item_weight(it) for it in self.items if not it.is_completed)

    def is_complete(self) -> bool:
        return bool(self.items) and all(it.is_completed for it in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "total_weight": self.total_weight, "items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Component":
        return cls(name=d["name"], total_weight=d["total_weight"],
                    items=[AssessmentItem.from_dict(i) for i in d.get("items", [])])


def default_theory_components() -> List[Component]:
    return [
        Component("Assignments", 10.0),
        Component("Quizzes", 15.0),
        Component("Midterm", 25.0),
        Component("Final", 50.0),
    ]


def default_lab_components() -> List[Component]:
    return [
        Component("Lab Assignments", 25.0),
        Component("Lab Midterm", 25.0),
        Component("Lab Final", 50.0),
    ]


# --------------------------------------------------------------------------- #
# Portion (the theory half, or the lab half, of a course)
# --------------------------------------------------------------------------- #
@dataclass
class Portion:
    credit_hours: float
    components: List[Component] = field(default_factory=list)

    def find_component(self, name: str) -> Optional[Component]:
        for c in self.components:
            if c.name.lower() == name.lower():
                return c
        return None

    def total_weight(self) -> float:
        return sum(c.total_weight for c in self.components)

    def achieved_contribution(self) -> float:
        return sum(c.contribution() for c in self.components)

    def completed_weight(self) -> float:
        return sum(c.completed_weight() for c in self.components)

    def remaining_weight(self) -> float:
        return sum(c.remaining_weight() for c in self.components)

    def is_complete(self) -> bool:
        return bool(self.components) and all(c.is_complete() for c in self.components)

    def current_percent(self) -> Optional[float]:
        """Percentage so far, scaled up over the weight actually completed (informational)."""
        cw = self.completed_weight()
        if cw == 0:
            return None
        return (self.achieved_contribution() / cw) * 100

    def final_percent(self) -> Optional[float]:
        """Only meaningful once every item is entered — the portion's locked-in percentage."""
        if not self.is_complete():
            return None
        return self.achieved_contribution()  # weights sum to 100

    def required_avg_on_remaining(self, target_percent: float) -> Optional[float]:
        """
        The average % you must score across ALL remaining (not-yet-graded) items
        in this portion, assuming equal effort on each, to hit target_percent
        overall for this portion. Returns None if nothing remains.
        Can be >100 (mathematically out of reach) or <0 (already secured).
        """
        remaining = self.remaining_weight()
        if remaining <= 0:
            return None
        needed_points = target_percent - self.achieved_contribution()
        return (needed_points / remaining) * 100

    def best_case_percent(self) -> float:
        """Ceiling: the highest percentage still reachable if you scored 100% on everything left."""
        return self.achieved_contribution() + self.remaining_weight()

    def pace_status(self, target_percent: float) -> Dict[str, Any]:
        """
        A single bundle of everything needed to judge whether you're on track:
        current running average, what's still needed, and the hard ceiling on
        what's still achievable (so 'is my target still even possible' is a
        direct lookup, not something the caller has to re-derive).
        """
        achieved = self.achieved_contribution()
        remaining = self.remaining_weight()
        current_avg = self.current_percent()
        required = self.required_avg_on_remaining(target_percent)
        best_case = self.best_case_percent()
        best_letter, best_gp = percentage_to_grade(best_case)
        target_letter, target_gp = percentage_to_grade(target_percent)
        return {
            "achieved_so_far": round(achieved, 2),
            "remaining_weight": round(remaining, 2),
            "current_avg": round(current_avg, 2) if current_avg is not None else None,
            "required_avg_on_remaining": round(required, 2) if required is not None else None,
            "best_case_percent": round(best_case, 2),
            "best_case_grade": best_letter,
            "target_letter": target_letter,
            "target_still_possible": best_case >= target_percent - 1e-9,
            "is_complete": self.is_complete(),
            "final_percent": round(self.final_percent(), 2) if self.is_complete() else None,
        }

    def find_item(self, item_name: str):
        for c in self.components:
            for it in c.items:
                if it.name.lower() == item_name.lower():
                    return c, it
        return None, None

    def item_weight(self, item) -> float:
        for c in self.components:
            if item in c.items and c.items:
                return c.total_weight / len(c.items)
        return 0.0

    def required_for_item(self, item_name: str, target_percent: float,
                           assumed_scores: Optional[Dict[str, float]] = None) -> Optional[float]:
        """
        Exact % needed on ONE specific pending item to hit target_percent overall,
        given assumed/expected scores (0-100) for every OTHER pending item. Any
        other pending item not given an assumed score falls back to the flat
        equal-effort average (i.e. behaves like required_avg_on_remaining if you
        don't override anything). Returns None if the item is already graded or
        doesn't exist.
        """
        comp, target_item = self.find_item(item_name)
        if target_item is None or target_item.is_completed:
            return None
        target_weight = self.item_weight(target_item)
        if target_weight <= 0:
            return None

        assumed_scores = {k.lower(): v for k, v in (assumed_scores or {}).items()}
        fallback = self.required_avg_on_remaining(target_percent) or 0.0

        assumed_contribution = 0.0
        for c in self.components:
            w = c.total_weight / len(c.items) if c.items else 0.0
            for it in c.items:
                if it is target_item or it.is_completed:
                    continue
                pct = assumed_scores.get(it.name.lower(), fallback)
                assumed_contribution += (pct / 100) * w

        needed_points = target_percent - self.achieved_contribution() - assumed_contribution
        return (needed_points / target_weight) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {"credit_hours": self.credit_hours, "components": [c.to_dict() for c in self.components]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Portion":
        return cls(credit_hours=d["credit_hours"], components=[Component.from_dict(c) for c in d.get("components", [])])


# --------------------------------------------------------------------------- #
# Course
# --------------------------------------------------------------------------- #
@dataclass
class Course:
    name: str
    credit_hours: float
    has_lab: bool
    theory: Portion
    lab: Optional[Portion] = None
    target_percent: Optional[float] = None  # course-level target, e.g. 85 for an A

    # ---- construction helpers ------------------------------------------------
    @classmethod
    def new(cls, name: str, credit_hours: float, has_lab: bool = False,
            theory_credit_hours: Optional[float] = None, lab_credit_hours: Optional[float] = None) -> "Course":
        if has_lab:
            th_cr = theory_credit_hours if theory_credit_hours is not None else round(credit_hours * 0.75, 2)
            lb_cr = lab_credit_hours if lab_credit_hours is not None else round(credit_hours - th_cr, 2)
        else:
            th_cr, lb_cr = credit_hours, None
        theory = Portion(credit_hours=th_cr, components=default_theory_components())
        lab = Portion(credit_hours=lb_cr, components=default_lab_components()) if has_lab else None
        return cls(name=name, credit_hours=credit_hours, has_lab=has_lab, theory=theory, lab=lab)

    # ---- status ---------------------------------------------------------------
    def is_complete(self) -> bool:
        if self.has_lab:
            return self.theory.is_complete() and self.lab.is_complete()
        return self.theory.is_complete()

    def overall_percent(self) -> Optional[float]:
        """Locked-in final percentage — only once every component in every portion is graded."""
        if not self.is_complete():
            return None
        if not self.has_lab:
            return self.theory.final_percent()
        t, l = self.theory.final_percent(), self.lab.final_percent()
        return (t * self.theory.credit_hours + l * self.lab.credit_hours) / self.credit_hours

    def projected_percent(self, assume_target_on_incomplete: bool = True) -> float:
        """
        Best current estimate of where this course stands: completed work counts
        at its real score, incomplete work is assumed to land exactly on target
        (or on current running average if no target set) — used for live SGPA projections.
        """
        def portion_projection(p: Portion, fallback_target: float) -> float:
            if p.is_complete():
                return p.final_percent()
            remaining = p.remaining_weight()
            if remaining <= 0:
                return p.achieved_contribution()
            assumed_avg = fallback_target if assume_target_on_incomplete else (p.current_percent() or fallback_target)
            return p.achieved_contribution() + (assumed_avg / 100) * remaining

        target = self.target_percent if self.target_percent is not None else 71  # default: aim for a B
        if not self.has_lab:
            return portion_projection(self.theory, target)
        t = portion_projection(self.theory, target)
        l = portion_projection(self.lab, target)
        return (t * self.theory.credit_hours + l * self.lab.credit_hours) / self.credit_hours

    def grade(self) -> Optional[tuple]:
        p = self.overall_percent()
        if p is None:
            return None
        return percentage_to_grade(p)

    def projected_grade(self) -> tuple:
        return percentage_to_grade(self.projected_percent())

    def best_case_percent(self) -> float:
        """Ceiling for the WHOLE course: ~100% on everything still ungraded, in every portion."""
        if not self.has_lab:
            return self.theory.best_case_percent()
        t = self.theory.best_case_percent()
        l = self.lab.best_case_percent()
        return (t * self.theory.credit_hours + l * self.lab.credit_hours) / self.credit_hours

    # ---- required-marks engine -------------------------------------------------
    def set_target_from_letter(self, letter: str):
        from grading import min_percentage_for_letter
        self.target_percent = float(min_percentage_for_letter(letter))

    def required_for_item(self, portion_name: str, item_name: str,
                           target_percent: Optional[float] = None,
                           assumed_scores: Optional[Dict[str, float]] = None) -> Optional[float]:
        """
        Course-level convenience wrapper: what do I need on ONE specific pending
        item (in theory or lab) to hit the course target — optionally assuming
        specific scores on other still-pending items instead of the flat average.
        """
        target = target_percent if target_percent is not None else self.target_percent
        if target is None:
            raise ValueError("No target set for this course.")
        portion = self.theory if portion_name.lower() == "theory" else self.lab
        if portion is None:
            return None

        if not self.has_lab:
            return portion.required_for_item(item_name, target, assumed_scores)

        # lab course: figure out the effective target FOR THIS PORTION, given the
        # other portion's status, then solve within that portion.
        other = self.lab if portion is self.theory else self.theory
        if other.is_complete():
            other_actual = other.final_percent()
            portion_target = (target * self.credit_hours - other_actual * other.credit_hours) / portion.credit_hours
        else:
            # both open: assume the other portion lands on the flat course-level target too
            portion_target = target
        return portion.required_for_item(item_name, portion_target, assumed_scores)

    def required_report(self, target_percent: Optional[float] = None, lab_split: Optional[float] = None) -> Dict[str, Any]:
        """
        Returns what you need to score, per portion, to hit target_percent overall.
        lab_split: optionally force the theory-portion target percent explicitly
                   (only used for lab courses where both portions are still open);
                   the lab target is then solved for automatically.
        """
        target = target_percent if target_percent is not None else self.target_percent
        if target is None:
            raise ValueError("No target set for this course. Provide target_percent or set course.target_percent first.")

        result: Dict[str, Any] = {"course": self.name, "target_percent": target}

        if not self.has_lab:
            req = self.theory.required_avg_on_remaining(target)
            result["theory"] = self._portion_report(self.theory, target, req)
            return result

        theory_done = self.theory.is_complete()
        lab_done = self.lab.is_complete()

        if theory_done and not lab_done:
            th_actual = self.theory.final_percent()
            lab_target = (target * self.credit_hours - th_actual * self.theory.credit_hours) / self.lab.credit_hours
            result["theory"] = {"status": "complete", "actual_percent": round(th_actual, 2)}
            result["lab"] = self._portion_report(self.lab, lab_target, self.lab.required_avg_on_remaining(lab_target))
        elif lab_done and not theory_done:
            lb_actual = self.lab.final_percent()
            theory_target = (target * self.credit_hours - lb_actual * self.lab.credit_hours) / self.theory.credit_hours
            result["lab"] = {"status": "complete", "actual_percent": round(lb_actual, 2)}
            result["theory"] = self._portion_report(self.theory, theory_target, self.theory.required_avg_on_remaining(theory_target))
        elif theory_done and lab_done:
            result["theory"] = {"status": "complete", "actual_percent": round(self.theory.final_percent(), 2)}
            result["lab"] = {"status": "complete", "actual_percent": round(self.lab.final_percent(), 2)}
        else:
            # both open: default to equal target on both portions unless caller overrides theory target
            th_target = lab_split if lab_split is not None else target
            lb_target = (target * self.credit_hours - th_target * self.theory.credit_hours) / self.lab.credit_hours
            result["theory"] = self._portion_report(self.theory, th_target, self.theory.required_avg_on_remaining(th_target))
            result["lab"] = self._portion_report(self.lab, lb_target, self.lab.required_avg_on_remaining(lb_target))

        return result

    @staticmethod
    def _portion_report(portion: Portion, target_percent: float, required_avg: Optional[float]) -> Dict[str, Any]:
        rep = {
            "status": "complete" if portion.is_complete() else "in_progress",
            "target_percent": round(target_percent, 2),
            "achieved_so_far": round(portion.achieved_contribution(), 2),
            "remaining_weight": round(portion.remaining_weight(), 2),
        }
        if required_avg is None:
            rep["required_avg_on_remaining"] = None
        else:
            rep["required_avg_on_remaining"] = round(required_avg, 2)
            rep["achievable"] = required_avg <= 100.0001
        # per-component breakdown of what's left, with the exact score needed on EACH item
        rep["components"] = []
        for c in portion.components:
            comp_entry = {"name": c.name, "weight": c.total_weight, "items": []}
            for it in c.items:
                item_entry = {
                    "name": it.name,
                    "max_marks": it.max_marks,
                    "obtained_marks": it.obtained_marks,
                    "completed": it.is_completed,
                }
                if not it.is_completed and required_avg is not None:
                    needed = portion.required_for_item(it.name, target_percent)
                    if needed is not None:
                        item_entry["required_percent"] = round(needed, 2)
                        item_entry["required_marks"] = round((needed / 100) * it.max_marks, 2)
                comp_entry["items"].append(item_entry)
            rep["components"].append(comp_entry)
        return rep

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "credit_hours": self.credit_hours, "has_lab": self.has_lab,
            "theory": self.theory.to_dict(),
            "lab": self.lab.to_dict() if self.lab else None,
            "target_percent": self.target_percent,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Course":
        return cls(
            name=d["name"], credit_hours=d["credit_hours"], has_lab=d["has_lab"],
            theory=Portion.from_dict(d["theory"]),
            lab=Portion.from_dict(d["lab"]) if d.get("lab") else None,
            target_percent=d.get("target_percent"),
        )


# --------------------------------------------------------------------------- #
# Semester
# --------------------------------------------------------------------------- #
@dataclass
class Semester:
    name: str
    target_sgpa: float
    courses: List[Course] = field(default_factory=list)
    finalized: bool = False
    actual_sgpa: Optional[float] = None  # locked in once finalized

    def add_course(self, course: Course):
        self.courses.append(course)

    def total_credit_hours(self) -> float:
        return sum(c.credit_hours for c in self.courses)

    def apply_uniform_target(self):
        """Give every course the same target percent, derived from the semester's target SGPA."""
        pct = min_percentage_for_grade_point(self.target_sgpa)
        for c in self.courses:
            c.target_percent = float(pct)

    def sgpa_from_targets(self) -> Optional[float]:
        tch = self.total_credit_hours()
        if tch == 0:
            return None
        total = 0.0
        for c in self.courses:
            if c.target_percent is None:
                return None
            _, gp = percentage_to_grade(c.target_percent)
            total += gp * c.credit_hours
        return total / tch

    def sgpa_projected(self) -> Optional[float]:
        """Live projection using actual marks where entered, target assumption elsewhere."""
        tch = self.total_credit_hours()
        if tch == 0:
            return None
        total = sum(percentage_to_grade(c.projected_percent())[1] * c.credit_hours for c in self.courses)
        return total / tch

    def sgpa_actual(self) -> Optional[float]:
        """Only counts courses that are fully complete; returns None if none are complete yet."""
        complete = [c for c in self.courses if c.is_complete()]
        if not complete:
            return None
        tch = sum(c.credit_hours for c in complete)
        total = sum(c.grade()[1] * c.credit_hours for c in complete)
        return total / tch

    def sgpa_trajectory(self) -> Optional[float]:
        """
        Honest read on where you're actually headed: for incomplete work, this
        assumes you keep performing like you HAVE been (real running average),
        not like you hit your target — unlike sgpa_projected(), which always
        looks close to on-target by assumption.
        """
        tch = self.total_credit_hours()
        if tch == 0:
            return None
        total = sum(
            percentage_to_grade(c.projected_percent(assume_target_on_incomplete=False))[1] * c.credit_hours
            for c in self.courses
        )
        return total / tch

    def sgpa_ceiling(self) -> Optional[float]:
        """The absolute best SGPA still reachable if every remaining assessment, in every course, is aced."""
        tch = self.total_credit_hours()
        if tch == 0:
            return None
        total = sum(percentage_to_grade(c.best_case_percent())[1] * c.credit_hours for c in self.courses)
        return total / tch

    def pace_status(self) -> Dict[str, Any]:
        """Single bundle for an honest on-track / behind / no-longer-possible read on the semester goal."""
        trajectory = self.sgpa_trajectory()
        ceiling = self.sgpa_ceiling()
        return {
            "target_sgpa": self.target_sgpa,
            "trajectory_sgpa": round(trajectory, 3) if trajectory is not None else None,
            "ceiling_sgpa": round(ceiling, 3) if ceiling is not None else None,
            "actual_sgpa": round(self.sgpa_actual(), 3) if self.sgpa_actual() is not None else None,
            "target_still_possible": (ceiling is None) or (ceiling >= self.target_sgpa - 1e-9),
        }

    def sensitivity_ranking(self) -> List[Dict[str, Any]]:
        """
        Ranks courses by how much a ONE-BAND grade change moves the overall SGPA —
        i.e. which courses to prioritise. Bigger credit hours = bigger leverage.
        """
        tch = self.total_credit_hours()
        rows = []
        for c in self.courses:
            impact_per_band = (c.credit_hours / tch) if tch else 0
            rows.append({
                "course": c.name,
                "credit_hours": c.credit_hours,
                "sgpa_impact_per_grade_band": round(impact_per_band, 4),
            })
        rows.sort(key=lambda r: -r["credit_hours"])
        return rows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "target_sgpa": self.target_sgpa,
            "courses": [c.to_dict() for c in self.courses],
            "finalized": self.finalized, "actual_sgpa": self.actual_sgpa,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Semester":
        return cls(
            name=d["name"], target_sgpa=d["target_sgpa"],
            courses=[Course.from_dict(c) for c in d.get("courses", [])],
            finalized=d.get("finalized", False), actual_sgpa=d.get("actual_sgpa"),
        )
