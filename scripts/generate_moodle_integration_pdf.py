"""Generate Steward ERP <-> Moodle LMS integration implementation PDF."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(r"c:\Users\HP\Desktop\Ndu Portal") / "Steward_ERP_Moodle_LMS_Integration_Guide.pdf"

BRAND = colors.HexColor("#7c1519")
DARK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#444444")
LIGHT = colors.HexColor("#f5f0f0")
BORDER = colors.HexColor("#d0c4c4")


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontSize=22,
            textColor=BRAND,
            spaceAfter=8,
            alignment=TA_CENTER,
            leading=28,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            parent=base["Normal"],
            fontSize=12,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=6,
            leading=16,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontSize=14,
            textColor=BRAND,
            spaceBefore=14,
            spaceAfter=8,
            leading=18,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontSize=11.5,
            textColor=DARK,
            spaceBefore=10,
            spaceAfter=6,
            leading=15,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontSize=9.5,
            textColor=DARK,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
            leading=13,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontSize=9.5,
            textColor=DARK,
            leading=13,
            leftIndent=4,
        ),
        "mono": ParagraphStyle(
            "mono",
            parent=base["Code"],
            fontSize=8,
            textColor=DARK,
            leading=11,
            backColor=LIGHT,
            borderPadding=4,
        ),
        "note": ParagraphStyle(
            "note",
            parent=base["Normal"],
            fontSize=9,
            textColor=BRAND,
            leading=12,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "th": ParagraphStyle(
            "th",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=colors.white,
            leading=11,
            fontName="Helvetica-Bold",
        ),
        "td": ParagraphStyle(
            "td",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=DARK,
            leading=11,
        ),
    }
    return s


def bullets(items, st):
    return ListFlowable(
        [ListItem(Paragraph(i, st["bullet"]), leftIndent=12, bulletColor=BRAND) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=15,
        spaceBefore=2,
        spaceAfter=8,
    )


def table(headers, rows, col_widths, st):
    data = [[Paragraph(h, st["th"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), st["td"]) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def add_page_number(canvas, doc):
    canvas.saveState()
    page = canvas.getPageNumber()
    canvas.setStrokeColor(BRAND)
    canvas.setLineWidth(1)
    canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1.0 * cm, "Steward ERP — Moodle LMS Integration Guide (Confidential)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm, f"Page {page}")
    canvas.restoreState()


def build():
    st = styles()
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=2.2 * cm,
        title="Steward ERP Moodle LMS Integration Guide",
        author="Steward ERP / NDU Portal Team",
    )
    story = []

    # Cover
    story.append(Spacer(1, 3.2 * cm))
    story.append(Paragraph("Steward ERP ↔ Moodle LMS", st["cover_title"]))
    story.append(Paragraph("Integration Implementation, Security &amp; Test Plan", st["cover_title"]))
    story.append(Spacer(1, 0.6 * cm))
    story.append(
        Paragraph(
            "Professional handoff document for ERP and Moodle (PHP) teams",
            st["cover_sub"],
        )
    )
    story.append(
        Paragraph(
            "Scope: Financial access control · First-year authentication · "
            "Course &amp; enrolment sync · Secure API keys · UAT checklist",
            st["cover_sub"],
        )
    )
    story.append(Spacer(1, 1.2 * cm))
    story.append(
        Paragraph(
            "<b>System of record:</b> Steward ERP (identity, fees, clearance, course registration).<br/>"
            "<b>Consumer:</b> Moodle LMS (learning access, courses, activities).<br/>"
            "<b>Architecture (Phase 1):</b> Moodle pulls Steward APIs on schedule; "
            "optional webhooks later for near real-time unlock.",
            st["body"],
        )
    )
    story.append(Spacer(1, 0.8 * cm))
    story.append(
        Paragraph(
            "<i>Classify as Confidential — Internal ICT / Bursar / Academic Affairs.</i>",
            st["note"],
        )
    )
    story.append(PageBreak())

    # 1 Objectives
    story.append(Paragraph("1. Objectives (what success looks like)", st["h1"]))
    story.append(
        Paragraph(
            "After integration, e-learning access is tied to fee compliance, first-year students "
            "can use Moodle without institutional email mailboxes, and course shells / enrolments "
            "are created from Steward data instead of manual Moodle admin work.",
            st["body"],
        )
    )
    story.append(
        table(
            ["Bursar goal", "Steward responsibility", "Moodle responsibility"],
            [
                [
                    "Fee-gated learning",
                    "Compute CLEARED / PARTIAL / BLOCKED from Accounts clearance + min tuition %",
                    "Unlock / restrict / suspend based on status",
                ],
                [
                    "First-year login without uni email",
                    "Verify reg_no + password; return profile",
                    "Custom auth plugin calls verify API; local user shell only",
                ],
                [
                    "Auto courses &amp; roles",
                    "Expose term courses, lecturers, registered students",
                    "Create courses; assign editingteacher / student",
                ],
            ],
            [5.2 * cm, 6.2 * cm, 5.5 * cm],
            st,
        )
    )

    # 2 Decisions
    story.append(Paragraph("2. Decisions to confirm before build", st["h1"]))
    story.append(
        bullets(
            [
                "<b>CLEARED</b> = Accounts registration cleared <b>and</b> current-term fee % ≥ Registration Settings minimum (recommended; same as course registration gate).",
                "<b>PARTIAL</b> policy: materials only, or treat like BLOCKED for CATs/exams? (Bursar decision.)",
                "Username convention: registration number as typed, or sanitized (e.g. slashes → underscores).",
                "Phase-1 scope: Main Campus Year 1 only, or all campuses.",
                "Sync interval: 5 / 10 / 15 minutes for finance pull.",
            ],
            st,
        )
    )

    # 3 Phases
    story.append(Paragraph("3. Implementation roadmap (ERP side)", st["h1"]))
    story.append(Paragraph("3.1 Phase 0 — Foundation (security)", st["h2"]))
    story.append(
        bullets(
            [
                "Create LMS Integration module (or package under accounts/payments) with versioned routes <font face='Courier'>/api/lms/v1/</font>.",
                "Implement <b>LmsApiKey</b> model: name, key hash, active flag, optional IP allow-list, created_at, last_used_at.",
                "Management command or admin UI: <font face='Courier'>create_lms_api_key --name moodle-prod</font> — show raw key once; store only hash.",
                "DRF permission: require header <font face='Courier'>X-API-Key</font> or <font face='Courier'>Authorization: Bearer &lt;key&gt;</font> on all LMS routes.",
                "Audit-log every LMS API call (key name, path, status, IP).",
                "Rate-limit LMS endpoints; HTTPS only in production.",
            ],
            st,
        )
    )
    story.append(Paragraph("3.2 Phase 1 — Auth verify + finance status", st["h2"]))
    story.append(
        bullets(
            [
                "<font face='Courier'>POST /api/lms/v1/auth/verify</font> — body: username (reg_no/student_id), password. Return ok, reg_no, student_id, full_name, email (personal or null), must_change_password, finance_status, cohort.",
                "Auth checks Steward student portal credentials only (reject staff/applicant).",
                "<font face='Courier'>GET /api/lms/v1/financial-status/</font> — bulk list with <b>CLEARED, PARTIAL, and BLOCKED</b> (not cleared-only). Support <font face='Courier'>updated_since</font> and pagination.",
                "<font face='Courier'>GET /api/lms/v1/financial-status/{reg_no}/</font> — single student (optional but useful).",
                "Reuse existing eligibility logic (Accounts cleared + min tuition %), do not invent a second fee formula.",
            ],
            st,
        )
    )
    story.append(Paragraph("3.3 Phase 2 — Courses &amp; enrolments", st["h2"]))
    story.append(
        bullets(
            [
                "<font face='Courier'>GET /api/lms/v1/courses/</font> — active term course units + lecturers; stable <b>idnumber</b> e.g. CODE-YEAR-YnTn.",
                "<font face='Courier'>GET /api/lms/v1/enrollments/</font> — student enrolments + lecturer teaching assignments.",
                "Source: StudentCourseUnitEnrollment + CourseUnit lecturers / section lecturers.",
            ],
            st,
        )
    )
    story.append(Paragraph("3.4 Phase 3 — Near real-time (optional)", st["h2"]))
    story.append(
        bullets(
            [
                "Moodle provides webhook URL + shared secret to ERP.",
                "On payment / Accounts clear / revoke / deregister: Celery task POSTs status change to Moodle with HMAC signature.",
                "Keep scheduled pull as safety net even if webhooks exist.",
            ],
            st,
        )
    )

    # 4 Why both APIs
    story.append(Paragraph("4. Why both auth/verify and financial-status?", st["h1"]))
    story.append(
        Paragraph(
            "<b>auth/verify</b> runs when the student logs into Moodle. It proves the password and can return "
            "the current finance_status so access can be set immediately at login.",
            st["body"],
        )
    )
    story.append(
        Paragraph(
            "<b>financial-status</b> runs on a schedule (or webhook). Fees and Accounts clearance change "
            "when the student is <i>not</i> logging in. Bulk sync updates CLEARED and BLOCKED so Moodle "
            "unlocks after payment and locks after revoke without waiting for the next login.",
            st["body"],
        )
    )
    story.append(
        Paragraph(
            "Include all statuses in bulk sync (or all changed since last sync)—not CLEARED-only—so Moodle can lock as well as unlock.",
            st["note"],
        )
    )

    # 5 Auth layman
    story.append(Paragraph("5. Authentication flow (how passwords work)", st["h1"]))
    story.append(
        bullets(
            [
                "Student enters Moodle with the same reg_no + password used on Steward ERP.",
                "Moodle does <b>not</b> store the ERP password. It calls Steward verify API every login.",
                "Steward validates against its user database and returns OK + profile.",
                "If the student changes password in Steward, the next Moodle login uses the new password automatically.",
                "Moodle may create a local user shell without a real institutional email (placeholder allowed).",
            ],
            st,
        )
    )

    # 6 Sync
    story.append(Paragraph("6. Scheduled sync vs webhook", st["h1"]))
    story.append(
        table(
            ["Approach", "Who calls whom", "When to use"],
            [
                [
                    "Scheduled pull (Celery / Moodle cron)",
                    "Moodle (or Steward job) calls Steward finance/enrol APIs every N minutes",
                    "Phase 1 default — simple and reliable",
                ],
                [
                    "Webhook push",
                    "Steward POSTs to a URL <b>provided by Moodle</b>",
                    "Phase 3 — faster unlock after pay",
                ],
            ],
            [5.5 * cm, 6.5 * cm, 4.9 * cm],
            st,
        )
    )
    story.append(
        Paragraph(
            "Webhook URL ownership: Moodle team creates the endpoint and gives the URL + secret to ERP. "
            "ERP stores it in settings and never hard-codes it in public repos.",
            st["body"],
        )
    )

    # 7 API key
    story.append(Paragraph("7. Creating and managing API keys (securely)", st["h1"]))
    story.append(
        bullets(
            [
                "Generate a long random key (32+ bytes). Display raw key once to Moodle admin.",
                "Store only a one-way hash in Steward DB (same idea as passwords).",
                "Separate keys for UAT and Production; name them clearly (moodle-uat, moodle-prod).",
                "Restrict by IP allow-list where possible (Moodle server IP).",
                "Never commit keys to Git; use server env / secrets manager.",
                "Rotate keys on staff change or suspected leak; revoke old key immediately.",
                "LMS APIs must reject student JWT for machine sync—service key only.",
            ],
            st,
        )
    )
    story.append(
        Paragraph(
            "Example (to implement): <font face='Courier'>python manage.py create_lms_api_key --name moodle-prod</font>",
            st["mono"],
        )
    )

    # 8 Endpoint contracts
    story.append(Paragraph("8. Endpoint contracts (Phase 1 handoff)", st["h1"]))
    story.append(Paragraph("8.1 POST /api/lms/v1/auth/verify", st["h2"]))
    story.append(
        Paragraph(
            "Request: <font face='Courier'>{ \"username\": \"26/2/212/I/0001\", \"password\": \"...\" }</font><br/>"
            "Response 200: ok, reg_no, student_id, full_name, email, must_change_password, finance_status, cohort.<br/>"
            "401/403: invalid credentials or not a student account.",
            st["body"],
        )
    )
    story.append(Paragraph("8.2 GET /api/lms/v1/financial-status/", st["h2"]))
    story.append(
        Paragraph(
            "Query: campus, programme, updated_since, page, page_size.<br/>"
            "Each row: reg_no, student_id, username, status (CLEARED|PARTIAL|BLOCKED), percentage_paid, "
            "accounts_cleared, academic_year, year_of_study, term_number.",
            st["body"],
        )
    )
    story.append(Paragraph("8.3 Later: /courses/ and /enrollments/", st["h2"]))
    story.append(
        Paragraph(
            "Agree course <b>idnumber</b> mapping before Phase 2. Lecturers → Moodle role editingteacher; "
            "registered students → student. Optionally enrol only if not BLOCKED, or enrol all and suspend BLOCKED.",
            st["body"],
        )
    )

    story.append(PageBreak())

    # 9 Security checklist
    story.append(Paragraph("9. Security checklist (must-pass before production)", st["h1"]))
    story.append(
        bullets(
            [
                "HTTPS only; HSTS on reverse proxy.",
                "API key required on all /api/lms/v1/* routes; no anonymous access.",
                "Auth verify rate-limited (anti password spraying).",
                "No password in logs; mask API keys in logs.",
                "Separate UAT/Prod databases and keys.",
                "Least privilege: LMS key cannot access admin ERP UI or unrelated APIs.",
                "Signed webhooks (HMAC) if push is enabled.",
                "Data minimization: return only fields Moodle needs.",
                "GDPR/personal data: treat as student PII; restrict who can download sync dumps.",
            ],
            st,
        )
    )

    # 10 Moodle tasks
    story.append(Paragraph("10. Moodle (PHP) team tasks", st["h1"]))
    story.append(
        bullets(
            [
                "Build/configure custom auth plugin calling Steward auth/verify.",
                "Store Steward base URL + API key in Moodle admin settings (encrypted if available).",
                "Cron every 10–15 minutes: pull financial-status; suspend/unsuspend or set profile field.",
                "Phase 2: course create + enrol plugin from courses/enrollments APIs.",
                "Optional: expose webhook URL for Steward push; document secret exchange.",
                "Provide UAT Moodle instance for joint testing.",
            ],
            st,
        )
    )

    # 11 Test plan
    story.append(Paragraph("11. Test plan", st["h1"]))
    story.append(Paragraph("11.1 Environment setup", st["h2"]))
    story.append(
        bullets(
            [
                "UAT Steward + UAT Moodle only.",
                "Issue moodle-uat API key; confirm rejected without key and with wrong key.",
                "Seed: Y1 student CLEARED, Y1 student BLOCKED, Y1 student PARTIAL (if used), one lecturer.",
            ],
            st,
        )
    )
    story.append(Paragraph("11.2 Auth verify tests", st["h2"]))
    story.append(
        table(
            ["#", "Case", "Expected"],
            [
                ["A1", "Valid reg_no + correct password", "200 ok=true; finance_status present"],
                ["A2", "Valid reg_no + wrong password", "401/403; no profile leak"],
                ["A3", "Staff email/password", "Reject (students only)"],
                ["A4", "Change password in Steward, login Moodle", "Old fails; new succeeds"],
                ["A5", "must_change_password=true", "Flag returned; policy agreed with Moodle"],
                ["A6", "Brute-force many bad passwords", "Rate limit / lockout behaviour"],
            ],
            [1.2 * cm, 8.5 * cm, 7.2 * cm],
            st,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("11.3 Financial status tests", st["h2"]))
    story.append(
        table(
            ["#", "Case", "Expected"],
            [
                ["F1", "Bulk pull without filter", "Includes CLEARED and BLOCKED rows"],
                ["F2", "Pay fees + Accounts clear student", "Status becomes CLEARED within sync window"],
                ["F3", "Revoke Accounts clearance", "Status leaves CLEARED; Moodle locks"],
                ["F4", "updated_since filter", "Only changed rows returned"],
                ["F5", "Single reg_no endpoint", "Matches bulk row for same student"],
                ["F6", "Call without API key", "401/403"],
            ],
            [1.2 * cm, 8.5 * cm, 7.2 * cm],
            st,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("11.4 End-to-end (joint ERP + Moodle)", st["h2"]))
    story.append(
        table(
            ["#", "Scenario", "Pass criteria"],
            [
                ["E1", "BLOCKED student opens Moodle course/CAT", "Access denied / suspended"],
                ["E2", "Same student pays &amp; cleared; wait for cron", "Access allowed without re-deploy"],
                ["E3", "CLEARED student logs in first time", "Moodle account created; courses visible per policy"],
                ["E4", "Password change in ERP mid-day", "Moodle accepts new password only"],
                ["E5", "Phase 2: registered unit appears in Moodle", "Course idnumber + student role present"],
                ["E6", "Lecturer appears as editingteacher", "Can edit course content"],
            ],
            [1.2 * cm, 8.5 * cm, 7.2 * cm],
            st,
        )
    )

    story.append(Paragraph("11.5 Performance &amp; resilience", st["h2"]))
    story.append(
        bullets(
            [
                "Bulk financial-status for expected Y1 population completes within agreed SLA (e.g. &lt; 30s).",
                "Pagination works; Moodle handles multi-page sync.",
                "Steward down: Moodle fails login gracefully (clear error, no crash).",
                "Duplicate sync runs are idempotent (no duplicate enrolments).",
            ],
            st,
        )
    )

    # 12 Acceptance
    story.append(Paragraph("12. Acceptance criteria (sign-off)", st["h1"]))
    story.append(
        bullets(
            [
                "Bursar: fee-gated access matches agreed CLEARED rule on UAT sample (≥ 20 students).",
                "ICT: API keys rotated once successfully; audit logs reviewed.",
                "Academic/e-learning: first-years log in with reg_no without institutional email.",
                "Moodle admin: cron sync documented; runbook for lock/unlock incidents.",
                "Joint UAT test sheet (Section 11) signed by ERP lead + Moodle lead.",
            ],
            st,
        )
    )

    # 13 Contact / next
    story.append(Paragraph("13. Immediate next actions (ERP)", st["h1"]))
    story.append(
        bullets(
            [
                "Confirm CLEARED / PARTIAL rules with Bursar in writing.",
                "Implement LmsApiKey + Phase 1 endpoints under /api/lms/v1/.",
                "Issue UAT key to Moodle admin; share Postman/OpenAPI collection.",
                "Run Section 11 tests; fix gaps; then production key + go-live checklist.",
            ],
            st,
        )
    )
    story.append(Spacer(1, 0.6 * cm))
    story.append(
        Paragraph(
            "Document version 1.0 · Steward ERP / NDU Application Admission Portal · "
            "For internal ICT collaboration with Moodle LMS administrators.",
            st["footer"],
        )
    )

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return OUT


if __name__ == "__main__":
    path = build()
    print(path)
