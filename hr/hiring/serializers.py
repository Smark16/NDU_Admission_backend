from rest_framework import serializers
from .models import *
from hr.staff.serializers import DepartmentSerializer

class JobOpeningSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = '__all__'

class ListJobOpeningSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['department'] = DepartmentSerializer(instance.department).data
        return response
    
# Serializer for JobApplication
class JobApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobApplication
        fields = '__all__'

class ListApplicationSerilaizer(serializers.ModelSerializer):
    department = serializers.CharField(source='job_opening.department.name', read_only=True)
    position = serializers.CharField(source='job_opening.title', read_only=True)
    class Meta:
        model = JobApplication
        fields = '__all__'

# job posiitons
class JobPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = ['id', 'title']

# Serializer for Interview
class InterviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interview
        fields = '__all__'

# hired candidates
class HiredCandidatesSerializer(serializers.ModelSerializer):
    department = serializers.CharField(source='job_opening.department.name', read_only=True)
    employment_type = serializers.CharField(source='job_opening.employment_type', read_only=True)
    position = serializers.CharField(source='job_opening.title', read_only=True)
    class Meta:
        model = JobApplication
        fields = ['id', 'full_name', 'email', 'position', 'employment_type', 'department', 'status']