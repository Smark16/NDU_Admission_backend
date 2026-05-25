# ARMS v2 — Provisional Results & Academic Transcript (reference)

**Source folder:** `C:\Users\JOSH\Desktop\New folder (3)\Active Solution\armsv2`  
**Database:** `arms_v2` (MySQL, see `Web.config`)

This copy is mostly **Razor views + static assets**. The PDF layout is **not** in `.cshtml` files; it is produced server-side by `ResultController` actions (compiled DLL not included in this folder).

---

## Where to find it in ARMS

| Document | Controller | Action | Who sees it |
|----------|------------|--------|-------------|
| **Provisional Results** | `Result` | `PrintStudentResult` | Students (`StudentResults.cshtml` button label **“Provisional Results”**); staff **“Student Result Slip”** |
| **Academic Transcript** | `Result` | `PrintStudentTranscript` | Staff only when `Student.StudentStatus == Graduated`; graduation lists |
| Testimonial | `Result` | `PrintStudentTestimonial` | Graduated students (separate doc) |

### Key view files

```
armsv2/Views/Result/StudentResults.cshtml          → student self-service “Provisional Results”
armsv2/Views/Result/StudentProgressionResult.cshtml → staff Result Slip + Transcript (if Graduated)
armsv2/Views/Student/StudentDetails.cshtml        → download links
armsv2/Views/Graduation/GraduatedStudents.cshtml  → Transcript per graduate
```

### ARMS rule (from `StudentProgressionResult.cshtml`)

```csharp
// Transcript button only when:
Model.Student.StudentStatus == StudentStatus.Graduated
// AND role ServiceDetail.Transcript

// Provisional / result slip:
PrintStudentResult  // no graduated check on student portal
```

### Data shown on screen (same fields as PDF)

- Per semester: `Course.Code`, `Course.Name`, `CreditUnits`, `FinalMark`, `Grade`, CTCUs, GPA, CGPA  
- Student block: registration number, name, faculty, hall, DOB, nationality, first registration  
- Summary: `StudentResultSummary` — `CumulativeTotatlCreditUnits`, `GradePointAverage`, `CumulativeGradePointAverage`, `Award`, `Remark`

Partials: `_StudentSemesterResultDetail.cshtml`, `_SemesterResultDetail.cshtml`

### Graduation link

- Ceremony flag: `GraduationCeremony.showTranscriptMarks` → UI *“Student Transcripts show Marks”*  
- Maps to NDU: `GraduationCeremony.show_marks_on_transcript`

---

## NDU portal mapping (implemented)

| ARMS | NDU portal |
|------|------------|
| `PrintStudentResult` | `GET .../transcript/?format=pdf` when **not** graduated → title **Provisional Results** |
| `PrintStudentTranscript` | Same endpoint when **graduated** → title **Academic Transcript** |
| `StudentStatus.Graduated` | `programme_enrollment.status == completed` OR graduation session date passed |
| `showTranscriptMarks` | `show_marks_on_transcript` on ceremony |

Template: `examinations/templates/examinations/provisional_results.html`  
Service: `examinations/services/provisional_results_pdf.py`

---

## Getting the exact ARMS PDF layout

1. **Live ARMS:** log in → student **Semester Results** → **Provisional Results**, or staff → student → **Transcript** (if graduated).  
2. **Report files on server** (if used): `Web.config` → `DocumentsFolderPath` = `C:\inetpub\wwwroot\ARMS-v2-Resources\Documents\` (may contain `.rdlc` / report definitions — not in this repo copy).  
3. **Full C# source:** `ARMS.sln` under `New folder (3)` references `Model\`, `Services\` projects that are **not** present next to `armsv2`; ask Active Solution for the complete solution or `ResultController.cs`.

---

## PDF filename from your sample

`rms_20260523011756.pdf` — ARMS RMS print module; query string pattern typically `/Result/PrintStudentResult?studentId=...` (opens PDF in browser).
