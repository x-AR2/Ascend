"""
database.py
-----------
SQLite persistence for the multi-user backend. One file, `gpa.db`, holds
everyone's data — every query is scoped by user_id so users can only ever
see their own semesters/courses/CGPA history.

Courses are stored as a JSON blob (Course.to_dict()) rather than fully
normalized into columns — the nested Component/AssessmentItem structure
already has clean to_dict()/from_dict() round-tripping in models.py, and
duplicating that as a relational schema would just be two representations
of the same thing to keep in sync. Semesters and users get real columns
since we query/filter on those directly (by user, by name).
"""
import sqlite3
import os
import json
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "gpa.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS semesters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    target_sgpa REAL NOT NULL,
    finalized INTEGER NOT NULL DEFAULT 0,
    actual_sgpa REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    semester_id INTEGER NOT NULL REFERENCES semesters(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cgpa_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sgpa REAL NOT NULL,
    credit_hours REAL NOT NULL
);
"""


def init_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def create_user(conn, username: str, email: str, password_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        (username, email, password_hash),
    )
    return cur.lastrowid


def get_user_by_username_or_email(conn, identifier: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier)
    ).fetchone()


def get_user_by_id(conn, user_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# --------------------------------------------------------------------------- #
# Semesters
# --------------------------------------------------------------------------- #
def create_semester(conn, user_id: int, name: str, target_sgpa: float) -> int:
    cur = conn.execute(
        "INSERT INTO semesters (user_id, name, target_sgpa) VALUES (?, ?, ?)",
        (user_id, name, target_sgpa),
    )
    return cur.lastrowid


def list_semesters(conn, user_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM semesters WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()


def get_semester(conn, semester_id: int, user_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM semesters WHERE id = ? AND user_id = ?", (semester_id, user_id)
    ).fetchone()


def update_semester_target(conn, semester_id: int, target_sgpa: float):
    conn.execute("UPDATE semesters SET target_sgpa = ? WHERE id = ?", (target_sgpa, semester_id))


def finalize_semester(conn, semester_id: int, actual_sgpa: float):
    conn.execute(
        "UPDATE semesters SET finalized = 1, actual_sgpa = ? WHERE id = ?", (actual_sgpa, semester_id)
    )


# --------------------------------------------------------------------------- #
# Courses (stored as a JSON blob — see module docstring)
# --------------------------------------------------------------------------- #
def create_course(conn, semester_id: int, course_dict: Dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO courses (semester_id, data) VALUES (?, ?)",
        (semester_id, json.dumps(course_dict)),
    )
    return cur.lastrowid


def list_courses(conn, semester_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, data FROM courses WHERE semester_id = ? ORDER BY id", (semester_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["_id"] = r["id"]
        out.append(d)
    return out


def get_course_row(conn, course_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()


def update_course(conn, course_id: int, course_dict: Dict[str, Any]):
    conn.execute("UPDATE courses SET data = ? WHERE id = ?", (json.dumps(course_dict), course_id))


def course_belongs_to_user(conn, course_id: int, user_id: int) -> Optional[int]:
    """Returns the semester_id if this course's semester belongs to user_id, else None."""
    row = conn.execute(
        """SELECT c.semester_id FROM courses c
           JOIN semesters s ON s.id = c.semester_id
           WHERE c.id = ? AND s.user_id = ?""",
        (course_id, user_id),
    ).fetchone()
    return row["semester_id"] if row else None


# --------------------------------------------------------------------------- #
# CGPA history
# --------------------------------------------------------------------------- #
def add_cgpa_entry(conn, user_id: int, name: str, sgpa: float, credit_hours: float) -> int:
    cur = conn.execute(
        "INSERT INTO cgpa_entries (user_id, name, sgpa, credit_hours) VALUES (?, ?, ?, ?)",
        (user_id, name, sgpa, credit_hours),
    )
    return cur.lastrowid


def list_cgpa_entries(conn, user_id: int) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM cgpa_entries WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()


def delete_cgpa_entry(conn, entry_id: int, user_id: int):
    conn.execute("DELETE FROM cgpa_entries WHERE id = ? AND user_id = ?", (entry_id, user_id))
