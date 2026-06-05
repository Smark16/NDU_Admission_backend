# Graduation module (NDU portal)

Standalone app: `graduation` — `/api/graduation/`

## Workflow

1. **Publish results** (examinations module, by batch).
2. **Qualified list** — `GET /api/graduation/qualified/?program_batch_id=`  
   Rules: min CGPA (default 2.0), min graduation load (programme/curriculum), no published fails, enrolled.
3. **Ceremonies** — create congregation → add graduation days (sessions).
4. **Assign students** — `POST /api/graduation/sessions/{id}/assignments/` with `student_ids`.
5. **Print list** — `GET /api/graduation/sessions/{id}/print-list/`

## Roles

- `Graduation Officer` — full access (`seed_graduation_roles`)
- `Graduation Viewer` — qualified + print lists only

## Horizon

Admin → **Graduation** → Qualified list | Ceremonies

Uses the same **cohort bar** as Exams (programme → batch).

## Later phases

- PDF transcript / ceremony book export
- Senate-configurable award bands
- Dissertation metadata (postgrad)
- ARMS import
