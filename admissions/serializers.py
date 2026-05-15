from rest_framework import serializers
from .models import *
from accounts.serializers import UserSerializer, CampusSerializer
from Programs.serializers import ProgramSerializer
from .utils.application_programs_display import ordered_programs_for_application

# serializers

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

    def get_programs(self, obj):
        return ProgramSerializer(ordered_programs_for_application(obj), many=True).data

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
            "status",
        ]

class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['reviewed_by'] = UserSerializer(instance.reviewed_by).data
        response['batch'] = BatchSerializer(instance.batch).data
        response['campus'] = CampusSerializer(instance.campus).data
        response['applicant'] = UserSerializer(instance.applicant).data
        response['programs'] = ProgramSerializer(
            ordered_programs_for_application(instance), many=True
        ).data
        return response

# list serializer (main application queue — excludes staff wizard direct entries)
class ListApplicationsSerializer(serializers.ModelSerializer):
    academic_level = serializers.CharField(source="academic_level.name", read_only=True)
    batch = serializers.CharField(source="batch.name", read_only=True)
    campus = serializers.CharField(source="campus.name", read_only=True)

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
        ]


class AllApplicationsReportSerializer(serializers.ModelSerializer):
    academic_level = serializers.SerializerMethodField()
    batch = serializers.SerializerMethodField()
    campus = serializers.SerializerMethodField()
    programs = serializers.SerializerMethodField()
    faculty = serializers.SerializerMethodField()

    def get_academic_level(self, obj):
        try:
            return obj.academic_level.name if obj.academic_level_id and obj.academic_level else ""
        except Exception:
            return ""

    def get_batch(self, obj):
        try:
            return obj.batch.name if obj.batch_id and obj.batch else ""
        except Exception:
            return ""

    def get_campus(self, obj):
        try:
            return obj.campus.name if obj.campus_id and obj.campus else ""
        except Exception:
            return ""

    def get_programs(self, obj):
        try:
            return ", ".join([p.name for p in ordered_programs_for_application(obj)])
        except Exception:
            return ""

    def get_faculty(self, obj):
        names = []
        try:
            for p in ordered_programs_for_application(obj):
                fac = getattr(p, "faculty", None)
                if fac is not None:
                    try:
                        names.append(fac.name)
                    except Exception:
                        continue
        except Exception:
            return ""
        return ", ".join(dict.fromkeys(names))

    def get_entered_by(self, obj):
        try:
            if getattr(obj, "is_direct_entry", False) and getattr(obj, "entered_by_id", None):
                eb = obj.entered_by
                if eb is None:
                    return "Staff"
                name = f"{eb.first_name or ''} {eb.last_name or ''}".strip()
                return name or getattr(eb, "username", "") or str(eb.pk)
        except Exception:
            return "Staff"
        return "Online"

    entered_by = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "gender",
            "academic_level",
            "batch",
            "campus",
            "programs",
            "faculty",
            "status",
            "created_at",
            "is_direct_entry",
            "entered_by",
            "program_choices_confirmed_at",
            "program_choices_verification_sent_at",
        ]

# detail serializer
class ApplicationDetailSerializer(serializers.ModelSerializer):
    reviewed_by = serializers.CharField(source='reviewed_by.full_name', read_only=True, allow_null=True)
    revoked_by = serializers.CharField(source='revoked_by.full_name', read_only=True, allow_null=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name','middle_name', 'date_of_birth', 'gender', 'nationality', 'phone', 'email',
                  'batch', "nin", "passport_number","disabled", 'olevel_school', 'olevel_year', 'alevel_school', 'alevel_year', 'address',
                  'middle_name', 'next_of_kin_name', 'next_of_kin_contact', 'next_of_kin_relationship', 'revoked_by', 'is_revoked','revocation_reason',
                  'status', 'application_fee_amount','application_fee_paid', 'created_at', 'reviewed_at', 'passport_photo','reviewed_by',
                  'program_choices_confirmed_at', 'program_choices_verification_sent_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["programs"] = [
            {"id": p.id, "name": p.name}
            for p in ordered_programs_for_application(instance)
        ]
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
        """Keep academic enrollment cohort aligned with ``intended_program_batch``."""
        from Programs.models import StudentProgrammeEnrollment

        intended_id = admitted.intended_program_batch_id
        if not intended_id:
            return
        try:
            spe = StudentProgrammeEnrollment.objects.get(student=admitted)
        except StudentProgrammeEnrollment.DoesNotExist:
            return
        if spe.program_batch_id == intended_id and spe.program_id == admitted.admitted_program_id:
            return
        update_fields = ['program_batch', 'updated_at']
        spe.program_batch_id = intended_id
        if spe.program_id != admitted.admitted_program_id:
            spe.program_id = admitted.admitted_program_id
            update_fields.insert(0, 'program')
        spe.save(update_fields=update_fields)

    def create(self, validated_data):
        from Programs.program_batch_resolution import resolve_default_program_batch_for_program

        if validated_data.get('intended_program_batch') is None:
            prog = validated_data.get('admitted_program')
            if prog is not None:
                default_pb = resolve_default_program_batch_for_program(prog)
                if default_pb is not None:
                    validated_data['intended_program_batch'] = default_pb
        admitted = super().create(validated_data)
        self._sync_programme_enrollment_batch(admitted)
        return admitted

    def update(self, instance, validated_data):
        from Programs.program_batch_resolution import resolve_default_program_batch_for_program

        prog = validated_data.get('admitted_program', instance.admitted_program)

        if 'intended_program_batch' in validated_data and validated_data['intended_program_batch'] is None:
            default_pb = resolve_default_program_batch_for_program(prog) if prog is not None else None
            validated_data['intended_program_batch'] = default_pb
        elif instance.intended_program_batch_id is None and 'intended_program_batch' not in validated_data:
            default_pb = resolve_default_program_batch_for_program(prog) if prog is not None else None
            if default_pb is not None:
                validated_data['intended_program_batch'] = default_pb

        admitted = super().update(instance, validated_data)
        self._sync_programme_enrollment_batch(admitted)
        return admitted

    def validate(self, attrs):
        if 'intended_program_batch' in attrs:
            intended = attrs['intended_program_batch']
        elif self.instance is not None:
            intended = self.instance.intended_program_batch
        else:
            intended = None

        program = attrs.get('admitted_program')
        if program is None and self.instance is not None:
            program = self.instance.admitted_program

        if intended is not None and program is not None:
            if intended.program_id != program.id:
                raise serializers.ValidationError({
                    'intended_program_batch': (
                        'Selected academic batch must belong to the admitted programme.'
                    ),
                })
        return attrs

class AdmittedStudentListSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='application.applicant.get_full_name', read_only=True)
    program = serializers.CharField(source='admitted_program.name', read_only=True)
    faculty = serializers.SerializerMethodField()  
    campus = serializers.CharField(source='admitted_campus.name', read_only=True)
    batch = serializers.CharField(source='admitted_batch.name', default='__', read_only=True)
    status = serializers.CharField(source='application.status', read_only=True)
    admission_letter_pdf = serializers.SerializerMethodField()
    # Optional registrar workflow (not on all DBs — default so UI stays usable)
    is_approved = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    approved_at = serializers.SerializerMethodField()

    class Meta:
        model = AdmittedStudent
        fields = [
            'id',
            'student_id',
            'reg_no',
            'schoolpay_code',
            'is_registered_with_schoolpay',
            'name',
            'program',
            'faculty',
            'campus',
            'batch',
            'admission_date',
            'is_registered',
            'application',
            'is_admitted',
            'admitted_by',
            'status',
            'admission_letter_pdf',
            'is_approved',
            'approved_by_name',
            'approved_at',
        ]

    def get_faculty(self, obj):
        if not obj.admitted_program:
            return "__"
        if not obj.admitted_program.faculty:
            return "__"
        return obj.admitted_program.faculty.name

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
            'application',
            'is_registered',
            'registration_date',
            'intended_program_batch',
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['admitted_program'] = ProgramSerializer(instance.admitted_program).data
        response['admitted_campus'] = CampusSerializer(instance.admitted_campus).data
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
        return response
    
# notification serializers
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalNotification
        fields = '__all__'


# ── Admission Change Request ──────────────────────────────────────────────────
class AdmissionChangeRequestSerializer(serializers.ModelSerializer):
    """Read serializer — expands FK names for display."""
    change_type_display = serializers.CharField(source='get_change_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.SerializerMethodField()
    student_id = serializers.CharField(source='admitted_student.student_id', read_only=True)
    current_program_name = serializers.CharField(source='current_program.name', read_only=True, default=None)
    current_campus_name = serializers.CharField(source='current_campus.name', read_only=True, default=None)
    new_program_name = serializers.CharField(source='new_program.name', read_only=True, default=None)
    new_campus_name = serializers.CharField(source='new_campus.name', read_only=True, default=None)
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'id', 'change_type', 'change_type_display', 'status', 'status_display',
            'student_name', 'student_id',
            'current_program_name', 'current_campus_name', 'current_study_mode',
            'new_program_name', 'new_campus_name', 'new_study_mode',
            'requested_year', 'requested_semester',
            'reason', 'review_notes', 'reviewed_by_name', 'reviewed_at', 'created_at',
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


class AdmissionChangeRequestCreateSerializer(serializers.ModelSerializer):
    """Write serializer — student submits a change request."""
    class Meta:
        model = AdmissionChangeRequest
        fields = [
            'change_type', 'new_program', 'new_campus', 'new_study_mode',
            'requested_year', 'requested_semester', 'reason',
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

# ============================Program choices========================================
class ApplicationProgramChoiceSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source='program.name', read_only=True)
    code = serializers.CharField(source='program.code', read_only=True)
    program_id = serializers.IntegerField(source='program.id')

    class Meta:
        model = ApplicationProgramChoice
        fields = ['id', 'application', 'choice_order', 'program_name', 'code', 'program_id']
