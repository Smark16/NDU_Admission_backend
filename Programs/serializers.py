from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from .catalog_reference_sync import sync_catalog_unit_references
from .models import *
from admissions.models import Faculty
from accounts.serializers import CampusSerializer


# ---------------------------------------------------------------------------
# Program Specialization serializer
# ---------------------------------------------------------------------------

class ProgramSpecializationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgramSpecialization
        fields = ['id', 'program', 'name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        v = (value or '').strip()
        if not v:
            raise serializers.ValidationError('Specialization name is required.')
        return v

    def validate(self, attrs):
        program = attrs.get('program', getattr(self.instance, 'program', None))
        name = attrs.get('name', getattr(self.instance, 'name', None))
        if program and name:
            qs = ProgramSpecialization.objects.filter(
                program=program, name__iexact=name
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'name': f"A specialization named '{name}' already exists for this programme."}
                )
        return attrs


class ProgramCurriculumVersionSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)
    program_short_form = serializers.CharField(source="program.short_form", read_only=True)
    lines_count = serializers.IntegerField(source="lines.count", read_only=True)
    effective_minimum_graduation_load = serializers.SerializerMethodField(read_only=True)
    graduation_load_inherits_from_programme = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ProgramCurriculumVersion
        fields = [
            "id",
            "program",
            "program_name",
            "program_short_form",
            "name",
            "description",
            "is_active",
            "is_default",
            "minimum_graduation_load",
            "effective_minimum_graduation_load",
            "graduation_load_inherits_from_programme",
            "lines_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "lines_count",
            "effective_minimum_graduation_load",
            "graduation_load_inherits_from_programme",
        ]

    def get_effective_minimum_graduation_load(self, obj):
        return str(obj.effective_minimum_graduation_load)

    def get_graduation_load_inherits_from_programme(self, obj):
        return obj.minimum_graduation_load is None

    def validate_minimum_graduation_load(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Minimum graduation load cannot be negative.")
        return value

    def validate_name(self, value):
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("Version name is required.")
        return v

    def validate(self, attrs):
        program = attrs.get("program", getattr(self.instance, "program", None))
        name = attrs.get("name", getattr(self.instance, "name", None))
        if program and name:
            qs = ProgramCurriculumVersion.objects.filter(program=program, name__iexact=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"name": f"A curriculum version named '{name}' already exists for this programme."}
                )
        return attrs


# programs
class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = '__all__'

    def validate(self, attrs):
        has_spec = attrs.get('has_specialization')
        if has_spec is None and self.instance:
            has_spec = getattr(self.instance, 'has_specialization', False)
        if not has_spec:
            return attrs

        try:
            from .specialization_rules import MSG_PROGRAM_ENTRY_FIELDS
            ey = attrs.get('specialization_entry_year')
            et = attrs.get('specialization_entry_term')
            if self.instance:
                if ey is None:
                    ey = getattr(self.instance, 'specialization_entry_year', None)
                if et is None:
                    et = getattr(self.instance, 'specialization_entry_term', None)
            if ey is None or et is None:
                raise serializers.ValidationError(MSG_PROGRAM_ENTRY_FIELDS)
        except ImportError:
            pass
        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response['campuses'] = CampusSerializer(instance.campuses.all(), many=True).data
        return response

# list programs
class ListProgramsSerializer(serializers.ModelSerializer):
    faculty = serializers.CharField(source='faculty.name', read_only=True, allow_null=True)
    academic_level = serializers.CharField(source='academic_level.name', read_only=True)

    class Meta:
        model = Program
        fields = [
            'id', 'name', 'code', 'short_form', 'faculty', 'academic_level',
            'campuses', 'min_years', 'max_years',
            'is_active', 'created_at', 'updated_at',
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


class CourseCatalogUnitSerializer(serializers.ModelSerializer):
    """Reusable academic catalog — no programme or semester linkage."""

    class Meta:
        model = CourseCatalogUnit
        fields = [
            "id",
            "code",
            "title",
            "description",
            "credit_units",
            "lecture_hours",
            "practical_hours",
            "tutorial_hours",
            "contact_hours",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        v = (value or "").strip().upper()
        if not v:
            raise serializers.ValidationError("Code is required.")
        if len(v) > 50:
            raise serializers.ValidationError("Code must be at most 50 characters.")
        return v

    def validate_credit_units(self, value):
        if value is None:
            raise serializers.ValidationError("Credit units are required.")
        d = Decimal(str(value))
        if d < 0 or d > Decimal("99.99"):
            raise serializers.ValidationError("Credit units must be between 0 and 99.99.")
        return d.quantize(Decimal("0.01"))

    def validate(self, attrs):
        lh = attrs.get("lecture_hours", getattr(self.instance, "lecture_hours", None)) or 0
        ph = attrs.get("practical_hours", getattr(self.instance, "practical_hours", None)) or 0
        th = attrs.get("tutorial_hours", getattr(self.instance, "tutorial_hours", None)) or 0
        contact = attrs.get("contact_hours", getattr(self.instance, "contact_hours", None))
        summed = int(lh) + int(ph) + int(th)
        if "contact_hours" in attrs and attrs["contact_hours"] is not None:
            if summed > 0 and int(attrs["contact_hours"]) < summed:
                raise serializers.ValidationError(
                    {
                        "contact_hours": (
                            "Contact hours cannot be less than lecture + practical + tutorial "
                            f"({summed}). Leave blank to auto-sum."
                        )
                    }
                )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        notice = getattr(instance, "_rename_notice", None)
        if notice:
            data["rename_notice"] = notice
        return data

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, "message_dict") else str(e))
        except IntegrityError:
            raise serializers.ValidationError({"code": "A catalog entry with this code already exists."})

    def update(self, instance, validated_data):
        previous_code = instance.code
        try:
            updated = super().update(instance, validated_data)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, "message_dict") else str(e))
        except IntegrityError:
            raise serializers.ValidationError({"code": "A catalog entry with this code already exists."})
        if previous_code != updated.code:
            notice = sync_catalog_unit_references(updated, previous_code=previous_code)
            setattr(updated, "_rename_notice", notice)
        return updated


class ProgramCurriculumLineSerializer(serializers.ModelSerializer):
    """Serializer for the programme curriculum mapping layer."""

    # Read-only convenience fields — avoids extra round-trips on the frontend
    catalog_course_detail = CourseCatalogUnitSerializer(source='catalog_course', read_only=True)
    program_name = serializers.CharField(source='program.name', read_only=True)
    program_short_form = serializers.CharField(source='program.short_form', read_only=True)
    curriculum_version_name = serializers.CharField(source='curriculum_version.name', read_only=True)

    class Meta:
        model = ProgramCurriculumLine
        fields = [
            'id',
            'program',
            'program_name',
            'program_short_form',
            'curriculum_version',
            'curriculum_version_name',
            'catalog_course',
            'catalog_course_detail',
            'year_of_study',
            'term_number',
            'course_type',
            'elective_group',
            'specialization',
            'sort_order',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_year_of_study(self, value):
        if value < 1:
            raise serializers.ValidationError("Year of study must be at least 1.")
        return value

    def validate_term_number(self, value):
        if value < 1:
            raise serializers.ValidationError("Term number must be at least 1.")
        return value

    def validate(self, attrs):
        program = attrs.get('program', getattr(self.instance, 'program', None))
        catalog_course = attrs.get('catalog_course', getattr(self.instance, 'catalog_course', None))
        year_of_study = attrs.get('year_of_study', getattr(self.instance, 'year_of_study', None))
        term_number = attrs.get('term_number', getattr(self.instance, 'term_number', None))
        curriculum_version = attrs.get('curriculum_version', getattr(self.instance, 'curriculum_version', None))

        if program and curriculum_version and curriculum_version.program_id != program.id:
            raise serializers.ValidationError(
                {'curriculum_version': 'Selected curriculum version does not belong to this programme.'}
            )

        # year must not exceed programme duration
        if program and year_of_study and year_of_study > program.max_years:
            raise serializers.ValidationError({
                'year_of_study': (
                    f"Year of study ({year_of_study}) exceeds this programme's "
                    f"max years ({program.max_years})."
                )
            })

        # term_number must be within the programme's calendar bounds
        if program and term_number:
            max_terms = program.max_terms_per_year
            if term_number not in range(1, max_terms + 1):
                raise serializers.ValidationError({
                    'term_number': (
                        f"Term number must be between 1 and {max_terms} "
                        f"for a {program.calendar_type}-based programme."
                    )
                })

        # duplicate slot check — surfaces a readable message before the DB constraint fires
        if program and catalog_course and year_of_study and term_number:
            qs = ProgramCurriculumLine.objects.filter(
                curriculum_version=curriculum_version,
                catalog_course=catalog_course,
                year_of_study=year_of_study,
                term_number=term_number,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    f"{catalog_course.code} is already mapped to this programme "
                    f"at Year {year_of_study} Term {term_number}."
                )

        # No track-specific lines before the programme's specialization entry point
        from .specialization_rules import has_complete_specialization_entry, is_before_specialization_entry

        specialization = attrs.get('specialization', getattr(self.instance, 'specialization', None))
        spec_value = (specialization or '').strip()
        if (
            program
            and program.has_specialization
            and has_complete_specialization_entry(program)
            and year_of_study is not None
            and term_number is not None
            and is_before_specialization_entry(program, int(year_of_study), int(term_number))
            and spec_value
        ):
            ey = program.specialization_entry_year
            et = program.specialization_entry_term
            raise serializers.ValidationError({
                'specialization': (
                    f"Track-specific courses are not allowed before specialization entry "
                    f"(Year {ey} Term {et}). Use a blank / shared course for all students in earlier terms."
                )
            })

        # specialization must be one of the programme's defined tracks (if defined)
        if spec_value and program:
            allowed = list(
                ProgramSpecialization.objects.filter(program=program, is_active=True)
                .values_list('name', flat=True)
            )
            if allowed:
                matched = next((a for a in allowed if a.lower() == spec_value.lower()), None)
                if not matched:
                    raise serializers.ValidationError({
                        'specialization': (
                            f"'{spec_value}' is not a defined specialization for this programme. "
                            f"Allowed values: {', '.join(allowed)}"
                        )
                    })
                # Normalize to the canonical casing stored in ProgramSpecialization
                attrs['specialization'] = matched

        return attrs

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                "A curriculum line with this programme / course / year / semester already exists."
            )

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                "A curriculum line with this programme / course / year / semester already exists."
            )


# ---------------------------------------------------------------------------
# Academic enrollment serializers
# ---------------------------------------------------------------------------

class StudentProgrammeEnrollmentSerializer(serializers.ModelSerializer):
    """Full read/write serializer used by admin endpoints."""

    # Read-only convenience fields
    student_id       = serializers.CharField(source='student.student_id',      read_only=True)
    student_name     = serializers.CharField(source='student.full_name',        read_only=True)
    program_name     = serializers.CharField(source='program.name',             read_only=True)
    program_short    = serializers.CharField(source='program.short_form',       read_only=True)
    batch_name       = serializers.CharField(source='program_batch.name',       read_only=True)
    curriculum_version_name = serializers.CharField(source='curriculum_version.name', read_only=True)
    calendar_type    = serializers.CharField(source='program.calendar_type',    read_only=True)
    enrolled_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentProgrammeEnrollment
        fields = [
            'id',
            'student', 'student_id', 'student_name',
            'program', 'program_name', 'program_short',
            'program_batch', 'batch_name',
            'curriculum_version', 'curriculum_version_name',
            'calendar_type',
            'current_year_of_study', 'current_term_number',
            'specialization',
            'status',
            'enrolled_at', 'enrolled_by', 'enrolled_by_name',
            'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'enrolled_at', 'created_at', 'updated_at']

    def get_enrolled_by_name(self, obj):
        if obj.enrolled_by:
            return obj.enrolled_by.get_full_name() or obj.enrolled_by.email
        return None

    def validate(self, attrs):
        from .specialization_rules import (
            normalize_specialization,
            resolve_specialization_for_program,
        )

        program = attrs.get('program', getattr(self.instance, 'program', None))

        if 'specialization' in attrs:
            spec_norm = normalize_specialization(attrs.get('specialization'))
            if not spec_norm:
                attrs['specialization'] = None
            elif program:
                matched, spec_err = resolve_specialization_for_program(program, spec_norm)
                if spec_err:
                    raise serializers.ValidationError({'specialization': spec_err})
                attrs['specialization'] = matched
            else:
                raise serializers.ValidationError(
                    {'specialization': 'Cannot validate specialization without a programme.'}
                )

        program       = attrs.get('program',       getattr(self.instance, 'program',       None))
        program_batch = attrs.get('program_batch', getattr(self.instance, 'program_batch', None))
        curriculum_version = attrs.get('curriculum_version', getattr(self.instance, 'curriculum_version', None))
        year          = attrs.get('current_year_of_study', getattr(self.instance, 'current_year_of_study', 1))
        term          = attrs.get('current_term_number',   getattr(self.instance, 'current_term_number',   1))

        if program and program_batch:
            if program_batch.program_id != program.id:
                raise serializers.ValidationError(
                    {'program_batch': 'This batch does not belong to the selected programme.'}
                )

        if program and year and year > program.max_years:
            raise serializers.ValidationError(
                {'current_year_of_study': f'Year {year} exceeds programme max years ({program.max_years}).'}
            )

        if program and term:
            max_terms = program.max_terms_per_year
            if term not in range(1, max_terms + 1):
                raise serializers.ValidationError(
                    {'current_term_number': f'Term {term} out of range for {program.calendar_type}-based programme (1–{max_terms}).'}
                )

        if not curriculum_version:
            if program_batch and program_batch.curriculum_version_id:
                attrs['curriculum_version'] = program_batch.curriculum_version
                curriculum_version = attrs['curriculum_version']
            elif program:
                default_version = resolve_program_default_curriculum_version(program)
                if default_version:
                    attrs['curriculum_version'] = default_version
                    curriculum_version = default_version

        if curriculum_version and program and curriculum_version.program_id != program.id:
            raise serializers.ValidationError(
                {'curriculum_version': 'This curriculum version does not belong to the selected programme.'}
            )

        return attrs


class StudentProgrammeEnrollmentReadSerializer(serializers.ModelSerializer):
    """Lightweight read-only serializer for the student-facing endpoint."""

    program_name  = serializers.CharField(source='program.name',       read_only=True)
    program_short = serializers.CharField(source='program.short_form', read_only=True)
    batch_name    = serializers.CharField(source='program_batch.name', read_only=True)
    curriculum_version_name = serializers.CharField(source='curriculum_version.name', read_only=True)
    calendar_type = serializers.CharField(source='program.calendar_type', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StudentProgrammeEnrollment
        fields = [
            'id',
            'program_name', 'program_short', 'batch_name', 'calendar_type',
            'curriculum_version_name',
            'current_year_of_study', 'current_term_number',
            'specialization',
            'status', 'status_display',
            'enrolled_at',
        ]
        read_only_fields = fields
