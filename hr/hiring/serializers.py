from rest_framework import serializers
from .models import *
from hr.staff.serializers import DepartmentSerializer

class JobOpeningSerializer(serializers.ModelSerializer):
    # Optional on update so existing PDF is kept when the client does not re-upload.
    description = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = JobOpening
        fields = '__all__'

    def update(self, instance, validated_data):
        # Never wipe an existing PDF when description is omitted / empty.
        if "description" in validated_data and not validated_data.get("description"):
            validated_data.pop("description")
        return super().update(instance, validated_data)

class ListJobOpeningSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['department'] = DepartmentSerializer(instance.department).data
        # Applicant_UI expects `description` to be a downloadable absolute URL.
        request = self.context.get('request')
        if instance.description:
            url = instance.description.url
            response['description'] = request.build_absolute_uri(url) if request else url
            response['description_name'] = (
                instance.description.name.rsplit("/", 1)[-1]
                if instance.description.name
                else "job_description.pdf"
            )
        else:
            response['description'] = None
            response['description_name'] = None
        response['description_url'] = response['description']
        return response
    
# Serializer for JobApplication
class JobApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobApplication
        fields = '__all__'

class ListApplicationSerilaizer(serializers.ModelSerializer):
    department = serializers.CharField(source='job_opening.department.name', read_only=True)
    position = serializers.CharField(source='job_opening.title', read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = '__all__'

    def get_full_name(self, obj):
        return obj.get_full_name()


# job posiitons
class JobPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = ['id', 'title']


class ApplicationDetailSerializer(serializers.ModelSerializer):
    department = serializers.CharField(source='job_opening.department.name', read_only=True)
    position = serializers.CharField(source='job_opening.title', read_only=True)
    full_name = serializers.SerializerMethodField()
    education = serializers.SerializerMethodField()
    employment = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()
    certificates = serializers.SerializerMethodField()
    references_list = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = [
            'id', 'reference', 'full_name', 'first_name', 'last_name', 'email', 'phone',
            'title', 'current_address', 'religious_affiliation', 'marital_status', 'dob',
            'brief_description', 'skills', 'status', 'current_stage', 'application_date',
            'has_declared', 'position', 'department', 'job_opening',
            'education', 'employment', 'projects', 'certificates', 'references_list',
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_education(self, obj):
        return list(obj.educationhistory_set.values('institution', 'award', 'start_date', 'end_date'))

    def get_employment(self, obj):
        return list(obj.employment_set.values(
            'current_employer', 'current_position', 'start_date', 'end_date', 'years_of_experience', 'duties'
        ))

    def get_projects(self, obj):
        return list(obj.projects_set.values('name', 'link', 'description'))

    def get_certificates(self, obj):
        return list(obj.certificates_and_training_set.values('certificate_name', 'institution', 'date_obtained'))

    def get_references_list(self, obj):
        return list(obj.references_set.values('name', 'job_position', 'email', 'phone'))

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