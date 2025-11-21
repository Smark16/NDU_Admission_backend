from rest_framework import serializers
from .models import *
from Programs.serializers import ProgramSerializer

# serializers

class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferLetterTemplate
        fields = '__all__'

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['programs'] = ProgramSerializer(instance.programs.all(), many=True).data
        return response

    def create(self, validated_data):
        request = self.context['request']
        file_obj = validated_data.pop('file')  # ← Remove file
        programs_data = validated_data.pop('programs', [])  # ← Extract programs

        # Create template
        doc = OfferLetterTemplate(
            file=file_obj,
            name=file_obj.name,
            **validated_data  # status, etc.
        )
        doc.save()

        # Set programs
        if programs_data:
            doc.programs.set(programs_data)

        # Save full URL
        doc.file_url = request.build_absolute_uri(doc.file.url)
        doc.save(update_fields=['file_url'])

        return doc

    def update(self, instance, validated_data):
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")

        new_file = validated_data.get('file')
        programs_data = validated_data.pop('programs', None)  # ← Extract

        # Update fields
        instance.name = validated_data.get('name', new_file.name if new_file else instance.name)
        instance.status = validated_data.get('status', instance.status)

        if new_file:
            instance.file = new_file

        instance.save()

        # Handle programs
        if programs_data is not None:
            instance.programs.set(programs_data)

        # Update file_url if file changed
        if new_file:
            instance.file_url = request.build_absolute_uri(instance.file.url)
            instance.save(update_fields=['file_url'])

        return instance