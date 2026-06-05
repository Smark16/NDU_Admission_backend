# Examinations module plan (standalone)

**Status:** Phases 1–4 implemented (marks, timetable, verify/publish, import, transcript, grade changes).  
**Not nested under:** `admissions`, `Programs`, or any other app.  
**Integrates via foreign keys only** to shared entities (`AdmittedStudent`, `CourseUnit`, `Semester`, `ProgramBatch`, `StudentCourseUnitEnrollment`).

---

## 1. Why a separate app

| Principle | Detail |
|-----------|--------|
| **Ownership** | Senate/registrar exam policy, marks entry, publication, retakes — distinct from admissions or curriculum admin |
| **API surface** | `/api/examinations/...` — same pattern as `/api/payments/`, `/api/program/` |
| **Horizon** | Lecturer **Enter scores**, student **Results** — already placeholder pages waiting for this service |
| **Legacy** | ARMS v2 MySQL + `armsv2/Views/Result` — see `RESULT_LEGACY_ARMS.md`; curriculum import stays in `Programs/legacy_arms` |

---

## 2. Legacy system (ARMS v2)

What exists in this repo today:

| Area | Location | Scope |
|------|----------|--------|
| MySQL connection | `Programs/legacy_arms/connection.py` | Env: `ARMS_MYSQL_*`, default DB `arms_v2` |
| Curriculum SQL | `Programs/legacy_arms/curriculum_queries.py` | `program_core`, `course`, campus programmes |
| Audit command | `Programs/management/commands/audit_arms_curriculum.py` | Import/compare curricula only |

**Exams in ARMS are not yet mapped in code.** To discover real table names on your server:

```powershell
cd NDU_Admission_backend
python manage.py inspect_arms_exams --password "<ARMS password>"
python manage.py inspect_arms_exams --password "<ARMS password>" --json-out arms_exam_tables.json
```

Optional: `--host`, `--user`, `--database`, `--all-tables`.

After the first run, document the matched tables in §8 below and add `examinations/legacy_arms/exam_queries.py` (read-only) plus an import command if you migrate historical marks.

**Note:** If production exams live in a **different** database or product (not `arms_v2`), tell the team the connection string/name so we add a second legacy connector — the portal code does not assume ARMS is the only legacy source.

---

## 3. Ndejje assessment rules (policy engine) — **agreed**

**Entry model (matches legacy ARMS UI):** lecturers enter **one CA total** (combined test + coursework), not two separate fields.

| What | Weight (of final 100) | Lecturer enters | Max |
|------|------------------------|-----------------|-----|
| **Continuous assessment (CA)** | 40% (internally 20% test + 20% coursework) | **Single CA mark** | **/40** |
| **Exam** | 60% | Exam mark | **/100** |

**Policy note:** Test and coursework are **not** separate columns in the portal. Senate policy is still 20% + 20%; the lecturer submits the **combined** score out of 40 once.

### Formulas (default)

```
ca_mark           = lecturer entry (0–40)
exam_mark         = lecturer entry (0–100), only if eligible
exam_eligible     = ca_mark >= 17.5
final_mark        = ca_mark + (exam_mark × 0.60)   // max 100
pass              = final_mark >= 50
letter_grade      = lookup(final_mark, GradeScale)
```

**Exam eligibility:** if `ca_mark < 17.5` → **cannot sit exam** (exam field disabled; no exam mark saved).

**Pass:** `final_mark ≥ 50` → pass; else fail / retake.

**Letter grade:** from configurable `GradeScale` (Senate-approved bands).

**Senate sign-off (optional):** minimum **exam paper** mark (e.g. 18/60 on the exam component) if required.

**NCHE context:** Same 40/60 display as legacy ARMS; aligns with `ContinousAssessment` + `ExamMark` on `student_course`.

---

## 4. Borrow from other ERPs (workflows only)

| System | Borrow |
|--------|--------|
| **OpenEduCat** | Exam session, hall ticket, multi-component marksheet, validate → publish |
| **Fedena** | Gradebook draft → submit → lock/unlock per class |
| **ERPNext** | Assessment plan (schedule), criteria weights, bulk result tool |
| **ARMS Semester** | Grading scheme, pass marks, award classification, semester deadlines — see `SEMESTER_LEGACY_ARMS.md` |

Implementation stays in `examinations` — no fork of those products.

---

## 5. Target data model (Phase 1 sketch)

```
AssessmentPolicy          # weights, CA sit threshold, pass mark, effective dates
GradeScale / GradeBand    # letter ↔ numeric ranges
CourseUnitAssessment      # per enrollment: ca (0–40), exam (0–100) — not separate test/cw fields
CourseUnitResult          # computed final, letter, pass/fail, exam_sitting_allowed
ResultPublication         # semester/batch lock + published_at (students see after publish)
```

**Links (FKs, not nested apps):**

- `StudentCourseUnitEnrollment` (`Programs`) — one result row per enrollment per policy period
- `CourseUnit`, `Semester`, `ProgramBatch` — scope and reporting
- `admissions.AdmittedStudent` / `accounts.User` — student identity
- Revoked students — exclude from sitting (see lifecycle report §8)

**Do not** store final marks only on `StudentCourseUnitEnrollment.grade` without the examinations module — that field remains a display cache updated when results are **published**.

---

## 6. API & UI phases

| Phase | Backend | Horizon |
|-------|---------|---------|
| **1** | Policy + grade scale CRUD; enter marks (lecturer); compute + eligibility; student read own published results | Wire `Lecturer/EnterScores`, `Student/Results` |
| **2** | Exam timetable / sitting list; block ineligible; retake registration | Admin tabs: schedule, sitting, retakes; student exam timetable |
| **3** | Publish workflow (draft → verified → published); transcripts; ARMS import | Reports, PDF transcript |
| **4** | Retakes, supps, grade change audit | Appeals / admin unlock |
| **5+** | **Graduation** (separate; see `GRADUATION_LEGACY_ARMS.md`) | Ceremonies, qualified lists, transcripts — **after** publish + CGPA |

Permissions (seed via `python manage.py seed_examination_manager_role` or migration `0005`):

| Group | Permissions |
|-------|-------------|
| **Examination Manager** | All examinations permissions (full office) |
| **Examination Marks Officer** | `access_examinations`, `enter_marks`, `view_all_results` |
| **Examination Results Publisher** | `access_examinations`, `publish_results`, `view_all_results` |
| **Examination Timetable Officer** | `access_examinations`, `manage_exam_schedule`, `view_all_results` |
| **Examination Retakes Officer** | `access_examinations`, `manage_retakes`, `view_all_results` |
| **Examination Grade Reviewer** | `access_examinations`, `approve_result_changes`, `view_all_results` |

**Graduation (legacy ARMS):** Not part of mark entry. Uses `currentCGPA`, `currentCTCU`, ceremony/day assignment, qualified lists, and transcript print. Full UI map: `examinations/docs/GRADUATION_LEGACY_ARMS.md`.

---

## 7. Batch / cohort scoping (scale)

Ndejje runs on **`ProgramBatch`** (intake cohort), not a flat student list.

| Layer | Behaviour |
|-------|-----------|
| **Data** | Each `CourseUnit` links to `program_batch` and/or `semester`; enrollments are per student × course. |
| **API** | `GET /api/examinations/staff/courses/?program_batch_id=&semester_id=&program_id=` filters the course list. |
| **Bulk ops** | `bulk-publish` and `reports/summary` accept `program_batch_id` and `semester_id`. |
| **Horizon** | **Cohort bar** on all Exams pages: Programme → Batch → Semester (optional). Selection is stored in `sessionStorage` while navigating tabs. |
| **Workflow** | Exams office should **always pick a batch** before marks, sitting lists, or publish — same pattern as Academic Enrollment. |

---

## 8. Integration points (existing code)

| Existing | Role |
|----------|------|
| `Programs.StudentCourseUnitEnrollment` | Who is registered for which unit |
| `Programs.course_enrollment_views` | Explicitly defers GPA/grades to examinations phase |
| `payments` fee head `exam` | Exam fees — link payment cleared → `exam_sitting_allowed` override if policy requires fee |
| `admissions/docs/STUDENT_LIFECYCLE_REPORT.md` | Revoked / not enrolled → no exam |
| Horizon routes | Already routed; placeholders mention “examinations service” |

---

## 8. ARMS exam schema (fill after inspect)

Run `inspect_arms_exams` on production/staging ARMS and record findings here:

| ARMS table | Purpose | Portal mapping |
|------------|---------|----------------|
| _TBD_ | | `CourseUnitAssessment` / `CourseUnitResult` |

Sample row mapping and id strategy (ARMS student id ↔ portal `AdmittedStudent`) to be decided after schema review.

---

## 9. Registration checklist

- [x] Django app `examinations` in `LOCAL_APPS`
- [x] URL prefix `api/examinations/`
- [x] Migrations for Phase 1 models
- [ ] `inspect_arms_exams` run against live ARMS
- [x] Senate-approved policy JSON seeded (`seed_examination_defaults`)
- [x] Horizon Enter scores / Results connected
- [x] **Examination Manager** + lighter office roles seeded (`0004`, `0005`, `seed_examination_manager_role`)

---

## 10. Document history

| Date | Note |
|------|------|
| 2026-05-20 | Initial plan; standalone app scaffold; ARMS inspect command |
| 2026-05-20 | Policy locked: CA /40 (combined 20+20), exam /100, formulas in §3 |
