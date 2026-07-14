from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from .utils.reference import generate_reference

class JobOpening(models.Model):
    EMPLOYMENT_TYPE_CHOICES = [
        ('FULL_TIME', 'Full Time'),
        ('PART_TIME', 'Part Time'),
        ('CONTRACT', 'Contract'),
        ('TEMPORARY', 'Temporary'),
        ('INTERNSHIP', 'Internship'),
    ]
    
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('OPEN', 'Open for Applications'),
        ('CLOSED', 'Closed'),
        ('CANCELLED', 'Cancelled'),
        ('FILLED', 'Position Filled'),
    ]
    
    title = models.CharField(max_length=200)
    department = models.ForeignKey(
        'staff.Department',
        on_delete=models.CASCADE,
        related_name='job_openings'
    )
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default='FULL_TIME')
    
    # Job Details — PDF only (careers portal serves this as a download)
    description = models.FileField(
        upload_to='job_descriptions/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
        help_text='Upload the full job description as a PDF.',
    )
   
    # Application Details
    number_of_positions = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    application_deadline = models.DateField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    published_date = models.DateField()
    
    class Meta:
        ordering = ['-published_date']
        verbose_name = 'Job Opening'
        verbose_name_plural = 'Job Openings'
    
    def __str__(self):
        return f"{self.title} - {self.department.name}"


class JobApplication(models.Model):
    STATUS_CHOICES = [
        ('APPLIED', 'Application Received'),
        ('SCREENING', 'Under Screening'),
        ('SHORTLISTED', 'Shortlisted'),
        ('INTERVIEWING', 'Interview Scheduled'),
        ('SELECTED', 'Selected for Offer'),
        ('HIRED', 'hired for job'),
        ('ACCEPTED', 'Offer Accepted'),
        ('REJECTED', 'Rejected'),
        ('WITHDRAWN', 'Application Withdrawn'),
        ('RESERVED', 'application reserved')
    ]
    
    job_opening = models.ForeignKey(
        JobOpening,
        on_delete=models.CASCADE,
        related_name='applications'
    )

    is_staff = models.BooleanField(default=False)
    
    # Candidate Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    title = models.CharField(max_length=20)
    current_address = models.TextField(max_length=255)
    religious_affiliation = models.CharField(max_length=100)
    marital_status = models.CharField(max_length=50)
    dob = models.CharField(max_length=20)
    brief_description = models.TextField(max_length=2000)
    
    # Application Details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='APPLIED')
    current_stage = models.CharField(max_length=20,null=True, blank=True)
    application_date = models.DateTimeField(auto_now_add=True)
    has_declared = models.BooleanField(default=False)
    skills = models.TextField(max_length=2000)
    reference = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.reference:
            ref = generate_reference()
            # ensure uniqueness (extra safety)
            while JobApplication.objects.filter(reference=ref).exists():
                ref = generate_reference()
            self.reference = ref
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    class Meta:
        ordering = ['-application_date']
        verbose_name = 'Job Application'
        verbose_name_plural = 'Job Applications'
    
    def __str__(self):
        return f"{self.get_full_name()} - {self.job_opening.title}"
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

class EducationHistory(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    institution = models.CharField(max_length=200)
    award = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
        
class Employment(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    current_employer = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    current_position = models.CharField(max_length=200)
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    duties = models.TextField(max_length=1000)

class Certificates_and_Training(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, null=True, blank=True)
    certificate_name = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    date_obtained = models.DateField()

class Projects(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    link = models.URLField(max_length=200)
    description = models.CharField(max_length=500)

class References(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    email = models.EmailField(max_length=100)
    job_position = models.CharField(max_length=100)

class Interview(models.Model):  
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('PASSED', 'passed'),
        ('FAILED', 'failed'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('RESCHEDULED', 'Rescheduled'),
        ('NO_SHOW', 'Candidate No Show'),
    ]
    
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name='interviews'
    )
    
    # Interview Details
    interview_type = models.CharField(max_length=20)
    interview_date = models.DateTimeField()
    duration_minutes = models.IntegerField(default=60)
    
    # Location/Link
    location = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)
    
    # Feedback
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    feedback = models.TextField(max_length=500, blank=True)

    class Meta:
        ordering = ['-interview_date']
        verbose_name = 'Interview'
        verbose_name_plural = 'Interviews'
    
    def __str__(self):
        return f"{self.interview_type}"

