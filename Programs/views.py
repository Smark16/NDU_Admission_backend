
from accounts.models import Campus
from .models import *
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.response import Response
from .serializers import *
from rest_framework.parsers import MultiPartParser, FormParser
from audit.utils import log_audit_event
from rest_framework.parsers import MultiPartParser, FormParser
import pandas as pd
from thefuzz import process, fuzz
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from admissions.models import Faculty, AcademicLevel
from accounts.models import Campus
from .utils.excel import create_workbook
from django.http import HttpResponse

# Create your views here.

# ====================================Programs==================================================================

# create Programs
class CreatePrograms(generics.CreateAPIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# list programs
class ListPrograms(generics.ListAPIView):
    queryset = Program.objects.select_related('faculty', 'academic_level').prefetch_related('campuses')
    serializer_class = ListProgramsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit program
class UpdateProgram(generics.UpdateAPIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
# delete program
class DeleteProgram(generics.RetrieveDestroyAPIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"program deleted sucessfully"})
    
# change status
class ChangeProgramStatus(APIView):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def patch(self, request, *args, **kwargs):
        program_id = self.kwargs['pk']
        newStatus = request.data.get('is_active')
        try:
            program = Program.objects.prefetch_related('campuses').select_related('faculty', 'academic_level').get(pk=program_id)
            program.is_active = newStatus
            program.save()

            serializer = self.serializer_class(program)
            return Response(serializer.data, status=200)
        except Exception as e:
            return Response({"detail":str(e)}, status=400)
        
# excel reports
class ExportProgramTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        headers = [
            "PROGRAM NAME *",
            "SHORT FORM",
            "PROGRAM CODE *",
            "FACULTY *",
            "ACADEMIC LEVEL *",
            "CAMPUS (comma-separated) *",
            "MIN YEARS",
            "MAX YEARS",
            "ACTIVE (TRUE/FALSE)",
        ]

        # Fetch dropdown options
        faculties = list(Faculty.objects.values_list("name", flat=True).order_by("name"))
        levels = list(AcademicLevel.objects.values_list("name", flat=True).order_by("name"))
        campuses = list(Campus.objects.values_list("name", flat=True).order_by("name"))

        # Column index (1-indexed): dropdown options
        dropdowns = {
            4: faculties,        
            5: levels,          
            6: campuses,        
            9: ["TRUE", "FALSE"],  
        }

        wb = create_workbook(
            headers=headers,
            rows=[], 
            sheet_name="Program Upload Template",
            header_bg="1E6F8A",
            dropdowns=dropdowns,
            instructions="Fill all the required fields. Use dropdowns to avoid errors.",
        )

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="program_upload_template.xlsx"'
        wb.save(response)
        return response
    
# ============================================================Bulk Upload====================================================

# === STRICT HEADER MAPPING (Exact match only) ===
HEADER_MAPPING = {
    "PROGRAM NAME *": "name",
    "SHORT FORM": "short_form",
    "PROGRAM CODE *": "code",
    "FACULTY *": "faculty",
    "ACADEMIC LEVEL *": "academic_level",
    "CAMPUS (comma-separated) *": "campuses",
    "MIN YEARS": "min_years",
    "MAX YEARS": "max_years",
    "ACTIVE (TRUE/FALSE)": "is_active",
}

REQUIRED_COLUMNS = ["name", "code", "faculty", "academic_level", "campuses"]


class HandleBulkUpload(generics.CreateAPIView):
    queryset = BulkUploadPrograms.objects.all()
    serializer_class = BulkUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        programs_to_create = []
        error_log = []
        success_count = 0

        try:
            with transaction.atomic():
                # 1. Save upload record
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                bulk_upload = serializer.save()

                file_path = bulk_upload.file_path.path
                file_name = bulk_upload.file_name

                # 2. Load file
                if file_name.lower().endswith('.xlsx'):
                    df = pd.read_excel(file_path, engine="openpyxl", skiprows=1)
                elif file_name.lower().endswith('.csv'):
                    df = pd.read_csv(file_path)
                else:
                    return Response(
                        {"error": "Only .xlsx and .csv files are allowed."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if df.empty:
                    return Response({"error": "Uploaded file is empty."}, status=status.HTTP_400_BAD_REQUEST)

                # 3. Strict header validation
                df.columns = df.columns.str.strip()
                col_map = {}
                missing_headers = []

                for template_header, standard_key in HEADER_MAPPING.items():
                    if template_header not in df.columns:
                        if standard_key in REQUIRED_COLUMNS:
                            missing_headers.append(template_header)
                    else:
                        col_map[standard_key] = template_header

                if missing_headers:
                    return Response({
                        "error": "Missing required columns",
                        "missing": missing_headers,
                        "detected": list(df.columns),
                        "tip": "Please download the latest template and use exact column names."
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Rename to standard keys
                df = df.rename(columns={v: k for k, v in col_map.items()})

                # 4. Pre-load reference data (fast lookup by name)
                faculty_map = {f.name.strip().lower(): f for f in Faculty.objects.all()}
                level_map = {al.name.strip().lower(): al for al in AcademicLevel.objects.all()}
                campus_map = {c.name.strip().lower(): c for c in Campus.objects.all()}

                # 5. Process rows
                for idx, row in df.iterrows():
                    try:
                        # Clean row values
                        row = row.astype(str).str.strip()
                        row = row.replace({"nan": None, "<NA>": None, "None": None})

                        # Required fields
                        name = row.get("name")
                        if not name or name in ("", "nan"):
                            raise ValueError("Program name is required")

                        code = row.get("code")
                        if not code or code in ("", "nan"):
                            raise ValueError("Program code is required")

                        faculty_name = row.get("faculty")
                        if not faculty_name:
                            raise ValueError("Faculty is required")
                        faculty_obj = faculty_map.get(faculty_name.strip().lower())
                        if not faculty_obj:
                            raise ValueError(f"Faculty '{faculty_name}' not found in system")

                        level_name = row.get("academic_level")
                        if not level_name:
                            raise ValueError("Academic level is required")
                        level_obj = level_map.get(level_name.strip().lower())
                        if not level_obj:
                            raise ValueError(f"Academic level '{level_name}' not found")

                        campus_input = row.get("campuses")
                        if not campus_input:
                            raise ValueError("At least one campus is required")
                        campus_names = [c.strip() for c in str(campus_input).split(",") if c.strip()]
                        if not campus_names:
                            raise ValueError("Invalid campus format")
                        campus_objs = []
                        for c_name in campus_names:
                            campus_obj = campus_map.get(c_name.lower())
                            if not campus_obj:
                                raise ValueError(f"Campus '{c_name}' not found")
                            campus_objs.append(campus_obj)

                        # Optional fields
                        short_form = row.get("short_form", "") or ""
                        min_years = row.get("min_years")
                        max_years = row.get("max_years")
                        is_active_str = row.get("is_active", "TRUE")
                        is_active = str(is_active_str).strip().upper() == "TRUE"

                        try:
                            min_years = int(min_years) if str(min_years).isdigit() else None
                            max_years = int(max_years) if str(max_years).isdigit() else None
                        except (ValueError, TypeError):
                            min_years = max_years = None

                        # Create program instance
                        program = Program(
                            name=name.strip(),
                            short_form=short_form.strip(),
                            code=code.strip(),
                            faculty=faculty_obj,
                            academic_level=level_obj,
                            min_years=min_years,
                            max_years=max_years,
                            is_active=is_active,
                        )
                        programs_to_create.append((program, campus_objs))
                        success_count += 1

                    except Exception as e:
                        error_log.append(f"Row {idx + 2}: {str(e)}")

                # 6. Remove duplicates (by name OR code)
                if programs_to_create:
                    existing_codes = set(
                        Program.objects.filter(code__in=[p.code for p, _ in programs_to_create])
                        .values_list("code", flat=True)
                    )
                    existing_names_lower = set(
                        Program.objects.filter(name__in=[p.name for p, _ in programs_to_create])
                        .values_list("name", flat=True)
                        .iterator()
                    )
                    existing_names_lower = {n.strip().lower() for n in existing_names_lower}

                    filtered = []
                    for program, campuses in programs_to_create:
                        # if program.code in existing_codes:
                        #     error_log.append(f"Row: Program code '{program.code}' already exists")
                        if program.name.strip().lower() in existing_names_lower:
                            error_log.append(f"Row: Program name '{program.name}' already exists")
                        else:
                            filtered.append((program, campuses))

                    programs_to_create = filtered
                    success_count = len(programs_to_create)

                # 7. Final check: anything to save?
                if not programs_to_create:
                    bulk_upload.status = "failed"
                    bulk_upload.error_log = "No valid programs to import (all had errors or duplicates)"
                    bulk_upload.save()
                    return Response({
                        "error": "Upload failed",
                        "details": "No new programs were imported.",
                        "errors": error_log[:50]
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 8. Bulk create
                program_objs = [p for p, _ in programs_to_create]
                Program.objects.bulk_create(program_objs, ignore_conflicts=False)

                # 9. Assign campuses via through model
                through_entries = []
                for program, campuses in programs_to_create:
                    for campus in campuses:
                        through_entries.append(
                            Program.campuses.through(program_id=program.id, campus_id=campus.id)
                        )
                if through_entries:
                    Program.campuses.through.objects.bulk_create(through_entries, ignore_conflicts=True)

                # 10. Finalize upload record
                bulk_upload.processed_records = len(df)
                bulk_upload.success_records = success_count
                bulk_upload.failed_records = len(error_log)
                bulk_upload.error_log = "\n".join(error_log) if error_log else None
                bulk_upload.status = "completed"
                bulk_upload.completed_at = timezone.now()
                bulk_upload.save()

                return Response({
                    "message": "Bulk upload completed successfully!",
                    "summary": {
                        "total": len(df),
                        "success": success_count,
                        "failed": len(error_log),
                        "errors": error_log[:20]  # limit for response size
                    },
                    "created_programs": ProgramSerializer(program_objs, many=True).data
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Ensure upload record is marked as failed
            if 'bulk_upload' in locals():
                bulk_upload.status = "failed"
                bulk_upload.error_log = str(e)
                bulk_upload.save()

            return Response({
                "error": "Server error during upload",
                "details": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)