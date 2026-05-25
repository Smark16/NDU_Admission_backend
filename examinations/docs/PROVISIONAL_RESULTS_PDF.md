# Provisional Results / Academic Transcript PDF

Single ARMS-style layout; the **title and footer** change automatically:

| Status | PDF title | Signatory | Filename |
|--------|-----------|-----------|----------|
| Not graduated | **Provisional Results** | Faculty Examination Coordinator | `Provisional_Results_{reg}.pdf` |
| Graduated | **Academic Transcript** | Academic Registrar | `Academic_Transcript_{reg}.pdf` |

## Graduation detection

A student is treated as **graduated** when either:

1. `StudentProgrammeEnrollment.status` is `completed`, or  
2. They have a `GraduationAssignment` on a session whose `graduation_date` is on or before today.

Until then, students download **Provisional Results** only.

## Reference

- Layout sample: `examinations/docs/templates/provisional_results_reference.pdf`

## API

| Who | Endpoint | Query |
|-----|----------|-------|
| Student | `GET /api/examinations/student/transcript/?format=pdf` | Optional `show_scores=0` |
| Staff | `GET /api/examinations/students/{id}/transcript/?format=pdf` | Same |

JSON transcript includes `document: { kind, title, is_graduated, filename_prefix }`.

If `show_scores` is omitted on PDF, the latest graduation ceremony’s `show_marks_on_transcript` flag applies.

## Logo

Place `Ndejje_University_Logo.png` in `NDU_Admission_Frontend/public/` (same as applicant profile PDF) for the crest on the printout.
