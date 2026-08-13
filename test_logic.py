"""Quick sanity tests — run with: python3 test_logic.py"""
from grading import percentage_to_grade, round_percentage, min_percentage_for_grade_point
from models import Course, Semester
from cgpa import CGPACalculator


def check(label, cond):
    print(f"{'OK ' if cond else 'FAIL'} - {label}")
    assert cond, label


# ---- rounding rule from the notice ----
check("70.5 -> 71", round_percentage(70.5) == 71)
check("70.8 -> 71", round_percentage(70.8) == 71)
check("70.4 -> 70", round_percentage(70.4) == 70)
check("70.6% grade is B", percentage_to_grade(70.6)[0] == "B")
check("70.4% grade is B-", percentage_to_grade(70.4)[0] == "B-")
check("85% grade is A / 4.00", percentage_to_grade(85) == ("A", 4.00))
check("49% grade is F", percentage_to_grade(49)[0] == "F")

# ---- theory-only course required-marks ----
c = Course.new("Data Structures", credit_hours=3, has_lab=False)
c.theory.find_component("Assignments").add_item("Assignment 1", 10, 8)
c.theory.find_component("Assignments").add_item("Assignment 2", 10, 8)
c.theory.find_component("Midterm").add_item("Midterm", 25, 20)  # 80%
c.theory.find_component("Quizzes").add_item("Quiz 1", 10)   # not entered
c.theory.find_component("Quizzes").add_item("Quiz 2", 10)   # not entered
c.theory.find_component("Final").add_item("Final Exam", 100)  # not entered

report = c.required_report(target_percent=71)  # target: B
theory_rep = report["theory"]
# achieved so far = assignments 10%*0.8=8 + midterm 25%*0.8=20 = 28
check("achieved_so_far == 28", abs(theory_rep["achieved_so_far"] - 28) < 0.01)
# remaining weight = quizzes 15 + final 50 = 65
check("remaining_weight == 65", abs(theory_rep["remaining_weight"] - 65) < 0.01)
# needed = 71-28=43 ; required avg = 43/65*100 = 66.15
check("required_avg_on_remaining ~= 66.15", abs(theory_rep["required_avg_on_remaining"] - 66.15) < 0.05)
check("achievable == True", theory_rep["achievable"] is True)

# ---- lab course, theory already complete ----
lc = Course.new("Programming Fundamentals", credit_hours=4, has_lab=True,
                theory_credit_hours=3, lab_credit_hours=1)
lc.theory.find_component("Assignments").add_item("A1", 10, 9)
lc.theory.find_component("Assignments").add_item("A2", 10, 9)
lc.theory.find_component("Quizzes").add_item("Q1", 10, 9)
lc.theory.find_component("Quizzes").add_item("Q2", 10, 9)
lc.theory.find_component("Midterm").add_item("Mid", 25, 22)
lc.theory.find_component("Final").add_item("Final", 100, 88)
check("theory portion complete", lc.theory.is_complete())

lc.lab.find_component("Lab Assignments").add_item("LA1", 20)
lc.lab.find_component("Lab Midterm").add_item("LMid", 20)
lc.lab.find_component("Lab Final").add_item("LFinal", 40)

lc_report = lc.required_report(target_percent=85)  # aiming for an A overall
check("theory reported as complete", lc_report["theory"]["status"] == "complete")
print("Lab course report (theory complete, lab pending):")
import json
print(json.dumps(lc_report, indent=2))

# ---- semester / SGPA ----
sem = Semester(name="Fall 2026", target_sgpa=3.5)
sem.add_course(c)
sem.add_course(lc)
sem.apply_uniform_target()
print("\nUniform target percent assigned to each course:", [co.target_percent for co in sem.courses])
sgpa_t = sem.sgpa_from_targets()
print("SGPA from targets:", sgpa_t)
check("SGPA from uniform targets ~= target_sgpa band", abs(sgpa_t - percentage_to_grade(min_percentage_for_grade_point(3.5))[1]) < 0.01)

print("\nSensitivity ranking (prioritise high-credit courses):")
for row in sem.sensitivity_ranking():
    print(" ", row)

# ---- CGPA ----
cg = CGPACalculator()
cg.add("Fall 2025", 3.2, 15)
cg.add("Spring 2026", 3.6, 17)
print("\nCGPA:", cg.cgpa())
print("Equivalent percentage:", cg.percentage_equivalent())
check("CGPA computed", cg.cgpa() is not None)

print("\nALL TESTS PASSED")

# ---- pace/warning logic ----
print("\n--- Pace status tests ---")
pc = Course.new("Warning Test", credit_hours=3, has_lab=False)
pc.set_target_from_letter("B")  # target 71%
pc.theory.find_component("Quizzes").add_item("Q1", 10)
pc.theory.find_component("Quizzes").add_item("Q2", 10)
pc.theory.find_component("Assignments").add_item("A1", 10)
pc.theory.find_component("Assignments").add_item("A2", 10)
pc.theory.find_component("Midterm").add_item("Mid", 25)
pc.theory.find_component("Final").add_item("Final", 100)

before = pc.theory.pace_status(pc.target_percent)
check("fresh course still possible", before["target_still_possible"] is True)
check("fresh course current_avg is None", before["current_avg"] is None)

# score badly on a quiz -> should still likely be possible but behind pace
pc.theory.find_component("Quizzes").items[0].obtained_marks = 3  # 30% on a 7.5%-weight item
mid = pc.theory.pace_status(pc.target_percent)
check("after weak quiz, current_avg reflects it", abs(mid["current_avg"] - 30) < 0.01)
check("required_avg_on_remaining rose above target", mid["required_avg_on_remaining"] > pc.target_percent)

# now bomb the midterm too, hard enough to make the target mathematically impossible
pc.theory.find_component("Midterm").items[0].obtained_marks = 0  # 0% on a 25%-weight item
after = pc.theory.pace_status(pc.target_percent)
check("target now impossible after bombing midterm", after["target_still_possible"] is False)
check("best_case_percent computed", after["best_case_percent"] < pc.target_percent)
print("best_case:", after["best_case_percent"], after["best_case_grade"])

# semester-level pace
sem2 = Semester(name="Pace Test", target_sgpa=3.0)
sem2.add_course(pc)
sem2.apply_uniform_target()
pc.set_target_from_letter("B")  # re-apply after uniform overwrote it, for a clean check
pstat = sem2.pace_status()
print("Semester pace status:", pstat)

print("\nALL PACE TESTS PASSED")
