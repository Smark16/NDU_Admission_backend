from rest_framework import generics, status
from .serializers import *
from .models import *
from accounts.models import Campus
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from .tasks import queue_staff_login_provision
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import HttpResponse
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import PermissionDenied
from .utils.excel import create_workbook
import pandas as pd
from .utils.staff_no import generate_number
from .utils.string_matching import get_fuzzy_matches
from .utils.profile_sync import resolve_staff_profile_for_user
from collections import defaultdict
#====================================================staff profile views====================================================

# create staff profile
class CreateStaffProfileView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.select_related("application")
    serializer_class = StaffProfileSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        staff = serializer.save()

        # Handle job application update
        if staff.application:
            application = staff.application  # no extra DB query
            application.is_staff = True
            application.save(update_fields=["is_staff"])

        # Create ERP login in background after commit (auto Changeme#### password).
        if staff.system_login:
            queue_staff_login_provision(staff.id)

# edit staff profile
class UpdateStaffProfileView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.all()
    serializer_class = StaffProfileSerializer

    @transaction.atomic
    def perform_update(self, serializer):
        staff = serializer.save()
        if staff.system_login and staff.user is None:
            queue_staff_login_provision(staff.id)
    
# delete staff profile
class DeleteStaffProfileView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.all()
    serializer_class = StaffProfileSerializer

    def delete(self, request, *args, **kwargs):
        staff_profile = self.get_object()
        staff_profile.delete()
        return Response({"detail":"Staff profile deleted successfully"}, status=204)
    
# list staff profiles
class StaffProfileListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.select_related('user','org_unit')
    serializer_class = AllStaffSerializer

    def get(self, request):
        user = request.user
        if not user.has_perm('staff.view_staffprofile'):
            return Response({"detail":"You do not have permission to view staff profiles."}, status=403)
        
        staff = self.get_queryset()
        serializer = self.get_serializer(staff, many=True)
        return Response(serializer.data, status=200)

# staff detail view
class StaffProfileDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.select_related(
        'team', 'org_unit', 'staff_type', 'position_level', 'pay_scale', 'user'
        ).prefetch_related('campus', 'managed_org_units')
    serializer_class = DetailStaffSerializer
    lookup_field = "id"
    lookup_url_kwarg = "staff_id"

# mini staff profile
class MiniStaffProfile(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffProfile.objects.select_related(
        'team', 'org_unit', 'staff_type', 'position_level', 'pay_scale', 'user'
        )
    serializer_class = MiniStaffSerializer
    lookup_field = 'user'
    lookup_url_kwarg = 'user_id'

#=========================================================departmental views=========================================================

#create departments
class CreateDepartmentView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

# edit departments
class UpdateDepartmentView(generics.UpdateAPIView):  
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

    def put(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    
# delete departments
class DeleteDepartmentView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

    def delete(self, request, *args, **kwargs):
        department = self.get_object()
        department.delete()
        return Response({"detail":"Department deleted successfully"}, status=204)
    
# list departments and teams
class DepartmentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ListDepartmentSerializer

    def get_queryset(self):
        user = self.request.user

        if not user.has_perm("staff.view_department"):
            raise PermissionDenied("You do not have permission to view departments.")

        return (
            Department.objects
            .prefetch_related("teams", "teams__members")
            .all()
        )
# list departments only
class ListDepartments(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

#============================================================units==================================================

# list units
class ListUnits(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffType.objects.all()
    serializer_class = UnitTypeSerializer

# create units
class CreateUnit(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffType.objects.all()
    serializer_class = UnitTypeSerializer

# update units
class UpdateUnit(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffType.objects.all()
    serializer_class = UnitTypeSerializer

# delete units
class DeleteUnit(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = StaffType.objects.all()
    serializer_class = UnitTypeSerializer

# ===============================================positon levels=============================================

# list levels
class ListLevels(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PositonLevel.objects.all()
    serializer_class = PositionLevelSerializer

# create levels
class CreateLevels(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PositonLevel.objects.all()
    serializer_class = PositionLevelSerializer

# update levels
class UpdateLevels(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PositonLevel.objects.all()
    serializer_class = PositionLevelSerializer

# delete levels
class DeleteLevel(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PositonLevel.objects.all()
    serializer_class = PositionLevelSerializer

# ===============================================pay scales (Ugandan U/P grades)================================

class ListPayScales(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PayScale.objects.filter(is_active=True)
    serializer_class = PayScaleSerializer

    def get_queryset(self):
        qs = PayScale.objects.all().order_by("rank_order", "code")
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category__iexact=category)
        active = self.request.query_params.get("active")
        if active is not None and active.lower() == "all":
            return qs
        if active is not None and active.lower() in ("0", "false", "no"):
            return qs.filter(is_active=False)
        return qs.filter(is_active=True)


class CreatePayScale(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PayScale.objects.all()
    serializer_class = PayScaleSerializer


class UpdatePayScale(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PayScale.objects.all()
    serializer_class = PayScaleSerializer


class DeletePayScale(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = PayScale.objects.all()
    serializer_class = PayScaleSerializer

# ==========================================================teams========================================

# list teams
class ListTeams(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = DepartmentTeams.objects.select_related('department')
    serializer_class = DepartmentTeamsSerializer

# create teams
class CreateTeam(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = DepartmentTeams.objects.all()
    serializer_class = DepartmentTeamsSerializer

# update teams
class UpdateTeam(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = DepartmentTeams.objects.all()
    serializer_class = DepartmentTeamsSerializer

# delete teams
class DeleteTeam(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = DepartmentTeams.objects.all()
    serializer_class = DepartmentTeamsSerializer

# ==============================staff list==========================

class SupervisorStaffListView(generics.ListAPIView):
    serializer_class = StaffProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        supervisor = get_object_or_404(
            StaffProfile.objects.only("id"),
            user=self.request.user
        )

        return (
            StaffProfile.objects
            .select_related("user", "team", "org_unit")
            .prefetch_related("managed_org_units", "campus")
            .filter(
                Q(assigned_supervisors__supervisor=supervisor) |
                Q(team__asigned_teams__supervisor=supervisor)
            )
            .exclude(id=supervisor.id)
            .distinct()
        )

# sample staff csv
class ExportSampleCSV(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        
        headers = [
            "FIRST NAME *",
            "LAST NAME *",
            "PERSONAL EMAIL",
            "UNIVERSITY EMAIL *",
            "FACULTY/DEPARTMENT *",
            "UNIT/TEAM",
            "JOB TITLE *",
            "NSSF NO",
            "TIN NO",
            "STAFF TYPE *",
            "POSITION LEVEL *",
            "SUPERVISOR (TRUE/FALSE) *",
            "UNITS SUPERVISED (comma-separated)",
            "STAFF SUPERVISED (comma-separated)",
            "HR (TRUE/FALSE) *",
            "DIRECTOR (TRUE/FALSE) *",
            "MANAGED DEPARTMENTS (comma-separated)",
            "CAMPUS (comma-separated) *",
        ]

        # Fetch dropdown options
        departments = list(Department.objects.values_list("name", flat=True).order_by("name"))
        staff_type = list(StaffType.objects.values_list("name", flat=True).order_by("name"))
        position_level = list(PositonLevel.objects.values_list("name", flat=True).order_by("name"))
        teams = list(DepartmentTeams.objects.values_list("team_name", flat=True).order_by("team_name"))
        campuses = list(Campus.objects.values_list("name", flat=True).order_by("name"))

        # Column index (1-indexed): dropdown options
        dropdowns = {
            5: departments,        
            6: teams,   
            10: staff_type,  
            11: position_level,  
            12: ["TRUE", "FALSE"],       
            13:teams, 
            15: ["TRUE", "FALSE"],
            16: ["TRUE", "FALSE"],
            17: departments,        
            18: campuses,  
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
        response["Content-Disposition"] = 'attachment; filename="staff_upload_template.xlsx"'
        wb.save(response)
        return response
    
# upload staff
# === STRICT HEADER MAPPING (Exact match only) ===
HEADER_MAPPING = {
    "FIRST NAME *": "first_name",
    "LAST NAME *": "last_name",
    "PERSONAL EMAIL": "personal_email",
    "UNIVERSITY EMAIL *": "university_email",
    "FACULTY/DEPARTMENT *": "org_unit",
    "UNIT/TEAM": "team",
    "JOB TITLE *": "job_title",
    "NSSF NO": "nssf_no",
    "TIN NO": "tin_no",
    "STAFF TYPE *": "staff_type",
    "POSITION LEVEL *": "position_level",
    "SUPERVISOR (TRUE/FALSE) *": "is_supervisor",
    "HR (TRUE/FALSE) *": "is_hr",
    "DIRECTOR (TRUE/FALSE) *": "is_director",
    "MANAGED DEPARTMENTS (comma-separated)": "managed_org_units",
    "CAMPUS (comma-separated) *": "campus",

    # handled separately
    "UNITS SUPERVISED (comma-separated)": "supervised_teams",
    "STAFF SUPERVISED (comma-separated)": "supervised_staff",
}

REQUIRED_COLUMNS = ["first_name", "last_name", "personal_email","university_email","org_unit","job_title",
            "staff_type","position_level", "is_supervisor", "is_hr", "is_director", "campus"]

# class HandleBulkStaffUpload(generics.CreateAPIView):
#     serializer_class = BulkUploadSerializer
#     permission_classes = [IsAuthenticated]
#     parser_classes = [MultiPartParser, FormParser]

#     def create(self, request, *args, **kwargs):
#         staff_to_create, campus_links, managed_dept_links = [], [], []
#         supervision_assignments, error_log = [], []

#         try:
#             with transaction.atomic():
#                 serializer = self.get_serializer(data=request.data)
#                 serializer.is_valid(raise_exception=True)
#                 bulk_upload = serializer.save()

#                 # Load file logic
#                 file_path = bulk_upload.file_path.path
#                 if bulk_upload.file_name.lower().endswith(".xlsx"):
#                     df = pd.read_excel(file_path, engine="openpyxl", skiprows=1)
#                 else:
#                     df = pd.read_csv(file_path)

#                 if df.empty:
#                     return Response({"error": "Uploaded file is empty."}, status=400)

#                 # Header mapping and renaming
#                 df.columns = df.columns.str.strip()
#                 df = df.rename(columns={v: k for k, v in HEADER_MAPPING.items() if v in df.columns})

#                 # --- PRE-LOADING DATA MAPS ---
#                 # We build these once to avoid repeated DB hits or attribute errors
#                 dept_map = {d.name.lower(): d for d in Department.objects.all()}
#                 campus_map = {c.name.lower(): c for c in Campus.objects.all()}
#                 staff_type_map = {s.name.lower(): s for s in StaffType.objects.all()}
#                 position_map = {p.name.lower(): p for p in PositonLevel.objects.all()}
#                 team_map = {t.team_name.lower(): t for t in DepartmentTeams.objects.all()}
                
#                 staff_by_email = {}

#                 # 1️⃣ Create StaffProfile objects
#                 for idx, row in df.iterrows():
#                     try:
#                         row = row.astype(str).str.strip().replace({"nan": None})
                        
#                         # Fuzzy match for org_unit (Single value)
#                         matched_depts = get_fuzzy_matches_from_map(row["org_unit"], dept_map)
#                         dept = matched_depts[0] if matched_depts else None
#                         if not dept:
#                             raise ValueError(f"Department '{row['org_unit']}' not found")

#                         # Team (Optional)
#                         team = None
#                         if row.get("team"):
#                             matched_teams = get_fuzzy_matches_from_map(row["team"], team_map)
#                             team = matched_teams[0] if matched_teams else None

#                         staff = StaffProfile(
#                             staff_no=generate_number(),
#                             first_name=row["first_name"],
#                             last_name=row["last_name"],
#                             university_email=row["university_email"].lower(),
#                             personal_email=row.get("personal_email"),
#                             staff_type=staff_type_map.get(row["staff_type"].lower()),
#                             position_level=position_map.get(row["position_level"].lower()),
#                             is_supervisor=str(row.get("is_supervisor")).upper() == "TRUE",
#                             is_hr=str(row.get("is_hr")).upper() == "TRUE",
#                             is_director=str(row.get("is_director")).upper() == "TRUE",
#                             job_title=row["job_title"],
#                             org_unit=dept,
#                             team=team,
#                         )
#                         staff_to_create.append(staff)
#                         staff_by_email[staff.university_email] = staff

#                     except Exception as e:
#                         error_log.append(f"Row {idx+2}: {e}")

#                 # Save staff first so they have IDs for M2M
#                 StaffProfile.objects.bulk_create(staff_to_create)

#                 # 2️⃣ Reload staff IDs for M2M
#                 staff_db_map = {
#                     s.university_email.lower(): s 
#                     for s in StaffProfile.objects.filter(university_email__in=staff_by_email.keys())
#                 }

#                 # 3️⃣ M2M + Supervision
#                 for idx, row in df.iterrows():
#                     try:
#                         email = str(row.get("university_email", "")).lower()
#                         staff = staff_db_map.get(email)
#                         if not staff: continue

#                         # Campus M2M (Fuzzy)
#                         for campus in get_fuzzy_matches_from_map(row.get("campus", ""), campus_map):
#                             campus_links.append(StaffProfile.campus.through(staffprofile_id=staff.id, campus_id=campus.id))

#                         # Managed Depts M2M (Fuzzy)
#                         for m_dept in get_fuzzy_matches_from_map(row.get("managed_org_units", ""), dept_map):
#                             managed_dept_links.append(StaffProfile.managed_org_units.through(staffprofile_id=staff.id, department_id=m_dept.id))

#                         # Supervision
#                         if staff.is_supervisor:
#                             # Teams (Fuzzy)
#                             for s_team in get_fuzzy_matches_from_map(row.get("supervised_teams", ""), team_map):
#                                 supervision_assignments.append(SupervisionAssignment(supervisor=staff, team=s_team))
                            
#                             # Staff (Strict Email Match - No fuzzy here for safety)
#                             s_staff_val = str(row.get("supervised_staff") or "")
#                             if s_staff_val:
#                                 email_list = [e.strip().lower() for e in s_staff_val.split(",") if e.strip()]
#                                 for s_email in email_list:
#                                     member = staff_db_map.get(s_email)
#                                     if member:
#                                         supervision_assignments.append(SupervisionAssignment(supervisor=staff, staff_member=member))

#                     except Exception as e:
#                         error_log.append(f"Row {idx+2} M2M: {e}")

#                 # 4️⃣ Final Bulk Operations
#                 StaffProfile.campus.through.objects.bulk_create(campus_links, ignore_conflicts=True)
#                 StaffProfile.managed_org_units.through.objects.bulk_create(managed_dept_links, ignore_conflicts=True)
#                 SupervisionAssignment.objects.bulk_create(supervision_assignments)

#                 # Update status
#                 bulk_upload.status = "completed"
#                 bulk_upload.success_records = len(staff_to_create)
#                 bulk_upload.failed_records = len(error_log)
#                 bulk_upload.error_log = "\n".join(error_log) if error_log else None
#                 bulk_upload.save()

#                 return Response({
#                     "message": "Staff bulk upload completed",
#                     "created": len(staff_to_create),
#                     "errors": error_log[:20]
#                 }, status=201)

#         except Exception as e:
#             return Response({"detail": str(e)}, status=500)
               
class HandleBulkStaffUpload(generics.CreateAPIView):
    serializer_class = BulkUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        staff_to_create = []
        campus_links = []
        managed_dept_links = []
        supervision_assignments = []
        error_log = []

        try:
            with transaction.atomic():

                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                bulk_upload = serializer.save()

                file_path = bulk_upload.file_path.path
                file_name = bulk_upload.file_name

                # Load file
                if file_name.lower().endswith(".xlsx"):
                    df = pd.read_excel(file_path, engine="openpyxl", skiprows=1)
                elif file_name.lower().endswith(".csv"):
                    df = pd.read_csv(file_path)
                else:
                    return Response({"error": "Only CSV or XLSX allowed"}, status=400)

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

                # Preload references
                dept_map = {d.name.lower(): d for d in Department.objects.all()}
                team_map = {t.team_name.lower(): t for t in DepartmentTeams.objects.all()}
                campus_map = {c.name.lower(): c for c in Campus.objects.all()}
                staff_type_map = {s.name.lower(): s for s in StaffType.objects.all()}
                position_map = {p.name.lower(): p for p in PositonLevel.objects.all()}
                staff_by_email = {}

                # 1️⃣ Create StaffProfile objects
                for idx, row in df.iterrows():
                    try:
                        row = row.astype(str).str.strip().replace({"nan": None})

                        dept = dept_map.get(row["org_unit"].lower())
                        if not dept:
                            raise ValueError(f"Department '{row['org_unit']}' not found")

                        team = None
                        if row.get("team"):
                            team = team_map.get(row["team"].lower())
                            if not team:
                                raise ValueError(f"Team '{row['team']}' not found")
                            
                        staff_type = staff_type_map.get(row["staff_type"].lower())
                        if not staff_type:
                            raise ValueError(f"Staff type '{row['staff_type']} not found")
                        
                        position = position_map.get(row["position_level"].lower())
                        if not position:
                            raise ValueError(f"Position '{row['position_level']} not found")

                        staff = StaffProfile(
                            staff_no=generate_number(),
                            first_name=row["first_name"],
                            last_name=row["last_name"],
                            personal_email=row.get("personal_email"),
                            university_email=row["university_email"],
                            staff_type=staff_type,
                            position_level=position,
                            is_supervisor=str(row.get("is_supervisor") or "").upper() == "TRUE",
                            is_hr=str(row.get("is_hr") or "").upper() == "TRUE",
                            is_director=str(row.get("is_director") or "").upper() == "TRUE",
                            job_title=row["job_title"],
                            nssf_no=row.get("nssf_no"),
                            tin_no=row.get("tin_no"),
                            org_unit=dept,
                            team=team,
                        )

                        staff_to_create.append(staff)
                        staff_by_email[row["university_email"].lower()] = staff

                    except Exception as e:
                        error_log.append(f"Row {idx+2}: {e}")

                StaffProfile.objects.bulk_create(staff_to_create)

                # 2️⃣ Reload staff IDs
                staff_db_map = {
                    s.university_email.lower(): s
                    for s in StaffProfile.objects.filter(
                        university_email__in=staff_by_email.keys()
                    )
                }

                # 3️⃣ M2M + Supervision
                for idx, row in df.iterrows():
                    try:
                        email = row["university_email"].lower()
                        staff = staff_db_map.get(email)

                        if not staff:
                            continue

                        # Campus
                        campus_val = str(row.get("campus") or "")
                        mactched_campuses = get_fuzzy_matches(campus_val, Campus.objects.all())
                        if campus_val:
                            for campus in mactched_campuses:
                                    campus_links.append(
                                        StaffProfile.campus.through(
                                            staffprofile_id=staff.id,
                                            campus_id=campus.id
                                        )
                                    )

                        # Managed departments
                        dept_val = str(row.get("managed_org_units") or "")
                        mactched_depts = get_fuzzy_matches(dept_val, Department.objects.all())
                        if dept_val:
                            for dept in mactched_depts:
                                    managed_dept_links.append(
                                        StaffProfile.managed_org_units.through(
                                            staffprofile_id=staff.id,
                                            department_id=dept.id
                                        )
                                    )

                        # Supervision
                        if staff.is_supervisor:
                            teams_val = str(row.get("supervised_teams") or "")
                            mactched_teams = get_fuzzy_matches(teams_val, DepartmentTeams.objects.all(), field_name="team_name")
                            print('teams', mactched_teams)
                            if teams_val:
                                for team in mactched_teams:
                                        supervision_assignments.append(
                                            SupervisionAssignment(
                                                supervisor=staff,
                                                team=team
                                            )
                                        )
                            
                            # staff_val = str(row.get("supervised_staff") or "")
                            # if staff_val:
                            #     for email in staff_val:
                            #         member = staff_db_map.get(email.strip().lower())
                            #         if member:
                            #             supervision_assignments.append(
                            #                 SupervisionAssignment(
                            #                     supervisor=staff,
                            #                     staff_member=member
                            #                 )
                            #             )
                               
                            s_staff_val = str(row.get("supervised_staff") or "")
                            if s_staff_val:
                                    email_list = [e.strip().lower() for e in s_staff_val.split(",") if e.strip()]
                                    for s_email in email_list:
                                        member = staff_db_map.get(s_email)
                                        if member:
                                            supervision_assignments.append(SupervisionAssignment(supervisor=staff, staff_member=member))

                    except Exception as e:
                        error_log.append(f"Row {idx+2}: {e}")

                # 4️⃣ Bulk create relations
                StaffProfile.campus.through.objects.bulk_create(campus_links, ignore_conflicts=True)
                StaffProfile.managed_org_units.through.objects.bulk_create(managed_dept_links, ignore_conflicts=True)
                SupervisionAssignment.objects.bulk_create(supervision_assignments)

                bulk_upload.status = "completed"
                bulk_upload.success_records = len(staff_to_create)
                bulk_upload.failed_records = len(error_log)
                bulk_upload.error_log = "\n".join(error_log) if error_log else None
                bulk_upload.save()

                return Response({
                    "message": "Staff bulk upload completed",
                    "created": len(staff_to_create),
                    "created_staff": StaffProfileSerializer(staff_to_create, many=True).data,
                    "create_supervisor":SupervisionSerializer(supervision_assignments, many=True).data,
                    "errors": error_log[:20]
                }, status=201)

        except Exception as e:
            return Response({"detail": str(e)}, status=500)

# department Units
class DepartmentUnits(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Prefetch teams + department in one go
        teams_qs = DepartmentTeams.objects.select_related('department')

        # Group in Python — still O(n) but only 2 queries total
        data = {}
        for team in teams_qs:
            dept_name = team.department.name
            if dept_name not in data:
                data[dept_name] = []
            data[dept_name].append(DepartmentTeamsSerializer(team).data)

        return Response(data)
    
# department staff
class DepartmentStaff(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = StaffProfile.objects.select_related('org_unit').all()

        grouped = defaultdict(list)
        for s in staff:
            if not s.org_unit_id or not s.org_unit:
                continue
            grouped[s.org_unit.name].append(s)

        data = {
            dept_name: ListStaffSerializer(staff_list, many=True).data
            for dept_name, staff_list in grouped.items()
        }

        return Response(data)


class CurrentStaffProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = resolve_staff_profile_for_user(request.user)
        if not profile:
            return Response(
                {
                    "detail": (
                        "No staff profile linked to your account. "
                        "Ask HR to add you in Staff directory with your university email, "
                        "or ensure your ERP login email matches your staff record."
                    )
                },
                status=404,
            )
        profile = (
            StaffProfile.objects.select_related("team", "org_unit", "staff_type", "position_level", "pay_scale", "user")
            .prefetch_related("campus", "managed_org_units")
            .get(pk=profile.pk)
        )
        return Response(DetailStaffSerializer(profile).data)


class StaffContractListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = StaffContractSerializer
    queryset = StaffContract.objects.select_related("staff", "department", "pay_scale").order_by("-start_date")

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.has_perm("staff.change_staffcontract"):
            return qs
        try:
            staff = self.request.user.staff_profile
            return qs.filter(staff=staff)
        except StaffProfile.DoesNotExist:
            return qs.none()


class StaffContractCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = StaffContractSerializer
    queryset = StaffContract.objects.all()
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("staff.add_staffcontract"):
            return Response({"detail": "Permission denied."}, status=403)
        return super().create(request, *args, **kwargs)