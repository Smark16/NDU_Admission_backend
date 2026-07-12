from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal


class AppraisalCycle(models.Model):
    """
    Annual performance review cycle (e.g., 2024/2025).
    Defines the period and review window for appraisals.
    """
    CYCLE_STATUS_CHOICES = [
        ('PLANNING', 'Planning'),
        ('OBJECTIVE_SETTING', 'Objective Setting'),
        ('ACTIVE', 'Active'),
        ('REVIEW_WINDOW', 'Review Window Open'),
        ('COMPLETED', 'Completed'),
        ('ARCHIVED', 'Archived'),
    ]
    
    campus = models.ForeignKey(
        'accounts.Campus',
        on_delete=models.CASCADE,
        related_name='appraisal_cycles'
    )
    academic_year = models.CharField(
        max_length=20,
        help_text="e.g., 2024/2025"
    )
    period_from = models.DateField(help_text="Review period start date")
    period_to = models.DateField(help_text="Review period end date")
    review_window_from = models.DateField(help_text="When staff can start submitting")
    review_window_to = models.DateField(help_text="Submission deadline")
    status = models.CharField(
        max_length=20,
        choices=CYCLE_STATUS_CHOICES,
        default='PLANNING'
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Only one active cycle per campus at a time"
    )
    
    class Meta:
        ordering = ['-academic_year', '-period_from']
        unique_together = [['campus', 'academic_year']]
    
    def __str__(self):
        return f"{self.campus.name} - {self.academic_year}"
    
    def clean(self):
        super().clean()
        if self.period_from >= self.period_to:
            raise ValidationError("Period end must be after period start")
        if self.review_window_from < self.period_to:
            raise ValidationError("Review window should start after the period ends")


class StrategicObjective(models.Model):
    """
    University-wide strategic objectives (e.g., SO5: Strengthen HR capacity).
    These are predefined by University management.
    """
    code = models.CharField(
        max_length=10,
        unique=True,
        help_text="e.g., SO5"
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['code']
    
    def __str__(self):
        return f"{self.code}: {self.title}"


class DepartmentalObjective(models.Model):
    """
    Department/Directorate objectives linked to strategic objectives.
    """
    strategic_objective = models.ForeignKey(
        StrategicObjective,
        on_delete=models.CASCADE,
        related_name='departmental_objectives'
    )
    org_unit = models.ForeignKey(
        'staff.Department',
        on_delete=models.CASCADE,
        related_name='departmental_objectives'
    )
    objective = models.TextField(help_text="Department objective")
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['org_unit', 'strategic_objective']
    
    def __str__(self):
        return f"{self.org_unit.name} - {self.strategic_objective.code}"


class Appraisal(models.Model):
    """
    Main appraisal record for a staff member.
    Represents the complete performance review document.
    """
    APPRAISAL_STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('OBJECTIVES_SET', 'Objectives Set'),
        ('SELF_ASSESSMENT', 'Self-Assessment In Progress'),
        ('SELF_COMPLETED', 'Self-Assessment Completed'),
        ('SUPERVISOR_REVIEW', 'Under Supervisor Review'),
        ('HR_REVIEW', 'HR Review'),
        ('APPROVED', 'Approved'),
        ('PUBLISHED', 'Published to Staff'),
        ('ACKNOWLEDGED', 'Acknowledged by Staff'),
    ]
    
    RATING_CHOICES = [
        ('EXCEPTIONAL', 'Exceptional (5)'),
        ('EXCELLENT', 'Excellent (4)'),
        ('SATISFACTORY', 'Satisfactory (3)'),
        ('UNSATISFACTORY', 'Unsatisfactory (0-2)'),
    ]
    
    cycle = models.ForeignKey(
        AppraisalCycle,
        on_delete=models.CASCADE,
        related_name='appraisals'
    )
    staff = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='appraisals'
    )
    supervisor = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        related_name='supervised_appraisals',
        help_text="Manager/Supervisor conducting the review"
    )
    status = models.CharField(
        max_length=20,
        choices=APPRAISAL_STATUS_CHOICES,
        default='DRAFT'
    )
    
    # Personal details (auto-filled from staff profile)
    highest_qualification = models.CharField(max_length=200, blank=True)
    courses_in_progress = models.TextField(blank=True)
    contract_expiry_date = models.DateField(null=True, blank=True)
    
    # Scores (calculated automatically)
    objectives_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average of all objective scores"
    )
    behavioral_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average of behavioral competencies"
    )
    performance_factors_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average of performance factors"
    )
    overall_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="(Objectives + Behavioral + Performance) / 3"
    )
    overall_rating = models.CharField(
        max_length=20,
        choices=RATING_CHOICES,
        blank=True
    )
    
    # Comments
    supervisor_overall_comment = models.TextField(blank=True)
    hr_comments = models.TextField(blank=True)
    staff_acknowledgment_comment = models.TextField(blank=True)
    
    # Timestamps
    self_completed_at = models.DateTimeField(null=True, blank=True)
    supervisor_completed_at = models.DateTimeField(null=True, blank=True)
    hr_approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-cycle__academic_year', 'staff__staff_no']
        unique_together = [['cycle', 'staff']]
    
    def __str__(self):
        return f"{self.staff.get_full_name} - {self.cycle.academic_year}"
    
    def calculate_scores(self):
        """Calculate all scores automatically."""
        from decimal import Decimal
        
        # Calculate objectives score (weighted average)
        objectives = self.objectives.all()
        if objectives.exists():
            total_weight = sum(obj.weight for obj in objectives)
            if total_weight > 0:
                weighted_sum = sum(
                    (obj.agreed_score or 0) * obj.weight 
                    for obj in objectives
                )
                self.objectives_score = Decimal(str(weighted_sum / total_weight))
        
        # Calculate behavioral score (simple average)
        behavioral = self.behavioral_competencies.all()
        if behavioral.exists():
            agreed_scores = [b.agreed_assessment for b in behavioral if b.agreed_assessment]
            if agreed_scores:
                avg = sum(agreed_scores) / len(agreed_scores)
                self.behavioral_score = Decimal(str(avg))
        
        # Calculate performance factors score (simple average)
        factors = self.performance_factors.all()
        if factors.exists():
            agreed_scores = [f.agreed_assessment for f in factors if f.agreed_assessment]
            if agreed_scores:
                avg = sum(agreed_scores) / len(agreed_scores)
                self.performance_factors_score = Decimal(str(avg))
        
        # Calculate overall score
        scores = []
        if self.objectives_score:
            scores.append(self.objectives_score)
        if self.behavioral_score:
            scores.append(self.behavioral_score)
        if self.performance_factors_score:
            scores.append(self.performance_factors_score)
        
        if scores:
            total = sum(scores)
            self.overall_score = total / Decimal(str(len(scores)))
            
            # Assign rating based on overall score
            if self.overall_score >= 5:
                self.overall_rating = 'EXCEPTIONAL'
            elif self.overall_score >= 4:
                self.overall_rating = 'EXCELLENT'
            elif self.overall_score >= 3:
                self.overall_rating = 'SATISFACTORY'
            else:
                self.overall_rating = 'UNSATISFACTORY'
        
        self.save()
    
    def get_supervisor(self):
        """Get the supervisor for this staff member from their org unit."""
        if self.supervisor:
            return self.supervisor
        
        # Find the manager of the staff's org unit
        org_unit = self.staff.org_unit
        manager_profile = org_unit.managed_by.first()
        return manager_profile


class AppraisalObjective(models.Model):
    """
    Individual objectives/KPIs for staff (Section 5.0 of the form).
    Linked to strategic and departmental objectives.
    """
    appraisal = models.ForeignKey(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='objectives'
    )
    strategic_objective = models.ForeignKey(
        StrategicObjective,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    departmental_objective = models.ForeignKey(
        DepartmentalObjective,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    # Objective details
    individual_objective = models.TextField(help_text="Individual objective")
    indicative_tasks = models.TextField(help_text="Tasks to achieve the objective")
    
    # Targets and weights
    target_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Target %"
    )
    baseline_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Baseline %"
    )
    weight = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        help_text="Weight out of 5"
    )
    
    # Self-assessment
    individual_score_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Staff's self-assessed score %"
    )
    achievements = models.TextField(
        blank=True,
        help_text="Staff describes their achievements"
    )
    
    # Supervisor assessment
    supervisor_comments = models.TextField(blank=True)
    agreed_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        help_text="Final agreed score out of 5"
    )
    action_required = models.TextField(
        blank=True,
        help_text="Any action required"
    )
    
    class Meta:
        ordering = ['appraisal', 'id']
    
    def __str__(self):
        return f"{self.appraisal.staff.get_full_name} - {self.individual_objective[:50]}"


class BehavioralCompetency(models.Model):
    """
    NDU Core Values assessment (Section 6.0 of the form).
    9 competencies: God fearing, Respect, Integrity, Teamwork, Commitment,
    Innovativeness, Equity, Excellence, Accountability.
    """
    COMPETENCY_CHOICES = [
        ('GOD_FEARING', 'God fearing'),
        ('RESPECT', 'Respect'),
        ('INTEGRITY', 'Integrity'),
        ('TEAMWORK', 'Teamwork'),
        ('COMMITMENT', 'Commitment'),
        ('INNOVATIVENESS', 'Innovativeness'),
        ('EQUITY', 'Equity'),
        ('EXCELLENCE', 'Excellence'),
        ('ACCOUNTABILITY', 'Accountability'),
    ]
    
    appraisal = models.ForeignKey(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='behavioral_competencies'
    )
    competency = models.CharField(max_length=20, choices=COMPETENCY_CHOICES)
    description = models.TextField(
        help_text="Description of the competency from NDU form"
    )
    
    # Assessments (1-5 scale)
    self_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    supervisor_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    agreed_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    class Meta:
        ordering = ['appraisal', 'id']
        unique_together = [['appraisal', 'competency']]
    
    def __str__(self):
        return f"{self.appraisal.staff.get_full_name} - {self.get_competency_display()}"


class PerformanceFactor(models.Model):
    """
    Performance factors assessment (Section 7.0 of the form).
    4 factors: Professional Competence, Quality of Work, Work Relationships, Leadership Skills.
    """
    FACTOR_CHOICES = [
        ('PROFESSIONAL_COMPETENCE', 'Professional Competence'),
        ('QUALITY_OF_WORK', 'Quality of Work'),
        ('WORK_RELATIONSHIPS', 'Work Relationships'),
        ('LEADERSHIP_SKILLS', 'Leadership Skills'),
    ]
    
    appraisal = models.ForeignKey(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='performance_factors'
    )
    factor = models.CharField(max_length=30, choices=FACTOR_CHOICES)
    description = models.TextField(
        help_text="Description of the performance factor"
    )
    
    # Assessments (1-5 scale)
    self_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    supervisor_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    agreed_assessment = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    # Additional fields
    is_applicable = models.BooleanField(
        default=True,
        help_text="Leadership Skills only for managers"
    )
    number_supervised = models.IntegerField(
        null=True,
        blank=True,
        help_text="For leadership skills - number of staff supervised"
    )
    
    class Meta:
        ordering = ['appraisal', 'id']
        unique_together = [['appraisal', 'factor']]
    
    def __str__(self):
        return f"{self.appraisal.staff.get_full_name} - {self.get_factor_display()}"


class DevelopmentObjective(models.Model):
    """
    Development objectives for next appraisal period (Section 8.0 of the form).
    """
    appraisal = models.ForeignKey(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='development_objectives'
    )
    objective = models.TextField(help_text="Development objective")
    how_to_achieve = models.TextField(help_text="How to achieve this objective")
    target_date = models.DateField(null=True, blank=True)
    
    STATUS_CHOICES = [
        ('PLANNED', 'Planned'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('DEFERRED', 'Deferred'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PLANNED'
    )
    
    class Meta:
        ordering = ['appraisal', 'id']
    
    def __str__(self):
        return f"{self.appraisal.staff.get_full_name} - {self.objective[:50]}"


class PerformanceImprovementPlan(models.Model):
    """
    Performance Improvement Plan (PIP) for unsatisfactory performers.
    Triggered when overall rating < 3.
    """
    PIP_STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('COMPLETED_IMPROVED', 'Completed - Improved'),
        ('COMPLETED_NOT_IMPROVED', 'Completed - Not Improved'),
        ('EXTENDED', 'Extended'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    appraisal = models.OneToOneField(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='pip'
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=30,
        choices=PIP_STATUS_CHOICES,
        default='DRAFT'
    )
    
    # Areas needing improvement
    improvement_areas = models.TextField(
        help_text="Specific areas that need improvement"
    )
    improvement_targets = models.TextField(
        help_text="Specific, measurable targets to achieve"
    )
    support_provided = models.TextField(
        blank=True,
        help_text="Training, mentoring, resources provided"
    )
    
    # Progress tracking
    progress_notes = models.TextField(blank=True)
    mid_pip_review_date = models.DateField(null=True, blank=True)
    mid_pip_review_notes = models.TextField(blank=True)
    
    # Outcome
    final_assessment = models.TextField(blank=True)
    outcome_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    
    class Meta:
        ordering = ['-start_date']
    
    def __str__(self):
        return f"PIP - {self.appraisal.staff.get_full_name} ({self.start_date})"


class MidYearReview(models.Model):
    """
    Mid-year performance review for satisfactory performers (rating = 3).
    Appendix A form.
    """
    appraisal = models.OneToOneField(
        Appraisal,
        on_delete=models.CASCADE,
        related_name='mid_year_review'
    )
    review_date = models.DateField()
    
    # Progress assessment
    objectives_progress = models.TextField(
        help_text="Progress on annual objectives"
    )
    challenges_faced = models.TextField(blank=True)
    support_needed = models.TextField(blank=True)
    
    # Mid-year score
    mid_year_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    
    # Comments
    staff_comments = models.TextField(blank=True)
    supervisor_comments = models.TextField(blank=True)
    
    # Action plan adjustments
    revised_objectives = models.TextField(
        blank=True,
        help_text="Any adjustments to objectives for second half"
    )
    
    class Meta:
        ordering = ['-review_date']
    
    def __str__(self):
        return f"Mid-Year Review - {self.appraisal.staff.get_full_name}"
