# Timetable CSV samples (Science · Semester I 2026/2027)

Starter files shaped from draft lecture grids. **Not** auto-imported.

Prefer **Download worksheet** from the Timetable dialog (or `export_timetable_worksheet`) —
that builds sections A/B/C from the live database. These samples are only for format reference.

| File | Campus / mode |
|------|----------------|
| `science_weekend_2026_s1.sample.csv` | Weekend Fri/Sat/Sun (+ online Sunday example) |
| `science_day_kla_2026_s1.sample.csv` | Day Kampala 08–11 / 11–14 / 14–17 |
| `science_day_main_2026_s1.sample.csv` | Day Main campus bands |

## Workflow (automated)
```bash
# 1) Export worksheet from DB (faculty + AY around a semester)
python manage.py export_timetable_worksheet --semester-id SEM_ID -o worksheet.csv

# 2) Fill day / start_time / end_time / venue_code in Excel

# 3) Dry-run then import
python manage.py import_timetable_csv --semester-id SEM_ID worksheet.csv --dry-run
python manage.py import_timetable_csv --semester-id SEM_ID worksheet.csv
```

Or in UI: **Download worksheet** → edit → **Upload CSV** → **Publish timetable**.

## Worksheet sections
- **A** Already Shared Teaching (STO)
- **B** Cross-cutting candidates (catalog flag / shared paper #)
- **C** Programme-only (+ stream rows when teaching sections exist)

Comment rows start with `#` and are skipped on import.
