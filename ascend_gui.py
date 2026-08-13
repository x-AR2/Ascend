#!/usr/bin/env python3
"""NiceGUI frontend for Ascend GPA tracker — CLI feature parity."""

from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional, Tuple

from nicegui import app, ui

from cli import pace_message, semester_pace_message
from grading import GRADE_SCALE, min_percentage_for_grade_point, percentage_to_grade
from models import Course, Semester
from storage import AppData


DEFAULT_DATA_PATH = "data/app_data.json"
app_data = AppData.load(DEFAULT_DATA_PATH)

LETTER_OPTIONS = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D"]
FIELD = "outlined dark color=primary stack-label"


def user_data_path() -> str:
    email = app.storage.user.get("auth_email")
    if not email:
        return DEFAULT_DATA_PATH
    safe = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    return os.path.join("data", "users", f"{safe}.json")


def reload_app_data() -> None:
    global app_data
    path = user_data_path()
    app_data = AppData.load(path)


def ensure_user_data() -> None:
    """Load persisted data for the logged-in user (per-account storage)."""
    if app.storage.user.get("auth_email"):
        reload_app_data()


def save_data() -> None:
    path = user_data_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    app_data.save(path)


def bind_user(email: str, *, is_new: bool = False) -> None:
    global app_data
    app.storage.user["auth_email"] = email.strip().lower()
    path = user_data_path()
    if os.path.exists(path):
        app_data = AppData.load(path)
        return
    # First login/signup: keep whatever is already in memory (or the shared file)
    # so existing courses are not wiped, then persist under this account.
    if not app_data.semesters and os.path.exists(DEFAULT_DATA_PATH):
        app_data = AppData.load(DEFAULT_DATA_PATH)
    save_data()


def ensure_semester() -> Semester:
    sem = app_data.active_semester()
    if sem:
        return sem
    sem = Semester(name="This Semester", target_sgpa=3.2)
    app_data.semesters.append(sem)
    app_data.active_semester_index = len(app_data.semesters) - 1
    save_data()
    return sem


def ui_gpa_text(text: str) -> str:
    """Display GPA instead of SGPA everywhere except the landing page."""
    return text.replace("SGPA", "GPA").replace("sgpa", "gpa")


def course_target(course: Course, sem: Semester) -> float:
    if course.target_percent is not None:
        return float(course.target_percent)
    return float(min_percentage_for_grade_point(sem.target_sgpa))


def current_target_letter(course: Course, sem: Semester) -> str:
    letter, _ = percentage_to_grade(course_target(course, sem))
    return letter if letter in LETTER_OPTIONS else "A-"


def render_required_report(course: Course, sem: Semester) -> None:
    target = course_target(course, sem)
    if course.target_percent is None:
        ui.label(
            f"(No course-specific target — using semester's uniform target: {target:.0f}%)"
        ).classes("cli-hint mb-3")

    with ui.row().classes("w-full items-center justify-between flex-wrap gap-2 mb-4"):
        ui.label(f"Required Marks Report — {course.name}").classes("text-violet-300 font-semibold text-lg")
        ui.label(f"Target: {target:.0f}%").classes("grade-chip")

    try:
        report = course.required_report(target_percent=target)
    except ValueError as e:
        ui.label(str(e)).classes("text-rose-400")
        return

    for portion_key, portion_obj in (("theory", course.theory), ("lab", course.lab)):
        if portion_key not in report or portion_obj is None:
            continue
        p = report[portion_key]

        with ui.card().classes("glass-card w-full p-4 mt-3"):
            ui.label(portion_key.upper()).classes("text-sky-300 font-bold tracking-wider text-sm mb-2")

            if p.get("status") == "complete":
                locked = p.get("actual_percent")
                if locked is None:
                    locked = portion_obj.final_percent()
                letter, gp = percentage_to_grade(float(locked))
                with ui.row().classes("gap-3 flex-wrap items-center"):
                    ui.label(f"Locked in: {locked}%").classes("text-white font-semibold")
                    ui.label(f"{letter} ({gp:.2f})").classes("grade-chip")
                status = portion_obj.pace_status(float(p.get("target_percent", target)))
                with ui.element("div").classes("pace-box w-full"):
                    ui.label(pace_message(status, portion_key.upper())).classes("cli-text")
            else:
                status = portion_obj.pace_status(float(p.get("target_percent", target)))
                with ui.element("div").classes("pace-box w-full"):
                    ui.label(pace_message(status, portion_key.upper())).classes("cli-text")
                with ui.row().classes("w-full gap-4 mt-3 flex-wrap"):
                    with ui.column().classes("min-w-40"):
                        ui.label("Achieved so far").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{p.get('achieved_so_far', 0)} pts").classes("text-white font-semibold")
                    with ui.column().classes("min-w-40"):
                        ui.label("Remaining weight").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{p.get('remaining_weight', 0)}%").classes("text-white font-semibold")
                    req = p.get("required_avg_on_remaining")
                    if req is not None:
                        with ui.column().classes("min-w-40"):
                            ui.label("Need on remaining").classes("text-gray-400 text-xs uppercase")
                            ui.label(f"{req:.2f}% avg").classes(
                                "text-sky-300 font-semibold"
                                if p.get("achievable", True)
                                else "text-rose-400 font-semibold"
                            )

            rows = []
            for comp in p.get("components", []):
                for it in comp["items"]:
                    if it["completed"]:
                        rows.append(
                            {
                                "component": comp["name"],
                                "item": it["name"],
                                "status": "Entered",
                                "score": f"{it['obtained_marks']} / {it['max_marks']}",
                                "required": "—",
                            }
                        )
                    elif "required_marks" in it:
                        rows.append(
                            {
                                "component": comp["name"],
                                "item": it["name"],
                                "status": "Pending",
                                "score": "—",
                                "required": f"{it['required_marks']} / {it['max_marks']} ({it['required_percent']}%)",
                            }
                        )
                    else:
                        rows.append(
                            {
                                "component": comp["name"],
                                "item": it["name"],
                                "status": "Not entered",
                                "score": "—",
                                "required": f"out of {it['max_marks']}",
                            }
                        )
            if rows:
                ui.table(
                    columns=[
                        {"name": "component", "label": "Component", "field": "component", "align": "left"},
                        {"name": "item", "label": "Assessment", "field": "item", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "center"},
                        {"name": "score", "label": "Your Score", "field": "score", "align": "center"},
                        {"name": "required", "label": "Required", "field": "required", "align": "left"},
                    ],
                    rows=rows,
                    row_key="item",
                ).classes("w-full ascend-table mt-3").props("flat bordered dense separator=horizontal")

    with ui.card().classes("glass-card w-full p-4 mt-4"):
        ui.label("Course summary").classes("text-violet-300 font-semibold mb-2")
        if course.is_complete():
            overall = course.overall_percent()
            letter, gp = course.grade()
            ui.label(f"Locked-in: {overall:.2f}% → {letter} ({gp:.2f})").classes("text-sky-300")
            ui.label(
                "Target grade achieved." if overall >= target - 1e-9 else f"Below target of {target:.0f}%."
            ).classes("cli-text mt-1")
        else:
            proj = course.projected_percent()
            letter, gp = percentage_to_grade(proj)
            ui.label(f"Projected from saved marks: {proj:.1f}% → {letter} ({gp:.2f})").classes("text-sky-300")
            best = course.best_case_percent()
            bletter, bgp = percentage_to_grade(best)
            ui.label(f"Best case if you ace the rest: {best:.1f}% → {bletter} ({bgp:.2f})").classes("cli-hint mt-1")


def apply_page_theme() -> None:
    ui.colors(
        primary="#7c3aed",
        secondary="#2563eb",
        accent="#a78bfa",
        dark="#02040a",
        positive="#38bdf8",
        negative="#f43f5e",
        warning="#f59e0b",
        info="#60a5fa",
    )
    ui.add_head_html(
        """
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/vanta@latest/dist/vanta.net.min.js"></script>
<style>
    body {
        background: radial-gradient(circle at 25% 15%, #0a0f1f 0%, #02040a 42%, #000000 100%);
        color: #e5e7eb;
        font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
    }
    .ascend-title {
        background: linear-gradient(90deg, #60a5fa, #a78bfa, #c084fc, #38bdf8, #60a5fa);
        background-size: 220% auto;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        animation: ascendShimmer 4.5s linear infinite, ascendFloat 3.2s ease-in-out infinite;
        text-shadow: 0 0 22px rgba(96, 165, 250, 0.35), 0 0 42px rgba(167, 139, 250, 0.28);
        letter-spacing: 0.22em;
    }
    @keyframes ascendShimmer {
        0% { background-position: 0% center; }
        100% { background-position: 220% center; }
    }
    @keyframes ascendFloat {
        0%, 100% { transform: translateY(0); filter: drop-shadow(0 0 10px rgba(96,165,250,.35)); }
        50% { transform: translateY(-8px); filter: drop-shadow(0 0 22px rgba(168,85,247,.45)); }
    }
    .glass-card {
        backdrop-filter: blur(12px);
        background: rgba(8, 12, 24, 0.78);
        border: 1px solid rgba(139, 92, 246, 0.28);
        border-radius: 16px;
    }
    .hero-shell {
        min-height: 100vh;
        position: relative;
        overflow: hidden;
    }
    .hero-content { position: relative; z-index: 2; }
    #hero-bg { position: absolute; inset: 0; z-index: 1; }
    .feature-card, .course-card {
        transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
        cursor: pointer;
    }
    .feature-card:hover, .course-card:hover {
        transform: translateY(-4px);
        border-color: rgba(96, 165, 250, 0.55);
        box-shadow: 0 0 24px rgba(124, 58, 237, 0.22);
    }
    .cli-hint { color: #9ca3af; font-size: 0.9rem; line-height: 1.45; }
    .cli-text { color: #d1d5db; white-space: pre-wrap; line-height: 1.55; }
    .dashboard-title {
        background: linear-gradient(90deg, #93c5fd, #c4b5fd, #a5b4fc, #93c5fd);
        background-size: 200% auto;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        animation: ascendShimmer 5s linear infinite;
        letter-spacing: 0.12em;
    }
    .ascend-table .q-table__top,
    .ascend-table thead tr:first-child th {
        background: rgba(15, 23, 42, 0.95);
        color: #e5e7eb;
    }
    .ascend-table tbody tr:hover td {
        background: rgba(124, 58, 237, 0.12);
    }
    .pace-box {
        background: rgba(30, 41, 59, 0.65);
        border-left: 3px solid #7c3aed;
        padding: 12px 16px;
        border-radius: 8px;
        margin: 8px 0;
    }
    .grade-chip {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 999px;
        background: rgba(56, 189, 248, 0.15);
        border: 1px solid rgba(56, 189, 248, 0.35);
        color: #7dd3fc;
        font-weight: 600;
    }
</style>
"""
    )


def nav_bar() -> None:
    with ui.header().classes("bg-[#02040acc] backdrop-blur-md border-b border-violet-400/25"):
        with ui.row().classes("w-full items-center justify-between px-4 md:px-8 py-2"):
            ui.label("A S C E N D").classes("text-sky-300 font-bold tracking-[0.35em] text-sm")
            with ui.row().classes("items-center gap-2"):
                ui.button("Login", on_click=lambda: ui.navigate.to("/login")).props("flat color=white")
                ui.button("Sign Up", on_click=lambda: ui.navigate.to("/signup")).props("outline color=primary")
                ui.button("Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).props("color=primary unelevated")
                ui.button("CGPA", on_click=lambda: ui.navigate.to("/cgpa")).props("outline color=secondary")


def footer_note() -> None:
    ui.label("Ascend • Stay focused, stay consistent.").classes("text-xs text-gray-500 mt-8 mb-2")


# --------------------------------------------------------------------------- #
# Landing / Auth
# --------------------------------------------------------------------------- #
@ui.page("/")
def landing_page() -> None:
    apply_page_theme()
    nav_bar()

    with ui.element("div").classes("hero-shell w-full"):
        ui.html('<div id="hero-bg"></div>', sanitize=False)
        with ui.column().classes("hero-content w-full items-center justify-center pt-24 pb-16 px-6"):
            ui.label("ASCEND").classes("text-6xl md:text-8xl font-black ascend-title")
            ui.label("Plan smarter. Track deeper. Finish stronger.").classes(
                "mt-4 text-lg md:text-xl text-sky-300 font-medium"
            )
            ui.label(
                "A dark-mode GPA companion that helps you register courses, track marks, and stay on pace "
                "for your target SGPA throughout the semester."
            ).classes("max-w-3xl text-center text-gray-300 mt-4")
            with ui.row().classes("mt-8 gap-4"):
                ui.button("Enter Ascend", on_click=lambda: ui.navigate.to("/dashboard")).props(
                    "color=primary size=lg unelevated"
                )
                ui.button("Create Account", on_click=lambda: ui.navigate.to("/signup")).props(
                    "outline color=secondary size=lg"
                )

            ui.separator().classes("w-full max-w-5xl mt-14 mb-8 bg-violet-400/20")
            ui.label("WHAT ASCEND DOES").classes("text-xs tracking-[0.3em] text-gray-400")
            with ui.row().classes("w-full max-w-6xl mt-6 gap-4 justify-center"):
                with ui.card().classes("glass-card feature-card w-80 p-5"):
                    ui.icon("timeline").classes("text-sky-400 text-2xl")
                    ui.label("Live SGPA Trajectory").classes("font-semibold text-white mt-2")
                    ui.label("See if your current pace can still hit your target before exams arrive.").classes(
                        "text-sm text-gray-300"
                    )
                with ui.card().classes("glass-card feature-card w-80 p-5"):
                    ui.icon("auto_graph").classes("text-violet-300 text-2xl")
                    ui.label("Required Marks Clarity").classes("font-semibold text-white mt-2")
                    ui.label("Know exactly what you need on each remaining assessment item.").classes(
                        "text-sm text-gray-300"
                    )
                with ui.card().classes("glass-card feature-card w-80 p-5"):
                    ui.icon("folder_special").classes("text-sky-300 text-2xl")
                    ui.label("Minimal Course Workspace").classes("font-semibold text-white mt-2")
                    ui.label("Register courses cleanly, organize components, and stay consistent daily.").classes(
                        "text-sm text-gray-300"
                    )
            footer_note()

    ui.run_javascript(
        """
        if (window.__ascendVanta) { window.__ascendVanta.destroy(); }
        window.__ascendVanta = VANTA.NET({
            el: '#hero-bg',
            mouseControls: true,
            touchControls: true,
            gyroControls: false,
            minHeight: 200.0,
            minWidth: 200.0,
            scale: 1.0,
            scaleMobile: 1.0,
            color: 0x7c3aed,
            backgroundColor: 0x000000,
            points: 10.0,
            maxDistance: 18.0,
            spacing: 18.0,
        });
        """
    )


def auth_card(title: str, subtitle: str, primary_label: str, primary_action) -> None:
    nav_bar()
    with ui.column().classes("w-full items-center justify-center min-h-[88vh] px-4"):
        with ui.card().classes("glass-card w-full max-w-md p-7"):
            ui.label(title).classes("text-3xl font-bold text-white")
            ui.label(subtitle).classes("text-sm text-gray-300 mt-1")
            email = ui.input("Email").props(f"type=email {FIELD}").classes("w-full mt-6")
            password = ui.input("Password").props(f"type=password {FIELD}").classes("w-full mt-2")
            confirm: Optional[ui.input] = None
            if "Sign Up" in title:
                confirm = ui.input("Confirm Password").props(f"type=password {FIELD}").classes("w-full mt-2")

            with ui.row().classes("w-full mt-6 gap-2"):
                ui.button(
                    primary_label,
                    on_click=lambda: primary_action(
                        email.value, password.value, confirm.value if confirm else None
                    ),
                ).props("color=primary unelevated").classes("flex-1")
                ui.button("Back Home", on_click=lambda: ui.navigate.to("/")).props(
                    "outline color=secondary"
                ).classes("flex-1")


@ui.page("/login")
def login_page() -> None:
    apply_page_theme()

    def do_login(email: str, password: str, _unused: Optional[str]) -> None:
        if not email or not password:
            ui.notify("Please enter both email and password.", color="negative")
            return
        app.storage.user["auth_email"] = email
        bind_user(email, is_new=False)
        ui.notify("Login successful.", color="positive")
        ui.navigate.to("/dashboard")

    auth_card("Login to Ascend", "Continue your semester momentum.", "Login", do_login)


@ui.page("/signup")
def signup_page() -> None:
    apply_page_theme()

    def do_signup(email: str, password: str, confirm: Optional[str]) -> None:
        if not email or not password:
            ui.notify("Email and password are required.", color="negative")
            return
        if confirm != password:
            ui.notify("Passwords do not match.", color="negative")
            return
        app.storage.user["auth_email"] = email
        bind_user(email, is_new=True)
        ui.notify("Account created. Your data will be saved to your profile.", color="positive")
        ui.navigate.to("/dashboard")

    auth_card("Sign Up for Ascend", "Create your profile and start tracking.", "Create Account", do_signup)


# --------------------------------------------------------------------------- #
# Dashboard helpers
# --------------------------------------------------------------------------- #
@ui.refreshable
def semester_overview() -> None:
    sem = ensure_semester()
    projected = sem.sgpa_projected()
    actual = sem.sgpa_actual()

    with ui.row().classes("w-full gap-4 flex-wrap justify-center"):
        for title, value, tone in [
            ("Target GPA", f"{sem.target_sgpa:.2f}", "text-violet-300"),
            ("Projected GPA", f"{projected:.3f}" if projected is not None else "-", "text-sky-300"),
            ("Actual GPA", f"{actual:.3f}" if actual is not None else "-", "text-indigo-300"),
        ]:
            with ui.card().classes("glass-card p-5 min-w-52 text-center"):
                ui.label(title).classes("text-gray-400 text-xs uppercase tracking-wider")
                ui.label(value).classes(f"text-3xl font-bold {tone} mt-1")

    ui.label(ui_gpa_text(semester_pace_message(sem))).classes("cli-text mt-4 text-center w-full")

    ui.label("Prioritisation (highest-leverage courses first)").classes(
        "text-white font-semibold mt-6 mb-2"
    )
    ranking = sem.sensitivity_ranking()
    if ranking:
        ui.table(
            columns=[
                {"name": "course", "label": "Course", "field": "course", "align": "left"},
                {"name": "credit_hours", "label": "Credit Hours", "field": "credit_hours", "align": "center"},
                {"name": "impact", "label": "GPA Impact per Grade Band", "field": "impact", "align": "center"},
            ],
            rows=[
                {
                    "course": row["course"],
                    "credit_hours": row["credit_hours"],
                    "impact": f"~{row['sgpa_impact_per_grade_band']:.3f}",
                }
                for row in ranking
            ],
            row_key="course",
        ).classes("w-full ascend-table glass-card").props("flat bordered separator=horizontal")
    else:
        ui.label("No courses registered yet.").classes("cli-hint")


@ui.refreshable
def courses_grid() -> None:
    sem = ensure_semester()

    def remove_course(course_idx: int) -> None:
        if 0 <= course_idx < len(sem.courses):
            removed = sem.courses.pop(course_idx)
            save_data()
            ui.notify(f"Removed course '{removed.name}'.", color="info")
            courses_grid.refresh()
            semester_overview.refresh()

    if not sem.courses:
        ui.label("No courses registered yet.").classes("text-gray-400 mt-4")
        return
    with ui.row().classes("w-full gap-4 flex-wrap"):
        for idx, course in enumerate(sem.courses):
            projected_pct = course.projected_percent()
            letter, gp = percentage_to_grade(projected_pct)
            tgt = course.target_percent
            tgt_txt = f"target {tgt:.0f}%" if tgt is not None else "no target set"
            with ui.card().classes("glass-card course-card w-[340px] p-5 relative"):
                ui.button(icon="delete", on_click=lambda i=idx: remove_course(i)).props(
                    "flat round dense color=negative size=sm"
                ).classes("absolute top-2 right-2 z-10").tooltip("Remove course")

                with ui.column().classes("w-full cursor-pointer pr-6").on(
                    "click", lambda i=idx: ui.navigate.to(f"/course/{i}")
                ):
                    ui.label(f"[{idx}] {course.name}").classes("text-lg text-white font-semibold")
                    ui.label(f"{course.credit_hours} cr, {tgt_txt}").classes("text-sm text-gray-400")
                    ui.label(f"projected: {letter} ({gp:.2f})").classes("text-sm text-sky-300 mt-2")
                    ui.label("Click to enter marks / view required-marks report →").classes(
                        "text-xs text-violet-300 mt-3"
                    )


def show_grade_scale() -> None:
    ui.label("Grading scale").classes("text-white font-semibold mb-2")
    rows = []
    for lo, hi, letter, gp in GRADE_SCALE:
        rng = f"{lo}–{hi}%" if hi < 100 else f"{lo}% and above"
        rows.append({"range": rng, "letter": letter, "gp": f"{gp:.2f}"})
    ui.table(
        columns=[
            {"name": "range", "label": "Percentage Range", "field": "range", "align": "left"},
            {"name": "letter", "label": "Letter Grade", "field": "letter", "align": "center"},
            {"name": "gp", "label": "Grade Point", "field": "gp", "align": "center"},
        ],
        rows=rows,
        row_key="range",
    ).classes("w-full ascend-table").props("flat bordered separator=horizontal")


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@ui.page("/dashboard")
def dashboard_page() -> None:
    apply_page_theme()
    ensure_user_data()
    nav_bar()
    sem = ensure_semester()

    with ui.column().classes("w-full px-4 md:px-10 py-6"):
        with ui.column().classes("w-full items-center text-center mb-6"):
            ui.label("Semester Dashboard").classes("text-4xl md:text-5xl font-black dashboard-title")
            ui.label(sem.name).classes("text-sky-300 text-lg tracking-widest mt-2")
            ui.label(
                f"Target GPA: {sem.target_sgpa:.2f}  ·  {sem.total_credit_hours()} credit hours"
            ).classes("cli-hint mt-1")

        with ui.card().classes("glass-card w-full p-4 mt-2"):
            ui.label("Active Semester").classes("text-violet-300 font-semibold")
            ui.label(
                "One semester is active at a time. Update the details below or create your first semester."
            ).classes("cli-hint mb-3")
            with ui.column().classes("w-full gap-3"):
                sem_name = ui.input("Semester name", value=sem.name).props(FIELD).classes("w-full")
                sem_target = ui.number(
                    "Target GPA for this semester (out of 4.00)",
                    value=sem.target_sgpa,
                    min=0,
                    max=4,
                    step=0.01,
                ).props(FIELD).classes("w-full")

                def save_semester() -> None:
                    if not sem_name.value:
                        ui.notify("Semester name is required.", color="negative")
                        return
                    active = ensure_semester()
                    active.name = sem_name.value
                    active.target_sgpa = float(sem_target.value or 3.2)
                    app_data.semesters = [active]
                    app_data.active_semester_index = 0
                    save_data()
                    ui.notify(
                        f"Semester '{active.name}' saved with target GPA {active.target_sgpa:.2f}.",
                        color="positive",
                    )
                    ui.navigate.to("/dashboard")

                ui.button("Save Semester", on_click=save_semester).props("color=primary unelevated")

            with ui.expansion("Show grading scale", icon="menu_book").classes("w-full mt-4"):
                show_grade_scale()

        semester_overview()
        ui.separator().classes("bg-violet-400/20 my-6")

        with ui.row().classes("w-full gap-2 flex-wrap mb-4"):
            def apply_uniform() -> None:
                active = ensure_semester()
                active.apply_uniform_target()
                save_data()
                ui.notify("Uniform target applied to all courses.", color="positive")
                semester_overview.refresh()
                courses_grid.refresh()

            def save_now() -> None:
                save_data()
                ui.notify(f"Saved to {user_data_path()}", color="positive")

            ui.button(
                "Apply uniform target to all courses in active semester",
                on_click=apply_uniform,
            ).props("outline color=secondary")
            ui.button("Save", on_click=save_now).props("color=primary unelevated")
            ui.button("CGPA module", on_click=lambda: ui.navigate.to("/cgpa")).props(
                "outline color=primary"
            )

        # ---- Register a Course (CLI wording) ----
        with ui.expansion("Register a Course", icon="school", value=True).classes(
            "w-full glass-card"
        ):
            with ui.column().classes("w-full p-4 gap-3"):
                name = ui.input("Course name").props(FIELD).classes("w-full")
                credit_hours = ui.number("Credit hours", value=3.0, min=0.5, step=0.5).props(FIELD).classes("w-full")
                has_lab = ui.switch(
                    "Does this course have a lab component?", value=False
                ).props("color=primary")

                th_ch = ui.number("Theory credit hours", value=2.25, min=0, step=0.25).props(FIELD).classes("w-full")
                lb_ch = ui.number("Lab credit hours", value=0.75, min=0, step=0.25).props(FIELD).classes("w-full")

                set_target_now = ui.switch(
                    "Set a target grade for this course now? (else it inherits the semester's uniform target)",
                    value=False,
                ).props("color=primary")
                target_letter = ui.select(
                    LETTER_OPTIONS,
                    value="A-",
                    label="Target letter grade (e.g. A, A-, B+, B ...)",
                ).props(FIELD).classes("w-full")

                ui.label(
                    "Configure assessment counts up front (defaults match the standard policy, but are adjustable)"
                ).classes("cli-hint mt-1")

                n_assign = ui.number("Number of theory assignments", value=2, min=1, step=1).props(FIELD).classes("w-full")
                assign_max = ui.number(
                    "Assignment total marks (applied to each assignment)", value=10, min=1, step=1
                ).props(FIELD).classes("w-full")
                n_quiz = ui.number("Number of theory quizzes", value=2, min=1, step=1).props(FIELD).classes("w-full")
                quiz_max = ui.number(
                    "Quiz total marks (applied to each quiz)", value=10, min=1, step=1
                ).props(FIELD).classes("w-full")
                mid_max = ui.number("Midterm total marks", value=25, min=1, step=1).props(FIELD).classes("w-full")
                final_max = ui.number("Final exam total marks", value=100, min=1, step=1).props(FIELD).classes("w-full")

                la_max = ui.number("Lab assignments total marks (combined)", value=25, min=1, step=1).props(
                    FIELD
                ).classes("w-full")
                lm_max = ui.number("Lab midterm total marks", value=25, min=1, step=1).props(FIELD).classes("w-full")
                lf_max = ui.number("Lab final total marks", value=50, min=1, step=1).props(FIELD).classes("w-full")

                def toggle_lab_fields() -> None:
                    visible = bool(has_lab.value)
                    th_ch.set_visibility(visible)
                    lb_ch.set_visibility(visible)
                    la_max.set_visibility(visible)
                    lm_max.set_visibility(visible)
                    lf_max.set_visibility(visible)

                def toggle_target_fields() -> None:
                    target_letter.set_visibility(bool(set_target_now.value))

                has_lab.on_value_change(lambda _: toggle_lab_fields())
                set_target_now.on_value_change(lambda _: toggle_target_fields())
                toggle_lab_fields()
                toggle_target_fields()

                def register_course() -> None:
                    active = ensure_semester()
                    if not name.value:
                        ui.notify("Course name is required.", color="negative")
                        return
                    ch = float(credit_hours.value or 0)
                    if has_lab.value:
                        course = Course.new(
                            name=name.value,
                            credit_hours=ch,
                            has_lab=True,
                            theory_credit_hours=float(th_ch.value or round(ch * 0.75, 2)),
                            lab_credit_hours=float(lb_ch.value or round(ch * 0.25, 2)),
                        )
                    else:
                        course = Course.new(name=name.value, credit_hours=ch, has_lab=False)

                    if set_target_now.value:
                        try:
                            course.set_target_from_letter(str(target_letter.value).upper())
                            ui.notify(
                                f"Target set: {target_letter.value} -> aiming for >= {course.target_percent:.0f}%",
                                color="info",
                            )
                        except ValueError:
                            ui.notify(
                                "Unrecognised letter, skipping — you can set it later.",
                                color="warning",
                            )

                    th_assign = course.theory.find_component("Assignments")
                    th_quiz = course.theory.find_component("Quizzes")
                    th_assign.items = []
                    th_quiz.items = []
                    for i in range(int(n_assign.value or 2)):
                        th_assign.add_item(f"Assignment {i + 1}", float(assign_max.value or 10))
                    for i in range(int(n_quiz.value or 2)):
                        th_quiz.add_item(f"Quiz {i + 1}", float(quiz_max.value or 10))

                    course.theory.find_component("Midterm").items = []
                    course.theory.find_component("Final").items = []
                    course.theory.find_component("Midterm").add_item("Midterm", float(mid_max.value or 25))
                    course.theory.find_component("Final").add_item(
                        "Final Exam", float(final_max.value or 100)
                    )

                    if course.has_lab and course.lab:
                        course.lab.find_component("Lab Assignments").items = []
                        course.lab.find_component("Lab Midterm").items = []
                        course.lab.find_component("Lab Final").items = []
                        course.lab.find_component("Lab Assignments").add_item(
                            "Lab Assignments", float(la_max.value or 25)
                        )
                        course.lab.find_component("Lab Midterm").add_item(
                            "Lab Midterm", float(lm_max.value or 25)
                        )
                        course.lab.find_component("Lab Final").add_item(
                            "Lab Final", float(lf_max.value or 50)
                        )

                    active.add_course(course)
                    save_data()
                    ui.notify(
                        f"Course '{course.name}' registered ({course.credit_hours} credit hours).",
                        color="positive",
                    )
                    courses_grid.refresh()
                    semester_overview.refresh()

                ui.button("Register Course", on_click=register_course).props(
                    "color=primary unelevated size=lg"
                ).classes("mt-3")

        ui.label("Your Courses").classes("text-xl font-semibold mt-6 text-white")
        ui.label("Pick a course number / click a card to open marks + required report.").classes(
            "cli-hint"
        )
        courses_grid()


# --------------------------------------------------------------------------- #
# Course detail — marks, required report, target, what-if
# --------------------------------------------------------------------------- #
@ui.page("/course/{course_idx}")
def course_page(course_idx: int) -> None:
    apply_page_theme()
    ensure_user_data()
    nav_bar()
    sem = ensure_semester()

    if course_idx < 0 or course_idx >= len(sem.courses):
        with ui.column().classes("w-full items-center pt-20"):
            ui.label("Course not found.").classes("text-rose-400 text-xl")
            ui.button("Back to Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).props(
                "color=primary"
            )
        return

    course = sem.courses[course_idx]

    with ui.column().classes("w-full px-4 md:px-10 py-6 gap-4"):
        ui.button("← Back to Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).props(
            "flat color=primary"
        )
        ui.label(f"Course: {course.name}").classes("text-3xl font-bold text-white")
        ui.label(
            f"{course.credit_hours} credit hours"
            + (" • has lab" if course.has_lab else " • theory only")
        ).classes("cli-hint")

        @ui.refreshable
        def required_report_panel() -> None:
            render_required_report(sem.courses[course_idx], sem)

        @ui.refreshable
        def course_panels() -> None:
            c = sem.courses[course_idx]
            target = course_target(c, sem)
            inherit_note = (
                f"(No course-specific target — using semester's uniform target: {target:.0f}%)"
                if c.target_percent is None
                else f"Current target: {c.target_percent:.0f}%"
            )
            ui.label(inherit_note).classes("cli-text")

            # ---- Set / change target ----
            with ui.card().classes("glass-card w-full p-5"):
                ui.label(f"Set Target: {c.name}").classes("text-violet-300 font-semibold")
                current = (
                    f"{c.target_percent:.0f}%"
                    if c.target_percent is not None
                    else "none (inherits semester uniform target)"
                )
                ui.label(f"Current target: {current}").classes("cli-text")
                mode = ui.select(
                    {"l": "Set by letter grade", "p": "Set by percent"},
                    value="l",
                    label="Set by (l)etter grade or (p)ercent?",
                ).props(FIELD).classes("w-full")
                letter_in = ui.select(
                    LETTER_OPTIONS,
                    value=current_target_letter(c, sem),
                    label="Target letter grade (e.g. A, A-, B+, B, B-, C+, C, C-, D+, D)",
                ).props(FIELD).classes("w-full")
                pct_in = ui.number(
                    "Target percent (e.g. 85)",
                    value=target,
                    min=0,
                    max=100,
                    step=1,
                ).props(FIELD).classes("w-full")

                def sync_mode() -> None:
                    is_letter = mode.value == "l"
                    letter_in.set_visibility(is_letter)
                    pct_in.set_visibility(not is_letter)

                mode.on_value_change(lambda _: sync_mode())
                sync_mode()

                def save_target() -> None:
                    if mode.value == "p":
                        pct = float(pct_in.value or 0)
                        c.target_percent = pct
                        letter, gp = percentage_to_grade(pct)
                        save_data()
                        ui.notify(
                            f"Target set: {pct:.0f}% (currently maps to {letter}, {gp:.2f})",
                            color="positive",
                        )
                    else:
                        try:
                            c.set_target_from_letter(str(letter_in.value).upper())
                            save_data()
                            ui.notify(
                                f"Target set: {letter_in.value} -> aiming for >= {c.target_percent:.0f}%",
                                color="positive",
                            )
                        except ValueError:
                            ui.notify("Unrecognised letter grade — nothing changed.", color="negative")
                            return
                    required_report_panel.refresh()
                    what_if_panel.refresh()
                    course_panels.refresh()

                ui.button("Save target", on_click=save_target).props("color=primary unelevated")

            # ---- Enter marks ----
            with ui.card().classes("glass-card w-full p-5"):
                ui.label("Enter marks for a course").classes("text-violet-300 font-semibold")
                portions: List[Tuple[str, object]] = [("theory", c.theory)]
                if c.has_lab and c.lab:
                    portions.append(("lab", c.lab))

                portion_choice = ui.select(
                    {p[0]: p[0].capitalize() for p in portions},
                    value="theory",
                    label="Theory or Lab component?",
                ).props(FIELD).classes("w-full")

                item_inputs: Dict[str, ui.number] = {}

                @ui.refreshable
                def marks_form() -> None:
                    item_inputs.clear()
                    which = portion_choice.value or "theory"
                    portion = c.theory if which == "theory" else c.lab
                    if portion is None:
                        ui.label("Lab portion not available.").classes("text-rose-400")
                        return
                    ui.label("Assessment items:").classes("text-white mt-2")
                    for comp in portion.components:
                        for item in comp.items:
                            status = (
                                f"(already {item.obtained_marks}/{item.max_marks})"
                                if item.is_completed
                                else "(not entered)"
                            )
                            ui.label(
                                f"  {comp.name} > {item.name} — out of {item.max_marks} {status}"
                            ).classes("cli-text text-sm")
                            key = f"{comp.name}::{item.name}"
                            item_inputs[key] = ui.number(
                                f"Marks obtained for {item.name} (out of {item.max_marks})",
                                value=item.obtained_marks if item.obtained_marks is not None else None,
                                min=0,
                                step=0.5,
                            ).props(FIELD).classes("w-full max-w-md")

                    def save_marks() -> None:
                        which_now = portion_choice.value or "theory"
                        portion_now = c.theory if which_now == "theory" else c.lab
                        if portion_now is None:
                            return
                        tgt = course_target(c, sem)
                        saved_any = False
                        for comp in portion_now.components:
                            for item in comp.items:
                                key = f"{comp.name}::{item.name}"
                                field = item_inputs.get(key)
                                if field is None or field.value is None or field.value == "":
                                    continue
                                marks = float(field.value)
                                if marks < 0:
                                    ui.notify("Marks can't be negative — not saved.", color="negative")
                                    continue
                                if marks > item.max_marks:
                                    ui.notify(
                                        f"Note: {marks} is above the max of {item.max_marks} — "
                                        "saving anyway in case of bonus marks.",
                                        color="warning",
                                    )
                                before = portion_now.pace_status(tgt)
                                needed_before = portion_now.required_for_item(item.name, tgt)
                                item.obtained_marks = marks
                                after = portion_now.pace_status(tgt)
                                saved_any = True
                                ui.notify(
                                    f"Saved: {item.name} = {marks}/{item.max_marks} ({item.percent_score:.1f}%)",
                                    color="positive",
                                )
                                if needed_before is not None:
                                    if item.percent_score >= needed_before - 1e-9:
                                        ui.notify(
                                            f"That's at or above the ~{needed_before:.2f}% this item needed — "
                                            "nice, it eases up what's left.",
                                            color="info",
                                        )
                                    else:
                                        ui.notify(
                                            f"That's below the ~{needed_before:.2f}% this item needed.",
                                            color="warning",
                                        )
                                if before["target_still_possible"] and not after["target_still_possible"]:
                                    ui.notify(
                                        f"WARNING: this drops your ceiling below target. Even 100% on everything "
                                        f"else now caps you at {after['best_case_percent']}% ({after['best_case_grade']}) — "
                                        "your target grade here is no longer reachable.",
                                        color="negative",
                                        timeout=8,
                                    )
                                elif (
                                    before.get("required_avg_on_remaining") is not None
                                    and after.get("required_avg_on_remaining") is not None
                                    and after["required_avg_on_remaining"]
                                    > before["required_avg_on_remaining"] + 1e-9
                                ):
                                    ui.notify(
                                        f"Heads-up: this raises what you need on the rest, from "
                                        f"{before['required_avg_on_remaining']:.2f}% to "
                                        f"{after['required_avg_on_remaining']:.2f}%.",
                                        color="warning",
                                        timeout=6,
                                    )
                        if saved_any:
                            save_data()
                            marks_form.refresh()
                            required_report_panel.refresh()
                            what_if_panel.refresh()
                        else:
                            ui.notify("Enter at least one mark value to save.", color="warning")

                    ui.button("Save entered marks", on_click=save_marks).props(
                        "color=primary unelevated"
                    ).classes("mt-3")

                portion_choice.on_value_change(lambda _: marks_form.refresh())
                marks_form()

        @ui.refreshable
        def what_if_panel() -> None:
            c = sem.courses[course_idx]
            tgt = course_target(c, sem)
            proj = c.projected_percent()
            letter, gp = percentage_to_grade(proj)

            ui.label("Grade calculator").classes("text-violet-300 font-semibold text-lg")
            ui.label(
                "Uses saved marks plus the official grading scale to tell you the current / projected letter grade, "
                "and what you still need on one upcoming item."
            ).classes("cli-hint mb-3")

            with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
                with ui.card().classes("glass-card p-4 min-w-44"):
                    ui.label("From saved marks").classes("text-gray-400 text-xs uppercase")
                    ui.label(f"{proj:.1f}%").classes("text-2xl font-bold text-sky-300")
                    ui.label(f"{letter}  ({gp:.2f})").classes("grade-chip mt-1")
                if c.is_complete():
                    overall = c.overall_percent()
                    fl, fgp = c.grade()
                    with ui.card().classes("glass-card p-4 min-w-44"):
                        ui.label("Locked-in grade").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{overall:.1f}%").classes("text-2xl font-bold text-white")
                        ui.label(f"{fl}  ({fgp:.2f})").classes("grade-chip mt-1")
                else:
                    best = c.best_case_percent()
                    bl, bgp = percentage_to_grade(best)
                    with ui.card().classes("glass-card p-4 min-w-44"):
                        ui.label("Best case remaining").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{best:.1f}%").classes("text-2xl font-bold text-violet-300")
                        ui.label(f"{bl}  ({bgp:.2f})").classes("grade-chip mt-1")

            portions2: List[Tuple[str, object]] = [("theory", c.theory)]
            if c.has_lab and c.lab:
                portions2.append(("lab", c.lab))

            which2 = ui.select(
                {p[0]: p[0].capitalize() for p in portions2},
                value="theory",
                label="Theory or Lab component?",
            ).props(FIELD).classes("w-full")

            item_select = ui.select(
                {},
                label="Which one are you about to take?",
            ).props(FIELD).classes("w-full")
            assume_toggle = ui.switch(
                "Assume specific scores on the OTHER pending items instead of the flat average?",
                value=False,
            ).props("color=primary")
            assumed_col = ui.column().classes("w-full")
            assumed_fields: Dict[str, ui.number] = {}
            result_box = ui.column().classes("w-full mt-3")

            def pending_for(portion_name: str):
                portion = c.theory if portion_name == "theory" else c.lab
                if portion is None:
                    return []
                return [
                    (comp.name, it)
                    for comp in portion.components
                    for it in comp.items
                    if not it.is_completed
                ]

            def fill_items() -> None:
                pending = pending_for(which2.value or "theory")
                if not pending:
                    item_select.set_options({})
                    item_select.value = None
                    return
                item_select.set_options(
                    {i: f"{comp_name} > {it.name}  (out of {it.max_marks})" for i, (comp_name, it) in enumerate(pending)}
                )
                item_select.value = 0

            def rebuild_assumed() -> None:
                assumed_col.clear()
                assumed_fields.clear()
                if not assume_toggle.value:
                    return
                pending = pending_for(which2.value or "theory")
                pick_idx = item_select.value
                with assumed_col:
                    for i, (_cn, it) in enumerate(pending):
                        if i == pick_idx:
                            continue
                        assumed_fields[it.name.lower()] = ui.number(
                            f"Expected % on '{it.name}' (blank = use flat average)",
                            value=None,
                            min=0,
                            max=100,
                            step=0.5,
                        ).props(FIELD).classes("w-full")

            def compute() -> None:
                result_box.clear()
                pname = which2.value or "theory"
                pending = pending_for(pname)
                with result_box:
                    if not pending:
                        ui.label("Nothing pending in this portion — it's fully graded.").classes("cli-text")
                        if c.is_complete():
                            overall = c.overall_percent()
                            fl, fgp = c.grade()
                            ui.label(f"Your grade from saved marks: {overall:.2f}% → {fl} ({fgp:.2f})").classes(
                                "text-sky-300 mt-2"
                            )
                        return
                    idx = int(item_select.value if item_select.value is not None else 0)
                    if not (0 <= idx < len(pending)):
                        ui.notify("Pick an upcoming item from the dropdown.", color="negative")
                        return
                    _, target_item = pending[idx]
                    assumed = {
                        k: float(f.value)
                        for k, f in assumed_fields.items()
                        if f.value is not None and f.value != ""
                    }
                    needed_pct = c.required_for_item(
                        pname, target_item.name, target_percent=tgt, assumed_scores=assumed
                    )
                    if needed_pct is None:
                        ui.notify("Could not compute — check the item and try again.", color="negative")
                        return
                    needed_marks = (needed_pct / 100) * target_item.max_marks
                    with ui.element("div").classes("pace-box w-full"):
                        ui.label(
                            f"To hit {tgt:.0f}% overall (with your assumptions on the rest):"
                        ).classes("text-white font-semibold")
                        if needed_pct > 100:
                            ui.label(
                                f"you'd need {needed_pct:.2f}% on '{target_item.name}' — that's above 100%, not achievable here. "
                                "You'll need a higher score elsewhere, or accept a lower grade in this course."
                            ).classes("cli-text mt-1")
                        elif needed_pct < 0:
                            ui.label(
                                f"'{target_item.name}' is already covered — you could score 0 here and still be on track."
                            ).classes("cli-text mt-1")
                        else:
                            ui.label(
                                f"you need {needed_marks:.2f} / {target_item.max_marks} ({needed_pct:.2f}%) on '{target_item.name}'."
                            ).classes("text-sky-300 mt-1")
                    ui.label(f"Current projected grade from saved marks: {letter} ({gp:.2f}) at {proj:.1f}%").classes(
                        "cli-hint mt-2"
                    )

            which2.on_value_change(lambda _: (fill_items(), rebuild_assumed()))
            item_select.on_value_change(lambda _: rebuild_assumed())
            assume_toggle.on_value_change(lambda _: rebuild_assumed())
            fill_items()
            ui.button("Calculate required score & grade", on_click=compute).props(
                "color=primary unelevated"
            ).classes("mt-3")

        course_panels()

        with ui.card().classes("glass-card w-full p-5"):
            required_report_panel()

        with ui.card().classes("glass-card w-full p-5"):
            what_if_panel()


# --------------------------------------------------------------------------- #
# CGPA module
# --------------------------------------------------------------------------- #
@ui.page("/cgpa")
def cgpa_page() -> None:
    apply_page_theme()
    ensure_user_data()
    nav_bar()

    with ui.column().classes("w-full px-4 md:px-10 py-6 gap-4"):
        ui.button("← Back to Dashboard", on_click=lambda: ui.navigate.to("/dashboard")).props(
            "flat color=primary"
        )
        with ui.column().classes("w-full items-center text-center mb-2"):
            ui.label("CGPA Module").classes("text-4xl md:text-5xl font-black dashboard-title")
            ui.label("Track past semesters and watch your cumulative GPA grow.").classes("cli-hint mt-2")

        @ui.refreshable
        def history_panel() -> None:
            ui.label("Semester history").classes("text-violet-300 font-semibold mb-2")
            if not app_data.cgpa.semesters:
                ui.label("No semester history yet. Add one below.").classes("cli-hint")
                return
            rows = [
                {
                    "name": s.name,
                    "gpa": f"{s.sgpa:.3f}",
                    "credits": s.credit_hours,
                }
                for s in app_data.cgpa.semesters
            ]
            ui.table(
                columns=[
                    {"name": "name", "label": "Semester", "field": "name", "align": "left"},
                    {"name": "gpa", "label": "GPA", "field": "gpa", "align": "center"},
                    {"name": "credits", "label": "Credit Hours", "field": "credits", "align": "center"},
                ],
                rows=rows,
                row_key="name",
            ).classes("w-full ascend-table").props("flat bordered separator=horizontal")
            c = app_data.cgpa.cgpa()
            if c is not None:
                with ui.row().classes("w-full gap-4 mt-4 flex-wrap"):
                    with ui.card().classes("glass-card p-4"):
                        ui.label("CGPA").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{c:.3f}").classes("text-3xl font-bold text-sky-300")
                    with ui.card().classes("glass-card p-4"):
                        ui.label("Equivalent percentage").classes("text-gray-400 text-xs uppercase")
                        ui.label(f"{app_data.cgpa.percentage_equivalent():.2f}%").classes(
                            "text-3xl font-bold text-violet-300"
                        )

        with ui.card().classes("glass-card w-full p-5"):
            history_panel()

        with ui.card().classes("glass-card w-full p-5"):
            ui.label("1) Add a past semester result manually").classes("text-violet-300 font-semibold")
            past_name = ui.input("Semester name").props(FIELD).classes("w-full")
            past_sgpa = ui.number("GPA (out of 4.00)", value=3.0, min=0, max=4, step=0.01).props(
                FIELD
            ).classes("w-full")
            past_ch = ui.number("Total credit hours that semester", value=15, min=1, step=0.5).props(
                FIELD
            ).classes("w-full")

            def add_manual() -> None:
                if not past_name.value:
                    ui.notify("Semester name is required.", color="negative")
                    return
                app_data.cgpa.add(
                    past_name.value, float(past_sgpa.value or 0), float(past_ch.value or 0)
                )
                save_data()
                ui.notify(f"Added {past_name.value}.", color="positive")
                history_panel.refresh()

            ui.button("Add manually", on_click=add_manual).props("color=primary unelevated")

        with ui.card().classes("glass-card w-full p-5"):
            ui.label("2) Pull in a tracked semester's GPA automatically").classes(
                "text-violet-300 font-semibold"
            )
            if not app_data.semesters:
                ui.label("No tracked semesters yet.").classes("cli-text")
            else:
                options = {}
                for i, s in enumerate(app_data.semesters):
                    val = s.actual_sgpa if s.finalized else s.sgpa_projected()
                    tag = "final" if s.finalized else "projected"
                    options[i] = f"[{i}] {s.name} — {tag} GPA: {val}"
                pick = ui.select(options, value=0, label="Pick one").props(FIELD).classes("w-full")

                def pull_tracked() -> None:
                    idx = int(pick.value if pick.value is not None else 0)
                    if not (0 <= idx < len(app_data.semesters)):
                        return
                    s = app_data.semesters[idx]
                    val = s.actual_sgpa if s.finalized else s.sgpa_projected()
                    if val is None:
                        ui.notify("No GPA available yet for that semester.", color="warning")
                        return
                    app_data.cgpa.add(s.name, val, s.total_credit_hours())
                    save_data()
                    ui.notify(f"Added {s.name} ({val:.3f}) to CGPA history.", color="positive")
                    history_panel.refresh()

                ui.button("Pull selected semester", on_click=pull_tracked).props("color=primary unelevated")

        with ui.card().classes("glass-card w-full p-5"):
            ui.label("4) Remove a semester entry").classes("text-violet-300 font-semibold")
            rem = ui.input("Semester name to remove").props(FIELD).classes("w-full")

            def remove_entry() -> None:
                if not rem.value:
                    return
                app_data.cgpa.remove(rem.value)
                save_data()
                ui.notify(f"Removed '{rem.value}' (if it existed).", color="info")
                history_panel.refresh()

            ui.button("Remove", on_click=remove_entry).props("outline color=negative")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Ascend",
        dark=True,
        storage_secret="ascend-dev-secret-key",
        reload=False,
    )
