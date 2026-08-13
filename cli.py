"""
cli.py
------
Interactive terminal front-end for the GPA engine. This is a stand-in for
the eventual Flask/FastAPI web UI — every action here just calls the same
models.py / cgpa.py functions a web route would call, so porting later is
mostly "replace input()/print() with request/response JSON".
"""
import sys
from grading import percentage_to_grade, min_percentage_for_grade_point, GRADE_SCALE
from models import Semester, Course
from storage import AppData

DATA_PATH_HINT = "data/app_data.json"


def pace_message(status: dict, label: str) -> str:
    """
    Turns a Portion.pace_status()-style dict into an honest, non-sugarcoated,
    non-discouraging status line. Same tiers used for the semester-level SGPA
    check by callers that pass in the equivalent fields.
    """
    if status.get("is_complete"):
        fp = status["final_percent"]
        letter, gp = percentage_to_grade(fp)
        return f"  [{label}] Locked in at {fp}% ({letter}, {gp:.2f}). Done."

    if not status["target_still_possible"]:
        return (f"  [{label}] Honest heads-up: even a perfect score on everything left caps you at "
                f"{status['best_case_percent']}% ({status['best_case_grade']}). Your current target is no "
                f"longer reachable here — worth revising it, or making up the difference in a higher-credit course.")

    req = status["required_avg_on_remaining"]
    cur = status["current_avg"]
    if req is None:
        return f"  [{label}] Nothing left to grade."
    if req <= 0:
        return f"  [{label}] Target already secured regardless of what's left — you're safely ahead here."
    if cur is None:
        return f"  [{label}] Nothing graded yet — you're aiming to average {req:.2f}% from here on."
    if req <= cur + 1e-9:
        return (f"  [{label}] On track. You're averaging {cur:.2f}% so far and only need {req:.2f}% "
                f"on what's left — keep doing what you're doing.")
    gap = req - cur
    if gap <= 5:
        return (f"  [{label}] Slightly behind pace: averaging {cur:.2f}% so far, need {req:.2f}% going "
                f"forward. A small step up closes it.")
    if gap <= 15:
        return (f"  [{label}] Behind pace: averaging {cur:.2f}% so far, but now need {req:.2f}% on what's "
                f"left. Still realistic — treat it as a signal to put in more focused work here.")
    return (f"  [{label}] Well behind pace: averaging {cur:.2f}% so far against a required {req:.2f}% "
            f"going forward. Mathematically possible, but it needs a real, sustained push — not a one-off good day.")


def semester_pace_message(sem) -> str:
    status = sem.pace_status()
    target = status["target_sgpa"]
    if not status["target_still_possible"]:
        return (f"Honest heads-up: even acing everything left this semester caps your SGPA at "
                f"{status['ceiling_sgpa']:.3f} — your {target:.2f} target is no longer reachable as scoped. "
                f"Worth revising the target, or accepting it and refocusing on CGPA for next semester.")
    traj = status["trajectory_sgpa"]
    if traj is None:
        return f"No marks entered yet this semester — target SGPA is {target:.2f}."
    if traj >= target - 1e-9:
        return f"On pace. At your current real performance, you're trending toward {traj:.3f} against a {target:.2f} target."
    gap = target - traj
    if gap <= 0.15:
        return (f"Slightly behind: trending toward {traj:.3f} against a {target:.2f} target. "
                f"A modest push closes this — check the prioritisation list below for where it counts most.")
    if gap <= 0.4:
        return (f"Behind pace: trending toward {traj:.3f} against a {target:.2f} target. Recoverable, "
                f"but it'll take a real, sustained effort — start with your highest-credit courses.")
    return (f"Well behind pace: trending toward {traj:.3f} against a {target:.2f} target. Still "
            f"mathematically possible per the ceiling above, but this needs an honest reset in how "
            f"you're approaching the remaining work.")


def prompt_float(msg, default=None):
    while True:
        raw = input(f"{msg}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if raw == "" and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number.")


def prompt_int(msg, default=None):
    return int(prompt_float(msg, default))


def prompt_yn(msg, default="n"):
    raw = input(f"{msg} (y/n) [{default}]: ").strip().lower()
    if raw == "":
        raw = default
    return raw.startswith("y")


def prompt_str(msg, default=None):
    raw = input(f"{msg}" + (f" [{default}]" if default else "") + ": ").strip()
    return raw if raw else default


def show_grade_scale():
    print("\nGrading scale:")
    for lo, hi, letter, gp in GRADE_SCALE:
        rng = f"{lo}-{hi}" if hi < 100 else f"{lo} and above"
        print(f"  {rng:>10}  {letter:>3}  {gp:.2f}")
    print()


def setup_semester(app: AppData) -> Semester:
    print("\n--- New Semester ---")
    name = prompt_str("Semester name", "This Semester")
    show_grade_scale()
    target_sgpa = prompt_float("Target SGPA for this semester (out of 4.00)")
    sem = Semester(name=name, target_sgpa=target_sgpa)
    app.semesters.append(sem)
    app.active_semester_index = len(app.semesters) - 1
    print(f"\nSemester '{name}' created with target SGPA {target_sgpa}.")
    return sem


def register_course(sem: Semester):
    print("\n--- Register a Course ---")
    name = prompt_str("Course name")
    credit_hours = prompt_float("Credit hours")
    has_lab = prompt_yn("Does this course have a lab component?", "n")
    if has_lab:
        th_cr = prompt_float("  Theory credit hours", round(credit_hours * 0.75, 2))
        lb_cr = prompt_float("  Lab credit hours", round(credit_hours - th_cr, 2))
        course = Course.new(name, credit_hours, has_lab=True, theory_credit_hours=th_cr, lab_credit_hours=lb_cr)
    else:
        course = Course.new(name, credit_hours, has_lab=False)

    set_target_now = prompt_yn("Set a target grade for this course now? (else it inherits the semester's uniform target)", "n")
    if set_target_now:
        letter = prompt_str("Target letter grade (e.g. A, A-, B+, B ...)")
        try:
            course.set_target_from_letter(letter.upper())
            print(f"  Target set: {letter.upper()} -> aiming for >= {course.target_percent:.0f}%")
        except ValueError:
            print("  Unrecognised letter, skipping — you can set it later.")

    # configure assessment counts up front (defaults match the standard policy, but are adjustable)
    n_assign = prompt_int("  Number of theory assignments", 2)
    n_quiz = prompt_int("  Number of theory quizzes", 2)
    th_assign = course.theory.find_component("Assignments")
    th_quiz = course.theory.find_component("Quizzes")
    th_assign.items = []
    th_quiz.items = []
    for i in range(n_assign):
        max_m = prompt_float(f"    Assignment {i+1} total marks", 10)
        th_assign.add_item(f"Assignment {i+1}", max_m)
    for i in range(n_quiz):
        max_m = prompt_float(f"    Quiz {i+1} total marks", 10)
        th_quiz.add_item(f"Quiz {i+1}", max_m)
    mid_max = prompt_float("  Midterm total marks", 25)
    course.theory.find_component("Midterm").add_item("Midterm", mid_max)
    final_max = prompt_float("  Final exam total marks", 100)
    course.theory.find_component("Final").add_item("Final Exam", final_max)

    if has_lab:
        la_max = prompt_float("  Lab assignments total marks (combined)", 25)
        course.lab.find_component("Lab Assignments").add_item("Lab Assignments", la_max)
        lm_max = prompt_float("  Lab midterm total marks", 25)
        course.lab.find_component("Lab Midterm").add_item("Lab Midterm", lm_max)
        lf_max = prompt_float("  Lab final total marks", 50)
        course.lab.find_component("Lab Final").add_item("Lab Final", lf_max)

    sem.add_course(course)
    print(f"\nCourse '{name}' registered ({credit_hours} credit hours).")
    return course


def find_course(sem: Semester) -> Course:
    if not sem.courses:
        print("No courses registered yet.")
        return None
    for i, c in enumerate(sem.courses):
        tgt = f"target {c.target_percent:.0f}%" if c.target_percent else "no target set"
        print(f"  [{i}] {c.name}  ({c.credit_hours} cr, {tgt})")
    idx = prompt_int("Pick a course number")
    if 0 <= idx < len(sem.courses):
        return sem.courses[idx]
    print("Invalid choice.")
    return None


def enter_marks(course: Course, sem: Semester):
    portions = [("theory", course.theory)]
    if course.has_lab:
        portions.append(("lab", course.lab))
    if len(portions) > 1:
        which = prompt_str("Theory or Lab component?", "theory").lower()
        portions = [p for p in portions if p[0] == which] or portions[:1]
    _, portion = portions[0]

    for comp in portion.components:
        for item in comp.items:
            status = f"(already {item.obtained_marks}/{item.max_marks})" if item.is_completed else "(not entered)"
            print(f"  {comp.name} > {item.name} — out of {item.max_marks} {status}")
    item_name = prompt_str("Which item are you entering marks for? (type exact name)")
    target = course.target_percent if course.target_percent is not None else min_percentage_for_grade_point(sem.target_sgpa)
    for comp in portion.components:
        for item in comp.items:
            if item.name.lower() == item_name.lower():
                marks = prompt_float(f"  Marks obtained (out of {item.max_marks})")
                if marks > item.max_marks:
                    print(f"  Note: {marks} is above the max of {item.max_marks} — saving anyway in case of bonus marks.")
                if marks < 0:
                    print("  Marks can't be negative — not saved.")
                    return

                before = portion.pace_status(target)
                needed_before = portion.required_for_item(item.name, target)
                item.obtained_marks = marks
                after = portion.pace_status(target)

                print(f"  Saved: {item.name} = {marks}/{item.max_marks} ({item.percent_score:.1f}%)")

                # --- immediate honest feedback on THIS entry specifically ---
                if needed_before is not None:
                    if item.percent_score >= needed_before - 1e-9:
                        print(f"  That's at or above the ~{needed_before:.2f}% this item needed — nice, it eases up what's left.")
                    else:
                        print(f"  That's below the ~{needed_before:.2f}% this item needed.")
                if before["target_still_possible"] and not after["target_still_possible"]:
                    print(f"  WARNING: this drops your ceiling below target. Even 100% on everything else now caps you "
                          f"at {after['best_case_percent']}% ({after['best_case_grade']}) — your target grade here is "
                          f"no longer reachable.")
                elif (before.get("required_avg_on_remaining") is not None and after.get("required_avg_on_remaining") is not None
                      and after["required_avg_on_remaining"] > before["required_avg_on_remaining"] + 1e-9):
                    print(f"  Heads-up: this raises what you need on the rest, from {before['required_avg_on_remaining']:.2f}% "
                          f"to {after['required_avg_on_remaining']:.2f}%.")

                # immediately show what this changes for what's still ahead
                show_required_report(course, sem)
                return
    print("  Item not found — check the exact name.")


def set_course_target(course: Course):
    print(f"\n--- Set Target: {course.name} ---")
    current = f"{course.target_percent:.0f}%" if course.target_percent is not None else "none (inherits semester uniform target)"
    print(f"  Current target: {current}")
    mode = prompt_str("Set by (l)etter grade or (p)ercent?", "l").lower()
    if mode.startswith("p"):
        pct = prompt_float("  Target percent (e.g. 85)")
        course.target_percent = pct
        letter, gp = percentage_to_grade(pct)
        print(f"  Target set: {pct:.0f}% (currently maps to {letter}, {gp:.2f})")
    else:
        letter = prompt_str("  Target letter grade (e.g. A, A-, B+, B, B-, C+, C, C-, D+, D)")
        try:
            course.set_target_from_letter(letter.upper())
            print(f"  Target set: {letter.upper()} -> aiming for >= {course.target_percent:.0f}%")
        except ValueError:
            print("  Unrecognised letter grade — nothing changed.")


def show_required_report(course: Course, sem: Semester):
    target = course.target_percent if course.target_percent is not None else None
    if target is None:
        pct = min_percentage_for_grade_point(sem.target_sgpa)
        print(f"  (No course-specific target — using semester's uniform target: {pct}%)")
        target = pct
    try:
        report = course.required_report(target_percent=target)
    except ValueError as e:
        print(f"  {e}")
        return

    print(f"\n=== Required Marks Report: {course.name} (target {target:.0f}%) ===")
    for portion_key, portion_obj in (("theory", course.theory), ("lab", course.lab)):
        if portion_key not in report:
            continue
        p = report[portion_key]
        print(f"\n  -- {portion_key.upper()} --")
        if p.get("status") == "complete":
            print(f"    Complete. Locked-in percentage: {p['actual_percent']}%")
            continue
        status = portion_obj.pace_status(p["target_percent"])
        print(pace_message(status, portion_key.upper()))
        print(f"    Achieved so far: {p['achieved_so_far']} percentage points | Remaining weight: {p['remaining_weight']}%")
        for comp in p["components"]:
            for it in comp["items"]:
                if it["completed"]:
                    continue
                if "required_marks" in it:
                    print(f"      {comp['name']} > {it['name']}: need {it['required_marks']} / {it['max_marks']}  ({it['required_percent']}%)")
                else:
                    print(f"      {comp['name']} > {it['name']}: out of {it['max_marks']} (not entered)")


def what_if_one_item(course: Course, sem: Semester):
    """Solve for the exact score needed on ONE specific upcoming item,
    letting the user optionally assume different scores on other pending items."""
    portions = [("theory", course.theory)]
    if course.has_lab:
        portions.append(("lab", course.lab))
    if len(portions) > 1:
        which = prompt_str("Theory or Lab component?", "theory").lower()
        portions = [p for p in portions if p[0] == which] or portions[:1]
    portion_name, portion = portions[0]

    pending = [(c.name, it) for c in portion.components for it in c.items if not it.is_completed]
    if not pending:
        print("  Nothing pending in this portion — it's fully graded.")
        return
    print("  Pending items:")
    for i, (comp_name, it) in enumerate(pending):
        print(f"    [{i}] {comp_name} > {it.name}  (out of {it.max_marks})")
    idx = prompt_int("  Which one are you about to take?")
    if not (0 <= idx < len(pending)):
        print("  Invalid choice.")
        return
    _, target_item = pending[idx]

    assumed = {}
    others = [it for _, it in pending if it is not target_item]
    if others and prompt_yn("  Assume specific scores on the OTHER pending items instead of the flat average?", "n"):
        for it in others:
            val = prompt_str(f"    Expected % on '{it.name}' (blank = use flat average)")
            if val:
                try:
                    assumed[it.name.lower()] = float(val)
                except ValueError:
                    print("    Not a number, skipping.")

    target = course.target_percent if course.target_percent is not None else min_percentage_for_grade_point(sem.target_sgpa)
    needed_pct = course.required_for_item(portion_name, target_item.name, target_percent=target, assumed_scores=assumed)
    if needed_pct is None:
        print("  Could not compute — check the item and try again.")
        return
    needed_marks = (needed_pct / 100) * target_item.max_marks
    print(f"\n  To hit {target:.0f}% overall (with your assumptions on the rest),")
    if needed_pct > 100:
        print(f"  you'd need {needed_pct:.2f}% on '{target_item.name}' — that's above 100%, not achievable here.")
        print("  You'll need a higher score elsewhere, or accept a lower grade in this course.")
    elif needed_pct < 0:
        print(f"  '{target_item.name}' is already covered — you could score 0 here and still be on track.")
    else:
        print(f"  you need {needed_marks:.2f} / {target_item.max_marks} ({needed_pct:.2f}%) on '{target_item.name}'.")


def show_semester_dashboard(sem: Semester):
    print(f"\n=== Semester Dashboard: {sem.name} ===")
    print(f"Target SGPA: {sem.target_sgpa:.2f}  |  Total credit hours: {sem.total_credit_hours()}")
    print(f"\n{semester_pace_message(sem)}")
    proj = sem.sgpa_projected()
    actual = sem.sgpa_actual()
    print(f"\n(If everything remaining lands exactly on target: {proj:.3f})" if proj is not None else "")
    print(f"(Actual SGPA, completed courses only: {actual:.3f})" if actual is not None else "")
    print("\nCourses:")
    for c in sem.courses:
        tgt = f"{c.target_percent:.0f}%" if c.target_percent is not None else "unset"
        pg = percentage_to_grade(c.projected_percent())
        print(f"  {c.name} ({c.credit_hours} cr) — target {tgt} | projected: {pg[0]} ({pg[1]:.2f})")
    print("\nPrioritisation (highest-leverage courses first):")
    for row in sem.sensitivity_ranking():
        print(f"  {row['course']:<25} {row['credit_hours']:>4} cr  ->  SGPA moves ~{row['sgpa_impact_per_grade_band']:.3f} per grade-band change here")


def cgpa_menu(app: AppData):
    while True:
        print("\n--- CGPA Module ---")
        print("  1) Add a past semester result manually")
        print("  2) Pull in a tracked semester's SGPA automatically")
        print("  3) View all semesters + CGPA")
        print("  4) Remove a semester entry")
        print("  0) Back")
        choice = prompt_str("Choose", "0")
        if choice == "1":
            name = prompt_str("Semester name")
            sgpa = prompt_float("SGPA (out of 4.00)")
            ch = prompt_float("Total credit hours that semester")
            app.cgpa.add(name, sgpa, ch)
        elif choice == "2":
            if not app.semesters:
                print("  No tracked semesters yet.")
                continue
            for i, s in enumerate(app.semesters):
                val = s.actual_sgpa if s.finalized else s.sgpa_projected()
                print(f"  [{i}] {s.name} — {'final' if s.finalized else 'projected'} SGPA: {val}")
            idx = prompt_int("Pick one")
            if 0 <= idx < len(app.semesters):
                s = app.semesters[idx]
                val = s.actual_sgpa if s.finalized else s.sgpa_projected()
                if val is None:
                    print("  No SGPA available yet for that semester.")
                else:
                    app.cgpa.add(s.name, val, s.total_credit_hours())
                    print(f"  Added {s.name} ({val:.3f}) to CGPA history.")
        elif choice == "3":
            if not app.cgpa.semesters:
                print("  No semester history yet.")
            for s in app.cgpa.semesters:
                print(f"  {s.name}: SGPA {s.sgpa:.3f}, {s.credit_hours} credit hours")
            c = app.cgpa.cgpa()
            if c is not None:
                print(f"\n  CGPA: {c:.3f}")
                print(f"  Equivalent percentage: {app.cgpa.percentage_equivalent():.2f}%")
        elif choice == "4":
            name = prompt_str("Semester name to remove")
            app.cgpa.remove(name)
        elif choice == "0":
            return


def main():
    app = AppData.load()
    print("=" * 60)
    print(" GPA Planner — reach your target SGPA/CGPA with confidence")
    print("=" * 60)

    try:
        _run_menu_loop(app)
    except (EOFError, KeyboardInterrupt):
        print("\n\nInput closed — saving before exit...")
        app.save()
        print(f"Saved to {DATA_PATH_HINT}. Goodbye!")
        sys.exit(0)


def _run_menu_loop(app: AppData):
    while True:
        sem = app.active_semester()
        print("\n--- Main Menu ---" + (f"  (active: {sem.name})" if sem else ""))
        print("  1) Start / switch active semester")
        print("  2) Register a course")
        print("  3) Enter marks for a course")
        print("  4) View required-marks report for a course")
        print("  5) Semester dashboard (SGPA + prioritisation)")
        print("  6) CGPA module")
        print("  7) Apply uniform target to all courses in active semester")
        print("  8) Set/change target grade for one course")
        print("  9) What do I need on ONE specific upcoming item?")
        print("  10) Save")
        print("  0) Save & exit")
        choice = prompt_str("Choose", "0")

        if choice == "1":
            if app.semesters:
                for i, s in enumerate(app.semesters):
                    print(f"  [{i}] {s.name} (target SGPA {s.target_sgpa})")
                pick = prompt_str("Enter number to switch, or 'new' to create one", "new")
                if pick == "new":
                    setup_semester(app)
                else:
                    try:
                        app.active_semester_index = int(pick)
                    except ValueError:
                        print("  Invalid.")
            else:
                setup_semester(app)
        elif choice == "2":
            if not sem:
                print("  Start a semester first.")
                continue
            register_course(sem)
        elif choice == "3":
            if not sem:
                print("  Start a semester first.")
                continue
            c = find_course(sem)
            if c:
                enter_marks(c, sem)
        elif choice == "4":
            if not sem:
                print("  Start a semester first.")
                continue
            c = find_course(sem)
            if c:
                show_required_report(c, sem)
        elif choice == "5":
            if not sem:
                print("  Start a semester first.")
                continue
            show_semester_dashboard(sem)
        elif choice == "6":
            cgpa_menu(app)
        elif choice == "7":
            if not sem:
                print("  Start a semester first.")
                continue
            sem.apply_uniform_target()
            print("  Uniform target applied to all courses.")
        elif choice == "8":
            if not sem:
                print("  Start a semester first.")
                continue
            c = find_course(sem)
            if c:
                set_course_target(c)
        elif choice == "9":
            if not sem:
                print("  Start a semester first.")
                continue
            c = find_course(sem)
            if c:
                what_if_one_item(c, sem)
        elif choice == "10":
            app.save()
            print(f"  Saved to {DATA_PATH_HINT}")
        elif choice == "0":
            app.save()
            print(f"  Saved to {DATA_PATH_HINT}. Goodbye!")
            sys.exit(0)
        else:
            print("  Unrecognised option.")


if __name__ == "__main__":
    main()
