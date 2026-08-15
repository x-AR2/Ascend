# Ascend

A GPA/CGPA planning tool built around a university's official grading scale
(85+ = A / 4.00, down to <50 = F / 0.00, with tenths-digit rounding). Instead
of just tracking grades after the fact, Ascend works backwards from a target
SGPA and tells you exactly what score you still need on each remaining quiz,
assignment, midterm, and final to get there — per course, and rolled up into
the semester.

The project ships as three interchangeable views over one shared calculation
engine:

| Interface | What it is | Where |
|---|---|---|
| **CLI** | Interactive terminal menu, single-user, local JSON storage | `main.py` |
| **GUI** | NiceGUI desktop/web app with the same features | `ascend_gui.py` |
| **API** | Flask backend with signup/login and per-user SQLite storage | `backend/` |

## Features

- **Required-marks engine** — for every ungraded component, computes the
  average you need on everything remaining to hit your target percentage,
  and tells you plainly when a target is no longer mathematically reachable.
- **Theory + lab courses** — lab courses combine both portions, weighted by
  their credit hours, once each portion is graded.
- **Semester target distribution** — set one target SGPA for the semester;
  Ascend spreads it evenly across courses as a starting point, then ranks
  courses by how much each one moves your SGPA so you know where to focus.
- **What-if analysis** — see how a single hypothetical mark shifts a
  course's required average before you've actually taken it.
- **CGPA tracking** — combine past semesters' SGPA and credit hours into a
  running CGPA, either typed in manually or pulled from semesters you
  tracked in the app.
- **Persistent progress** — marks you enter are saved as you go; only the
  *remaining* requirement is ever recomputed, never your actual scores.

## Getting started

### CLI (no setup required)

Built entirely in core Python — no dependencies to install.

```bash
python main.py
```

### GUI

```bash
pip install -r requirements.txt
python ascend_gui.py
```

Opens a NiceGUI app (dashboard, per-course view, CGPA page) backed by the
same local `data/app_data.json` file the CLI uses. Its login/signup screens
are currently a front-end mock and aren't wired to the backend below yet.

### Backend API

```bash
cd backend
pip install -r requirements.txt
python3 app.py
```

Serves on `http://localhost:5000`, with real signup/login (hashed
passwords, JWT sessions) and the same engine scoped per user in SQLite. See
[`backend/README.md`](backend/README.md) for the full endpoint reference and
deployment notes.

## Project structure

```
grading.py    Grade scale, official rounding rule, %<->GPA conversions
models.py     AssessmentItem -> Component -> Portion -> Course -> Semester
              (the required-marks engine lives here)
cgpa.py       Standalone CGPA module (SGPA history -> CGPA)
storage.py    JSON persistence for the CLI/GUI (data/app_data.json)
cli.py        Terminal front-end
ascend_gui.py NiceGUI front-end
main.py       CLI entry point
backend/      Flask API: auth, SQLite storage, JSON routes over the
              same engine (see backend/README.md)
```

`models.py` and `cgpa.py` don't know any front-end exists — the CLI, GUI,
and API all just import the same classes and call the same methods.

## Testing

```bash
python3 test_logic.py           # grading / required-marks math
python3 backend/test_backend.py # full API flow: auth, courses, marks, reports
```

## Assumptions baked into the engine

- Lab courses default to a 75% theory / 25% lab credit-hour split unless set
  otherwise at registration.
- Required-marks math assumes **equal effort** across everything still
  ungraded in a portion (same average needed on, say, every remaining quiz
  and the final).
- Marks above an item's max are allowed, with a warning, in case a course
  gives bonus marks.
