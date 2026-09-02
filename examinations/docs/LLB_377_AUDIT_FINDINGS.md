# LLB-377-Main audit findings (fill after production run)

Run on the API host:

```bash
cd /home/admissions/NDU_Admission_backend
source venv/bin/activate
python manage.py audit_batch_marks_readiness --batch "LLB-377-Main" --csv /tmp/llb377_marks_audit.csv
```

Paste the command summary below after the first production run.

## Snapshot

| Metric | Value |
|--------|-------|
| ProgramBatch id | |
| SPE total / legacy / portal | |
| Enrollments registered / unregistered | |
| Results draft / verified / published | |
| Marks windows | |
| Courses missing lecturers | |
| Courses missing policy | |

## Interpretation notes

- Draft + verified → clear with `clear_batch_test_marks` (default).
- Published → only clear with `--include-published --i-understand-published` after Faculty of Law confirms they are not real.
- Unregistered enrollments → stamp with `prepare_batch_marks_readiness --stamp-registration` (prefer `--semester-id`) after confirming students should sit.
- Closed windows → `--open-windows`.
- Missing policies → `--seed-policies`.

## Local note

Developer SQLite/local DB may not contain `LLB-377-Main`; `audit_batch_marks_readiness` correctly errors until run against production.
