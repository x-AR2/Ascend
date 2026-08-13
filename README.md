# GPA Planner

A grade-planning tool built around your university's official grading scale
(85+ = A/4.00 down to <50 = F/0.00, with the tenths-digit rounding rule).
It tells you exactly what you need to score in each remaining quiz,
assignment, midterm, and final to hit a target grade — per course, and
rolled up into your semester's target SGPA.

## Running it

```
python3 main.py
```

No external dependencies — everything is Python standard library (`dataclasses`,
`json`, `decimal`). That's deliberate: it makes porting the logic into a
Flask/FastAPI backend later a matter of adding routes, not rewriting math.

Run `python3 test_logic.py` any time to sanity-check the grading/required-marks
math (also useful after you or I change anything).

## How it's organised

```
grading.py    Grade scale, official rounding rule, %<->GPA conversions
models.py     AssessmentItem -> Component -> Portion -> Course -> Semester
              (this is where the "required marks" engine lives)
cgpa.py       Standalone CGPA module (SGPA history -> CGPA)
storage.py    JSON persistence (data/app_data.json)
cli.py        Interactive terminal front-end — thin, calls into models.py
main.py       Entry point
```

Nothing in `models.py` or `cgpa.py` knows the CLI exists. When you're ready
for a real frontend, a Flask/FastAPI route just imports these same classes,
calls the same methods, and returns JSON instead of printing to a terminal —
the CLI and the future API become two interchangeable "views" on the same
engine.

## What each module actually does

**Course structure.** Every course has a `theory` portion (Assignments 10% /
Quizzes 15% / Midterm 25% / Final 50%). Courses with a lab also get a `lab`
portion (Lab Assignments 25% / Lab Midterm 25% / Lab Final 50%), each with
its own credit hours; the two portions' percentages are combined weighted by
their credit hours once both are graded, per the policy you shared. Within a
component (e.g. "Quizzes"), weight is split evenly across however many items
you add — so it doesn't matter if a teacher gives 1 quiz or 4, the 15% is
just divided accordingly.

**Required-marks engine** (`Course.required_report`). For each portion:
`required average on everything remaining = (target% − % already banked) / remaining weight%`.
If that number is over 100, it tells you plainly that the target is no
longer mathematically reachable in that portion. For lab courses where one
portion is already fully graded, it *solves* for the other portion's
required percentage using the credit-hour weighting, rather than just
assuming a flat target on both sides.

**Target distribution across a semester.** You give one target SGPA for the
whole semester. As a starting point, `apply_uniform_target()` assigns the
*same* target percentage to every course (this is mathematically guaranteed
to hit your target SGPA if you actually hit it in every course). From there
you're expected to override individual courses — e.g. aim higher in a
course you're strong in, lower in one you're not — and the sensitivity
ranking (`Semester.sensitivity_ranking()` / dashboard option 5) tells you
which courses move the SGPA needle most per grade-band, so you know where
to concentrate effort. This directly implements "high-credit courses affect
SGPA/CGPA the most, prioritise them" — it's advisory rather than an
automatic solver, because only you know which courses you can realistically
pull a higher grade in.

**Progress tracking.** Marks are saved permanently to
`data/app_data.json` as you enter them (dashboard option 3 / 9 to save).
Nothing is recalculated retroactively in a way that loses your actual
scores — "achieved so far" always reflects real entered marks; only the
*remaining* requirement gets recomputed.

**CGPA module** (`cgpa.py`). Independent of the semester planner above — it
just takes `(semester name, SGPA, credit hours)` triples, either typed in
manually for old semesters or pulled automatically from a semester you
tracked in this app, and computes `CGPA = Σ(SGPA × credit hours) / Σ(credit hours)`,
plus the `(CGPA/4.0)×100` percentage equivalent.

## Assumptions I made (flag if any are wrong for your program)

- Lab course credit-hour split defaults to 75% theory / 25% lab if you don't
  specify one explicitly at registration (fully editable per course).
- "Required marks" assumes **equal effort** across everything still
  ungraded in a portion (e.g. same average needed on quizzes and the
  final). If you'd rather fix one (say, assume a specific quiz score and
  solve only for the final), that's a small extension to
  `Portion.required_avg_on_remaining` — happy to add it next.
- Marks above 100% of an item's max are allowed with a warning, in case
  your teachers give bonus marks.
- The percentage→GPA table matches exactly what's in the notification you
  uploaded, including the tenths-digit rounding rule.

## About deploying with Netlify

One thing worth flagging early: **Netlify hosts static frontends and simple
serverless functions — it doesn't run a persistent Python/Flask/FastAPI
backend.** When you build the web frontend, the usual pattern is:

- Frontend (HTML/JS, or React/Vite build) → deployed on Netlify.
- Python API (Flask/FastAPI wrapping `models.py`/`cgpa.py`) → deployed
  separately on something like Render, Railway, Fly.io, or a small VPS —
  the frontend just calls it over HTTPS.
- Alternatively, if you want everything on Netlify, the backend logic would
  need to be ported to Netlify Functions (Node/Python via AWS Lambda-style
  functions), which is a bigger rewrite than wrapping this in FastAPI.

Not a blocker at all — just worth knowing now so the API design doesn't
assume same-origin hosting.

## Suggested next steps

1. Tell me if the assumptions above match your actual course policies.
2. I can add: per-item custom weighting (uneven quiz weights), a "what
   grade is still achievable" summary even after a target becomes
   unreachable, and edit/delete for registered courses.
3. Then we wrap `models.py`/`cgpa.py` in FastAPI endpoints and start on the
   frontend.
