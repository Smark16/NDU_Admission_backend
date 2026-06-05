# Student lifecycle report (NDU Admissions portal)

**Purpose:** Plain-language map of how a person moves from applicant → admitted student → payments → registration, what can go wrong, and what to check before modules like **exams**.

**Audience:** Admissions staff, developers, and anyone planning new features.

---

## 1. The journey in six steps

| Step | Who they are | Main database record | Typical status / flag |
|------|----------------|----------------------|------------------------|
| 1 | **Applicant** | `Application` + `User` (applicant login) | `draft` → `submitted` |
| 2 | **Fee (application)** | `ApplicationPayment` | `application_fee_paid` |
| 3 | **Review** | `Application` | `accepted` or `rejected` |
| 4 | **Admitted** | `AdmittedStudent` + `Application` → `Admitted` | `is_admitted=True` |
| 5 | **Payments (after admit)** | SchoolPay, tuition, commitment | `admission_fee_paid`, tuition payments, enrollment `enrolled` |
| 6 | **Registration (courses)** | `StudentCourseUnitEnrollment` | `is_registered`, `registration_date` |

A person can be stuck at any step. **There is no single “fully done” checkbox** — reports must use the right flag for the question you are asking.

---

## 2. Two different “batches” (do not mix them up)

| Name in system | What it is | Used for |
|----------------|------------|----------|
| **Admission intake** (`admissions.Batch`) | Application window (e.g. “May 2026 intake”) | Every `Application` must have one; `AdmittedStudent.admitted_batch` |
| **Academic cohort** (`Programs.ProgramBatch`) | Year/level within a programme (e.g. “Year 1, 2025/26”) | Fees, curriculum, `StudentProgrammeEnrollment`, **exams should use this** |

**Important:** Creating a new intake later does **not** move old students. Students admitted before intakes were set up properly are still on **whatever intake batch was used at admit time** (often the first batch ever created).

---

## 3. Stage-by-stage detail

### 3.1 Application

- Applicant logs in with **email** (applicant account).
- Application is tied to **one intake batch** (required).
- Programmes: choices on the application (`programs` + `ApplicationProgramChoice` where enabled).
- **Sources:** portal, direct entry (staff), legacy import.

**Watch out**

- Same email can apply again in a **different intake** (duplicate rule is per batch).
- Application fee webhook may mark the **latest** application paid, not always the correct one if they have several.

### 3.2 Review

- Staff set status to **`accepted`** (approved for admission) or **`rejected`**.
- **`accepted` is not admission** — no student number yet, no student portal login.

**Watch out**

- Status text is not fully standardized (`Admitted` vs `admitted` vs `accepted`) — reports should normalize.

### 3.3 Admission

- Staff use **Admit** (or **Direct admission**).
- Creates **`AdmittedStudent`**: programme, intake batch, reg number, student ID, etc.
- Application status becomes **`Admitted`**.
- Background jobs (if Celery is running):
  - Send admission email
  - Create **student login** (username = **registration number**, not email)
  - Create **programme enrollment** (`StudentProgrammeEnrollment`) if an academic `ProgramBatch` exists

**Watch out**

- **Two accounts:** applicant (email) and student (reg no).
- If **no academic ProgramBatch** exists for the programme, enrollment may be **skipped** even though they are admitted.
- SchoolPay registration at admit can fail without undoing admission.

### 3.4 Payments (three tracks)

| Track | What it pays for | Where recorded |
|-------|------------------|----------------|
| Application fee | Apply online | `application_fee_paid` on `Application` |
| Admission / commitment | Confirm place | `admission_fee_paid`; may activate enrollment `enrolled` |
| Tuition | Semester fees | `StudentTuitionPayment`; used for **course registration %** |

**Watch out**

- **`is_registered_with_schoolpay`** = billing gateway — not the same as **registered for courses**.
- A student can be admitted but not have paid tuition or commitment yet.

### 3.5 Academic enrollment (programme placement)

- Record: **`StudentProgrammeEnrollment`** (one per admitted student).
- Status **`pending`** until commitment/admin activates → **`enrolled`**.
- Tied to **`ProgramBatch`** (academic cohort).

This is **required for fees and course registration** when settings demand it — not the same as “admitted” on the admissions list.

### 3.6 Course registration

- Gates: registration window open, admitted, (optional) enrollment `enrolled`, (optional) minimum tuition % paid.
- Registering for course units sets **`is_registered`** and **`registration_date`** on `AdmittedStudent`.
- **`physical_documents_verified`** is separate (desk check of paper files).

---

## 4. Revoke and remove (what happens to the student)

| Action | Admitted list | Application | Student login (reg no) | Programme enrollment |
|--------|---------------|-------------|------------------------|----------------------|
| **Revoke admission** | Row removed | Stays; `revoked`, `is_revoked=True` | User deleted | Enrollment deleted |
| **Delete admission** | Row removed | Stays; back to **`accepted`** | May remain | Enrollment deleted |

Revoked students are **not** on the admitted list but **still in the database** on the application — exclude them from exams and active cohorts.

---

## 5. Suggested rules for exams (eligibility)

Treat someone as an **exam candidate** only if **all** apply:

1. `AdmittedStudent` exists and `is_admitted=True`
2. `Application` status is not `revoked` / `rejected` / `draft`
3. `Application.is_revoked = False`
4. `StudentProgrammeEnrollment` exists with status **`enrolled`** (unless you deliberately allow `pending`)
5. `program_batch` is set and matches the exam session cohort
6. Your chosen payment rule (e.g. commitment met **or** `admission_fee_paid` — **pick one policy**)

Do **not** use only intake batch or only `is_registered` unless exams are tied to that specific step.

---

## 6. Academic years (canonical labels)

Staff maintain years at **Admissions → Academic years** (`/admin/academic-years`).

- Add labels like `2025/2026` once; batch forms use a **dropdown** (no typos).
- Mark one year as **Current** (default on new batch forms).
- **Sync from batches** imports years already used on intake or programme records.

API: `GET/POST /api/admissions/academic_years/`

---

## 7. Health checks (what to run)

On the server (or locally):

```bash
cd /home/admissions/NDU_Admission_backend
source venv/bin/activate
python manage.py audit_student_lifecycle
```

Optional:

```bash
python manage.py audit_student_lifecycle --csv reports/lifecycle_audit.csv
python manage.py audit_student_lifecycle --verbose
python manage.py audit_student_lifecycle --timetable-only
python manage.py audit_student_lifecycle --timetable-only --verbose
```

The command prints student problem buckets **and** a **Timetable readiness** block (or use `--timetable-only` for structure checks only).

---

## 11. Timetable readiness checklist (before building timetables)

Use this after admissions are flowing and before you schedule class times. Each row maps to a section in `audit_student_lifecycle` output.

| # | Prerequisite | What “good” looks like | If GAP — what to do |
|---|--------------|------------------------|---------------------|
| 1 | **Academic year registry** | At least one active year; exactly one **current**; batch labels match registry | Admissions → Academic years: **Use calendar year**, add next years; fix batch `academic_year` typos |
| 2 | **Programme batches + semesters** | Every **active** `ProgramBatch` has semesters; each semester has **year_of_study** + **term_number** | Batch management: auto-create semesters or edit semester; align Y/T with curriculum |
| 3 | **Course units for the term** | Active `CourseUnit` rows on the target semester(s); lecturers assigned where known | Pull from curriculum for that Y/T or add units manually; assign lecturers on each unit |
| 4 | **Programme enrollment** | `StudentProgrammeEnrollment` with status **`enrolled`** and `program_batch` set | Admin enrollment page; confirm commitment fee; backfill SPE for admitted students |
| 5 | **Course registration** | Enrolled students have `StudentCourseUnitEnrollment` on the units you will timetable | Student portal registration or admin registration for the term |
| 6 | **Data cleanup** | Low counts for `NO_ENROLLMENT`, `NO_ACADEMIC_BATCH`, `ENROLL_PENDING` in lifecycle audit | Fix buckets in §8; do not timetable revoked / students without cohort |

**Anchor timetables on:** `ProgramBatch` → `Semester` → `CourseUnit` — **not** on admission intake (`admissions.Batch`).

**Strict “ready for Phase 1 timetable” rule:** all five structure rows above show `[OK]` in the audit summary.

### Where to manage timetables (Phase 1 — built)

| Step | Location |
|------|----------|
| 1 | NDU-HORIZON → **Batch management** (`/admin/batch-management`) |
| 2 | Open a **programme** → expand an academic **batch** (cohort) |
| 3 | On a **semester** row, click **Timetable** |
| 4 | Add sessions: course unit, day, start/end time, venue or room |

**API (same scope):** `GET/POST /api/program/semester/<semester_id>/timetable`  
**Student view:** `GET /api/program/student/my_timetable`  
**Lecturer view:** `GET /api/program/lecturer/my_timetable`  

Run migration on server: `python manage.py migrate Programs` and `python manage.py migrate accounts`

### Classrooms & clash rules (Phase 2)

| Item | Where |
|------|--------|
| **Register rooms** | Academics → **Classrooms** (`/admin/classrooms`) — per campus |
| **Build timetable** | Batch management → semester → **Timetable** |
| **Room clash** | **Blocked** if same registered room overlaps (all programmes on that campus) |
| **Lecturer time clash** | **Blocked** if same lecturer overlaps (university-wide) |
| **Two campuses same day** | **Blocked** for lecturer unless **Allow multi-campus per day** on staff user (Django admin / user management) |

### Ndejje scheduling rules (Phase 3)

| Rule | Behaviour |
|------|-----------|
| **Delivery mode** | `on_campus`, `online`, `hybrid` on each session. **Online** skips room clash checks; published on-campus/hybrid still need a registered venue. |
| **Parallel labs** | On **Classrooms**, enable **Allow parallel lab groups** for a room. Multiple **practical** sessions may overlap in that room (split groups). |
| **Shared catalog courses** | Course units linked to the same **catalog** row (e.g. Christian Ethics under different programme codes) may share the same time/room/lecturer without clash errors. |
| **Teaching load** | Timetable dialog → **Teaching load** tab: total hours per lecturer (published by default). |
| **Week grid** | Timetable dialog → **Week grid**: Mon–Sun columns with all sessions. |
| **Variable duration** | Use free start/end times (3h, 4h blocks) — no fixed period templates required. |
| **Draft vs publish** | Use **Publish timetable** / **Unpublish timetable** in the dialog; per-slot chip **Publish slot** or **Save as draft**. Students/lecturers only see published slots. |

**Migration:** `python manage.py migrate Programs` (through `0010_timetable_ndejje_rules`).

---

## 8. Problem buckets (glossary)

| Label | Meaning | Action |
|-------|---------|--------|
| **Admitted, no enrollment** | In admitted list but no `StudentProgrammeEnrollment` | Create enrollment / check ProgramBatch exists |
| **Enrollment pending** | SPE exists but not `enrolled` | Confirm commitment fee or admin enroll |
| **No academic batch** | No `intended_program_batch` / SPE without cohort | Assign ProgramBatch, backfill |
| **Admitted but not accepted path** | Status oddities | Data cleanup |
| **Revoked** | Application flagged revoked | Exclude from exams |
| **No student login** | No `student_user` linked | Re-run account creation or fix Celery |
| **Fee paid flags mismatch** | Application vs admission vs tuition out of sync | Reconcile payments |
| **Registered for courses** | `is_registered=True` | May still lack enrollment or tuition |

---

## 9. What complicates future work

1. Multiple meanings of “registered” and “batch”.
2. Celery/SchoolPay failures leaving half-finished admission setup.
3. Early students on first intake batch without academic `ProgramBatch`.
4. Status string inconsistency in `Application.status`.
5. Revoke deletes admission row — weak history/restore story.
6. Deleting an **intake batch** cascades and **deletes all linked applications and admissions**.

---

## 10. Document history

| Date | Note |
|------|------|
| 2026-05-21 | Initial report from codebase audit (application → registration) |
| 2026-05-21 | §11 Timetable readiness checklist; audit command `--timetable-only` |
| 2026-05-20 | Phase 3 Ndejje rules: delivery mode, parallel labs, catalog clashes, teaching load |

For technical detail, see management command: `admissions/management/commands/audit_student_lifecycle.py`.
