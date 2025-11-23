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
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'gender', 'status', 'created_at', 'email']

# detail serializer
class ApplicationDetailSerializer(serializers.ModelSerializer):
    reviewed_by = serializers.CharField(source='reviewed_by.full_name', read_only=True, allow_null=True)
    batch = serializers.CharField(source='batch.name', read_only=True)
    class Meta:
        model = Application
        fields = ['id', 'first_name', 'last_name', 'date_of_birth', 'gender', 'nationality', 'phone', 'email',
                  'batch', 'olevel_school', 'olevel_year', 'alevel_school', 'alevel_year', 'address',
                  'status', 'application_fee_amount', 'created_at', 'reviewed_at', 'passport_photo','reviewed_by']
    
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
    class Meta:
        model = ApplicationDocument
        fields = '__all__'


# faculty serializer
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
            'is_admitted'
        ]

    def get_faculty(self, obj):
        if not obj.admitted_program:
            return "__"
        if not obj.admitted_program.faculty:
            return "__"
        return obj.admitted_program.faculty.name
    
# notification serializers
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortalNotification
        fields = '__all__'
