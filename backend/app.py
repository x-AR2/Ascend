"""
app.py
------
The web backend. Auth routes are the focus of this pass; the GPA routes
below wrap the exact same models.py/cgpa.py engine the CLI uses — same
math, same required-marks/pace logic, just JSON in and out instead of
input()/print(), and now scoped per logged-in user in SQLite instead of
one shared local file.

Run locally with:  python3 app.py   (serves on http://localhost:5000)
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # so "models"/"cgpa" import cleanly

from flask import Flask, request, jsonify, g
import database as db
import auth
from models import Course, Semester, Portion
from grading import percentage_to_grade, min_percentage_for_grade_point, GRADE_SCALE

app = Flask(__name__)
db.init_db()


# --------------------------------------------------------------------------- #
# CORS — hand-rolled since flask-cors isn't installable in this environment;
# it's about a dozen lines anyway. Restrict ALLOWED_ORIGIN before deploying.
# --------------------------------------------------------------------------- #
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")  # e.g. "https://your-app.netlify.app" in production


@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return "", 204


def body() -> dict:
    return request.get_json(silent=True) or {}


def err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #
@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = body()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    problem = auth.validate_signup_fields(username, email, password)
    if problem:
        return err(problem, 400)

    with db.get_conn() as conn:
        if db.get_user_by_username_or_email(conn, username) or db.get_user_by_username_or_email(conn, email):
            return err("That username or email is already registered.", 409)
        user_id = db.create_user(conn, username, email, auth.hash_password(password))

    token = auth.create_token(user_id, username)
    return jsonify({"token": token, "user": {"id": user_id, "username": username, "email": email}}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = body()
    identifier = (data.get("username_or_email") or "").strip()
    password = data.get("password") or ""
    if not identifier or not password:
        return err("Username/email and password are required.", 400)

    with db.get_conn() as conn:
        user = db.get_user_by_username_or_email(conn, identifier)
    if not user or not auth.verify_password(password, user["password_hash"]):
        return err("Incorrect username/email or password.", 401)

    token = auth.create_token(user["id"], user["username"])
    return jsonify({"token": token, "user": {"id": user["id"], "username": user["username"], "email": user["email"]}})


@app.route("/api/auth/me", methods=["GET"])
@auth.require_auth
def me():
    with db.get_conn() as conn:
        user = db.get_user_by_id(conn, g.user_id)
    if not user:
        return err("User not found.", 404)
    return jsonify({"id": user["id"], "username": user["username"], "email": user["email"]})


# --------------------------------------------------------------------------- #
# Semester routes
# --------------------------------------------------------------------------- #
@app.route("/api/semesters", methods=["POST"])
@auth.require_auth
def create_semester():
    data = body()
    name = (data.get("name") or "").strip()
    target_sgpa = data.get("target_sgpa")
    if not name or target_sgpa is None:
        return err("name and target_sgpa are required.", 400)
    try:
        target_sgpa = float(target_sgpa)
    except (TypeError, ValueError):
        return err("target_sgpa must be a number.", 400)

    with db.get_conn() as conn:
        sem_id = db.create_semester(conn, g.user_id, name, target_sgpa)
    return jsonify({"id": sem_id, "name": name, "target_sgpa": target_sgpa}), 201


@app.route("/api/semesters", methods=["GET"])
@auth.require_auth
def list_semesters():
    with db.get_conn() as conn:
        rows = db.list_semesters(conn, g.user_id)
    return jsonify([dict(r) for r in rows])


def _load_semester_object(conn, semester_id: int, user_id: int):
    """Reconstruct a full models.Semester (with Course objects) from the DB, or None if not found/owned."""
    srow = db.get_semester(conn, semester_id, user_id)
    if not srow:
        return None, None
    sem = Semester(name=srow["name"], target_sgpa=srow["target_sgpa"],
                    finalized=bool(srow["finalized"]), actual_sgpa=srow["actual_sgpa"])
    course_dicts = db.list_courses(conn, semester_id)
    id_map = {}
    for cd in course_dicts:
        cid = cd.pop("_id")
        course = Course.from_dict(cd)
        sem.add_course(course)
        id_map[id(course)] = cid
    return sem, id_map


@app.route("/api/semesters/<int:semester_id>", methods=["GET"])
@auth.require_auth
def get_semester(semester_id):
    with db.get_conn() as conn:
        sem, id_map = _load_semester_object(conn, semester_id, g.user_id)
        if not sem:
            return err("Semester not found.", 404)
        srow = db.get_semester(conn, semester_id, g.user_id)
    courses_out = []
    for c in sem.courses:
        courses_out.append({
            "id": id_map[id(c)], "name": c.name, "credit_hours": c.credit_hours,
            "has_lab": c.has_lab, "target_percent": c.target_percent,
            "is_complete": c.is_complete(),
            "projected_grade": {"letter": c.projected_grade()[0], "gp": c.projected_grade()[1]},
        })
    return jsonify({
        "id": semester_id, "name": sem.name, "target_sgpa": sem.target_sgpa,
        "finalized": sem.finalized, "courses": courses_out,
    })


@app.route("/api/semesters/<int:semester_id>/apply-uniform-target", methods=["POST"])
@auth.require_auth
def apply_uniform_target(semester_id):
    with db.get_conn() as conn:
        sem, id_map = _load_semester_object(conn, semester_id, g.user_id)
        if not sem:
            return err("Semester not found.", 404)
        sem.apply_uniform_target()
        for c in sem.courses:
            db.update_course(conn, id_map[id(c)], c.to_dict())
    return jsonify({"applied_target_percent": min_percentage_for_grade_point(sem.target_sgpa)})


@app.route("/api/semesters/<int:semester_id>/dashboard", methods=["GET"])
@auth.require_auth
def semester_dashboard(semester_id):
    with db.get_conn() as conn:
        sem, id_map = _load_semester_object(conn, semester_id, g.user_id)
    if not sem:
        return err("Semester not found.", 404)
    pace = sem.pace_status()
    courses_out = []
    for c in sem.courses:
        pg = c.projected_grade()
        courses_out.append({
            "id": id_map[id(c)], "name": c.name, "credit_hours": c.credit_hours,
            "target_percent": c.target_percent, "projected_letter": pg[0], "projected_gp": pg[1],
        })
    return jsonify({
        "pace": pace,
        "sgpa_projected_if_on_target": sem.sgpa_projected(),
        "sgpa_actual": sem.sgpa_actual(),
        "courses": courses_out,
        "prioritisation": sem.sensitivity_ranking(),
    })


# --------------------------------------------------------------------------- #
# Course routes
# --------------------------------------------------------------------------- #
def _build_course_from_payload(data: dict) -> Course:
    name = data["name"]
    credit_hours = float(data["credit_hours"])
    has_lab = bool(data.get("has_lab", False))
    course = Course.new(
        name=name, credit_hours=credit_hours, has_lab=has_lab,
        theory_credit_hours=data.get("theory_credit_hours"),
        lab_credit_hours=data.get("lab_credit_hours"),
    )

    assignments = data.get("assignments") or [{"name": "Assignment 1", "max_marks": 10}, {"name": "Assignment 2", "max_marks": 10}]
    quizzes = data.get("quizzes") or [{"name": "Quiz 1", "max_marks": 10}, {"name": "Quiz 2", "max_marks": 10}]
    course.theory.find_component("Assignments").items = []
    course.theory.find_component("Quizzes").items = []
    for a in assignments:
        course.theory.find_component("Assignments").add_item(a["name"], float(a["max_marks"]))
    for q in quizzes:
        course.theory.find_component("Quizzes").add_item(q["name"], float(q["max_marks"]))
    course.theory.find_component("Midterm").add_item("Midterm", float(data.get("midterm_max", 25)))
    course.theory.find_component("Final").add_item("Final Exam", float(data.get("final_max", 100)))

    if has_lab:
        course.lab.find_component("Lab Assignments").add_item("Lab Assignments", float(data.get("lab_assignments_max", 25)))
        course.lab.find_component("Lab Midterm").add_item("Lab Midterm", float(data.get("lab_midterm_max", 25)))
        course.lab.find_component("Lab Final").add_item("Lab Final", float(data.get("lab_final_max", 50)))

    if data.get("target_percent") is not None:
        course.target_percent = float(data["target_percent"])
    elif data.get("target_letter"):
        course.set_target_from_letter(data["target_letter"].upper())

    return course


@app.route("/api/semesters/<int:semester_id>/courses", methods=["POST"])
@auth.require_auth
def register_course(semester_id):
    with db.get_conn() as conn:
        srow = db.get_semester(conn, semester_id, g.user_id)
        if not srow:
            return err("Semester not found.", 404)
        data = body()
        if not data.get("name") or data.get("credit_hours") is None:
            return err("name and credit_hours are required.", 400)
        try:
            course = _build_course_from_payload(data)
        except (KeyError, ValueError, TypeError) as e:
            return err(f"Invalid course payload: {e}", 400)
        course_id = db.create_course(conn, semester_id, course.to_dict())
    return jsonify({"id": course_id, "name": course.name}), 201


def _load_course(conn, course_id: int, user_id: int):
    semester_id = db.course_belongs_to_user(conn, course_id, user_id)
    if not semester_id:
        return None
    row = db.get_course_row(conn, course_id)
    return Course.from_dict(json.loads(row["data"]))


@app.route("/api/courses/<int:course_id>/target", methods=["PATCH"])
@auth.require_auth
def set_course_target(course_id):
    data = body()
    with db.get_conn() as conn:
        course = _load_course(conn, course_id, g.user_id)
        if not course:
            return err("Course not found.", 404)
        if data.get("target_percent") is not None:
            course.target_percent = float(data["target_percent"])
        elif data.get("target_letter"):
            course.set_target_from_letter(data["target_letter"].upper())
        else:
            return err("Provide target_percent or target_letter.", 400)
        db.update_course(conn, course_id, course.to_dict())
    return jsonify({"target_percent": course.target_percent})


@app.route("/api/courses/<int:course_id>/report", methods=["GET"])
@auth.require_auth
def course_report(course_id):
    with db.get_conn() as conn:
        course = _load_course(conn, course_id, g.user_id)
    if not course:
        return err("Course not found.", 404)
    if course.target_percent is None:
        return err("No target set for this course yet.", 400)
    report = course.required_report()
    pace = {}
    if report.get("theory", {}).get("status") != "complete":
        pace["theory"] = course.theory.pace_status(report["theory"]["target_percent"])
    if course.has_lab and report.get("lab", {}).get("status") != "complete":
        pace["lab"] = course.lab.pace_status(report["lab"]["target_percent"])
    return jsonify({"report": report, "pace": pace})


@app.route("/api/courses/<int:course_id>/marks", methods=["POST"])
@auth.require_auth
def enter_marks(course_id):
    data = body()
    portion_name = data.get("portion", "theory")
    item_name = data.get("item_name")
    marks = data.get("marks")
    if not item_name or marks is None:
        return err("item_name and marks are required.", 400)
    try:
        marks = float(marks)
    except (TypeError, ValueError):
        return err("marks must be a number.", 400)
    if marks < 0:
        return err("marks can't be negative.", 400)

    with db.get_conn() as conn:
        course = _load_course(conn, course_id, g.user_id)
        if not course:
            return err("Course not found.", 404)
        portion = course.lab if (portion_name == "lab" and course.has_lab) else course.theory
        comp, item = portion.find_item(item_name)
        if item is None:
            return err(f"No such item: {item_name}", 404)

        target = course.target_percent if course.target_percent is not None else None
        warnings = []
        before = after = None
        needed_before = None
        if target is not None:
            before = portion.pace_status(target)
            needed_before = portion.required_for_item(item.name, target)

        item.obtained_marks = marks

        if target is not None:
            after = portion.pace_status(target)
            if needed_before is not None:
                if item.percent_score < needed_before - 1e-9:
                    warnings.append(f"That's below the ~{needed_before:.2f}% this item needed.")
                else:
                    warnings.append(f"That's at or above the ~{needed_before:.2f}% this item needed.")
            if before["target_still_possible"] and not after["target_still_possible"]:
                warnings.append(
                    f"This drops your ceiling below target — even 100% on everything else now caps you at "
                    f"{after['best_case_percent']}% ({after['best_case_grade']})."
                )
            elif (before.get("required_avg_on_remaining") is not None and after.get("required_avg_on_remaining") is not None
                  and after["required_avg_on_remaining"] > before["required_avg_on_remaining"] + 1e-9):
                warnings.append(
                    f"This raises what you need on the rest, from {before['required_avg_on_remaining']:.2f}% "
                    f"to {after['required_avg_on_remaining']:.2f}%."
                )

        db.update_course(conn, course_id, course.to_dict())

    return jsonify({
        "saved": {"item": item.name, "obtained_marks": item.obtained_marks, "percent_score": item.percent_score},
        "warnings": warnings,
        "pace_before": before, "pace_after": after,
    })


@app.route("/api/courses/<int:course_id>/what-if", methods=["POST"])
@auth.require_auth
def what_if(course_id):
    data = body()
    portion_name = data.get("portion", "theory")
    item_name = data.get("item_name")
    assumed_scores = data.get("assumed_scores") or {}
    if not item_name:
        return err("item_name is required.", 400)

    with db.get_conn() as conn:
        course = _load_course(conn, course_id, g.user_id)
    if not course:
        return err("Course not found.", 404)
    if course.target_percent is None:
        return err("No target set for this course yet.", 400)

    needed_pct = course.required_for_item(portion_name, item_name, assumed_scores=assumed_scores)
    if needed_pct is None:
        return err("Could not compute — check portion/item_name.", 400)
    _, item = (course.lab if portion_name == "lab" else course.theory).find_item(item_name)
    return jsonify({
        "required_percent": round(needed_pct, 2),
        "required_marks": round((needed_pct / 100) * item.max_marks, 2) if needed_pct <= 100 else None,
        "max_marks": item.max_marks,
        "achievable": needed_pct <= 100.0001,
    })


# --------------------------------------------------------------------------- #
# CGPA routes
# --------------------------------------------------------------------------- #
@app.route("/api/cgpa", methods=["GET"])
@auth.require_auth
def get_cgpa():
    with db.get_conn() as conn:
        rows = db.list_cgpa_entries(conn, g.user_id)
    entries = [dict(r) for r in rows]
    tch = sum(e["credit_hours"] for e in entries)
    cgpa_val = (sum(e["sgpa"] * e["credit_hours"] for e in entries) / tch) if tch else None
    return jsonify({
        "entries": entries,
        "cgpa": round(cgpa_val, 3) if cgpa_val is not None else None,
        "percentage_equivalent": round((cgpa_val / 4.0) * 100, 2) if cgpa_val is not None else None,
    })


@app.route("/api/cgpa", methods=["POST"])
@auth.require_auth
def add_cgpa_entry():
    data = body()
    name = (data.get("name") or "").strip()
    sgpa = data.get("sgpa")
    credit_hours = data.get("credit_hours")
    if not name or sgpa is None or credit_hours is None:
        return err("name, sgpa, and credit_hours are required.", 400)
    with db.get_conn() as conn:
        entry_id = db.add_cgpa_entry(conn, g.user_id, name, float(sgpa), float(credit_hours))
    return jsonify({"id": entry_id}), 201


@app.route("/api/cgpa/<int:entry_id>", methods=["DELETE"])
@auth.require_auth
def delete_cgpa_entry(entry_id):
    with db.get_conn() as conn:
        db.delete_cgpa_entry(conn, entry_id, g.user_id)
    return "", 204


@app.route("/api/grading-scale", methods=["GET"])
def grading_scale():
    return jsonify([{"min": lo, "max": hi, "letter": l, "grade_point": gp} for lo, hi, l, gp in GRADE_SCALE])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
