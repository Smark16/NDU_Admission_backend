# LLB-377-Main audit findings (production)

Snapshot from `audit_batch_marks_readiness --batch "LLB-377-Main"` (server).

**Important:** three ProgramBatches share the name `LLB-377-Main`. Always use `--batch-id` from here on.

| Batch id | Cohort label | Academic year | SPE | Legacy | Registered enr | Unregistered | Results d/v/p | Windows |
|----------|--------------|---------------|-----|--------|----------------|--------------|---------------|---------|
| **259** | CLASS OF 2025-2029-AUG | 2025/2026 | 16 | **16** | 5 | 105 | **20 / 0 / 4** | 2 active but **CLOSED** now |
| **154** | CLASS OF 2026-2030-AUG | 2026/2027 | 41 | 0 | 49 | 238 | 0 / 0 / 0 | none |
| **262** | 2025/2027 | 2025/2026 | 1 | 0 | 0 | 7 | 0 / 0 / 0 | none |

## Interpretation

### Batch #259 — legacy continuing cohort (where test marks live)

- All 16 SPE students are **legacy imports**.
- Test marks entered late July 2026 by **ALLAN WALUSIMBI** (20 drafts) and **SSENYANGE JOSHUA** (4 published).
- All 24 results sit on **unregistered** enrollments (`registration_date` missing) — rules were not enforced at entry time (or office override).
- Activity is on **Year 1 Semester 1** papers (LLB1101–1107) plus some Y2S1 enrollments (16 students on LLB2101–2105, almost all unregistered).
- Batch-level windows exist (`#1`, `#2`) but resolve as **CLOSED** right now (date range / inactive effect). Names mention Y1S2 / “august 2028” — not aligned with Y1S1 test entry.

### Batch #154 — larger portal Year-1 intake

- 41 portal SPE (4 revoked). No results yet.
- Y1S1 fully enrolled (~41 per paper) but only **~7 registered** per paper → roster will look empty to lecturers until registration is stamped or students register.
- No marks windows. Several Y1S1 papers still missing lecturers.

### Batch #262 — tiny / misc

- Single portal student, Y1S1 enrollments unregistered, no marks, no windows. Ignore until Faculty confirms it is a real cohort.

## Policy / scale

OK on all courses (defaults resolve).

## Recommended way forward

1. **Clean #259 test marks** — clear drafts now; confirm with Law whether the **4 published** rows are real or also test.
2. **Do not bulk-stamp registration** across all 238/#154 or 105/#259 rows until Faculty names the semester they will mark first (likely Y1S1 or Y2S1 for #259).
3. **Open a semester-scoped window** for that semester on the chosen batch(es).
4. **Assign lecturers** on papers with enrollments.
5. Pilot one paper → verify → publish, then continue.

## Server commands (next)

```bash
# Re-audit one cohort only
python manage.py audit_batch_marks_readiness --batch-id 259

# Clear draft/verified test marks on legacy cohort
python manage.py clear_batch_test_marks --batch-id 259 --dry-run
python manage.py clear_batch_test_marks --batch-id 259

# Only if Faculty confirms the 4 published rows are also test:
python manage.py clear_batch_test_marks --batch-id 259 \
  --include-published --i-understand-published --dry-run
```
