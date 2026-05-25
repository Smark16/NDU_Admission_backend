# Assessment policies

Senate rules for CA, exam sitting, and pass marks. Configurable per **academic level** (e.g. postgraduate pass 60%, undergraduate 50%).

## Admin UI

**Admin → Exams → Assessment policies** (`/admin/examinations/policies`)

Requires `examinations.publish_results` (examination manager).

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/examinations/policies/` | List all policies |
| POST | `/api/examinations/policies/` | Create |
| GET/PATCH/DELETE | `/api/examinations/policies/<id>/` | Detail |
| GET | `/api/examinations/policy/?course_unit_id=` | Resolved policy for a course |
| GET | `/api/examinations/policy/?academic_level_id=` | Resolved policy for a level |

## Resolution

1. `CourseUnit` → `program_batch.program.academic_level` → active policy for that level.
2. Otherwise → global default (`academic_level` null, `is_default=True`).

Mark entry stores the resolved policy on each `CourseUnitResult.policy` (frozen at save).

## Seed

```bash
python manage.py seed_examination_defaults
```

Creates global default (CA 40, sit ≥17.5, pass 50) and, if a level named Postgraduate/Masters exists, a level policy with pass 60.
