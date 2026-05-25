# Grading scheme & class of award

Two related configurations, both **per academic level** (with a global fallback).

## Admin UI

**Admin → Exams → Grading & awards** (`/admin/examinations/grading`)

Tabs:

1. **Letter grades** — final mark (0–100) → letter + grade point (GPA/CGPA).
2. **Class of award** — cumulative CGPA → degree class (First Class, Second Upper, etc.).

Requires `examinations.publish_results`.

## Resolution (same pattern as assessment policies)

Programme on the course or student → `Program.academic_level` → level-specific scheme → else **global fallback** (no academic level).

## API

| Resource | List/create | Detail | Activate |
|----------|-------------|--------|----------|
| Letter grades | `/api/examinations/grade-scales/` | `.../<id>/` | `.../<id>/activate/` |
| Class of award | `/api/examinations/award-schemes/` | `.../<id>/` | `.../<id>/activate/` |
| Active (read) | `/api/examinations/grade-scale/?course_unit_id=` | | |
| Active award | `/api/examinations/award-scheme/?academic_level_id=` | | |
| Preview award | `/api/examinations/award-class/preview/?cgpa=4.2&academic_level_id=` | | |

## Default seed (global fallback)

**Letters:** A 80–100 (5.0), B+ 75–79.9, … F 0–49.9.

**Award classes (on 5-point CGPA):**

| Class | Min CGPA |
|-------|----------|
| First Class | 4.40 |
| Second Class (Upper) | 3.60 |
| Second Class (Lower) | 2.80 |
| Pass | 2.00 |

Used on provisional/transcript PDFs and graduation qualified lists.

```bash
python manage.py seed_examination_defaults
```

## Postgraduate example

Create schemes with academic level = Postgraduate (different pass letters or CGPA cut-offs), then **Activate** each.
