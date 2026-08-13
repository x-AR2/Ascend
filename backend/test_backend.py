"""End-to-end backend test. Run with: python3 test_backend.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# fresh DB for the test run
DB_PATH = os.path.join(os.path.dirname(__file__), "gpa.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

from app import app  # noqa: E402


def check(label, cond):
    print(f"{'OK ' if cond else 'FAIL'} - {label}")
    assert cond, label


client = app.test_client()

# ---- signup ----
r = client.post("/api/auth/signup", json={"username": "asma_k", "email": "asma@example.com", "password": "hunter22"})
check("signup returns 201", r.status_code == 201)
token = r.get_json()["token"]
check("signup returns a token", bool(token))
check("signup returns user info", r.get_json()["user"]["username"] == "asma_k")

# duplicate signup should fail
r2 = client.post("/api/auth/signup", json={"username": "asma_k", "email": "other@example.com", "password": "hunter22"})
check("duplicate username rejected", r2.status_code == 409)

# weak password rejected
r3 = client.post("/api/auth/signup", json={"username": "someone_else", "email": "someone@example.com", "password": "123"})
check("weak password rejected", r3.status_code == 400)

# ---- login ----
r = client.post("/api/auth/login", json={"username_or_email": "asma_k", "password": "hunter22"})
check("login succeeds", r.status_code == 200)
token = r.get_json()["token"]

r_bad = client.post("/api/auth/login", json={"username_or_email": "asma_k", "password": "wrongpassword"})
check("wrong password rejected", r_bad.status_code == 401)

AUTH = {"Authorization": f"Bearer {token}"}

# ---- /me requires auth ----
r_noauth = client.get("/api/auth/me")
check("me without token is 401", r_noauth.status_code == 401)
r_me = client.get("/api/auth/me", headers=AUTH)
check("me with token is 200", r_me.status_code == 200)
check("me returns correct username", r_me.get_json()["username"] == "asma_k")

# ---- semester ----
r = client.post("/api/semesters", json={"name": "Fall 2026", "target_sgpa": 3.5}, headers=AUTH)
check("create semester", r.status_code == 201)
sem_id = r.get_json()["id"]

r = client.get("/api/semesters", headers=AUTH)
check("list semesters", len(r.get_json()) == 1)

# ---- register a course (theory-only) ----
payload = {
    "name": "Data Structures", "credit_hours": 3, "has_lab": False,
    "target_letter": "B",
    "assignments": [{"name": "Assignment 1", "max_marks": 10}, {"name": "Assignment 2", "max_marks": 10}],
    "quizzes": [{"name": "Quiz 1", "max_marks": 10}, {"name": "Quiz 2", "max_marks": 10}],
    "midterm_max": 25, "final_max": 100,
}
r = client.post(f"/api/semesters/{sem_id}/courses", json=payload, headers=AUTH)
check("register course", r.status_code == 201)
course_id = r.get_json()["id"]

# a second user should NOT be able to touch this course
r2 = client.post("/api/auth/signup", json={"username": "other_user", "email": "other2@example.com", "password": "password1"})
token2 = r2.get_json()["token"]
r_forbidden = client.get(f"/api/courses/{course_id}/report", headers={"Authorization": f"Bearer {token2}"})
check("other user can't access this course", r_forbidden.status_code == 404)

# ---- enter marks (a weak quiz score) ----
r = client.post(f"/api/courses/{course_id}/marks", json={"portion": "theory", "item_name": "Quiz 1", "marks": 3}, headers=AUTH)
check("enter marks succeeds", r.status_code == 200)
data = r.get_json()
check("warns about below-pace score", any("below" in w.lower() for w in data["warnings"]))
print("Warnings after weak quiz:", data["warnings"])

# ---- report ----
r = client.get(f"/api/courses/{course_id}/report", headers=AUTH)
check("report succeeds", r.status_code == 200)
rep = r.get_json()
check("theory pace present", "theory" in rep["pace"])
print("Pace status:", rep["pace"]["theory"])

# ---- what-if ----
r = client.post(f"/api/courses/{course_id}/what-if",
                 json={"portion": "theory", "item_name": "Quiz 2", "assumed_scores": {"final exam": 90}},
                 headers=AUTH)
check("what-if succeeds", r.status_code == 200)
print("What-if result:", r.get_json())

# ---- dashboard ----
r = client.get(f"/api/semesters/{sem_id}/dashboard", headers=AUTH)
check("dashboard succeeds", r.status_code == 200)
print("Dashboard pace:", r.get_json()["pace"])

# ---- CGPA ----
r = client.post("/api/cgpa", json={"name": "Spring 2025", "sgpa": 3.2, "credit_hours": 15}, headers=AUTH)
check("add cgpa entry", r.status_code == 201)
r = client.get("/api/cgpa", headers=AUTH)
check("get cgpa", r.status_code == 200)
print("CGPA:", r.get_json())

print("\nALL BACKEND TESTS PASSED")
