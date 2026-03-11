from rest_framework import serializers
from .models import *
from admissions.serializers import *

# application serilazer
class ApplicationFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationFee
        fields = '__all__'
  
# list serializer
class ListApplicationFeeSerializer(serializers.ModelSerializer):
    admission_period = serializers.CharField(source="admission_period.name")
    admission_id = serializers.IntegerField(source="admission_period.id")
    academic_year = serializers.CharField(source="admission_period.academic_year")
    class Meta:
        model = ApplicationFee
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['academic_level'] = AcademicLevelSerializer(instance.academic_level.all(), many=True).data
        return response

# ==============payments==============
class ApplicationPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationPayment
        fields = '__all__'
