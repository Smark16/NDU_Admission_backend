from rest_framework import serializers
from .models import *
from accounts.serializers import UserSerializer, CampusSerializer
from Programs.serializers import ProgramSerializer

# serializers

# batch
class BatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Batch
        fields = '__all__'

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

# single application
class SingleApplicationSerializer(serializers.ModelSerializer):
    programs = ProgramSerializer(read_only=True, many=True)
    campus = CampusSerializer(read_only=True)
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'email', 'phone', 'date_of_birth', 'nationality', 'gender',
                  'programs', 'campus', 'application_fee_paid', 'school_pay_reference', 'entered_by']

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
        response['programs'] = ProgramSerializer(instance.programs.all(), many=True).data
        return response

# list serializer
class ListApplicationsSerializer(serializers.ModelSerializer):
    programs = serializers.SerializerMethodField()
    academic_level = serializers.CharField(source='academic_level.name', read_only=True)

    def get_programs(self, obj):
        return [{'id': p.id, 'name': p.name} for p in obj.programs.all()]

    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'gender', 'status', 'created_at', 'email', 'programs', 'academic_level']


class AllApplicationsReportSerializer(serializers.ModelSerializer):
    academic_level = serializers.CharField(source='academic_level.name', read_only=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    campus = serializers.CharField(source='campus.name', read_only=True)
    programs = serializers.SerializerMethodField()
    faculty = serializers.SerializerMethodField()

    def get_programs(self, obj):
        return ', '.join([p.name for p in obj.programs.all()])

    def get_faculty(self, obj):
        names = [p.faculty.name for p in obj.programs.all() if p.faculty]
        return ', '.join(dict.fromkeys(names))  # distinct, preserve order

    def get_entered_by(self, obj):
        if obj.is_direct_entry and obj.entered_by:
            return f"{obj.entered_by.first_name} {obj.entered_by.last_name}".strip() or obj.entered_by.username
        return "Online"

    entered_by = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'email', 'gender',
                  'academic_level', 'batch', 'campus', 'programs', 'faculty',
                  'status', 'created_at', 'is_direct_entry', 'entered_by']

# detail serializer
class ApplicationDetailSerializer(serializers.ModelSerializer):
    reviewed_by = serializers.CharField(source='reviewed_by.full_name', read_only=True, allow_null=True)
    entered_by = serializers.CharField(source='entered_by.full_name', read_only=True, allow_null=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    programs = serializers.SerializerMethodField()

    def get_programs(self, obj):
        return [{"id": p.id, "name": p.name, "code": p.code} for p in obj.programs.all()]

    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'date_of_birth', 'gender', 'nationality', 'phone', 'email',
                  'batch', 'programs', 'nin', 'passport_number', 'disabled', 'olevel_school', 'olevel_year', 'alevel_school', 'alevel_year', 'address',
                  'status', 'application_fee_amount', 'application_fee_paid', 'school_pay_reference',
                  'application_reference', 'created_at', 'reviewed_at', 'passport_photo', 'reviewed_by', 'entered_by']
    
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

class AdmittedStudentListSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='application.applicant.get_full_name', read_only=True)
    program = serializers.CharField(source='admitted_program.name', read_only=True)
    faculty = serializers.SerializerMethodField()  
    campus = serializers.CharField(source='admitted_campus.name', read_only=True)
    batch = serializers.CharField(source='admitted_batch.name', default='__', read_only=True)

    class Meta:
        model = AdmittedStudent
        fields = [
            'id',
            'student_id',
            'reg_no',
            'name',
            'program',
            'faculty',
            'campus',
            'batch',
            'admission_date',
            'is_registered',
            'application',
            'is_admitted'
        ]

    def get_faculty(self, obj):
        if not obj.admitted_program:
            return "__"
        if not obj.admitted_program.faculty:
            return "__"
        return obj.admitted_program.faculty.name
    
# admission detail serializer
class AdmissionDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmittedStudent
        fields = ['id', 'student_id', 'reg_no','study_mode', 'admission_notes', 'admitted_program', 'admitted_campus', 'application']

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['admitted_program'] = ProgramSerializer(instance.admitted_program).data
        response['admitted_campus'] = CampusSerializer(instance.admitted_campus).data
        return response
    
# notification serializers
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalNotification
        fields = '__all__'

# =========================================Additionsl qualifficaations ===================================

class AdditionalQualifficationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdditionalQualifications
        fields = '__all__'
