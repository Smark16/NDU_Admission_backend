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

        # Auto-detect file type
        ext = file_obj.name.rsplit('.', 1)[-1].lower() if '.' in file_obj.name else 'docx'
        file_type = 'pdf' if ext == 'pdf' else 'docx'

        doc = OfferLetterTemplate(
            file=file_obj,
            name=file_obj.name,
            file_type=file_type,
            **validated_data
        )
        doc.save()

        if programs_data:
            doc.programs.set(programs_data)

        doc.file_url = request.build_absolute_uri(doc.file.url)
        doc.save(update_fields=['file_url'])

        return doc

    def update(self, instance, validated_data):
        request = self.context.get('request')
        if not request:
            raise serializers.ValidationError("Request context is missing.")

        new_file = validated_data.get('file')
        programs_data = validated_data.pop('programs', None)

        instance.name = validated_data.get('name', new_file.name if new_file else instance.name)
        instance.status = validated_data.get('status', instance.status)
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.hall_of_residence = validated_data.get('hall_of_residence', instance.hall_of_residence)

        if new_file:
            instance.file = new_file
            ext = new_file.name.rsplit('.', 1)[-1].lower() if '.' in new_file.name else 'docx'
            instance.file_type = 'pdf' if ext == 'pdf' else 'docx'
            # Reset field positions when template file is replaced
            instance.field_positions = {}

        instance.save()

        if programs_data is not None:
            instance.programs.set(programs_data)

        if new_file:
            instance.file_url = request.build_absolute_uri(instance.file.url)
            instance.save(update_fields=['file_url'])

        return instance