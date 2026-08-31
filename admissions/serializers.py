import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import *
from accounts.serializers import UserSerializer, CampusSerializer
from Programs.serializers import ProgramSerializer
from .utils.application_programs_display import ordered_programs_for_application
from .utils.academic_year import get_registered_academic_year_label

logger = logging.getLogger(__name__)

# serializers


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["id", "label", "is_current", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


# batch
class BatchSerializer(serializers.ModelSerializer):
    # Default M2M PK field uses allow_empty=False; empty list breaks saves for intakes with no programmes yet
    programs = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Program.objects.all(),
        allow_empty=True,
    )
    is_offer_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Batch
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            self.fields['created_by'].read_only = True

    def validate(self, attrs):
        inst = self.instance
        start = attrs.get('offer_start_date', inst.offer_start_date if inst else None)
        end = attrs.get('offer_end_date', inst.offer_end_date if inst else None)
        if start and end and end < start:
            raise serializers.ValidationError({
                'offer_end_date': 'Offer end date cannot be before offer start date.',
            })
        raw_year = attrs.get('academic_year')
        if raw_year is not None and str(raw_year).strip():
            try:
                attrs['academic_year'] = get_registered_academic_year_label(str(raw_year))
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'academic_year': str(exc)}) from exc

        if 'programs' in attrs:
            from admissions.intake_program_eligibility import validate_intake_program_selection

            program_ids = [p.pk for p in attrs['programs']]
            grandfather = set()
            if inst is not None:
                grandfather = set(inst.programs.values_list('id', flat=True))
            messages = validate_intake_program_selection(
                program_ids,
                grandfather_ids=grandfather,
            )
            if messages:
                raise serializers.ValidationError({'programs': messages})

        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['programs'] = ProgramSerializer(instance.programs.all(), many=True).data
        return response
    
# academic level
class AcademicLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicLevel
        fields = '__all__'

# ============================================applications==========================================================

# db application serializer
class CudApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = '__all__'
        extra_kwargs = {
            # Academic result fields are optional — not all applicants have O/A levels
            'olevel_year':          {'required': False, 'default': 0},
            'olevel_index_number':  {'required': False, 'allow_blank': True, 'default': ''},
            'olevel_school':        {'required': False, 'allow_blank': True, 'default': ''},
            'alevel_year':          {'required': False, 'default': 0},
            'alevel_index_number':  {'required': False, 'allow_blank': True, 'default': ''},
            'alevel_school':        {'required': False, 'allow_blank': True, 'default': ''},
            'alevel_combination':   {'required': False, 'allow_blank': True, 'default': ''},
        }

# single application
class SingleApplicationSerializer(serializers.ModelSerializer):
    programs = serializers.SerializerMethodField()
    campus = CampusSerializer(read_only=True)
    batch = serializers.SerializerMethodField()

    def get_programs(self, obj):
        return ProgramSerializer(ordered_programs_for_application(obj), many=True).data

    def get_batch(self, obj):
        if not obj.batch_id:
            return None
        return {"id": obj.batch_id, "name": obj.batch.name}

    class Meta:
        model = Application
        # Include status so admit-staff UI can verify "accepted" before admitting
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "nationality",
            "gender",
            "programs",
            "campus",
            "batch",
            "status",
        ]

class ApplicationSerializer(serializers.ModelSerializer):
    campus = serializers.CharField(source='campus.name', read_only=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    reviewed_by = serializers.CharField(source='reviewed_by.full_name', read_only=True, allow_null=True)
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name','middle_name', 'date_of_birth', 'gender', 'nationality', 'applicant_category', 'phone', 'email',
                  'batch', 'campus', "nin", "passport_number","disabled", 'is_refugee', 'refugee_status_proof', 'olevel_school', 'olevel_year', 'alevel_school', 'alevel_year', 'address',
                  'middle_name', 'next_of_kin_name', 'next_of_kin_contact', 'next_of_kin_relationship', 'reviewed_by', 'applicant', 'status',
                  'title', 'alevel_combination', 'alevel_index_number', 'olevel_index_number','application_fee_amount', 'created_at', 'address', 'passport_photo',
                  'has_olevel', 'has_alevel']
        

# list serializer (main application queue — excludes staff wizard direct entries)
class ListApplicationsSerializer(serializers.ModelSerializer):
    academic_level = serializers.CharField(source="academic_level.name", read_only=True)
    batch = serializers.CharField(source="batch.name", read_only=True)
    campus = serializers.CharField(source="campus.name", read_only=True)
    reviewed_by = serializers.CharField(source="reviewed_by.full_name", read_only=True, allow_null=True)
    revoked_by = serializers.CharField(source="revoked_by.full_name", read_only=True, allow_null=True)

    class Meta:
        model = Application
        fields = [
            "id",
            "first_name",
            "last_name",
            "gender",
            "status",
            "created_at",
            "email",
            "academic_level",
            "batch",
            "campus",
            "program_choices_confirmed_at",
            "program_choices_verification_sent_at",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "is_revoked",
            "revocation_reason",
            "revoked_by",
        ]

class AllApplicationsReportSerializer(serializers.ModelSerializer):
    academic_level = serializers.SerializerMethodField()
    batch = serializers.SerializerMethodField()
    campus = serializers.SerializerMethodField()
    programs = serializers.SerializerMethodField()
    faculty = serializers.SerializerMethodField()
    entered_by = serializers.SerializerMethodField()
    reviewed_by = serializers.CharField(source="reviewed_by.full_name", read_only=True, allow_null=True)
    revoked_by = serializers.CharField(source="revoked_by.full_name", read_only=True, allow_null=True)

    def get_academic_level(self, obj):
        return obj.academic_level.name if obj.academic_level else ""

    def get_batch(self, obj):
        return obj.batch.name if obj.batch else ""

    def get_campus(self, obj):
        return obj.campus.name if obj.campus else ""

    def get_programs(self, obj):
        try:
            choices = getattr(obj, 'prefetched_program_choices', [])
            return ", ".join([choice.program.name for choice in choices])
        except:
            return ""

    def get_faculty(self, obj):
        try:
            choices = getattr(obj, 'prefetched_program_choices', [])
            faculties = []
            for choice in choices:
                faculty = getattr(choice.program, 'faculty', None)
                if faculty and faculty.name:
                    faculties.append(faculty.name)
            # Remove duplicates while preserving order
            return ", ".join(dict.fromkeys(faculties))
        except:
            return ""

    def get_entered_by(self, obj):
        if getattr(obj, 'is_direct_entry', False) and getattr(obj, 'entered_by', None):
            eb = obj.entered_by
            name = f"{eb.first_name or ''} {eb.last_name or ''}".strip()
            return name or eb.username or str(eb.pk)
        return "Online"

    class Meta:
        model = Application
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "gender",
            "nationality",
            "applicant_category",
            "is_refugee",
            "academic_level",
            "batch",
            "campus",
            'pending_reason',
            "programs",
            "faculty",
            "status",
            "created_at",
            "is_direct_entry",
            "entered_by",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "is_revoked",
            "revocation_reason",
            "revoked_by",
        ]

# detail serializer
class ApplicationDetailSerializer(serializers.ModelSerializer):
    reviewed_by = serializers.CharField(source='reviewed_by.full_name', read_only=True, allow_null=True)
    revoked_by = serializers.CharField(source='revoked_by.full_name', read_only=True, allow_null=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name','middle_name', 'date_of_birth', 'gender', 'nationality', 'applicant_category', 'phone', 'email',
                  'batch', "nin", "passport_number","disabled", "is_refugee", "refugee_status_proof", "has_olevel",'olevel_school', 'olevel_year',"olevel_index_number", "has_alevel", 'alevel_school', 'alevel_year', 'alevel_index_number', 
                  'address','middle_name', 'next_of_kin_name', 'next_of_kin_contact', 'next_of_kin_relationship', 'revoked_by', 'is_revoked','revocation_reason',"alevel_combination",
                  'status', 'application_fee_amount','application_fee_paid', 'created_at', 'reviewed_at', 'passport_photo','reviewed_by',
                  'review_notes',
                  'program_choices_confirmed_at', 'program_choices_verification_sent_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["programs"] = [
            {"id": p.id, "name": p.name}
            for p in ordered_programs_for_application(instance)
        ]
        data["campus_id"] = instance.campus_id
        data["campus"] = instance.campus.name if instance.campus_id else None
        return data
    
# o level subject
class OlevelSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = OLevelSubject
        fields = '__all__'

# a level subject
class AlevelSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = ALevelSubject
        fields = '__all__'

# =================================olevel result=========================================================

# list Olevel results
class ListOlevelResultSerializer(serializers.ModelSerializer):
    subject = OlevelSubjectSerializer(read_only=True) 

    class Meta:
        model = OLevelResult
        fields = ['id', 'grade', 'subject']
   
class OlevelResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = OLevelResult
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['subject'] = OlevelSubjectSerializer(instance.subject).data
        return response

# =============================================alevel result===============================================

# list alevel results
class ListAlevelResultSerializer(serializers.ModelSerializer):
    subject = AlevelSubjectSerializer(read_only=True)  
    class Meta:
        model = ALevelResult
        fields = ['id', 'grade', 'subject']

class AlevelResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ALevelResult
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['subject'] = AlevelSubjectSerializer(instance.subject).data
        return response

# OLEVEL subjects
class OlevelSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = OLevelSubject
        fields = '__all__'

# ALevel Subjects
class AlevelSubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = ALevelSubject
        fields = '__all__'

class DocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.CharField(source='file.url', read_only=True)

    class Meta:
        model = ApplicationDocument
        fields = ['id', 'name', 'document_type', 'file', 'file_url', 'uploaded_at', 'application']

# ========================================faculty========================================== 
# list faculty serializer
class AcademicDepartmentSerializer(serializers.ModelSerializer):
    head_of_department_name = serializers.SerializerMethodField()
    head_of_department_email = serializers.SerializerMethodField()
    programs = serializers.SerializerMethodField()
    program_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = AcademicDepartment
        fields = [
            "id",
            "faculty",
            "name",
            "code",
            "is_active",
            "sort_order",
            "head_of_department",
            "head_of_department_name",
            "head_of_department_email",
            "programs",
            "program_ids",
        ]
        extra_kwargs = {
            "head_of_department": {"allow_null": True, "required": False},
        }

    def get_head_of_department_name(self, obj):
        user = obj.head_of_department
        if not user:
            return None
        name = f"{user.first_name} {user.last_name}".strip()
        return name or user.username

    def get_head_of_department_email(self, obj):
        user = obj.head_of_department
        return user.email if user else None

    def get_programs(self, obj):
        rows = getattr(obj, "programs", None)
        if rows is None:
            return []
        return [
            {"id": p.id, "name": p.name, "code": p.code}
            for p in rows.all().order_by("name")
        ]

    def _assign_programs(self, department, program_ids):
        from Programs.models import Program

        ids = [int(pk) for pk in (program_ids or [])]
        Program.objects.filter(department=department).exclude(pk__in=ids).update(
            department=None
        )
        if ids:
            Program.objects.filter(pk__in=ids).update(
                department=department,
                faculty_id=department.faculty_id,
            )

    def create(self, validated_data):
        program_ids = validated_data.pop("program_ids", None)
        head = validated_data.pop("head_of_department", None)
        dept = super().create(validated_data)
        if head:
            dept.assign_head(head)
        if program_ids is not None:
            self._assign_programs(dept, program_ids)
        return dept

    def update(self, instance, validated_data):
        program_ids = validated_data.pop("program_ids", None)
        if "head_of_department" in validated_data:
            head = validated_data.pop("head_of_department")
            instance = super().update(instance, validated_data)
            instance.assign_head(head)
        else:
            instance = super().update(instance, validated_data)
        if program_ids is not None:
            self._assign_programs(instance, program_ids)
        return instance


class FacultySerializer(serializers.ModelSerializer):
    departments = AcademicDepartmentSerializer(many=True, read_only=True)

    class Meta:
        model = Faculty
        fields = "__all__"

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["campuses"] = CampusSerializer(instance.campuses.all(), many=True).data
        return response
    
# admissions
class AdmittedStudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmittedStudent
        fields = '__all__'

    @staticmethod
    def _sync_programme_enrollment_batch(admitted):
        """Keep academic enrollment cohort, curriculum, and specialization aligned with admission."""
        from Programs.models import (
            StudentProgrammeEnrollment,
            resolve_program_default_curriculum_version,
        )
        from Programs.program_batch_resolution import resolve_default_program_batch_for_program
        from Programs.teaching_sections import ensure_enrollment_teaching_section

        spec_name = (
            admitted.admitted_specialization.name
            if admitted.admitted_specialization_id
            else None
        )
        try:
            spe = StudentProgrammeEnrollment.objects.get(student=admitted)
        except StudentProgrammeEnrollment.DoesNotExist:
            return

        intended = admitted.intended_program_batch
        if intended is not None and intended.program_id != admitted.admitted_program_id:
            intended = None
        if intended is None and admitted.admitted_program_id:
            intended = resolve_default_program_batch_for_program(
                admitted.admitted_program,
                admission_batch=admitted.admitted_batch,
            )

        update_fields: list[str] = []
        placement_changed = False

        if intended is not None:
            if spe.program_batch_id != intended.id:
                spe.program_batch_id = intended.id
                update_fields.append("program_batch")
                placement_changed = True
            if spe.program_id != admitted.admitted_program_id:
                spe.program_id = admitted.admitted_program_id
                update_fields.append("program")
                placement_changed = True

            if placement_changed and admitted.admitted_program_id:
                cv = (
                    intended.curriculum_version
                    if intended.curriculum_version_id
                    else resolve_program_default_curriculum_version(
                        admitted.admitted_program
                    )
                )
                if cv is not None and spe.curriculum_version_id != cv.id:
                    spe.curriculum_version_id = cv.id
                    update_fields.append("curriculum_version")
                if spe.teaching_section_id is not None:
                    spe.teaching_section_id = None
                    update_fields.append("teaching_section")

        if spec_name and spe.specialization != spec_name:
            spe.specialization = spec_name
            update_fields.append("specialization")

        if update_fields:
            update_fields.append("updated_at")
            spe.save(update_fields=list(dict.fromkeys(update_fields)))
        else:
            ensure_enrollment_teaching_section(spe, assign_only=False)

    def create(self, validated_data):
        from Programs.program_batch_resolution import resolve_default_program_batch_for_program

        if validated_data.get('intended_program_batch') is None:
            prog = validated_data.get('admitted_program')
            intake = validated_data.get('admitted_batch')
            if prog is not None:
                default_pb = resolve_default_program_batch_for_program(
                    prog, admission_batch=intake
                )
                if default_pb is not None:
                    validated_data['intended_program_batch'] = default_pb
        admitted = super().create(validated_data)
        self._sync_programme_enrollment_batch(admitted)
        return admitted

    def update(self, instance, validated_data):
        from Programs.program_batch_resolution import resolve_default_program_batch_for_program
        from admissions.placement_sync import (
            bill_programme_change_if_required,
            regenerate_reg_no_for_admission,
        )

        old_program_id = instance.admitted_program_id
        old_campus_id = instance.admitted_campus_id
        old_study_mode = (instance.study_mode or "").strip()

        placement_touch = any(
            key in validated_data
            for key in ("admitted_program", "admitted_campus", "study_mode")
        )
        # Placement changes must never rewrite SchoolPay codes or accept a client
        # reg. number — the server assigns the next free number for the new prefix.
        if placement_touch:
            validated_data.pop("schoolpay_code", None)
            validated_data.pop("is_registered_with_schoolpay", None)
            validated_data.pop("reg_no", None)

        prog = validated_data.get('admitted_program', instance.admitted_program)

        intake = validated_data.get('admitted_batch', instance.admitted_batch)
        if 'intended_program_batch' in validated_data and validated_data['intended_program_batch'] is None:
            default_pb = (
                resolve_default_program_batch_for_program(prog, admission_batch=intake)
                if prog is not None
                else None
            )
            validated_data['intended_program_batch'] = default_pb
        elif instance.intended_program_batch_id is None and 'intended_program_batch' not in validated_data:
            default_pb = (
                resolve_default_program_batch_for_program(prog, admission_batch=intake)
                if prog is not None
                else None
            )
            if default_pb is not None:
                validated_data['intended_program_batch'] = default_pb

        admitted = super().update(instance, validated_data)
        self._sync_programme_enrollment_batch(admitted)

        placement_changed = (
            admitted.admitted_program_id != old_program_id
            or admitted.admitted_campus_id != old_campus_id
            or (admitted.study_mode or "").strip() != old_study_mode
        )
        # Reg numbers encode campus / programme / study mode — always regenerate on placement change.
        if placement_changed:
            regenerate_reg_no_for_admission(admitted, sync_portal=True)
            admitted.refresh_from_db(fields=["reg_no"])

        if admitted.admitted_program_id != old_program_id:
            bill_programme_change_if_required(
                admitted,
                old_program=old_program_id,
                new_program=admitted.admitted_program,
                charged_by=getattr(getattr(self, "context", {}).get("request"), "user", None),
            )

        return admitted

    def validate(self, attrs):
        program = attrs.get('admitted_program')
        if program is None and self.instance is not None:
            program = self.instance.admitted_program

        if 'intended_program_batch' in attrs:
            intended = attrs['intended_program_batch']
        elif self.instance is not None:
            intended = self.instance.intended_program_batch
        else:
            intended = None

        # Programme changed — drop a cohort that belongs to the old programme.
        if (
            program is not None
            and intended is not None
            and intended.program_id != program.id
        ):
            intended = None
            attrs['intended_program_batch'] = None

        if intended is not None and program is not None:
            if intended.program_id != program.id:
                raise serializers.ValidationError({
                    'intended_program_batch': (
                        'Selected academic batch must belong to the admitted programme.'
                    ),
                })

        application = attrs.get('application')
        if application is None and self.instance is not None:
            application = self.instance.application

        campus = attrs.get('admitted_campus')
        if campus is None and self.instance is not None:
            campus = self.instance.admitted_campus

        if application is not None and program is not None:
            # Initial admit: programme must be one of the application choices.
            # Later staff placement changes (change of course) may use any offered programme.
            if self.instance is None:
                allowed_ids = {
                    p.id for p in ordered_programs_for_application(application)
                }
                if allowed_ids and program.id not in allowed_ids:
                    raise serializers.ValidationError({
                        'admitted_program': (
                            'Programme must be one of the applicant\'s choices on the application.'
                        ),
                    })

            if campus is not None and program.campuses.exists():
                if not program.campuses.filter(id=campus.id).exists():
                    raise serializers.ValidationError({
                        'admitted_program': (
                            'This programme is not offered at the selected campus.'
                        ),
                    })

        from admissions.admission_specialization import (
            program_requires_admission_specialization,
            validate_admitted_specialization_for_program,
        )

        admitted_specialization = attrs.get('admitted_specialization')
        if admitted_specialization is None and self.instance is not None:
            if 'admitted_specialization' not in attrs:
                admitted_specialization = self.instance.admitted_specialization

        if program is not None and not program_requires_admission_specialization(program):
            attrs['admitted_specialization'] = None
        elif program is not None:
            if (
                'admitted_program' in attrs
                and self.instance is not None
                and admitted_specialization is not None
                and admitted_specialization.program_id != program.id
            ):
                attrs['admitted_specialization'] = None
                admitted_specialization = None

            spec_err = validate_admitted_specialization_for_program(
                program, admitted_specialization
            )
            if spec_err:
                raise serializers.ValidationError({'admitted_specialization': spec_err})

        if self.instance is not None:
            from payments.utils.tuition_ledger_linking import student_payment_code_locked

            if student_payment_code_locked(self.instance):
                locked_msg = (
                    "This SchoolPay payment code has recorded payments and cannot be changed."
                )
                for field in ("student_id", "schoolpay_code"):
                    if field not in attrs:
                        continue
                    new_value = (attrs.get(field) or "").strip()
                    old_value = (getattr(self.instance, field) or "").strip()
                    if new_value != old_value:
                        raise serializers.ValidationError({field: locked_msg})
                if "is_registered_with_schoolpay" in attrs and not attrs[
                    "is_registered_with_schoolpay"
                ]:
                    raise serializers.ValidationError({
                        "is_registered_with_schoolpay": locked_msg,
                    })

            program_changing = (
                program is not None
                and self.instance.admitted_program_id is not None
                and program.id != self.instance.admitted_program_id
            )
            if program_changing:
                from Programs.models import StudentProgrammeEnrollment
                from Programs.program_batch_resolution import (
                    resolve_default_program_batch_for_program,
                )

                if StudentProgrammeEnrollment.objects.filter(
                    student_id=self.instance.pk
                ).exists():
                    intake = attrs.get("admitted_batch", self.instance.admitted_batch)
                    resolved_batch = intended
                    if resolved_batch is None and program is not None:
                        resolved_batch = resolve_default_program_batch_for_program(
                            program, admission_batch=intake
                        )
                    if resolved_batch is None:
                        raise serializers.ValidationError({
                            "admitted_program": (
                                "This programme has no academic batch configured. "
                                "Create a ProgramBatch under Academic Setup before "
                                "moving the student."
                            ),
                        })

        return attrs

    def to_representation(self, instance):
        from payments.utils.tuition_ledger_linking import schoolpay_wallet_api_fields

        data = super().to_representation(instance)
        data.update(schoolpay_wallet_api_fields(instance))
        return data

class AdmittedStudentListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    program = serializers.CharField(source='admitted_program.name', read_only=True)
    program_id = serializers.IntegerField(source='admitted_program_id', read_only=True)
    faculty = serializers.SerializerMethodField()  
    campus = serializers.CharField(source='admitted_campus.name', read_only=True)
    batch = serializers.CharField(source='admitted_batch.name', default='__', read_only=True)
    academic_batch = serializers.SerializerMethodField()
    status = serializers.CharField(source='application.status', read_only=True)
    admission_letter_pdf = serializers.SerializerMethodField()
    physical_documents_verified_by_name = serializers.SerializerMethodField()
    is_revoked = serializers.SerializerMethodField()
    # Optional registrar workflow (not on all DBs — default so UI stays usable)
    is_approved = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    approved_at = serializers.SerializerMethodField()
    subject_combination = serializers.SerializerMethodField()
    schoolpay_payment_code_locked = serializers.SerializerMethodField()
    schoolpay_ledger_total_ugx = serializers.SerializerMethodField()
    schoolpay_payment_warning = serializers.SerializerMethodField()
    commitment_met = serializers.SerializerMethodField()
    commitment_paid_ugx = serializers.SerializerMethodField()
    commitment_balance = serializers.SerializerMethodField()
    commitment_threshold = serializers.SerializerMethodField()
    can_revoke_or_delete = serializers.SerializerMethodField()
    can_revoke = serializers.SerializerMethodField()
    admission_lock_reason = serializers.SerializerMethodField()
    phone = serializers.CharField(source="application.phone", default="", read_only=True)
    email = serializers.EmailField(source="application.email", default="", read_only=True)
    gender = serializers.CharField(source="application.gender", default="", read_only=True)
    nationality = serializers.CharField(source="application.nationality", default="", read_only=True)
    date_of_birth = serializers.DateField(source="application.date_of_birth", read_only=True)

    class Meta:
        model = AdmittedStudent
        fields = [
            'id',
            'student_id',
            'reg_no',
            'schoolpay_code',
            'is_registered_with_schoolpay',
            'name',
            'phone',
            'email',
            'gender',
            'nationality',
            'date_of_birth',
            'study_mode',
            'program',
            'program_id',
            'subject_combination',
            'faculty',
            'campus',
            'batch',
            'academic_batch',
            'admission_date',
            'is_registered',
            'application',
            'is_admitted',
            'is_revoked',
            'admitted_by',
            'status',
            'admission_letter_pdf',
            'physical_documents_verified',
            'physical_documents_verified_at',
            'physical_documents_verified_by_name',
            'physical_documents_notes',
            'accounts_registration_cleared',
            'can_revoke_or_delete',
            'can_revoke',
            'admission_lock_reason',
            'is_approved',
            'approved_by_name',
            'approved_at',
            'admission_fee_paid',
            'schoolpay_payment_code_locked',
            'schoolpay_ledger_total_ugx',
            'schoolpay_payment_warning',
            'commitment_met',
            'commitment_paid_ugx',
            'commitment_balance',
            'commitment_threshold',
        ]

    def get_name(self, obj):
        app = obj.application
        if not app:
            return "N/A"
        
        first = getattr(app, 'first_name', '') or ''
        last = getattr(app, 'last_name', '') or ''
        middle = getattr(app, 'middle_name', '') or ''
        
        full_name = f"{first} {middle} {last}".strip()
        return full_name if full_name else "Unnamed Student"

    def get_subject_combination(self, obj):
        from admissions.admission_specialization import admitted_subject_combination_label

        return admitted_subject_combination_label(obj) or None

    def get_faculty(self, obj):
        if not obj.admitted_program:
            return "__"
        if not obj.admitted_program.faculty:
            return "__"
        return obj.admitted_program.faculty.name

    def _list_programme_enrollment(self, obj):
        """Safe SPE load — avoid SELECT of teaching_section when column is missing."""
        try:
            cache = getattr(obj, "_prefetched_objects_cache", None) or {}
            if "programme_enrollment" in cache:
                return obj.programme_enrollment
        except Exception:
            pass
        try:
            from Programs.spe_queryset import programme_enrollment_qs_for_lists

            return programme_enrollment_qs_for_lists().filter(student_id=obj.pk).first()
        except Exception:
            return None

    def get_academic_batch(self, obj):
        from Programs.program_batch_resolution import format_program_batch_display

        enrollment = self._list_programme_enrollment(obj)
        if enrollment is not None and enrollment.program_batch_id:
            try:
                return format_program_batch_display(enrollment.program_batch)
            except Exception:
                pass
        intended = getattr(obj, "intended_program_batch", None)
        if intended is not None and getattr(intended, "pk", None):
            return format_program_batch_display(intended)
        return "—"

    def get_physical_documents_verified_by_name(self, obj):
        user = getattr(obj, "physical_documents_verified_by", None)
        if user is None:
            return None
        return user.get_full_name() or getattr(user, "username", None)

    def get_is_revoked(self, obj):
        app = obj.application
        if app is None:
            return False
        return bool(getattr(app, "is_revoked", False))

    def get_admission_letter_pdf(self, obj):
        app = obj.application
        if app and app.admission_letter_pdf:
            try:
                return app.admission_letter_pdf.url
            except ValueError:
                return None
        return None

    def get_is_approved(self, obj):
        return getattr(obj, "is_approved", True)

    def get_approved_by_name(self, obj):
        user = getattr(obj, "approved_by", None) or getattr(obj, "admitted_by", None)
        if user is None:
            return None
        return user.get_full_name() or getattr(user, "username", None)

    def get_approved_at(self, obj):
        return getattr(obj, "approved_at", None)

    def _request_user_can_view_finance(self) -> bool:
        cached = getattr(self, "_directory_can_view_finance", None)
        if cached is not None:
            return cached
        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        if user is None:
            self._directory_can_view_finance = False
            return False
        from accounts.finance_access import user_can_view_student_finance

        self._directory_can_view_finance = user_can_view_student_finance(user)
        return self._directory_can_view_finance

    def _wallet_fields(self, obj):
        if not self._request_user_can_view_finance():
            return {
                "schoolpay_payment_code_locked": None,
                "schoolpay_ledger_total_ugx": None,
                "schoolpay_payment_warning": None,
            }
        cached = getattr(obj, "_directory_wallet_fields_cache", None)
        if cached is not None:
            return cached
        from payments.utils.tuition_ledger_linking import schoolpay_wallet_api_fields

        cached = schoolpay_wallet_api_fields(obj)
        obj._directory_wallet_fields_cache = cached
        return cached

    def get_schoolpay_payment_code_locked(self, obj):
        return self._wallet_fields(obj)["schoolpay_payment_code_locked"]

    def get_schoolpay_ledger_total_ugx(self, obj):
        return self._wallet_fields(obj)["schoolpay_ledger_total_ugx"]

    def get_schoolpay_payment_warning(self, obj):
        return self._wallet_fields(obj)["schoolpay_payment_warning"]

    def _commitment_totals(self, obj):
        if not self._request_user_can_view_finance():
            return None
        from decimal import Decimal

        from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

        annotated = getattr(obj, "commitment_paid_ugx", None)
        if annotated is None:
            return None
        ugx_credit = Decimal(str(annotated))
        admission_paid = bool(getattr(obj, "admission_fee_paid", False))
        commitment_paid = min(ugx_credit, COMMITMENT_FEE_THRESHOLD)
        commitment_met = commitment_paid >= COMMITMENT_FEE_THRESHOLD or admission_paid
        commitment_balance = max(COMMITMENT_FEE_THRESHOLD - commitment_paid, Decimal("0"))
        return {
            "commitment_met": commitment_met,
            "commitment_paid_ugx": float(commitment_paid),
            "commitment_balance": float(commitment_balance),
            "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        }

    def get_commitment_met(self, obj):
        totals = self._commitment_totals(obj)
        return totals["commitment_met"] if totals else None

    def get_commitment_paid_ugx(self, obj):
        totals = self._commitment_totals(obj)
        return totals["commitment_paid_ugx"] if totals else None

    def get_commitment_balance(self, obj):
        totals = self._commitment_totals(obj)
        return totals["commitment_balance"] if totals else None

    def get_commitment_threshold(self, obj):
        totals = self._commitment_totals(obj)
        return totals["commitment_threshold"] if totals else None

    def _admission_lock_reason(self, obj, *, action: str = "delete"):
        try:
            from admissions.registration_workflow import (
                admission_revoke_or_delete_blocked_reason,
            )

            request = self.context.get("request")
            user = getattr(request, "user", None) if request else None
            return admission_revoke_or_delete_blocked_reason(obj, user, action=action)
        except Exception:
            # Never 500 the directory over lock metadata.
            return "Unable to determine admission lock status."

    def get_admission_lock_reason(self, obj):
        # Informational lock text for registered/verified students.
        return self._admission_lock_reason(obj, action="delete")

    def get_can_revoke_or_delete(self, obj):
        # Delete remains blocked for registered/verified students (even Super Admin).
        return self._admission_lock_reason(obj, action="delete") is None

    def get_can_revoke(self, obj):
        # Super Admin / staff with revoke permission may revoke locked admissions.
        return self._admission_lock_reason(obj, action="revoke") is None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._request_user_can_view_finance():
            data["admission_fee_paid"] = None
            data["schoolpay_ledger_total_ugx"] = None
            data["schoolpay_payment_warning"] = None
            data["schoolpay_payment_code_locked"] = None
            data["commitment_met"] = None
            data["commitment_paid_ugx"] = None
            data["commitment_balance"] = None
            data["commitment_threshold"] = None
        return data


class BonafideStudentSerializer(serializers.ModelSerializer):
    """Bio + identity + academic placement only (no qualifications / admission workflow)."""

    name = serializers.SerializerMethodField()
    application = serializers.IntegerField(source="application_id", read_only=True)
    first_name = serializers.CharField(source="application.first_name", default="", read_only=True)
    middle_name = serializers.CharField(source="application.middle_name", default="", read_only=True)
    last_name = serializers.CharField(source="application.last_name", default="", read_only=True)
    gender = serializers.CharField(source="application.gender", default="", read_only=True)
    phone = serializers.CharField(source="application.phone", default="", read_only=True)
    email = serializers.EmailField(source="application.email", default="", read_only=True)
    date_of_birth = serializers.DateField(
        source="application.date_of_birth", read_only=True, allow_null=True
    )
    nationality = serializers.CharField(source="application.nationality", default="", read_only=True)
    program = serializers.CharField(source="admitted_program.name", default="", read_only=True)
    program_id = serializers.IntegerField(source="admitted_program_id", read_only=True)
    level = serializers.CharField(
        source="admitted_program.academic_level.name", default="", read_only=True
    )
    academic_batch_id = serializers.SerializerMethodField()
    faculty = serializers.SerializerMethodField()
    campus = serializers.CharField(source="admitted_campus.name", default="", read_only=True)
    academic_batch = serializers.SerializerMethodField()
    admission_intake = serializers.CharField(source="admitted_batch.name", default="", read_only=True)
    current_year_of_study = serializers.SerializerMethodField()
    current_term_number = serializers.SerializerMethodField()
    enrollment_status = serializers.SerializerMethodField()
    registration_stage = serializers.SerializerMethodField()
    registration_stage_label = serializers.SerializerMethodField()
    requires_document_verification = serializers.SerializerMethodField()
    accounts_registration_cleared_by_name = serializers.SerializerMethodField()
    accounts_hostel_cleared_by_name = serializers.SerializerMethodField()
    physical_documents_verified_by_name = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    total_required = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    balance_currency = serializers.SerializerMethodField()
    exemption_pending = serializers.SerializerMethodField()
    has_temporary_access_pass = serializers.SerializerMethodField()
    temporary_access_sponsor = serializers.SerializerMethodField()
    temporary_access_valid_until = serializers.SerializerMethodField()
    is_scholarship_sponsored = serializers.SerializerMethodField()
    scholarship_name = serializers.SerializerMethodField()

    class Meta:
        model = AdmittedStudent
        fields = [
            "id",
            "application",
            "name",
            "first_name",
            "middle_name",
            "last_name",
            "gender",
            "phone",
            "email",
            "date_of_birth",
            "nationality",
            "reg_no",
            "student_id",
            "schoolpay_code",
            "campus",
            "program",
            "program_id",
            "level",
            "academic_batch_id",
            "faculty",
            "academic_batch",
            "admission_intake",
            "study_mode",
            "current_year_of_study",
            "current_term_number",
            "enrollment_status",
            "admission_fee_paid",
            "accounts_registration_cleared",
            "accounts_registration_cleared_at",
            "accounts_registration_cleared_by_name",
            "accounts_hostel_cleared",
            "accounts_hostel_cleared_at",
            "accounts_hostel_cleared_by_name",
            "physical_documents_verified",
            "physical_documents_verified_at",
            "physical_documents_verified_by_name",
            "registration_stage",
            "registration_stage_label",
            "requires_document_verification",
            "balance",
            "total_required",
            "total_paid",
            "balance_currency",
            "exemption_pending",
            "has_temporary_access_pass",
            "temporary_access_sponsor",
            "temporary_access_valid_until",
            "is_scholarship_sponsored",
            "scholarship_name",
        ]

    def get_name(self, obj):
        app = obj.application
        if not app:
            return "N/A"
        first = getattr(app, "first_name", "") or ""
        last = getattr(app, "last_name", "") or ""
        middle = getattr(app, "middle_name", "") or ""
        full_name = f"{first} {middle} {last}".strip()
        return full_name if full_name else "Unnamed Student"

    def get_faculty(self, obj):
        if not obj.admitted_program or not obj.admitted_program.faculty:
            return ""
        return obj.admitted_program.faculty.name

    def _enrollment(self, obj):
        try:
            return obj.programme_enrollment
        except Exception:
            # Missing OneToOne, or schema drift (e.g. teaching_section column).
            return None

    def get_academic_batch(self, obj):
        from Programs.program_batch_resolution import format_program_batch_display

        enrollment = self._enrollment(obj)
        if enrollment is not None and enrollment.program_batch_id:
            try:
                return format_program_batch_display(enrollment.program_batch)
            except Exception:
                pass
        intended = getattr(obj, "intended_program_batch", None)
        if intended is not None and getattr(intended, "pk", None):
            return format_program_batch_display(intended)
        return "—"

    def get_academic_batch_id(self, obj):
        enrollment = self._enrollment(obj)
        if enrollment is not None and enrollment.program_batch_id:
            return enrollment.program_batch_id
        intended = getattr(obj, "intended_program_batch", None)
        if intended is not None and getattr(intended, "pk", None):
            return intended.pk
        return None

    def get_current_year_of_study(self, obj):
        enr = self._enrollment(obj)
        return getattr(enr, "current_year_of_study", None) if enr else None

    def get_current_term_number(self, obj):
        enr = self._enrollment(obj)
        return getattr(enr, "current_term_number", None) if enr else None

    def get_enrollment_status(self, obj):
        enr = self._enrollment(obj)
        return getattr(enr, "status", None) if enr else None

    def get_requires_document_verification(self, obj):
        from admissions.registration_workflow import requires_physical_document_verification

        return requires_physical_document_verification(obj)

    def get_registration_stage(self, obj):
        from admissions.registration_workflow import registration_stage_for_student

        return registration_stage_for_student(obj)

    def get_registration_stage_label(self, obj):
        from admissions.registration_workflow import registration_stage_label

        return registration_stage_label(self.get_registration_stage(obj))

    def _cached_access_flags(self) -> tuple[bool, bool]:
        """Cache finance/scholarship visibility once per serializer instance."""
        cached = getattr(self, "_bonafide_access_flags", None)
        if cached is not None:
            return cached
        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        if user is None:
            flags = (False, False)
        else:
            from accounts.finance_access import (
                user_can_view_scholarship_status,
                user_can_view_student_finance,
            )

            flags = (
                user_can_view_student_finance(user),
                user_can_view_scholarship_status(user),
            )
        self._bonafide_access_flags = flags
        return flags

    def _request_user_can_view_finance(self) -> bool:
        return self._cached_access_flags()[0]

    def _request_user_can_view_scholarship(self) -> bool:
        return self._cached_access_flags()[1]

    def _finance_totals(self, obj):
        """Balance carried forward across all terms (not just the current one).

        Cached per-instance so the four balance-related fields below share one
        finance allocation computation instead of recomputing it four times.
        Only computed for users with finance visibility.
        """
        if not self._request_user_can_view_finance():
            return {
                "balance": None,
                "total_required": None,
                "total_paid": None,
                "display_currency": None,
                "exemption_pending": None,
            }
        cached = getattr(obj, "_bonafide_finance_totals_cache", None)
        if cached is not None:
            return cached
        from payments.student_portal_finance import student_finance_totals

        try:
            totals = student_finance_totals(obj)
        except Exception:
            logger.exception("Finance totals failed for bonafide student id=%s", obj.pk)
            totals = {
                "balance": None,
                "total_required": None,
                "total_paid": None,
                "display_currency": "UGX",
                "exemption_pending": None,
            }
        obj._bonafide_finance_totals_cache = totals
        return totals

    def get_balance(self, obj):
        return self._finance_totals(obj).get("balance")

    def get_total_required(self, obj):
        return self._finance_totals(obj).get("total_required")

    def get_total_paid(self, obj):
        return self._finance_totals(obj).get("total_paid")

    def get_balance_currency(self, obj):
        ccy = self._finance_totals(obj).get("display_currency")
        return ccy if self._request_user_can_view_finance() else None

    def get_exemption_pending(self, obj):
        return self._finance_totals(obj).get("exemption_pending")

    def get_has_temporary_access_pass(self, obj):
        if not self._request_user_can_view_scholarship():
            return None
        annotated = getattr(obj, "has_temporary_access_pass", None)
        if annotated is not None:
            return bool(annotated)
        from admissions.temporary_access import get_active_pass

        return get_active_pass(obj) is not None

    def get_temporary_access_sponsor(self, obj):
        if not self._request_user_can_view_scholarship():
            return None
        annotated = getattr(obj, "temporary_access_sponsor", None)
        if annotated is not None:
            return annotated or None
        if not self.get_has_temporary_access_pass(obj):
            return None
        from admissions.temporary_access import get_active_pass

        p = get_active_pass(obj)
        return (p.sponsor_label if p else None) or None

    def get_temporary_access_valid_until(self, obj):
        if not self._request_user_can_view_scholarship():
            return None
        annotated = getattr(obj, "temporary_access_valid_until", None)
        if annotated is not None:
            return annotated.isoformat() if hasattr(annotated, "isoformat") else annotated
        if not self.get_has_temporary_access_pass(obj):
            return None
        from admissions.temporary_access import get_active_pass

        p = get_active_pass(obj)
        if not p or not p.valid_until:
            return None
        return p.valid_until.isoformat()

    def get_is_scholarship_sponsored(self, obj):
        if not self._request_user_can_view_scholarship():
            return None
        annotated = getattr(obj, "is_scholarship_sponsored", None)
        if annotated is not None:
            return bool(annotated)
        from admissions.temporary_access import student_is_sponsored

        return student_is_sponsored(obj)

    def get_scholarship_name(self, obj):
        if not self._request_user_can_view_scholarship():
            return None
        annotated = getattr(obj, "scholarship_name", None)
        if annotated:
            return annotated
        if self.get_is_scholarship_sponsored(obj) is False:
            return None
        from admissions.temporary_access import student_active_scholarship_awards

        award = student_active_scholarship_awards(obj).first()
        if not award or not award.programme_id:
            return None
        return award.programme.name

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._request_user_can_view_finance():
            data["admission_fee_paid"] = None
            data["balance"] = None
            data["total_required"] = None
            data["total_paid"] = None
            data["balance_currency"] = None
        if not self._request_user_can_view_scholarship():
            data["has_temporary_access_pass"] = None
            data["temporary_access_sponsor"] = None
            data["temporary_access_valid_until"] = None
            data["is_scholarship_sponsored"] = None
            data["scholarship_name"] = None
        return data

    def get_accounts_registration_cleared_by_name(self, obj):
        u = getattr(obj, "accounts_registration_cleared_by", None)
        if not u:
            return None
        full = (getattr(u, "get_full_name", lambda: "")() or "").strip()
        return full or getattr(u, "username", None) or getattr(u, "email", None)

    def get_accounts_hostel_cleared_by_name(self, obj):
        u = getattr(obj, "accounts_hostel_cleared_by", None)
        if not u:
            return None
        full = (getattr(u, "get_full_name", lambda: "")() or "").strip()
        return full or getattr(u, "username", None) or getattr(u, "email", None)

    def get_physical_documents_verified_by_name(self, obj):
        u = getattr(obj, "physical_documents_verified_by", None)
        if not u:
            return None
        full = (getattr(u, "get_full_name", lambda: "")() or "").strip()
        return full or getattr(u, "username", None) or getattr(u, "email", None)


class BonafideStudentProfileSerializer(BonafideStudentSerializer):
    """Full personal profile (application first page) + placement — no qualifications."""

    title = serializers.CharField(source="application.title", default="", read_only=True)
    applicant_category = serializers.CharField(
        source="application.applicant_category", default="", read_only=True
    )
    address = serializers.CharField(source="application.address", default="", read_only=True)
    nin = serializers.CharField(source="application.nin", default="", read_only=True)
    passport_number = serializers.CharField(
        source="application.passport_number", default="", read_only=True
    )
    disabled = serializers.CharField(source="application.disabled", default="", read_only=True)
    is_refugee = serializers.BooleanField(source="application.is_refugee", read_only=True)
    next_of_kin_name = serializers.CharField(
        source="application.next_of_kin_name", default="", read_only=True
    )
    next_of_kin_contact = serializers.CharField(
        source="application.next_of_kin_contact", default="", read_only=True
    )
    next_of_kin_relationship = serializers.CharField(
        source="application.next_of_kin_relationship", default="", read_only=True
    )
    passport_photo = serializers.SerializerMethodField()

    class Meta(BonafideStudentSerializer.Meta):
        fields = BonafideStudentSerializer.Meta.fields + [
            "title",
            "applicant_category",
            "address",
            "nin",
            "passport_number",
            "disabled",
            "is_refugee",
            "next_of_kin_name",
            "next_of_kin_contact",
            "next_of_kin_relationship",
            "passport_photo",
            "accounts_registration_clearance_notes",
            "accounts_hostel_clearance_notes",
            "physical_documents_notes",
        ]

    def get_passport_photo(self, obj):
        from admissions.student_photo import admitted_student_photo_url

        request = self.context.get("request")
        return admitted_student_photo_url(obj, request)


# admission detail serializer
class AdmissionDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmittedStudent
        fields = [
            'id',
            'student_id',
            'reg_no',
            'schoolpay_code',
            'is_registered_with_schoolpay',
            'study_mode',
            'admission_notes',
            'admitted_program',
            'admitted_campus',
            'admitted_batch',
            'application',
            'is_registered',
            'registration_date',
            'physical_documents_verified',
            'accounts_registration_cleared',
            'intended_program_batch',
            'admitted_specialization',
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['admitted_program'] = ProgramSerializer(instance.admitted_program).data
        response['admitted_campus'] = CampusSerializer(instance.admitted_campus).data
        ab = instance.admitted_batch
        if ab is not None:
            response['admitted_batch'] = {'id': ab.id, 'name': ab.name}
        else:
            response['admitted_batch'] = None
        ipb = instance.intended_program_batch
        if ipb is not None:
            response['intended_program_batch'] = {
                'id': ipb.id,
                'name': ipb.name,
                'academic_year': ipb.academic_year or '',
                'start_date': ipb.start_date.isoformat() if ipb.start_date else None,
            }
        else:
            response['intended_program_batch'] = None
        spec = instance.admitted_specialization
        if spec is not None:
            response['admitted_specialization'] = {
                'id': spec.id,
                'name': spec.name,
            }
            response['subject_combination'] = spec.name
        else:
            response['admitted_specialization'] = None
            response['subject_combination'] = None
        from payments.utils.tuition_ledger_linking import schoolpay_wallet_api_fields
        from admissions.registration_workflow import (
            admission_revoke_or_delete_blocked_reason,
        )

        response.update(schoolpay_wallet_api_fields(instance))
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        delete_lock = admission_revoke_or_delete_blocked_reason(
            instance, user, action="delete"
        )
        revoke_lock = admission_revoke_or_delete_blocked_reason(
            instance, user, action="revoke"
        )
        response["admission_lock_reason"] = delete_lock
        response["can_revoke_or_delete"] = delete_lock is None
        response["can_revoke"] = revoke_lock is None
        return response
    
# notification serializers
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalNotification
        fields = '__all__'


# ── Admission Change Request ──────────────────────────────────────────────────
class ExemptionRequestLineSerializer(serializers.ModelSerializer):
    decision_display = serializers.CharField(source="get_decision_display", read_only=True)
    dean_decision_display = serializers.CharField(source="get_dean_decision_display", read_only=True)
    ar_decision_display = serializers.CharField(source="get_ar_decision_display", read_only=True)

    class Meta:
        model = ExemptionRequestLine
        fields = [
            "id",
            "curriculum_line",
            "course_code",
            "course_name",
            "year_of_study",
            "term_number",
            "score_obtained",
            "decision",
            "decision_display",
            "decision_note",
            "dean_decision",
            "dean_decision_display",
            "dean_decision_note",
            "ar_decision",
            "ar_decision_display",
            "ar_decision_note",
        ]


class ExemptionSupportingDocumentSerializer(serializers.ModelSerializer):
    document_type_display = serializers.CharField(source="get_document_type_display", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ExemptionSupportingDocument
        fields = [
            "id",
            "document_type",
            "document_type_display",
            "original_filename",
            "file_url",
            "uploaded_at",
        ]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return None
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


def _application_doc_is_academic(doc) -> bool:
    raw = (getattr(doc, "document_type", None) or "").strip().lower()
    compact = raw.replace(" ", "").replace("_", "").replace("-", "")
    if compact in {
        "passport",
        "passportphoto",
        "photo",
        "profilephoto",
        "refugee",
        "refugeeproof",
        "refugeeid",
        "nin",
        "nationalid",
    }:
        return False
    return True


def _application_doc_label(doc) -> str:
    raw = (getattr(doc, "document_type", None) or "").strip()
    compact = raw.lower().replace(" ", "").replace("_", "").replace("-", "")
    labels = {
        "olevel": "O-Level",
        "alevel": "A-Level",
        "otherqualifications": "Other qualifications",
        "otherqualification": "Other qualifications",
        "others": "Other application document",
        "other": "Other application document",
        "diploma": "Diploma",
        "certificate": "Certificate",
        "transcript": "Transcript (application)",
    }
    if compact in labels:
        return labels[compact]
    return raw or "Application document"


class AdmissionChangeRequestSerializer(serializers.ModelSerializer):
    """Read serializer — expands FK names for display."""
    change_type_display = serializers.CharField(source='get_change_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.SerializerMethodField()
    student_id = serializers.CharField(source='admitted_student.student_id', read_only=True)
    admitted_student_pk = serializers.IntegerField(source='admitted_student_id', read_only=True)
    current_program_name = serializers.CharField(source='current_program.name', read_only=True, default=None)
    current_campus_name = serializers.CharField(source='current_campus.name', read_only=True, default=None)
    new_program_name = serializers.CharField(source='new_program.name', read_only=True, default=None)
    new_campus_name = serializers.CharField(source='new_campus.name', read_only=True, default=None)
    reviewed_by_name = serializers.SerializerMethodField()
    hod_reviewed_by_name = serializers.SerializerMethodField()
    dean_reviewed_by_name = serializers.SerializerMethodField()
    ar_reviewed_by_name = serializers.SerializerMethodField()
    accounts_reviewed_by_name = serializers.SerializerMethodField()
    hod_status_display = serializers.CharField(source="get_hod_status_display", read_only=True)
    dean_status_display = serializers.CharField(source="get_dean_status_display", read_only=True)
    ar_status_display = serializers.CharField(source="get_ar_status_display", read_only=True)
    accounts_status_display = serializers.CharField(source="get_accounts_status_display", read_only=True)
    exemption_lines = ExemptionRequestLineSerializer(many=True, read_only=True)
    supporting_documents = serializers.SerializerMethodField()
    application_documents = serializers.SerializerMethodField()
    form_fee_paid = serializers.SerializerMethodField()
    exemption_course_fee_rate = serializers.SerializerMethodField()
    exemption_course_fee_total = serializers.SerializerMethodField()
    exemption_billing_lines = serializers.SerializerMethodField()
    suggested_promotion = serializers.SerializerMethodField()
    promotion_context = serializers.SerializerMethodField()

    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'id', 'change_type', 'change_type_display', 'status', 'status_display',
            'student_name', 'student_id', 'admitted_student_pk',
            'current_program_name', 'current_campus_name', 'current_study_mode',
            'new_program_name', 'new_campus_name', 'new_study_mode',
            'requested_year', 'requested_semester',
            'reason', 'review_notes', 'reviewed_by_name', 'reviewed_at', 'created_at',
            'hod_status', 'hod_status_display', 'hod_reviewed_by_name', 'hod_reviewed_at', 'hod_notes',
            'dean_status', 'dean_status_display', 'dean_reviewed_by_name', 'dean_reviewed_at', 'dean_notes',
            'ar_status', 'ar_status_display', 'ar_reviewed_by_name', 'ar_reviewed_at', 'ar_notes',
            'accounts_status', 'accounts_status_display', 'accounts_reviewed_by_name',
            'accounts_reviewed_at', 'accounts_notes',
            'exemption_lines', 'supporting_documents', 'application_documents',
            'form_fee_charge_id', 'form_fee_paid_at', 'form_fee_paid',
            'exemption_attained_at', 'exemption_academic_years', 'exemption_is_alumnus',
            'exemption_course_fee_rate', 'exemption_course_fee_total',
            'exemption_billing_lines',
            'suggested_promotion', 'promotion_context',
        ]

    def get_supporting_documents(self, obj):
        return ExemptionSupportingDocumentSerializer(
            obj.supporting_documents.all(), many=True, context=self.context
        ).data

    def get_application_documents(self, obj):
        if self.context.get("list_view"):
            return []
        if obj.change_type != "exemption":
            return []
        try:
            application = obj.admitted_student.application
        except Exception:
            return []
        if application is None:
            return []
        request = self.context.get("request")
        rows = []
        for doc in application.documents.all():
            if not _application_doc_is_academic(doc) or not doc.file:
                continue
            url = doc.file.url
            if request:
                url = request.build_absolute_uri(url)
            filename = (doc.name or "").strip()
            if not filename:
                filename = (getattr(doc.file, "name", "") or "").split("/")[-1]
            rows.append(
                {
                    "id": doc.id,
                    "document_type": doc.document_type or "application",
                    "document_type_display": _application_doc_label(doc),
                    "original_filename": filename,
                    "file_url": url,
                    "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                    "source": "application",
                }
            )
        return rows

    def get_student_name(self, obj):
        try:
            return obj.admitted_student.application.full_name
        except Exception:
            return None

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return None

    def _reviewer_name(self, user):
        if user:
            return user.get_full_name() or user.username
        return None

    def get_hod_reviewed_by_name(self, obj):
        return self._reviewer_name(getattr(obj, "hod_reviewed_by", None))

    def get_dean_reviewed_by_name(self, obj):
        return self._reviewer_name(getattr(obj, "dean_reviewed_by", None))

    def get_ar_reviewed_by_name(self, obj):
        return self._reviewer_name(getattr(obj, "ar_reviewed_by", None))

    def get_accounts_reviewed_by_name(self, obj):
        return self._reviewer_name(getattr(obj, "accounts_reviewed_by", None))

    def _request_user_can_view_finance(self) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        if user is None:
            return False
        from accounts.finance_access import user_can_view_student_finance

        return user_can_view_student_finance(user)

    def get_form_fee_paid(self, obj):
        if obj.change_type != "exemption":
            return None
        # List view: avoid per-row payment lookups — stamp is enough for the queue.
        if self.context.get("list_view"):
            if obj.form_fee_paid_at:
                return True
            charge = getattr(obj, "form_fee_charge", None)
            if charge is not None and getattr(charge, "status", None) == "completed":
                return True
            return False
        from admissions.exemption_services import student_has_paid_exemption_form_fee

        try:
            return student_has_paid_exemption_form_fee(obj.admitted_student)
        except Exception:
            return bool(obj.form_fee_paid_at)

    def get_exemption_course_fee_rate(self, obj):
        if obj.change_type != "exemption":
            return None
        if not self._request_user_can_view_finance():
            return None
        from admissions.exemption_services import exemption_course_fee_rate

        rate = exemption_course_fee_rate(obj)
        return float(rate) if rate is not None else None

    def get_exemption_course_fee_total(self, obj):
        if obj.change_type != "exemption":
            return None
        if self.context.get("list_view"):
            return None
        if not self._request_user_can_view_finance():
            return None
        from admissions.exemption_services import exemption_course_fee_total

        try:
            return float(exemption_course_fee_total(obj))
        except Exception:
            return None

    def get_exemption_billing_lines(self, obj):
        if obj.change_type != "exemption":
            return None
        if self.context.get("list_view"):
            return None
        if not self._request_user_can_view_finance():
            return None
        from admissions.exemption_services import exemption_billing_lines_for_request

        try:
            return exemption_billing_lines_for_request(obj)
        except Exception:
            return []

    def get_suggested_promotion(self, obj):
        if obj.change_type != "exemption" or obj.hod_status != "approved":
            return None
        if self.context.get("list_view"):
            return None
        from admissions.exemption_services import suggest_promotion_after_exemption

        try:
            return suggest_promotion_after_exemption(obj)
        except Exception:
            return None

    def get_promotion_context(self, obj):
        if obj.change_type != "exemption" or obj.hod_status != "approved":
            return None
        if self.context.get("list_view"):
            return None
        from admissions.exemption_services import enrollment_promotion_context

        try:
            return enrollment_promotion_context(obj.admitted_student)
        except Exception:
            return None

    def to_representation(self, instance):
        if instance.change_type == "exemption":
            from admissions.exemption_services import ensure_exemption_request_stages_synced

            ensure_exemption_request_stages_synced(instance)
        data = super().to_representation(instance)
        if not self._request_user_can_view_finance():
            data["form_fee_charge_id"] = None
            data["form_fee_paid_at"] = None
            data["form_fee_paid"] = None
            data["exemption_course_fee_rate"] = None
            data["exemption_course_fee_total"] = None
            data["exemption_billing_lines"] = None
        return data


class AdmissionChangeRequestCreateSerializer(serializers.ModelSerializer):
    """Write serializer — student submits a change request."""
    curriculum_line_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'change_type', 'new_program', 'new_campus', 'new_study_mode',
            'requested_year', 'requested_semester', 'reason',
            'curriculum_line_ids',
            'exemption_attained_at', 'exemption_academic_years',
        ]

    def validate(self, data):
        ct = data.get('change_type')
        if ct == 'program' and not data.get('new_program'):
            raise serializers.ValidationError({'new_program': 'Required for a programme change.'})
        if ct == 'campus' and not data.get('new_campus'):
            raise serializers.ValidationError({'new_campus': 'Required for a campus transfer.'})
        if ct == 'study_mode' and not data.get('new_study_mode', '').strip():
            raise serializers.ValidationError({'new_study_mode': 'Required for a study mode change.'})
        if ct == 'dead_semester':
            if not data.get('requested_year'):
                raise serializers.ValidationError({'requested_year': 'Year of study is required for a dead semester request.'})
            if not data.get('requested_semester'):
                raise serializers.ValidationError({'requested_semester': 'Semester number is required for a dead semester request.'})
        if ct == 'dead_year':
            if not data.get('requested_year'):
                raise serializers.ValidationError({'requested_year': 'Year of study is required for a dead year request.'})
        if ct == 'exemption':
            # Papers arrive as multipart JSON string (exemption_papers) and are
            # validated in the view — serializer only checks the common fields.
            if not (data.get('reason') or '').strip():
                raise serializers.ValidationError({'reason': 'Reason is required for an exemption request.'})
            if not (data.get('exemption_attained_at') or '').strip():
                raise serializers.ValidationError(
                    {'exemption_attained_at': 'Institution where the credit was earned is required.'}
                )
        return data

# =========================================Additionsl qualifficaations ===================================

class AdditionalQualifficationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdditionalQualifications
        fields = '__all__'


class EmailTemplateSerializer(serializers.ModelSerializer):
    placeholders = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = [
            "id",
            "key",
            "name",
            "description",
            "subject_template",
            "body_template_html",
            "is_active",
            "placeholders",
            "updated_at",
        ]

    def get_placeholders(self, obj):
        from admissions.email_templates import get_template_definition

        definition = get_template_definition(obj.key)
        return definition.get("placeholders", []) if definition else []


class EmailTemplateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["subject_template", "body_template_html", "is_active"]


class WeeklyReportSettingsSerializer(serializers.ModelSerializer):
    schedule_day_label = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyReportSettings
        fields = [
            "is_enabled",
            "schedule_day",
            "schedule_day_label",
            "schedule_hour",
            "schedule_minute",
            "last_sent_at",
            "last_sent_summary",
            "updated_at",
        ]
        read_only_fields = ["last_sent_at", "last_sent_summary", "updated_at"]

    def get_schedule_day_label(self, obj):
        return dict(WeeklyReportSettings.WEEKDAY_CHOICES).get(obj.schedule_day, "")


class WeeklyReportRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyReportRecipient
        fields = [
            "id",
            "email",
            "name",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

# ============================Program choices========================================
class ApplicationProgramChoiceSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source='program.name', read_only=True)
    code = serializers.CharField(source='program.code', read_only=True)
    program_id = serializers.IntegerField(source='program.id')

    class Meta:
        model = ApplicationProgramChoice
        fields = ['id', 'application', 'choice_order', 'program_name', 'code', 'program_id']
