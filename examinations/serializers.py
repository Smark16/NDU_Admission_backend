from rest_framework import serializers

from .models import (
    AssessmentPolicy,
    AwardClassBand,
    AwardClassificationScheme,
    CourseUnitResult,
    ExamRetakeRegistration,
    ExamSession,
    GradeBand,
    GradeScale,
    MarksEntryWindow,
    ResultChangeRequest,
)


def _deactivate_active_for_level(model, academic_level_id, exclude_pk=None):
    qs = model.objects.filter(is_active=True, academic_level_id=academic_level_id)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    qs.update(is_active=False)


class AssessmentPolicySerializer(serializers.ModelSerializer):
    academic_level_name = serializers.CharField(
        source="academic_level.name", read_only=True, allow_null=True
    )

    class Meta:
        model = AssessmentPolicy
        fields = [
            "id",
            "name",
            "academic_level",
            "academic_level_name",
            "ca_max",
            "exam_weight",
            "min_ca_to_sit_exam",
            "pass_mark",
            "is_default",
            "is_active",
        ]


class AssessmentPolicyWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentPolicy
        fields = [
            "name",
            "academic_level",
            "ca_max",
            "exam_weight",
            "min_ca_to_sit_exam",
            "pass_mark",
            "is_default",
            "is_active",
        ]

    def validate(self, attrs):
        academic_level = attrs.get(
            "academic_level",
            getattr(self.instance, "academic_level", None) if self.instance else None,
        )
        is_default = attrs.get(
            "is_default",
            getattr(self.instance, "is_default", False) if self.instance else False,
        )
        if is_default and academic_level:
            raise serializers.ValidationError(
                {"is_default": "Global default cannot be tied to an academic level."}
            )
        if academic_level:
            qs = AssessmentPolicy.objects.filter(academic_level=academic_level)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "academic_level": (
                            f"A policy already exists for {academic_level.name}. "
                            "Edit that policy instead."
                        )
                    }
                )
        return attrs


class GradeBandSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeBand
        fields = ["id", "letter", "min_mark", "max_mark", "grade_point", "order"]


class GradeScaleListSerializer(serializers.ModelSerializer):
    band_count = serializers.IntegerField(source="bands.count", read_only=True)
    academic_level_name = serializers.CharField(
        source="academic_level.name", read_only=True, allow_null=True
    )

    class Meta:
        model = GradeScale
        fields = [
            "id",
            "name",
            "academic_level",
            "academic_level_name",
            "is_active",
            "band_count",
            "created_at",
        ]


class GradeBandWriteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = GradeBand
        fields = ["id", "letter", "min_mark", "max_mark", "grade_point", "order"]


class GradeScaleWriteSerializer(serializers.ModelSerializer):
    bands = GradeBandWriteSerializer(many=True, required=False)

    class Meta:
        model = GradeScale
        fields = ["name", "academic_level", "is_active", "bands"]

    def validate(self, attrs):
        academic_level = attrs.get(
            "academic_level",
            getattr(self.instance, "academic_level", None) if self.instance else None,
        )
        if academic_level:
            qs = GradeScale.objects.filter(academic_level=academic_level)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "academic_level": (
                            f"A grading scheme already exists for {academic_level.name}. "
                            "Edit that scheme instead."
                        )
                    }
                )
        bands = attrs.get("bands")
        if bands is None:
            if self.instance is None:
                raise serializers.ValidationError({"bands": "At least one grade band is required."})
            return attrs
        if not bands:
            raise serializers.ValidationError({"bands": "At least one grade band is required."})
        letters = [str(b.get("letter", "")).strip().upper() for b in bands if b.get("letter")]
        if len(letters) != len(set(letters)):
            raise serializers.ValidationError({"bands": "Duplicate grade letters are not allowed."})
        for idx, band in enumerate(bands):
            lo = band.get("min_mark")
            hi = band.get("max_mark")
            if lo is not None and hi is not None and lo > hi:
                raise serializers.ValidationError(
                    {
                        "bands": (
                            f"Band '{band.get('letter')}': min mark cannot exceed max mark."
                        )
                    }
                )
            band.setdefault("order", idx)
        return attrs

    def _sync_bands(self, scale: GradeScale, bands_data: list):
        keep_ids = {b["id"] for b in bands_data if b.get("id")}
        scale.bands.exclude(pk__in=keep_ids).delete()
        for idx, row in enumerate(bands_data):
            band_data = dict(row)
            band_id = band_data.pop("id", None)
            band_data["order"] = band_data.get("order", idx)
            if band_id:
                GradeBand.objects.filter(pk=band_id, grade_scale=scale).update(**band_data)
            else:
                GradeBand.objects.create(grade_scale=scale, **band_data)

    def create(self, validated_data):
        bands_data = validated_data.pop("bands")
        is_active = validated_data.get("is_active", False)
        level_id = validated_data.get("academic_level")
        level_pk = level_id.pk if level_id else None
        if is_active:
            _deactivate_active_for_level(GradeScale, level_pk)
        scale = GradeScale.objects.create(**validated_data)
        for idx, band_data in enumerate(bands_data):
            payload = {k: v for k, v in dict(band_data).items() if k != "id" and v is not None}
            payload["order"] = payload.get("order", idx)
            GradeBand.objects.create(grade_scale=scale, **payload)
        return scale

    def update(self, instance, validated_data):
        bands_data = validated_data.pop("bands", None)
        is_active = validated_data.get("is_active", instance.is_active)
        level = validated_data.get("academic_level", instance.academic_level)
        level_pk = level.pk if level else None
        if is_active:
            _deactivate_active_for_level(GradeScale, level_pk, exclude_pk=instance.pk)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if bands_data is not None:
            self._sync_bands(instance, [dict(b) for b in bands_data])
        return instance


class GradeScaleDetailSerializer(serializers.ModelSerializer):
    bands = GradeBandSerializer(many=True, read_only=True)
    academic_level_name = serializers.CharField(
        source="academic_level.name", read_only=True, allow_null=True
    )

    class Meta:
        model = GradeScale
        fields = [
            "id",
            "name",
            "academic_level",
            "academic_level_name",
            "is_active",
            "bands",
            "created_at",
        ]


class AwardClassBandSerializer(serializers.ModelSerializer):
    class Meta:
        model = AwardClassBand
        fields = ["id", "title", "min_cgpa", "order"]


class AwardSchemeListSerializer(serializers.ModelSerializer):
    band_count = serializers.IntegerField(source="bands.count", read_only=True)
    academic_level_name = serializers.CharField(
        source="academic_level.name", read_only=True, allow_null=True
    )

    class Meta:
        model = AwardClassificationScheme
        fields = [
            "id",
            "name",
            "academic_level",
            "academic_level_name",
            "is_active",
            "band_count",
            "created_at",
        ]


class AwardClassBandWriteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = AwardClassBand
        fields = ["id", "title", "min_cgpa", "order"]


class AwardSchemeWriteSerializer(serializers.ModelSerializer):
    bands = AwardClassBandWriteSerializer(many=True, required=False)

    class Meta:
        model = AwardClassificationScheme
        fields = ["name", "academic_level", "is_active", "bands"]

    def validate(self, attrs):
        academic_level = attrs.get(
            "academic_level",
            getattr(self.instance, "academic_level", None) if self.instance else None,
        )
        if academic_level:
            qs = AwardClassificationScheme.objects.filter(academic_level=academic_level)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {
                        "academic_level": (
                            f"An award scheme already exists for {academic_level.name}. "
                            "Edit that scheme instead."
                        )
                    }
                )
        bands = attrs.get("bands")
        if bands is None:
            if self.instance is None:
                raise serializers.ValidationError(
                    {"bands": "At least one award class band is required."}
                )
            return attrs
        if not bands:
            raise serializers.ValidationError(
                {"bands": "At least one award class band is required."}
            )
        for idx, band in enumerate(bands):
            band.setdefault("order", idx)
        return attrs

    def _sync_bands(self, scheme: AwardClassificationScheme, bands_data: list):
        keep_ids = {b["id"] for b in bands_data if b.get("id")}
        scheme.bands.exclude(pk__in=keep_ids).delete()
        for idx, row in enumerate(bands_data):
            band_data = dict(row)
            band_id = band_data.pop("id", None)
            band_data["order"] = band_data.get("order", idx)
            if band_id:
                AwardClassBand.objects.filter(pk=band_id, scheme=scheme).update(**band_data)
            else:
                AwardClassBand.objects.create(scheme=scheme, **band_data)

    def create(self, validated_data):
        bands_data = validated_data.pop("bands")
        is_active = validated_data.get("is_active", False)
        level = validated_data.get("academic_level")
        level_pk = level.pk if level else None
        if is_active:
            _deactivate_active_for_level(AwardClassificationScheme, level_pk)
        scheme = AwardClassificationScheme.objects.create(**validated_data)
        for idx, band_data in enumerate(bands_data):
            payload = {k: v for k, v in dict(band_data).items() if k != "id" and v is not None}
            payload["order"] = payload.get("order", idx)
            AwardClassBand.objects.create(scheme=scheme, **payload)
        return scheme

    def update(self, instance, validated_data):
        bands_data = validated_data.pop("bands", None)
        is_active = validated_data.get("is_active", instance.is_active)
        level = validated_data.get("academic_level", instance.academic_level)
        level_pk = level.pk if level else None
        if is_active:
            _deactivate_active_for_level(
                AwardClassificationScheme, level_pk, exclude_pk=instance.pk
            )
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if bands_data is not None:
            self._sync_bands(instance, [dict(b) for b in bands_data])
        return instance


class AwardSchemeDetailSerializer(serializers.ModelSerializer):
    bands = AwardClassBandSerializer(many=True, read_only=True)
    academic_level_name = serializers.CharField(
        source="academic_level.name", read_only=True, allow_null=True
    )

    class Meta:
        model = AwardClassificationScheme
        fields = [
            "id",
            "name",
            "academic_level",
            "academic_level_name",
            "is_active",
            "bands",
            "created_at",
        ]


class MarkRowSerializer(serializers.Serializer):
    enrollment_id = serializers.IntegerField()
    ca_mark = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    exam_mark = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)


class SaveMarksSerializer(serializers.Serializer):
    marks = MarkRowSerializer(many=True)


class CourseUnitResultSerializer(serializers.ModelSerializer):
    enrollment_id = serializers.IntegerField(source="enrollment.id", read_only=True)
    student_reg_no = serializers.CharField(source="enrollment.student.reg_no", read_only=True)
    student_name = serializers.CharField(source="enrollment.student.full_name", read_only=True)
    course_code = serializers.CharField(source="enrollment.course_unit.code", read_only=True)
    course_name = serializers.CharField(source="enrollment.course_unit.name", read_only=True)
    is_published = serializers.SerializerMethodField()
    has_pending_change_request = serializers.SerializerMethodField()

    class Meta:
        model = CourseUnitResult
        fields = [
            "id",
            "enrollment_id",
            "student_reg_no",
            "student_name",
            "course_code",
            "course_name",
            "ca_mark",
            "exam_mark",
            "final_mark",
            "exam_sitting_allowed",
            "is_pass",
            "grade_letter",
            "grade_point",
            "remark",
            "status",
            "is_published",
            "has_pending_change_request",
            "published_at",
        ]

    def get_is_published(self, obj):
        return obj.status == CourseUnitResult.STATUS_PUBLISHED

    def get_has_pending_change_request(self, obj):
        return obj.change_requests.filter(
            status=ResultChangeRequest.STATUS_PENDING
        ).exists()


class ResultChangeRequestSerializer(serializers.ModelSerializer):
    reg_no = serializers.CharField(source="result.enrollment.student.reg_no", read_only=True)
    student_name = serializers.CharField(source="result.enrollment.student.full_name", read_only=True)
    course_code = serializers.CharField(source="result.enrollment.course_unit.code", read_only=True)
    result_id = serializers.IntegerField(source="result.id", read_only=True)

    class Meta:
        model = ResultChangeRequest
        fields = [
            "id",
            "result_id",
            "reg_no",
            "student_name",
            "course_code",
            "status",
            "reason",
            "review_notes",
            "old_ca_mark",
            "old_exam_mark",
            "old_final_mark",
            "old_grade_letter",
            "new_ca_mark",
            "new_exam_mark",
            "requested_at",
            "reviewed_at",
        ]


class ExamSessionSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course_unit.code", read_only=True)
    course_name = serializers.CharField(source="course_unit.name", read_only=True)
    venue_display = serializers.SerializerMethodField()
    registered_retakes = serializers.SerializerMethodField()
    effective_capacity = serializers.SerializerMethodField()
    candidate_count = serializers.SerializerMethodField()
    invigilators = serializers.SerializerMethodField()
    invigilator_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = ExamSession
        fields = [
            "id",
            "course_unit",
            "course_code",
            "course_name",
            "session_type",
            "title",
            "exam_date",
            "start_time",
            "end_time",
            "venue",
            "venue_text",
            "venue_display",
            "max_candidates",
            "effective_capacity",
            "candidate_count",
            "is_published",
            "notes",
            "invigilators",
            "invigilator_ids",
            "registered_retakes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "effective_capacity", "candidate_count", "invigilators"]

    def get_venue_display(self, obj):
        if obj.venue_id:
            parts = [obj.venue.name]
            if obj.venue.building:
                parts.insert(0, obj.venue.building)
            return " — ".join(parts)
        return obj.venue_text or ""

    def get_registered_retakes(self, obj):
        return obj.retake_registrations.filter(
            status__in=(
                ExamRetakeRegistration.STATUS_APPROVED,
                ExamRetakeRegistration.STATUS_SCHEDULED,
            )
        ).count()

    def get_effective_capacity(self, obj):
        from .services.clash import effective_capacity

        return effective_capacity(obj)

    def get_candidate_count(self, obj):
        from .services.clash import candidate_count

        return candidate_count(obj.course_unit, obj.session_type)

    def get_invigilators(self, obj):
        return [
            {
                "id": s.id,
                "name": s.get_full_name,
                "staff_no": s.staff_no,
            }
            for s in obj.invigilators.all()
        ]

    def create(self, validated_data):
        invigilator_ids = validated_data.pop("invigilator_ids", None)
        session = super().create(validated_data)
        if invigilator_ids is not None:
            session.invigilators.set(invigilator_ids)
        return session

    def update(self, instance, validated_data):
        invigilator_ids = validated_data.pop("invigilator_ids", None)
        session = super().update(instance, validated_data)
        if invigilator_ids is not None:
            session.invigilators.set(invigilator_ids)
        return session


class MarksEntryWindowSerializer(serializers.ModelSerializer):
    program_batch_name = serializers.CharField(source="program_batch.name", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True, allow_null=True)
    course_code = serializers.CharField(source="course_unit.code", read_only=True, allow_null=True)
    course_name = serializers.CharField(source="course_unit.name", read_only=True, allow_null=True)
    scope = serializers.SerializerMethodField()

    class Meta:
        model = MarksEntryWindow
        fields = [
            "id",
            "name",
            "program_batch",
            "program_batch_name",
            "semester",
            "semester_name",
            "course_unit",
            "course_code",
            "course_name",
            "scope",
            "opens_at",
            "closes_at",
            "is_active",
            "notes",
            "closed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["closed_at", "created_at", "updated_at"]

    def get_scope(self, obj):
        if obj.course_unit_id:
            return "course"
        if obj.semester_id:
            return "semester"
        return "batch"

    def validate(self, attrs):
        program_batch = attrs.get(
            "program_batch",
            getattr(self.instance, "program_batch", None) if self.instance else None,
        )
        semester = attrs.get(
            "semester",
            getattr(self.instance, "semester", None) if self.instance else None,
        )
        course_unit = attrs.get(
            "course_unit",
            getattr(self.instance, "course_unit", None) if self.instance else None,
        )
        opens_at = attrs.get(
            "opens_at",
            getattr(self.instance, "opens_at", None) if self.instance else None,
        )
        closes_at = attrs.get(
            "closes_at",
            getattr(self.instance, "closes_at", None) if self.instance else None,
        )

        if course_unit and program_batch and course_unit.program_batch_id != program_batch.id:
            raise serializers.ValidationError(
                {"course_unit": "Course unit must belong to the selected programme batch."}
            )
        if semester and course_unit and course_unit.semester_id != semester.id:
            raise serializers.ValidationError(
                {"course_unit": "Course unit must belong to the selected semester."}
            )
        if opens_at and closes_at and opens_at >= closes_at:
            raise serializers.ValidationError(
                {"closes_at": "Closing time must be after opening time."}
            )
        return attrs


class ExamRetakeRegistrationSerializer(serializers.ModelSerializer):
    reg_no = serializers.CharField(source="enrollment.student.reg_no", read_only=True)
    student_name = serializers.CharField(source="enrollment.student.full_name", read_only=True)
    course_code = serializers.CharField(source="enrollment.course_unit.code", read_only=True)
    course_name = serializers.CharField(source="enrollment.course_unit.name", read_only=True)
    exam_session_date = serializers.DateField(source="exam_session.exam_date", read_only=True)

    class Meta:
        model = ExamRetakeRegistration
        fields = [
            "id",
            "enrollment",
            "reg_no",
            "student_name",
            "course_code",
            "course_name",
            "exam_session",
            "exam_session_date",
            "status",
            "reason",
            "admin_notes",
            "requested_at",
            "reviewed_at",
        ]
        read_only_fields = ["requested_at", "reviewed_at", "reg_no", "student_name", "course_code", "course_name"]
