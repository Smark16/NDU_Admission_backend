# Portal Results ↔ ARMS menu map

Use this so staff trained on ARMS know where to click.

| ARMS (legacy) | NDU portal | What you do |
|---------------|------------|-------------|
| **Results → Progression** | Admin **Exams → Marks** (or Lecturer **Enter scores**) | Enter **CA /40** and **Exam /100** per course; columns **Total**, **GP**, **Remark**. Legacy URL `/admin/examinations/progression` redirects here. |
| **Results → Publish** | Admin **Results → Publish** | Release marks so students see them |
| **Results → Import** | Admin **Results → Import** | Excel: `reg_no`, `ca_mark`, `exam_mark` |
| **Results → Changes** | Admin **Results → Changes** | Approve edits after publish |
| **Student → Results** | Student **Results** | Published marks only |

**Scoring (same as ARMS):** CA /40, Exam /100, Total = CA + 0.6×exam, sit if CA ≥ 17.5, pass ≥ 50.

**Not in portal UI (ARMS had these separately):** Academic Board, CGPA formula editor, Purge uploads — use Django admin or a later phase if needed.

**Backend extras (hidden from menu):** exam timetable, sitting list, retakes, verify step — APIs exist but are not the main ARMS-style path.
