# Examination card

Block-entry pass for students with **full outstanding balance cleared** on all tuition and fee lines.

## Student

**Student portal → Examination card** (`/student/exam-card`)

Requirements:

1. **Finance** — every billing line balance is zero (tuition structure, scheduled fees, pending ad-hoc).
2. **Academic** — at least one enrolled course with CA ≥ sit threshold (or approved retake).

Actions:

- View eligible course units and on-screen QR
- **Print / download PDF** (includes QR linking to live verification)

## QR verification (accounts at block entrance)

QR encodes: `{ERP_FRONTEND_URL}/verify-exam-card/{uuid}`

Public API (no login): `GET /api/examinations/exam-card/verify/{uuid}/`

Response includes **live** `payment.cleared`, shortfalls, eligible courses, and `may_enter_examination_block`.

Staff should always scan — do not rely on the PDF alone (balance may change after print).

## API

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/examinations/student/exam-card/` | Student |
| GET | `/api/examinations/student/exam-card/?format=pdf` | Student |
| GET | `/api/examinations/exam-card/verify/{uuid}/` | Public |

## Configuration

Set `ERP_FRONTEND_URL` in Django settings to the Horizon base URL (e.g. `https://portal.ndejjeuniversity.ac.ug`).

## Admin

`ExamCardToken` in Django admin — revoke a card if needed (`is_revoked`).
