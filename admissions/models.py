from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from accounts.models import User, Campus
from Programs.models import Program
from .utils.academic_year import get_current_academic_year
# from cloudinary.models import CloudinaryField

class Faculty(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    campuses = models.ManyToManyField(Campus, related_name='faculties', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Faculties"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

class AcademicLevel(models.Model):
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class Batch(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    programs = models.ManyToManyField(Program, related_name='batches')
    academic_year = models.CharField(max_length=15, blank=True)
    application_start_date = models.DateField()
    application_end_date = models.DateField()
    admission_start_date = models.DateField()
    admission_end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.academic_year:
            self.academic_year = get_current_academic_year()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def is_application_open(self):
        from django.utils import timezone
        now = timezone.now()
        return self.application_start_date <= now <= self.application_end_date

class OLevelSubject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']
        verbose_name = "O-Level Subject"
        verbose_name_plural = "O-Level Subjects"

    def __str__(self):
        return f"{self.name} ({self.code})"

class ALevelSubject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']
        verbose_name = "A-Level Subject"
        verbose_name_plural = "A-Level Subjects"

    def __str__(self):
        return f"{self.name} ({self.code})"

class Application(models.Model): 
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='applications')
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='applications')
    programs = models.ManyToManyField(Program, related_name='application_programs')
    academic_level = models.ForeignKey(AcademicLevel, on_delete=models.CASCADE)
    study_mode = models.CharField(max_length=10)
    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10)
    nationality = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    address = models.TextField()
    
    # Next of Kin Information
    next_of_kin_name = models.CharField(max_length=200)
    next_of_kin_contact = models.CharField(max_length=20)
    next_of_kin_relationship = models.CharField(max_length=20)
    
    # O-Level Information
    olevel_year = models.PositiveIntegerField()
    olevel_index_number = models.CharField(max_length=50)
    olevel_school = models.CharField(max_length=200)
    
    # A-Level Information
    alevel_year = models.PositiveIntegerField()
    alevel_index_number = models.CharField(max_length=50)
    alevel_school = models.CharField(max_length=200)
    alevel_combination = models.CharField(max_length=5)
    
    # Additional Qualifications
    additional_qualification_institution = models.CharField(max_length=200, blank=True, help_text="Institution Name")
    additional_qualification_type = models.CharField(max_length=20, blank=True)
    additional_qualification_year = models.PositiveIntegerField(blank=True, null=True, help_text="Award Year")
    class_of_award = models.CharField(max_length=200, blank=True, null=True)

    # Document uploads
    passport_photo = models.ImageField(upload_to='passport_photos/')
    # passport_photo = CloudinaryField('passport_photo', folder='admission_Folder/images')
    payment_proof = models.FileField(upload_to='payment_proofs/', blank=True, null=True, help_text="Payment Proof (PDF)")
    # payment_proof = CloudinaryField('payment_proof', folder='admission_Folder/images', blank=True, null=True)
    # Application Status
    status = models.CharField(max_length=20, default='draft')
    application_fee_paid = models.BooleanField(default=False)
    application_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Review Information
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    admission_letter_docx = models.FileField(upload_to="admission_template/", null=True, blank=True)
    admission_letter_pdf = models.FileField(upload_to="admission_template/", null=True, blank=True)
    offer_letter_status = models.CharField(max_length=20, default='pending')
    offer_letter_progress = models.IntegerField(default=0)
    # admission_letter_docx = CloudinaryField('admission_letter_docx',folder='admission_Folder/templates/',resource_type='raw', null=True, blank=True)
    # admission_letter_pdf = CloudinaryField('admission_letter_pdf',folder='admission_Folder/templates/',resource_type='raw', null=True,blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.middle_name} {self.last_name}".strip()

class OLevelResult(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='olevel_results')
    subject = models.ForeignKey(OLevelSubject, on_delete=models.CASCADE)
    grade = models.CharField(max_length=2)

    class Meta:
        ordering = ['subject__name']
        unique_together = ['application', 'subject']
        verbose_name = "O-Level Result"
        verbose_name_plural = "O-Level Results"

    def __str__(self):
        return f"{self.application.full_name} - {self.subject.name}: {self.grade}"

class ALevelResult(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='alevel_results')
    subject = models.ForeignKey(ALevelSubject, on_delete=models.CASCADE)
    grade = models.CharField(max_length=1)

    class Meta:
        ordering = ['subject__name']
        unique_together = ['application', 'subject']
        verbose_name = "A-Level Result"
        verbose_name_plural = "A-Level Results"

    def __str__(self):
        return f"{self.application.full_name} - {self.subject.name}: {self.grade}"

class ApplicationDocument(models.Model): 
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=25, null=True, blank=True)
    document_type = models.CharField(max_length=30)
    file_url = models.URLField(max_length=100, null=True, blank=True)
    file = models.FileField(upload_to='application_documents/')
    # file = CloudinaryField('document',folder='admission_Folder/documents/', resource_type='raw')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

class AdmittedStudent(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='admission')
    student_id = models.CharField(max_length=50, unique=True)
    reg_no = models.CharField(max_length=100, unique=True)
    admitted_program = models.ForeignKey(Program, on_delete=models.CASCADE)
    admitted_batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='admitted_students', null=True, blank=True)
    admitted_campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='admitted_students')
    
    # Admission information
    admission_date = models.DateTimeField(default=timezone.now)
    admission_letter_sent = models.BooleanField(default=False)
    admission_letter_sent_at = models.DateTimeField(null=True, blank=True)
    is_admitted= models.BooleanField(default=False)
    
    # Registration information
    is_registered = models.BooleanField(default=False)
    registration_date = models.DateTimeField(null=True, blank=True)
    
    # Notes
    admission_notes = models.TextField(blank=True, help_text="Notes about the admission")
    admitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='admitted_students')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-admission_date']
        verbose_name = "Admitted Student"
        verbose_name_plural = "Admitted Students"
    
    def __str__(self):
        return f"{self.application.full_name} - {self.student_id}"
    
    @property
    def full_name(self):
        return self.application.full_name
    
    @property
    def email(self):
        return self.application.email
    
    @property
    def phone(self):
        return self.application.phone

class PortalNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.email} - {self.title}"











