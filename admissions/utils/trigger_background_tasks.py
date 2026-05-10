from admissions.tasks import (
    celery_admission_email,
    celery_create_student_account
)

def trigger_background_tasks(admission_id, application_id):
    celery_admission_email.delay(application_id, admission_id)
    celery_create_student_account.delay(admission_id, application_id)