from rest_framework import serializers
from .models import *
from admissions.serializers import *

class ApplicationFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationFee
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['academic_level'] = AcademicLevelSerializer(instance.academic_level.all(), many=True).data
        response['admission_period'] = BatchSerializer(instance.admission_period).data
        return response