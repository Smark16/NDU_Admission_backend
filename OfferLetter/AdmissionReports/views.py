from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import *
from admissions.models import * 
from django.db.models.functions import Coalesce
from django.db.models import Count, When, Case,F, FloatField,  Prefetch
from collections import defaultdict
from django.db import connection

from .utils.excel import create_workbook
from .utils.calculate_passes import calculate_pp_sp
from django.http import HttpResponse
from admissions.models import *
from admissions.utils.academic_year import get_current_academic_year

# Create your views here.

# general overview
class GeneralOverview(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        batches = Batch.objects.all().order_by("academic_year", "name")

        results = []

        for batch in batches:
            apps = Application.objects.filter(batch=batch).select_related('batch', 'campus', 'academic_level', 'reviewed_by').prefetch_related('programs')
            admitted_qs = AdmittedStudent.objects.filter(admitted_batch=batch).select_related('admitted_campus', 'admitted_program', 'admitted_batch', 'admitted_by', 'application__applicant')

            stats = {
                "admission_period": batch.name,  
                "academic_year": batch.academic_year, 
                "total_applications": apps.count(),
                "accepted": admitted_qs.filter(is_admitted=True).count(),
                "pending": apps.filter(status="submitted").count(),
                "rejected": apps.filter(status="rejected").count(),
                "total_admitted": admitted_qs.count(),
            }

            results.append(stats)

        return Response(results, status=200)

# Admitted students grouped by Academic Year and Admission Period
class Admitted_students_by_Faculty(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        batches = Batch.objects.all().order_by("academic_year", "name")

        final_output = []

        for batch in batches:
            faculty_stats = (
                AdmittedStudent.objects
                .filter(admitted_batch=batch, is_admitted=True)
                .values(
                    academic_year=F("admitted_batch__academic_year"),
                    admission_period=F("admitted_batch__name"),
                    faculty=F("admitted_program__faculty__name")
                )
                .annotate(admitted=Count("id"))
                .order_by("faculty")
            )

            # convert queryset → list
            faculty_list = list(faculty_stats)

            # Skip if no admissions
            if not faculty_list:
                continue

            # Prepare final batch-grouped block
            final_output.append({
                "academic_year": faculty_list[0]["academic_year"],
                "admission_period": faculty_list[0]["admission_period"],
                "faculty_data": [
                    {
                        "faculty": item["faculty"],
                        "admitted": item["admitted"]
                    }
                    for item in faculty_list
                ]
            })

        return Response(final_output, status=200)

    
# Faculty Admitted Students reports
class ViewFacultyAdmissions(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        print("QUERIES BEFORE:", len(connection.queries))

        # --------------------------------------------------------------
        # 1. ONE query – all admitted students + foreign-key objects
        # --------------------------------------------------------------
        admitted_students = list(
            AdmittedStudent.objects
            .select_related(
                "application",
                "admitted_program",
                "admitted_campus",
                "admitted_batch",
            )
            .filter(is_admitted=True)
        )

        app_ids = [adm.application_id for adm in admitted_students]
        if not app_ids:
            return Response([])

        # --------------------------------------------------------------
        # 2. ONE query – program names for every application
        # --------------------------------------------------------------
        program_data = defaultdict(list)
        for prog in (
            Program.objects
            .filter(application_programs__id__in=app_ids)
            .values("application_programs__id", "name")
            .order_by("application_programs__id")
        ):
            program_data[prog["application_programs__id"]].append(prog["name"])

        # --------------------------------------------------------------
        # 3. ONE query – O-Level results (subject code + grade)
        # --------------------------------------------------------------
        olevel_data = defaultdict(list)
        for res in (
            OLevelResult.objects
            .filter(application_id__in=app_ids)
            .select_related("subject")
            .values("application_id", "subject__code", "grade")
        ):
            olevel_data[res["application_id"]].append(
                f"{res['subject__code']}:{res['grade']}"
            )

        # --------------------------------------------------------------
        # 4. ONE query – A-Level results (subject name + grade) for PP/SP
        # --------------------------------------------------------------
        alevel_for_pp_sp = defaultdict(list)
        alevel_scores   = defaultdict(list)

        for res in (
            ALevelResult.objects
            .filter(application_id__in=app_ids)
            .select_related("subject")
            .values("application_id", "subject__code", "grade")
        ):
            app_id = res["application_id"]
            alevel_for_pp_sp[app_id].append({
                "subject_name": res["subject__code"],
                "grade": res["grade"]
            })
            alevel_scores[app_id].append(f"{res['subject__code']}:{res['grade']}")

        # --------------------------------------------------------------
        # 5. Build the response – **no more DB hits**
        # --------------------------------------------------------------
        grouped = {}

        for adm in admitted_students:
            app   = adm.application
            batch = adm.admitted_batch
            key   = f"{batch.academic_year}-{batch.name}"

            if key not in grouped:
                grouped[key] = {
                    "academic_year": batch.academic_year,
                    "admission_period": batch.name,
                    "students": [],
                }

            # ---- program choices ------------------------------------------------
            programs = program_data.get(app.id, [])
            course_applied_for = programs[0] if programs else ""
            other_choices = ", ".join(programs[1:])

            # ---- O-Level string -------------------------------------------------
            olevel_scores = "; ".join(olevel_data[app.id])

            # ---- A-Level string -------------------------------------------------
            alevel_scores_str = "; ".join(alevel_scores[app.id])

            # ---- PP / SP  (your function – receives a list of dicts) ----------
            pp, sp = calculate_pp_sp(alevel_for_pp_sp[app.id])
            principal_sub = f"{pp}PP, {sp}SP"

            # ---- final row ------------------------------------------------------
            grouped[key]["students"].append({
                "id": adm.id,
                "student_names": f"{app.first_name} {app.last_name}",
                "gender": app.gender,
                "nationality": app.nationality,
                "contact_address": app.address,
                "course_applied_for": course_applied_for,
                "other_choices": other_choices,
                "program": adm.admitted_program.name,
                "study_mode": app.study_mode,
                "campus": adm.admitted_campus.name if adm.admitted_campus else "",
                "olevel_school": app.olevel_school,
                "olevel_year": app.olevel_year,
                "olevel_index_number": app.olevel_index_number,
                "olevel_scores": olevel_scores,
                "alevel_school": app.alevel_school,
                "alevel_year": app.alevel_year,
                "alevel_index_number": app.alevel_index_number,
                "alevel_combination": app.alevel_combination,
                "alevel_scores": alevel_scores_str,
                "principal_subsidiaries": principal_sub,
                "other_qualifications": app.additional_qualification_type or "",
                "institution": app.additional_qualification_institution or "",
                "class_of_award": app.class_of_award or "",
                "course_admitted_for": adm.admitted_program.name,
                "remarks": adm.admission_notes or "",
                "payments": "NOT IMPLEMENTED",
                "admission_date": adm.admission_date.strftime("%Y-%m-%d"),
                "origin": "APPLIED ONLINE",
            })

        return Response(list(grouped.values()), status=200)
    
# excel reports
class ExportFacultyAdmissionsExcel(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # --------------------------------------------------------------
        # 1. FILTERS
        # --------------------------------------------------------------
        academic_year   = request.query_params.get("academic_year") or get_current_academic_year()
        admission_period = request.query_params.get("admission_period")
        campus_id       = request.query_params.get("campus")          # ID from UI

        # --------------------------------------------------------------
        # 2. ONE BIG QUERY + three prefetches (exactly like the JSON view)
        # --------------------------------------------------------------
        qs = (
            AdmittedStudent.objects
            .select_related(
                "application",
                "admitted_program",
                "admitted_campus",
                "admitted_batch",
            )
            .filter(is_admitted=True)
        )

        if academic_year:
            qs = qs.filter(admitted_batch__academic_year=academic_year)
        if admission_period:
            qs = qs.filter(admitted_batch__name__icontains=admission_period)
        if campus_id:
            qs = qs.filter(admitted_campus_id=campus_id)   # <-- use ID

        admitted_students = list(qs)                         # materialise
        app_ids = [adm.application_id for adm in admitted_students]

        if not app_ids:
            # empty file
            wb = create_workbook([], [], sheet_name="Faculty Admissions")
            resp = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            resp["Content-Disposition"] = 'attachment; filename="faculty_admissions.xlsx"'
            wb.save(resp)
            return resp

        # --------------------------------------------------------------
        # 3. ONE QUERY – program names
        # --------------------------------------------------------------
        program_data = defaultdict(list)
        for prog in (
            Program.objects
            .filter(application_programs__id__in=app_ids)
            .values("application_programs__id", "name")
            .order_by("application_programs__id")
        ):
            program_data[prog["application_programs__id"]].append(prog["name"])

        # --------------------------------------------------------------
        # 4. ONE QUERY – O-Level (code:grade)
        # --------------------------------------------------------------
        olevel_data = defaultdict(list)
        for res in (
            OLevelResult.objects
            .filter(application_id__in=app_ids)
            .select_related("subject")
            .values("application_id", "subject__code", "grade")
        ):
            olevel_data[res["application_id"]].append(f"{res['subject__code']}:{res['grade']}")

        # --------------------------------------------------------------
        # 5. ONE QUERY – A-Level (for scores + PP/SP)
        # --------------------------------------------------------------
        alevel_scores = defaultdict(list)   # for the "A-LEVEL SCORES" column
        alevel_for_pp = defaultdict(list)   # for calculate_pp_sp
        for res in (
            ALevelResult.objects
            .filter(application_id__in=app_ids)
            .select_related("subject")
            .values("application_id", "subject__name", "grade")
        ):
            app_id = res["application_id"]
            alevel_scores[app_id].append(f"{res['subject__name']}:{res['grade']}")
            alevel_for_pp[app_id].append({
                "subject_name": res["subject__name"],
                "grade": res["grade"],
            })

        # --------------------------------------------------------------
        # 6. BUILD EXCEL ROWS
        # --------------------------------------------------------------
        headers = [
            "ID","ACADEMIC YEAR","INTAKE","STUDENT NAMES","GENDER","NATIONALITY",
            "CONTACT/ADDRESS","COURSE APPLIED FOR","OTHER COURSE CHOICES","PROGRAM",
            "STUDY MODE","CAMPUS","O-LEVEL SCHOOL","O-LEVEL YEAR","O-LEVEL INDEX NO",
            "O-LEVEL SCORES","A-LEVEL SCHOOL","A-LEVEL YEAR","A-LEVEL INDEX NO",
            "A-LEVEL COMBINATION","A-LEVEL SCORES","PRINCIPALS/SUBSIDIARIES",
            "OTHER QUALIFICATIONS","INSTITUTION","CLASS OF AWARD",
            "COURSE ADMITTED FOR","REMARKS","PAYMENTS","DATE OF ENTRY","ORIGIN"
        ]

        rows = []

        for adm in admitted_students:
            app   = adm.application
            batch = adm.admitted_batch

            # ---- programs -------------------------------------------------
            programs = program_data.get(app.id, [])
            course_applied_for = programs[0] if programs else ""
            other_choices = ", ".join(programs[1:])

            # ---- O-Level --------------------------------------------------
            olevel_scores = "; ".join(olevel_data[app.id])

            # ---- A-Level --------------------------------------------------
            alevel_scores_str = "; ".join(alevel_scores[app.id])

            # ---- PP / SP --------------------------------------------------
            pp, sp = calculate_pp_sp(alevel_for_pp[app.id])
            principal_sub = f"{pp}PP, {sp}SP"

            # ---- other fields ---------------------------------------------
            rows.append([
                adm.id,
                batch.academic_year if batch else "",
                batch.name if batch else "",
                app.full_name,
                app.gender,
                app.nationality,
                app.address,
                course_applied_for,
                other_choices,
                adm.admitted_program.name,
                app.study_mode,
                adm.admitted_campus.name if adm.admitted_campus else "",
                app.olevel_school,
                app.olevel_year,
                app.olevel_index_number,
                olevel_scores,
                app.alevel_school,
                app.alevel_year,
                app.alevel_index_number,
                app.alevel_combination,
                alevel_scores_str,
                principal_sub,                     # ← FIXED
                app.additional_qualification_type or "",
                app.additional_qualification_institution or "",
                app.class_of_award or "",
                adm.admitted_program.name,
                adm.admission_notes or "",
                "NOT IMPLEMENTED",
                adm.admission_date.strftime("%Y-%m-%d"),
                "APPLIED ONLINE",
            ])

        # --------------------------------------------------------------
        # 7. CREATE EXCEL FILE
        # --------------------------------------------------------------
        wb = create_workbook(headers, rows, sheet_name="Faculty Admissions")

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="faculty_admissions_{academic_year}_{admission_period or "all"}.xlsx"'
        )
        wb.save(response)
        return response
        
