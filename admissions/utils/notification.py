# create notification
from admissions.models import PortalNotification

def create_notification(user, title, msg):
    PortalNotification.objects.create(
            recipient=user,
            title=title,
            message=msg
     )
    