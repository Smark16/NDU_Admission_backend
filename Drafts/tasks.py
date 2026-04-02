from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    autoretry_for=(Exception,),          # Retry on any error
    retry_backoff=10,                    # 10, 20, 40, 80... seconds
    retry_backoff_max=300,               # Max 5 minutes between retries
    max_retries=5,                       # Don't retry forever
    default_retry_delay=60,              # Fallback delay
)
def auto_process_drafts_deletion(self):
    try:
        expired_time = timezone.now() - timedelta(days=7)

        # Use .filter().delete() and capture the count
        deleted_count, _ = DraftApplication.objects.filter(
            created_at__lt=expired_time
        ).delete()

        logger.info(f"Auto-deleted {deleted_count} old draft applications (older than 7 days)")
        
        return f"Successfully deleted {deleted_count} old drafts"

    except Exception as exc:
        logger.error(f"Failed to delete old drafts: {exc}", exc_info=True)
        # Let Celery's autoretry handle it
        raise