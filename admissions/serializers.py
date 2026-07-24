from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import *
from accounts.serializers import UserSerializer, CampusSerializer
from Programs.serializers import ProgramSerializer
from .utils.application_programs_display import ordered_programs_for_application
from .utils.academic_year import get_registered_academic_year_label

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
class FacultySerializer(serializers.ModelSerializer):
    class Meta:
        model = Faculty
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        return response
    
# admissions
class AdmittedStudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmittedStudent
        fields = '__all__'

    @staticmethod
    def _sync_programme_enrollment_batch(admitted):
        """Keep academic enrollment cohort and specialization aligned with admission."""
        from Programs.models import StudentProgrammeEnrollment

        intended_id = admitted.intended_program_batch_id
        spec_name = (
            admitted.admitted_specialization.name
            if admitted.admitted_specialization_id
            else None
        )
        try:
            spe = StudentProgrammeEnrollment.objects.get(student=admitted)
        except StudentProgrammeEnrollment.DoesNotExist:
            return
        update_fields = []
        if intended_id and (
            spe.program_batch_id != intended_id
            or spe.program_id != admitted.admitted_program_id
        ):
            spe.program_batch_id = intended_id
            if spe.program_id != admitted.admitted_program_id:
                spe.program_id = admitted.admitted_program_id
            update_fields.extend(["program_batch", "program"])
        if spec_name and spe.specialization != spec_name:
            spe.specialization = spec_name
            update_fields.append("specialization")
        if update_fields:
            update_fields.append("updated_at")
            spe.save(update_fields=update_fields)

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
        from admissions.placement_sync import regenerate_reg_no_for_admission

        old_program_id = instance.admitted_program_id
        old_campus_id = instance.admitted_campus_id
        old_study_mode = (instance.study_mode or "").strip()
        old_reg_no = (instance.reg_no or "").strip()
        reg_no_provided = "reg_no" in validated_data

        placement_touch = any(
            key in validated_data
            for key in ("admitted_program", "admitted_campus", "study_mode")
        )
        # Placement changes must never rewrite SchoolPay codes.
        if placement_touch:
            validated_data.pop("schoolpay_code", None)
            validated_data.pop("is_registered_with_schoolpay", None)

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
        # Reg numbers encode campus / programme / study mode. Regenerate when
        # placement changed and the client did not already supply a new reg_no.
        if placement_changed and (
            not reg_no_provided or (admitted.reg_no or "").strip() == old_reg_no
        ):
            regenerate_reg_no_for_admission(admitted, sync_portal=True)
            admitted.refresh_from_db(fields=["reg_no"])

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

    def get_academic_batch(self, obj):
        from Programs.program_batch_resolution import format_program_batch_display

        try:
            enrollment = obj.programme_enrollment
        except Exception:
            enrollment = None
        if enrollment is not None and enrollment.program_batch_id:
            return format_program_batch_display(enrollment.program_batch)
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

    def _wallet_fields(self, obj):
        from payments.utils.tuition_ledger_linking import schoolpay_wallet_api_fields

        return schoolpay_wallet_api_fields(obj)

    def get_schoolpay_payment_code_locked(self, obj):
        return self._wallet_fields(obj)["schoolpay_payment_code_locked"]

    def get_schoolpay_ledger_total_ugx(self, obj):
        return self._wallet_fields(obj)["schoolpay_ledger_total_ugx"]

    def get_schoolpay_payment_warning(self, obj):
        return self._wallet_fields(obj)["schoolpay_payment_warning"]

    def _commitment_totals(self, obj):
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
    date_of_birth = serializers.DateField(source="application.date_of_birth", read_only=True)
    nationality = serializers.CharField(source="application.nationality", default="", read_only=True)
    program = serializers.CharField(source="admitted_program.name", default="", read_only=True)
    program_id = serializers.IntegerField(source="admitted_program_id", read_only=True)
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
            "physical_documents_verified",
            "physical_documents_verified_at",
            "registration_stage",
            "registration_stage_label",
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

    def get_academic_batch(self, obj):
        from Programs.program_batch_resolution import format_program_batch_display

        try:
            enrollment = obj.programme_enrollment
        except Exception:
            enrollment = None
        if enrollment is not None and enrollment.program_batch_id:
            return format_program_batch_display(enrollment.program_batch)
        intended = getattr(obj, "intended_program_batch", None)
        if intended is not None and getattr(intended, "pk", None):
            return format_program_batch_display(intended)
        return "—"

    def get_academic_batch_id(self, obj):
        try:
            enrollment = obj.programme_enrollment
        except Exception:
            enrollment = None
        if enrollment is not None and enrollment.program_batch_id:
            return enrollment.program_batch_id
        intended = getattr(obj, "intended_program_batch", None)
        if intended is not None and getattr(intended, "pk", None):
            return intended.pk
        return None

    def _enrollment(self, obj):
        try:
            return obj.programme_enrollment
        except Exception:
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

    def get_registration_stage(self, obj):
        if obj.physical_documents_verified:
            return "docs_verified"
        if obj.accounts_registration_cleared:
            return "awaiting_docs"
        if obj.admission_fee_paid:
            return "awaiting_accounts"
        return "unpaid"

    def get_registration_stage_label(self, obj):
        return {
            "unpaid": "1. Payment pending",
            "awaiting_accounts": "2. Awaiting Accounts clear",
            "awaiting_docs": "3. Awaiting AR (documents)",
            "docs_verified": "Cleared — Accounts + AR done",
        }.get(self.get_registration_stage(obj), "—")


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
    accounts_registration_cleared_by_name = serializers.SerializerMethodField()
    physical_documents_verified_by_name = serializers.SerializerMethodField()

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
            "accounts_registration_cleared_by_name",
            "physical_documents_notes",
            "physical_documents_verified_by_name",
        ]

    def get_passport_photo(self, obj):
        app = obj.application
        if not app or not getattr(app, "passport_photo", None):
            return None
        try:
            return app.passport_photo.url
        except ValueError:
            return None

    def get_accounts_registration_cleared_by_name(self, obj):
        u = getattr(obj, "accounts_registration_cleared_by", None)
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

        response.update(schoolpay_wallet_api_fields(instance))
        return response
    
# notification serializers
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalNotification
        fields = '__all__'


# ── Admission Change Request ──────────────────────────────────────────────────
class ExemptionRequestLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExemptionRequestLine
        fields = [
            "id",
            "curriculum_line",
            "course_code",
            "course_name",
            "year_of_study",
            "term_number",
        ]


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
    exemption_lines = ExemptionRequestLineSerializer(many=True, read_only=True)
    form_fee_paid = serializers.SerializerMethodField()

    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'id', 'change_type', 'change_type_display', 'status', 'status_display',
            'student_name', 'student_id', 'admitted_student_pk',
            'current_program_name', 'current_campus_name', 'current_study_mode',
            'new_program_name', 'new_campus_name', 'new_study_mode',
            'requested_year', 'requested_semester',
            'reason', 'review_notes', 'reviewed_by_name', 'reviewed_at', 'created_at',
            'exemption_lines', 'form_fee_charge_id', 'form_fee_paid_at', 'form_fee_paid',
        ]

    def get_student_name(self, obj):
        try:
            return obj.admitted_student.application.full_name
        except Exception:
            return None

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return None

    def get_form_fee_paid(self, obj):
        if obj.change_type != "exemption":
            return None
        return bool(obj.form_fee_paid_at)


class AdmissionChangeRequestCreateSerializer(serializers.ModelSerializer):
    """Write serializer — student submits a change request."""
    curriculum_line_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        write_only=True,
    )

    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'change_type', 'new_program', 'new_campus', 'new_study_mode',
            'requested_year', 'requested_semester', 'reason',
            'curriculum_line_ids',
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
            ids = data.get('curriculum_line_ids') or []
            if not ids:
                raise serializers.ValidationError(
                    {'curriculum_line_ids': 'Select at least one course unit to exempt.'}
                )
            if not (data.get('reason') or '').strip():
                raise serializers.ValidationError({'reason': 'Reason is required for an exemption request.'})
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
