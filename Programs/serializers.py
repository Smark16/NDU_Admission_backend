from rest_framework import serializers
from .models import *
from admissions.models import Faculty
from accounts.serializers import CampusSerializer

# programs
class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        # response['academic_level'] = AcademicLevelSerializer(instance.academic_level).data
        # response['faculty'] = FacultySerializer(instance.faculty).data
        return response
    
# list programs
class ListProgramsSerializer(serializers.ModelSerializer):
    faculty = serializers.CharField(source='faculty.name', read_only=True, allow_null=True)
    academic_level = serializers.CharField(source='academic_level.name', read_only=True)
    
    # This shows the string representation of each campus (usually campus.name)
    # campuses = serializers.StringRelatedField(many=True, read_only=True)

    class Meta:
        model = Program
        fields = [
            'id', 'name', 'code', 'faculty', 'academic_level',
            'campuses', 'min_years', 'max_years', 'is_active',
            'created_at', 'updated_at','short_form'
        ]
    
    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        return response

# bulk upload serializer
class BulkUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = BulkUploadPrograms
        fields = '__all__'