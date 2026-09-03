# Faculty of Law — LLB-377-Main marks go-live checklist

Target cohort: **Bachelor of Laws (Main) — ProgramBatch `LLB-377-Main`**.

Marks entry uses `CourseUnitResult` + open `MarksEntryWindow` + registered enrollments (`registration_date`). A published exam timetable is **not** required.

## 1. Deploy commands

On the API server after pulling `main`:

```bash
cd /home/admissions/NDU_Admission_backend
source venv/bin/activate
git fetch origin main && git reset --hard origin/main
sudo systemctl restart gunicorn   # only needed for API; manage.py works without restart
```

## 2. Audit (read-only)

```bash
python manage.py audit_batch_marks_readiness --batch "LLB-377-Main" --csv /tmp/llb377_marks_audit.csv
```

Review:

- SPE totals: legacy vs portal
- Enrollments with / without `registration_date`
- Results: draft / verified / published (and who entered them)
- Marks windows, assessment policy, grade scale
- Courses with enrollments but no lecturers

## 3. Clear test marks

Default: remove **draft** and **verified** only.

```bash
python manage.py clear_batch_test_marks --batch "LLB-377-Main" --dry-run
python manage.py clear_batch_test_marks --batch "LLB-377-Main"
```

Published rows stay until you explicitly approve:

```bash
python manage.py clear_batch_test_marks --batch "LLB-377-Main" \
  --include-published --i-understand-published --dry-run
```

## 4. Close readiness gaps

```bash
# Policies / grade bands
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --seed-policies

# Who still needs lecturer assignment (fix in UI / admin)
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --report-lecturers

# Open semester windows (dry-run first)
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --open-windows --dry-run
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --open-windows

# Stamp registration only after audit shows students should sit
# Prefer a single semester: --semester-id <id>
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --stamp-registration --dry-run
python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --stamp-registration --semester-id <id>
```

## 5. Go-live sequence

1. Audit clean: no unexpected published leftovers; draft/verified cleared.
2. Windows open for the target semester(s).
3. Lecturers assigned on papers that will be marked.
4. Roster in Enter Scores shows **registered** students only.
5. Pilot: enter marks on **one** course → verify → publish.
6. Confirm students/lecturers see expected outcomes.
7. Proceed with remaining courses / bulk import if needed.

## 6. Rules reminder

| Required | Not required |
|----------|----------------|
| Open `MarksEntryWindow` (or exam-office override) | Published `ExamSession` |
| Assessment policy + grade scale | Teaching-section membership |
| Enrollment `status=enrolled` + `registration_date` | Global “active semester” flag |
| Lecturer (or exam office) permission | |

Legacy imports (`application.source=legacy_import`) use the same roster rules once enrolled and registered.

## Related commands

- `audit_batch_marks_readiness`
- `clear_batch_test_marks`
- `prepare_batch_marks_readiness`
- `seed_examination_defaults`
- `investigate_law_students` (Faculty of Law reg_no reconciliation)
